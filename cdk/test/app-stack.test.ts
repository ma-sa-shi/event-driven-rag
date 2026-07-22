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
    expect(env.OPENAI_API_KEY_PARAMETER_NAME).toBe(OPENAI_API_KEY_PARAMETER_NAME);
    expect(env).not.toHaveProperty('COHERE_API_KEY_PARAMETER_NAME');
  });

  test('ingest-fnはworkerターゲットの別イメージを使う', () => {
    const [, apiFn] = findFunctionByServiceName('api');
    const [, chatFn] = findFunctionByServiceName('chat');
    const [, ingestFn] = findFunctionByServiceName('ingest');
    // web(api/chat)は同一アセット、worker(ingest)は別アセット
    expect(apiFn.Properties.Code.ImageUri).toEqual(chatFn.Properties.Code.ImageUri);
    expect(ingestFn.Properties.Code.ImageUri).not.toEqual(apiFn.Properties.Code.ImageUri);
  });
});

describe('Function URL', () => {
  test('api-fnとchat-fnの2つだけ作成される', () => {
    template.resourceCountIs('AWS::Lambda::Url', 2);
  });

  // TODO: EdgeStack実装時にAWS_IAM + CloudFront OACへ切り替える
  test('認証タイプは当面NONEで公開される', () => {
    const urls = template.findResources('AWS::Lambda::Url');
    for (const url of Object.values(urls)) {
      expect(url.Properties.AuthType).toBe('NONE');
    }
    template.hasResourceProperties('AWS::Lambda::Permission', {
      Action: 'lambda:InvokeFunctionUrl',
      Principal: '*',
      FunctionUrlAuthType: 'NONE',
    });
  });

  test('chat-fnのFunction URLはRESPONSE_STREAMを有効化する', () => {
    template.hasResourceProperties('AWS::Lambda::Url', {
      InvokeMode: 'RESPONSE_STREAM',
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
    expect(statement.Action).toContain('s3vectors:ListVectors');
    expect(statement.Action).toContain('s3vectors:DeleteVectors');
  });

  test('SSM SecureStringの読み取り権限が付与される', () => {
    const statements = policyStatements().filter(
      (s) => Array.isArray(s.Action) && s.Action.includes('ssm:GetParameter'),
    );
    // chat-fn(openai + cohere)とingest-fn(openai)
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
