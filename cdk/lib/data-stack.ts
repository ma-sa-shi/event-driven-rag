import * as cdk from "aws-cdk-lib/core";
import { Construct } from "constructs";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3vectors from "aws-cdk-lib/aws-s3vectors";
import * as sqs from "aws-cdk-lib/aws-sqs";

/**
 * データ層スタック
 * DynamoDB(シングルテーブル構造)、S3バケット、S3 Vectors、ドキュメント取込用SQS、
 * Cognito User Pool（認証基盤）を構築・管理する
 */
export class DataStack extends cdk.Stack {
  public readonly table: dynamodb.Table;
  public readonly spaBucket: s3.Bucket;
  public readonly documentsBucket: s3.Bucket;
  public readonly vectorBucket: s3vectors.CfnVectorBucket;
  public readonly vectorIndex: s3vectors.CfnIndex;
  public readonly ingestQueue: sqs.Queue;
  public readonly ingestDeadLetterQueue: sqs.Queue;
  public readonly userPool: cognito.UserPool;
  public readonly userPoolClient: cognito.UserPoolClient;
  public readonly userPoolDomain: cognito.UserPoolDomain;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Users / Documents / Chat / Chat Messages を1つのテーブルで管理(シングルテーブル)
    this.table = new dynamodb.Table(this, "Table", {
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "SK", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // 全ユーザー横断での一覧取得用GSI（Chatは'GSI1PK=CHAT'、Documentは'GSI1PK=DOC'として共有利用）
    this.table.addGlobalSecondaryIndex({
      indexName: "GSI1",
      partitionKey: { name: "GSI1PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "GSI1SK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // SPA静的ファイル配信用バケット
    // CloudFront OAC経由の読み取り許可設定はEdgeStackで実施
    this.spaBucket = new s3.Bucket(this, "SpaBucket", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // RAG用ドキュメント保存用バケット（SPAからPresigned URLを利用して直接PUT/GETを実行）
    this.documentsBucket = new s3.Bucket(this, "DocumentsBucket", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      cors: [
        {
          // TODO: EdgeStackでCloudFrontドメイン確定後にallowedOriginsを絞る
          allowedMethods: [s3.HttpMethods.PUT, s3.HttpMethods.GET],
          allowedOrigins: ["*"],
          allowedHeaders: ["*"],
        },
      ],
    });

    this.vectorBucket = new s3vectors.CfnVectorBucket(this, "VectorBucket");

    this.vectorIndex = new s3vectors.CfnIndex(this, "VectorIndex", {
      vectorBucketArn: this.vectorBucket.attrVectorBucketArn,
      dataType: "float32",
      // Cohere embed-v4.0の次元数
      // 作成後に変更できない為、埋め込みモデルを変えるときはインデックスを作り直す
      dimension: 1536,
      distanceMetric: "cosine",
      metadataConfiguration: {
        // 作成後に変更できない
        // text=チャンク本文、filename=出典表示用
        // // フィルタリング対象のメタデータはdocumentIdのみ（データ書き込み時に付与）
        nonFilterableMetadataKeys: ["text", "filename"],
      },
    });

    // ドキュメント取込失敗時の退避用DLQ
    this.ingestDeadLetterQueue = new sqs.Queue(this, "IngestDeadLetterQueue", {
      retentionPeriod: cdk.Duration.days(14),
    });

    // ドキュメント取込非同期処理用Queue
    this.ingestQueue = new sqs.Queue(this, "IngestQueue", {
      // ingest-fnの最大実行時間（Lambdaの最大15分）に合わせた可視性タイムアウト設定
      visibilityTimeout: cdk.Duration.seconds(900),
      deadLetterQueue: {
        queue: this.ingestDeadLetterQueue,
        maxReceiveCount: 3,
      },
    });

    // Cognito ユーザープール設定
    // 運用形態: 管理者によるユーザー作成および招待メール送信の運用（セルフサインアップは無効化）
    // 詳細仕様は docs/authorization.md, ADR-0004を参照
    this.userPool = new cognito.UserPool(this, "UserPool", {
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      standardAttributes: {
        email: { required: true, mutable: true },
        // 表示名。サインイン時にDynamoDBへキャッシュされる
        fullname: { required: true, mutable: true },
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // prefixはグローバル一意制約がある為、AWSアカウントIDを付与して衝突を避ける
    this.userPoolDomain = this.userPool.addDomain("HostedUiDomain", {
      cognitoDomain: { domainPrefix: `event-driven-rag-${this.account}` },
    });

    // SPA用パブリッククライアント。Client Secret無し、Authorization Code Flow + PKCE
    this.userPoolClient = this.userPool.addClient("SpaClient", {
      generateSecret: false,
      preventUserExistenceErrors: true,
      oAuth: {
        flows: { authorizationCodeGrant: true },
        // profileは表示名(name)の取得に必要
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.PROFILE,
        ],
        // TODO: EdgeStack実装時にCloudFrontドメインのURLを追加する
        callbackUrls: ["http://localhost:5173/auth/callback"],
        logoutUrls: ["http://localhost:5173"],
      },
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(30),
    });

    new cdk.CfnOutput(this, "TableName", { value: this.table.tableName });
    new cdk.CfnOutput(this, "SpaBucketName", {
      value: this.spaBucket.bucketName,
    });
    new cdk.CfnOutput(this, "DocumentsBucketName", {
      value: this.documentsBucket.bucketName,
    });
    new cdk.CfnOutput(this, "VectorBucketArn", {
      value: this.vectorBucket.attrVectorBucketArn,
    });
    new cdk.CfnOutput(this, "VectorIndexArn", {
      value: this.vectorIndex.attrIndexArn,
    });
    new cdk.CfnOutput(this, "IngestQueueUrl", {
      value: this.ingestQueue.queueUrl,
    });
    new cdk.CfnOutput(this, "UserPoolId", { value: this.userPool.userPoolId });
    new cdk.CfnOutput(this, "UserPoolClientId", {
      value: this.userPoolClient.userPoolClientId,
    });
    // SPAのVITE_COGNITO_AUTHORITYとバックエンドのCOGNITO_ISSUERに使う
    new cdk.CfnOutput(this, "CognitoIssuer", {
      value: this.userPool.userPoolProviderUrl,
    });
    // SPAのVITE_COGNITO_DOMAIN。サインアウトの/logoutリダイレクト
    new cdk.CfnOutput(this, "CognitoDomainUrl", {
      value: this.userPoolDomain.baseUrl(),
    });
  }
}
