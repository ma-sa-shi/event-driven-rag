import * as cdk from "aws-cdk-lib/core";
import { Construct } from "constructs";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as s3 from "aws-cdk-lib/aws-s3";
import { AppStack } from "./app-stack";

export interface EdgeStackProps extends cdk.StackProps {
  appStack: AppStack;
}

/**
 * 配信層スタック。
 * 単一のCloudFrontディストリビューションから、SPAの静的ファイルをS3へ、
 * `/api/*`をLambda Function URLへ振り分ける。
 * SPA配信用バケットは、OACのバケットポリシーがディストリビューションARNを参照し
 * スタック間の循環参照になる為、DataStackではなく本スタックで保持する。
 */
export class EdgeStack extends cdk.Stack {
  public readonly spaBucket: s3.Bucket;
  public readonly distribution: cloudfront.Distribution;

  constructor(scope: Construct, id: string, props: EdgeStackProps) {
    super(scope, id, props);

    const { appStack } = props;

    // SPA静的ファイル配信用バケット。CloudFront OAC経由でのみ読み取れる
    this.spaBucket = new s3.Bucket(this, "SpaBucket", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // OACとバケットポリシー(cloudfront.amazonaws.comへのs3:GetObject許可)が自動生成される
    const spaOrigin = origins.S3BucketOrigin.withOriginAccessControl(
      this.spaBucket,
    );

    // SSEのストリーミングを中断させない為のタイムアウト設定(設計書9.2)
    const chatOrigin = new origins.FunctionUrlOrigin(appStack.chatFunctionUrl, {
      readTimeout: cdk.Duration.seconds(60),
      keepaliveTimeout: cdk.Duration.seconds(20),
    });

    const apiOrigin = new origins.FunctionUrlOrigin(appStack.apiFunctionUrl, {
      // api-fnのLambdaタイムアウトに合わせる
      readTimeout: cdk.Duration.seconds(30),
      keepaliveTimeout: cdk.Duration.seconds(20),
    });

    // APIレスポンスはキャッシュせず、Authorizationヘッダー(Cognito JWT)を素通しする。
    // ALL_VIEWER_EXCEPT_HOST_HEADERはHostだけを落とす。
    // Function URLはHostでルーティングする為、ビューワーのHostを転送すると到達できない
    const apiBehavior = {
      viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
      cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
      originRequestPolicy:
        cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
    };

    // React Routerのクライアントサイドルーティング用。
    // 拡張子を持たないパスをindex.htmlへ書き換える。
    // errorResponsesはディストリビューション全体に効き、FastAPIが返す403/404のJSONまで
    // index.html+200へ差し替えてしまう為、デフォルトビヘイビアだけに効く本Functionを使う
    const spaRouterFunction = new cloudfront.Function(this, "SpaRouter", {
      runtime: cloudfront.FunctionRuntime.JS_2_0,
      code: cloudfront.FunctionCode.fromInline(`
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  // 拡張子付き(=静的アセット)とルート以外はSPAのエントリポイントへ寄せる
  if (!uri.includes('.')) {
    request.uri = '/index.html';
  }
  return request;
}
`),
    });

    this.distribution = new cloudfront.Distribution(this, "Distribution", {
      defaultBehavior: {
        origin: spaOrigin,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        functionAssociations: [
          {
            function: spaRouterFunction,
            eventType: cloudfront.FunctionEventType.VIEWER_REQUEST,
          },
        ],
      },
      // 定義順がそのままCloudFrontのビヘイビア優先順になる為、具体的なパスを先に置く
      additionalBehaviors: {
        // 圧縮はレスポンスをバッファリングしSSEのイベント到達を遅らせる為、無効にする
        "/api/chats/stream": {
          ...apiBehavior,
          origin: chatOrigin,
          compress: false,
        },
        "/api/*": { ...apiBehavior, origin: apiOrigin },
      },
      defaultRootObject: "index.html",
      httpVersion: cloudfront.HttpVersion.HTTP2_AND_3,
      // 固定費ゼロの方針(ADR-0001)に沿ってエッジロケーションを絞る。日本を含む
      priceClass: cloudfront.PriceClass.PRICE_CLASS_200,
    });

    new cdk.CfnOutput(this, "DistributionDomainName", {
      value: this.distribution.distributionDomainName,
    });
    new cdk.CfnOutput(this, "DistributionId", {
      value: this.distribution.distributionId,
    });
    new cdk.CfnOutput(this, "SpaBucketName", {
      value: this.spaBucket.bucketName,
    });
  }
}
