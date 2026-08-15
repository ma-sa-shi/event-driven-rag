import * as cdk from 'aws-cdk-lib/core';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { AppStack } from '../lib/app-stack';
import { CertificateStack } from '../lib/certificate-stack';
import { DataStack } from '../lib/data-stack';
import { EdgeStack } from '../lib/edge-stack';
import { normalizeAssetHashes } from './helpers';

// CloudFrontのマネージドポリシーID(固定値)
const CACHING_DISABLED = '4135ea2d-6df8-44a3-9df3-4b5a84be39ad';
const CACHING_OPTIMIZED = '658327ea-f89d-4fab-a63d-7e88639e58f6';
const ALL_VIEWER_EXCEPT_HOST_HEADER = 'b689b0a8-53d0-40ab-baf2-68738e2966ac';

const ACCOUNT = '123456789012';
const REGION = 'ap-northeast-1';
const DOMAIN_NAME = 'rag.business-efficiency.pro';

let template: Template;
let distributionConfig: any;

// 証明書はus-east-1にしか置けない為、実際のデプロイと同じくリージョンを跨いで組み立てる。
// スタック間参照の強度はcdk.jsonのフラグで決まり、jestはcdk.jsonを読まない為ここで与える。
// weakならリージョンを跨ぐ参照もデプロイ時解決となり、Exportもカスタムリソースも作られない
function synthEdgeStack(withCustomDomain: boolean) {
  const app = new cdk.App({
    context: { '@aws-cdk/core:defaultCrossStackReferences': 'weak' },
  });
  const env = { account: ACCOUNT, region: REGION };
  const dataStack = new DataStack(app, 'TestDataStack', { env });
  const appStack = new AppStack(app, 'TestAppStack', { env, dataStack });

  if (!withCustomDomain) {
    return Template.fromStack(new EdgeStack(app, 'TestEdgeStack', { env, appStack }));
  }

  const certificateStack = new CertificateStack(app, 'TestCertificateStack', {
    env: { account: ACCOUNT, region: 'us-east-1' },
    domainName: DOMAIN_NAME,
  });
  const edgeStack = new EdgeStack(app, 'TestEdgeStack', {
    env,
    appStack,
    customDomain: {
      domainName: DOMAIN_NAME,
      certificate: certificateStack.certificate,
    },
  });
  return Template.fromStack(edgeStack);
}

beforeAll(() => {
  template = synthEdgeStack(true);
  distributionConfig = Object.values(
    template.findResources('AWS::CloudFront::Distribution'),
  )[0].Properties.DistributionConfig;
});

// TargetOriginIdからOriginsの該当エントリを引くヘルパー
function originFor(targetOriginId: string) {
  const origin = distributionConfig.Origins.find(
    (o: any) => o.Id === targetOriginId,
  );
  expect(origin).toBeDefined();
  return origin;
}

describe('CloudFront', () => {
  test('ディストリビューションが1つ作成される', () => {
    template.resourceCountIs('AWS::CloudFront::Distribution', 1);
    expect(distributionConfig.DefaultRootObject).toBe('index.html');
    expect(distributionConfig.HttpVersion).toBe('http2and3');
    expect(distributionConfig.PriceClass).toBe('PriceClass_200');
  });

  test('S3とAPI Gateway 2つの計3オリジンを持つ', () => {
    expect(distributionConfig.Origins).toHaveLength(3);
  });

  test('デフォルトビヘイビアはS3オリジンをキャッシュして配信する', () => {
    const behavior = distributionConfig.DefaultCacheBehavior;
    expect(behavior.CachePolicyId).toBe(CACHING_OPTIMIZED);
    expect(behavior.ViewerProtocolPolicy).toBe('redirect-to-https');
    // S3OriginConfigを持つ = S3オリジン
    expect(originFor(behavior.TargetOriginId)).toHaveProperty('S3OriginConfig');
  });
});

describe('独自ドメイン', () => {
  test('代替ドメイン名にサブドメインを設定しACM証明書を関連付ける(ADR-0013)', () => {
    expect(distributionConfig.Aliases).toEqual([DOMAIN_NAME]);
    expect(distributionConfig.ViewerCertificate).toEqual(
      expect.objectContaining({
        AcmCertificateArn: expect.anything(),
        SslSupportMethod: 'sni-only',
        MinimumProtocolVersion: 'TLSv1.2_2021',
      }),
    );
  });

  test('customDomain未指定ならCloudFrontのデフォルト証明書で配信する', () => {
    const defaultDomainConfig = Object.values(
      synthEdgeStack(false).findResources('AWS::CloudFront::Distribution'),
    )[0].Properties.DistributionConfig;
    // ViewerCertificateを省略するとCloudFrontのデフォルト証明書が使われる
    expect(defaultDomainConfig.Aliases).toBeUndefined();
    expect(defaultDomainConfig.ViewerCertificate).toBeUndefined();
  });
});

describe('APIルーティング', () => {
  test('/api/chats/streamが/api/*より先に評価される', () => {
    // CloudFrontは定義順にビヘイビアを評価する為、順序自体が仕様
    expect(
      distributionConfig.CacheBehaviors.map((b: any) => b.PathPattern),
    ).toEqual(['/api/chats/stream', '/api/*']);
  });

  test('API系ビヘイビアはキャッシュせずAuthorizationヘッダーを転送する', () => {
    for (const behavior of distributionConfig.CacheBehaviors) {
      expect(behavior.CachePolicyId).toBe(CACHING_DISABLED);
      // Hostのみを落とし、Authorization(Cognito JWT)を含む全ヘッダーを転送する
      expect(behavior.OriginRequestPolicyId).toBe(ALL_VIEWER_EXCEPT_HOST_HEADER);
      expect(behavior.AllowedMethods).toEqual(
        expect.arrayContaining(['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']),
      );
      expect(behavior.ViewerProtocolPolicy).toBe('redirect-to-https');
      // API Gatewayオリジン
      expect(originFor(behavior.TargetOriginId)).toHaveProperty(
        'CustomOriginConfig',
      );
    }
  });

  test('API系ビヘイビアはAppStackの同一REST APIのステージを指す(ADR-0011)', () => {
    const apiOrigins = distributionConfig.CacheBehaviors.map((b: any) =>
      originFor(b.TargetOriginId),
    );
    // タイムアウト設定違いの2オリジンだが、指す先は同じexecute-apiのドメイン
    const [chat, api] = apiOrigins;
    expect(JSON.stringify(chat.DomainName)).toContain('execute-api');
    expect(JSON.stringify(chat.DomainName)).toBe(JSON.stringify(api.DomainName));
    // ステージ名はOriginPathとして付与され、CloudFrontのパスはそのままオリジンへ渡る
    for (const origin of apiOrigins) {
      expect(origin.OriginPath).toBeDefined();
    }
  });

  test('SSEビヘイビアはタイムアウトを60秒へ延ばし圧縮を無効にする', () => {
    const [streamBehavior] = distributionConfig.CacheBehaviors;
    // 圧縮はレスポンスをバッファリングしSSEの到達を遅らせる
    expect(streamBehavior.Compress).toBeFalsy();
    expect(originFor(streamBehavior.TargetOriginId).CustomOriginConfig).toEqual(
      expect.objectContaining({
        OriginReadTimeout: 60,
        OriginKeepaliveTimeout: 20,
        OriginProtocolPolicy: 'https-only',
      }),
    );
  });

  test('通常APIビヘイビアはapi-fnのタイムアウトに合わせる', () => {
    const [, apiBehavior] = distributionConfig.CacheBehaviors;
    expect(originFor(apiBehavior.TargetOriginId).CustomOriginConfig).toEqual(
      expect.objectContaining({
        OriginReadTimeout: 30,
        OriginKeepaliveTimeout: 20,
      }),
    );
  });
});

describe('SPAルーティング', () => {
  test('拡張子なしのURIをindex.htmlへ書き換えるCloudFront Functionを持つ', () => {
    template.resourceCountIs('AWS::CloudFront::Function', 1);
    const [fn] = Object.values(template.findResources('AWS::CloudFront::Function'));
    expect(fn.Properties.FunctionCode).toContain("request.uri = '/index.html'");
  });

  test('CloudFront Functionはデフォルトビヘイビアにのみ適用する', () => {
    expect(distributionConfig.DefaultCacheBehavior.FunctionAssociations).toEqual([
      { EventType: 'viewer-request', FunctionARN: expect.anything() },
    ]);
    // API側に適用するとJSONレスポンスまでindex.htmlへ書き換わる
    for (const behavior of distributionConfig.CacheBehaviors) {
      expect(behavior.FunctionAssociations).toBeUndefined();
    }
  });

  test('カスタムエラーレスポンスは使わない', () => {
    // ディストリビューション全体に効く為、FastAPIの403/404 JSONまで書き換えてしまう
    expect(distributionConfig.CustomErrorResponses).toBeUndefined();
  });
});

describe('S3 OAC', () => {
  test('SPAバケットはパブリックアクセスを全てブロックする', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });

  test('S3オリジンにOACが紐づく', () => {
    template.resourceCountIs('AWS::CloudFront::OriginAccessControl', 1);
    template.hasResourceProperties('AWS::CloudFront::OriginAccessControl', {
      OriginAccessControlConfig: Match.objectLike({
        OriginAccessControlOriginType: 's3',
        SigningBehavior: 'always',
        SigningProtocol: 'sigv4',
      }),
    });
    const s3Origin = originFor(
      distributionConfig.DefaultCacheBehavior.TargetOriginId,
    );
    expect(s3Origin.OriginAccessControlId).toBeDefined();
  });

  test('バケットポリシーがこのディストリビューションだけに読み取りを許可する', () => {
    const [policy] = Object.values(
      template.findResources('AWS::S3::BucketPolicy'),
    );
    const statement = policy.Properties.PolicyDocument.Statement.find(
      (s: any) => s.Principal?.Service === 'cloudfront.amazonaws.com',
    );
    expect(statement).toBeDefined();
    expect(statement.Action).toBe('s3:GetObject');
    // SourceArn条件で自ディストリビューション以外からのアクセスを弾く
    expect(JSON.stringify(statement.Condition)).toContain('AWS:SourceArn');
  });
});

test('スナップショット', () => {
  expect(normalizeAssetHashes(template)).toMatchSnapshot();
});
