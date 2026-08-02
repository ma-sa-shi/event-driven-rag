import * as cdk from 'aws-cdk-lib/core';
import { Match, Template } from 'aws-cdk-lib/assertions';
import {
  AppStack,
  COHERE_API_KEY_PARAMETER_NAME,
  OPENAI_API_KEY_PARAMETER_NAME,
} from '../lib/app-stack';
import { DataStack } from '../lib/data-stack';

let template: Template;

beforeAll(() => {
  const app = new cdk.App();
  const dataStack = new DataStack(app, 'TestDataStack');
  const appStack = new AppStack(app, 'TestAppStack', { dataStack });
  template = Template.fromStack(appStack);
});

// 環境変数からLambda論理リソースを特定するヘルパー
function findFunctionByServiceName(serviceName: string) {
  const functions = template.findResources('AWS::Lambda::Function');
  const matched = Object.entries(functions).filter(
    ([, fn]) =>
      fn.Properties.Environment?.Variables?.POWERTOOLS_SERVICE_NAME === serviceName,
  );
  expect(matched).toHaveLength(1);
  return matched[0];
}

describe('ECR', () => {
  test('CI/CD用の常設リポジトリが作成される', () => {
    template.resourceCountIs('AWS::ECR::Repository', 1);
    template.hasResource('AWS::ECR::Repository', {
      Properties: { EmptyOnDelete: true },
      DeletionPolicy: 'Delete',
    });
  });
});

describe('Lambda', () => {
  test('3つのコンテナイメージLambdaが作成される', () => {
    template.resourceCountIs('AWS::Lambda::Function', 3);
    const functions = template.findResources('AWS::Lambda::Function');
    for (const fn of Object.values(functions)) {
      expect(fn.Properties.PackageType).toBe('Image');
    }
  });

  test('api-fnは512MB/30秒でDataStackのリソース名を環境変数に持つ', () => {
    const [, fn] = findFunctionByServiceName('api');
    expect(fn.Properties.MemorySize).toBe(512);
    expect(fn.Properties.Timeout).toBe(30);
    const env = fn.Properties.Environment.Variables;
    expect(env).toHaveProperty('TABLE_NAME');
    expect(env).toHaveProperty('DOCUMENTS_BUCKET_NAME');
    expect(env).toHaveProperty('INGEST_QUEUE_URL');
    expect(env.POWERTOOLS_LOG_LEVEL).toBe('INFO');
  });

  test('api-fnとchat-fnはJWT検証用のCognito環境変数を持つ', () => {
    for (const serviceName of ['api', 'chat']) {
      const [, fn] = findFunctionByServiceName(serviceName);
      const env = fn.Properties.Environment.Variables;
      expect(env).toHaveProperty('COGNITO_ISSUER');
      expect(env).toHaveProperty('COGNITO_CLIENT_ID');
    }
    // HTTPリクエストを受けないingest-fnには不要
    const [, ingestFn] = findFunctionByServiceName('ingest');
    expect(ingestFn.Properties.Environment.Variables).not.toHaveProperty('COGNITO_ISSUER');
  });

  test('chat-fnは1024MB/300秒でストリーミングとSSMパラメータ名を設定する', () => {
    const [, fn] = findFunctionByServiceName('chat');
    expect(fn.Properties.MemorySize).toBe(1024);
    expect(fn.Properties.Timeout).toBe(300);
    const env = fn.Properties.Environment.Variables;
    expect(env.AWS_LWA_INVOKE_MODE).toBe('response_stream');
    expect(env.OPENAI_API_KEY_PARAMETER_NAME).toBe(OPENAI_API_KEY_PARAMETER_NAME);
    expect(env.COHERE_API_KEY_PARAMETER_NAME).toBe(COHERE_API_KEY_PARAMETER_NAME);
    expect(env).toHaveProperty('VECTOR_BUCKET_ARN');
    expect(env).toHaveProperty('VECTOR_INDEX_ARN');
  });

  test('ingest-fnは1024MB/600秒でWeb Adapter用環境変数を持たない', () => {
    const [, fn] = findFunctionByServiceName('ingest');
    expect(fn.Properties.MemorySize).toBe(1024);
    expect(fn.Properties.Timeout).toBe(600);
    const env = fn.Properties.Environment.Variables;
    expect(env).not.toHaveProperty('AWS_LWA_INVOKE_MODE');
    // Embeddingはchat-fnの検索側と同じCohereモデルを使うため、OpenAIキーは持たない
    expect(env.COHERE_API_KEY_PARAMETER_NAME).toBe(COHERE_API_KEY_PARAMETER_NAME);
    expect(env).not.toHaveProperty('OPENAI_API_KEY_PARAMETER_NAME');
    expect(env).toHaveProperty('DOCUMENTS_BUCKET_NAME');
    expect(env).toHaveProperty('VECTOR_INDEX_ARN');
  });

  test('3つのLambdaはそれぞれ別ターゲットのイメージを使う', () => {
    const imageUris = ['api', 'chat', 'ingest'].map((serviceName) =>
      JSON.stringify(findFunctionByServiceName(serviceName)[1].Properties.Code.ImageUri),
    );
    // web / chat / worker の3ターゲットに対応し、どれも共有しない
    expect(new Set(imageUris).size).toBe(3);
  });
});

describe('API Gateway', () => {
  // リソースの論理IDからパス(PathPart)を組み立てるヘルパー
  function resourcePaths() {
    const resources = template.findResources('AWS::ApiGateway::Resource');
    const paths: Record<string, string> = {};
    const pathOf = (logicalId: string): string => {
      const props = resources[logicalId].Properties;
      const parent = props.ParentId.Ref;
      // ParentIdがRestApiのRootResourceIdを指す場合はFn::GetAttになりRefを持たない
      return parent === undefined
        ? `/${props.PathPart}`
        : `${pathOf(parent)}/${props.PathPart}`;
    };
    for (const logicalId of Object.keys(resources)) {
      paths[logicalId] = pathOf(logicalId);
    }
    return paths;
  }

  // メソッドをパス文字列で引けるようにする
  function methodsByPath() {
    const paths = resourcePaths();
    const methods = Object.values(template.findResources('AWS::ApiGateway::Method'));
    return new Map(
      methods.map((m) => [
        `${m.Properties.HttpMethod} ${paths[m.Properties.ResourceId.Ref]}`,
        m.Properties,
      ]),
    );
  }

  test('Function URLは作成されず、公開経路はREST APIだけになる(ADR-0011)', () => {
    template.resourceCountIs('AWS::Lambda::Url', 0);
    template.resourceCountIs('AWS::ApiGateway::RestApi', 1);
  });

  // CloudFrontを前段に置く為、エッジ最適化ではなくリージョナル
  test('エンドポイントはリージョナル', () => {
    template.hasResourceProperties('AWS::ApiGateway::RestApi', {
      EndpointConfiguration: { Types: ['REGIONAL'] },
    });
  });

  test('FastAPIのルート構成に対応したリソースを持つ', () => {
    expect(new Set(Object.values(resourcePaths()))).toEqual(
      new Set([
        '/api',
        '/api/health',
        '/api/chats',
        '/api/chats/stream',
        '/api/chats/{proxy+}',
        '/api/{proxy+}',
      ]),
    );
  });

  test('全メソッドがLambdaプロキシ統合で接続される', () => {
    for (const props of methodsByPath().values()) {
      expect(props.Integration.Type).toBe('AWS_PROXY');
      expect(props.Integration.IntegrationHttpMethod).toBe('POST');
    }
  });

  test('SSEのルートだけがchat-fnへストリーミングで統合される', () => {
    const methods = methodsByPath();
    const stream = methods.get('POST /api/chats/stream');
    expect(stream).toBeDefined();
    // STREAMを指定しないとレスポンス全体が揃うまで送出されない
    expect(stream.Integration.ResponseTransferMode).toBe('STREAM');

    for (const [key, props] of methods) {
      if (key === 'POST /api/chats/stream') continue;
      expect(props.Integration.ResponseTransferMode).toBeUndefined();
    }
  });

  test('統合タイムアウトがサービスクォータの上限を超えない', () => {
    // 上限を超えるとデプロイがInvalidRequestで失敗する。
    // クォータ`Maximum integration timeout in milliseconds`(L-E5AE38E3)の既定値
    const quotaLimitMillis = 29_000;
    for (const props of methodsByPath().values()) {
      expect(props.Integration.TimeoutInMillis).toBeLessThanOrEqual(
        quotaLimitMillis,
      );
    }
  });

  test('SSEはchat-fn、それ以外はapi-fnへ振り分ける', () => {
    const methods = methodsByPath();
    const uriOf = (key: string) =>
      JSON.stringify(methods.get(key)!.Integration.Uri);
    const chatUri = uriOf('POST /api/chats/stream');
    const apiUri = uriOf('ANY /api/{proxy+}');
    expect(chatUri).not.toBe(apiUri);
    // chats配下のGETはapi-fnが処理する
    expect(uriOf('ANY /api/chats')).toBe(apiUri);
    expect(uriOf('ANY /api/chats/{proxy+}')).toBe(apiUri);
    expect(uriOf('GET /api/health')).toBe(apiUri);
  });

  test('Cognitoオーソライザが/api/health以外の全ルートへ適用される', () => {
    template.resourceCountIs('AWS::ApiGateway::Authorizer', 1);
    template.hasResourceProperties('AWS::ApiGateway::Authorizer', {
      Type: 'COGNITO_USER_POOLS',
      // FastAPIへ渡るBearerトークンと同じヘッダーをオーソライザも読む
      IdentitySource: 'method.request.header.Authorization',
    });

    for (const [key, props] of methodsByPath()) {
      if (key === 'GET /api/health') {
        expect(props.AuthorizationType).toBe('NONE');
        expect(props.AuthorizerId).toBeUndefined();
      } else {
        expect(props.AuthorizationType).toBe('COGNITO_USER_POOLS');
        expect(props.AuthorizerId).toBeDefined();
        // 未指定だとオーソライザがIDトークンとして検証し、
        // アクセストークンを送る本システムでは全て401になる
        expect(props.AuthorizationScopes).toEqual(['openid']);
      }
    }
  });

  test('ステージにスロットリングの上限が設定される', () => {
    template.hasResourceProperties('AWS::ApiGateway::Stage', {
      StageName: 'prod',
      MethodSettings: Match.arrayWith([
        Match.objectLike({
          HttpMethod: '*',
          ResourcePath: '/*',
          ThrottlingRateLimit: 20,
          ThrottlingBurstLimit: 40,
        }),
      ]),
    });
  });
});

describe('SQS', () => {
  test('ingest-fnは取込キューから1メッセージずつ受け取る', () => {
    template.hasResourceProperties('AWS::Lambda::EventSourceMapping', {
      BatchSize: 1,
      EventSourceArn: Match.anyValue(),
    });
  });
});

describe('IAM', () => {
  function policyStatements() {
    const policies = template.findResources('AWS::IAM::Policy');
    return Object.values(policies).flatMap(
      (policy) => policy.Properties.PolicyDocument.Statement,
    );
  }

  test('DynamoDBテーブルへの読み書き権限が付与される', () => {
    const statement = policyStatements().find(
      (s) => Array.isArray(s.Action) && s.Action.includes('dynamodb:PutItem'),
    );
    expect(statement).toBeDefined();
  });

  test('chat-fnにS3 Vectorsの検索権限が付与される', () => {
    const statement = policyStatements().find(
      (s) => Array.isArray(s.Action) && s.Action.includes('s3vectors:QueryVectors'),
    );
    expect(statement).toBeDefined();
    expect(statement.Action).toContain('s3vectors:GetVectors');
    expect(statement.Action).toContain('s3vectors:GetIndex');
  });

  test('ingest-fnにS3 Vectorsの登録・削除権限が付与される', () => {
    const statement = policyStatements().find(
      (s) => Array.isArray(s.Action) && s.Action.includes('s3vectors:PutVectors'),
    );
    expect(statement).toBeDefined();
    expect(statement.Action).toContain('s3vectors:DeleteVectors');
  });

  test('SSM SecureStringの読み取り権限が付与される', () => {
    const statements = policyStatements().filter(
      (s) => Array.isArray(s.Action) && s.Action.includes('ssm:GetParameter'),
    );
    // chat-fn(openai + cohere)とingest-fn(cohere)
    expect(statements.length).toBeGreaterThanOrEqual(2);
    expect(JSON.stringify(statements)).toContain(
      `parameter${OPENAI_API_KEY_PARAMETER_NAME}`,
    );
    expect(JSON.stringify(statements)).toContain(
      `parameter${COHERE_API_KEY_PARAMETER_NAME}`,
    );
  });

  test('api-fnにSQS送信権限、ingest-fnにSQS消費権限が付与される', () => {
    const statements = policyStatements();
    expect(
      statements.find((s) => Array.isArray(s.Action) && s.Action.includes('sqs:SendMessage')),
    ).toBeDefined();
    expect(
      statements.find(
        (s) => Array.isArray(s.Action) && s.Action.includes('sqs:ReceiveMessage'),
      ),
    ).toBeDefined();
  });
});

// backendソースの変更でイメージアセットハッシュが変わるため、
// スナップショットはbackend編集のたびに更新される(意図した挙動)
test('スナップショット', () => {
  expect(template.toJSON()).toMatchSnapshot();
});
