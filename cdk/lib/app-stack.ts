import * as path from 'node:path';
import * as cdk from 'aws-cdk-lib/core';
import { Construct } from 'constructs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import { Platform } from 'aws-cdk-lib/aws-ecr-assets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { DataStack } from './data-stack';

// SecureStringはCloudFormationで作成できないため、パラメータ本体は手動作成する
// (手順はcdk/README.md参照)。CDKは名前参照で読み取り権限のみ付与し、
// Lambdaへはパラメータ名を環境変数で渡す(値は渡さない)。ADR-0008参照。
export const OPENAI_API_KEY_PARAMETER_NAME = '/event-driven-rag/openai-api-key';
export const COHERE_API_KEY_PARAMETER_NAME = '/event-driven-rag/cohere-api-key';

export interface AppStackProps extends cdk.StackProps {
  dataStack: DataStack;
}

/**
 * アプリケーション層スタック。
 * 単一のbackendコードベースを責務別に3つのコンテナLambda
 * (api-fn / chat-fn / ingest-fn)としてデプロイする(ADR-0003)。
 */
export class AppStack extends cdk.Stack {
  public readonly repository: ecr.Repository;
  public readonly apiFunction: lambda.DockerImageFunction;
  public readonly chatFunction: lambda.DockerImageFunction;
  public readonly ingestFunction: lambda.DockerImageFunction;
  public readonly apiFunctionUrl: lambda.FunctionUrl;
  public readonly chatFunctionUrl: lambda.FunctionUrl;

  constructor(scope: Construct, id: string, props: AppStackProps) {
    super(scope, id, props);

    const { dataStack } = props;

    // CI/CD用の常設リポジトリ(CIが build → push → update-function-code で使う)。
    // 現時点のLambdaは下のイメージアセット(bootstrapのアセットリポジトリ)を参照する
    this.repository = new ecr.Repository(this, 'Repository', {
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });

    const backendPath = path.join(__dirname, '..', '..', 'apps', 'backend');
    // web: Lambda Web Adapter + uvicorn(api-fn / chat-fn)
    const webImage = lambda.DockerImageCode.fromImageAsset(backendPath, {
      target: 'web',
      platform: Platform.LINUX_AMD64,
    });
    // worker: awslambdaricによるプレーンハンドラ(ingest-fn)
    const workerImage = lambda.DockerImageCode.fromImageAsset(backendPath, {
      target: 'worker',
      platform: Platform.LINUX_AMD64,
    });

    const openaiApiKeyParameter = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      'OpenaiApiKeyParameter',
      { parameterName: OPENAI_API_KEY_PARAMETER_NAME },
    );
    const cohereApiKeyParameter = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      'CohereApiKeyParameter',
      { parameterName: COHERE_API_KEY_PARAMETER_NAME },
    );

    // REST API(認証、一覧、presigned URL発行、取込開始のSQS送信)
    this.apiFunction = new lambda.DockerImageFunction(this, 'ApiFunction', {
      code: webImage,
      memorySize: 512,
      timeout: cdk.Duration.seconds(30),
      environment: {
        TABLE_NAME: dataStack.table.tableName,
        DOCUMENTS_BUCKET_NAME: dataStack.documentsBucket.bucketName,
        INGEST_QUEUE_URL: dataStack.ingestQueue.queueUrl,
        COGNITO_ISSUER: dataStack.userPool.userPoolProviderUrl,
        COGNITO_CLIENT_ID: dataStack.userPoolClient.userPoolClientId,
        POWERTOOLS_SERVICE_NAME: 'api',
        POWERTOOLS_LOG_LEVEL: 'INFO',
      },
    });

    // TODO: EdgeStack実装時にAWS_IAM + CloudFront OACへ切り替える
    this.apiFunctionUrl = this.apiFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
    });

    dataStack.table.grantReadWriteData(this.apiFunction);
    // presigned URLはLambdaロールの権限で署名されるため、発行対象の操作権限が必要
    dataStack.documentsBucket.grantReadWrite(this.apiFunction);
    dataStack.ingestQueue.grantSendMessages(this.apiFunction);

    // LangGraph Self-RAGによるSSEストリーミングチャット
    this.chatFunction = new lambda.DockerImageFunction(this, 'ChatFunction', {
      code: webImage,
      memorySize: 1024,
      timeout: cdk.Duration.seconds(300),
      environment: {
        TABLE_NAME: dataStack.table.tableName,
        VECTOR_BUCKET_ARN: dataStack.vectorBucket.attrVectorBucketArn,
        VECTOR_INDEX_ARN: dataStack.vectorIndex.attrIndexArn,
        COGNITO_ISSUER: dataStack.userPool.userPoolProviderUrl,
        COGNITO_CLIENT_ID: dataStack.userPoolClient.userPoolClientId,
        OPENAI_API_KEY_PARAMETER_NAME,
        COHERE_API_KEY_PARAMETER_NAME,
        // Function URLのRESPONSE_STREAMとセットで必要(片方だけだとバッファリングされる)
        AWS_LWA_INVOKE_MODE: 'response_stream',
        POWERTOOLS_SERVICE_NAME: 'chat',
        POWERTOOLS_LOG_LEVEL: 'INFO',
      },
    });

    // TODO: EdgeStack実装時にAWS_IAM + CloudFront OACへ切り替える
    this.chatFunctionUrl = this.chatFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
    });

    dataStack.table.grantReadWriteData(this.chatFunction);
    this.chatFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['s3vectors:GetIndex', 's3vectors:QueryVectors', 's3vectors:GetVectors'],
        resources: [dataStack.vectorIndex.attrIndexArn],
      }),
    );
    openaiApiKeyParameter.grantRead(this.chatFunction);
    cohereApiKeyParameter.grantRead(this.chatFunction);

    // テキスト抽出 → チャンク分割 → embedding → S3 Vectors登録(SQSトリガー)
    this.ingestFunction = new lambda.DockerImageFunction(this, 'IngestFunction', {
      code: workerImage,
      memorySize: 1024,
      // SQSの可視性タイムアウト900秒以内に収める
      timeout: cdk.Duration.seconds(600),
      environment: {
        TABLE_NAME: dataStack.table.tableName,
        DOCUMENTS_BUCKET_NAME: dataStack.documentsBucket.bucketName,
        VECTOR_BUCKET_ARN: dataStack.vectorBucket.attrVectorBucketArn,
        VECTOR_INDEX_ARN: dataStack.vectorIndex.attrIndexArn,
        OPENAI_API_KEY_PARAMETER_NAME,
        POWERTOOLS_SERVICE_NAME: 'ingest',
        POWERTOOLS_LOG_LEVEL: 'INFO',
      },
    });

    // 1ドキュメントの処理が長いため1メッセージずつ起動する
    this.ingestFunction.addEventSource(
      new SqsEventSource(dataStack.ingestQueue, { batchSize: 1 }),
    );

    dataStack.table.grantReadWriteData(this.ingestFunction);
    dataStack.documentsBucket.grantRead(this.ingestFunction);
    this.ingestFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          's3vectors:GetIndex',
          's3vectors:PutVectors',
          // 再取込時の既存ベクトル削除用
          's3vectors:ListVectors',
          's3vectors:DeleteVectors',
        ],
        resources: [dataStack.vectorIndex.attrIndexArn],
      }),
    );
    openaiApiKeyParameter.grantRead(this.ingestFunction);

    new cdk.CfnOutput(this, 'ApiFunctionUrl', { value: this.apiFunctionUrl.url });
    new cdk.CfnOutput(this, 'ChatFunctionUrl', { value: this.chatFunctionUrl.url });
    new cdk.CfnOutput(this, 'EcrRepositoryUri', { value: this.repository.repositoryUri });
    new cdk.CfnOutput(this, 'ApiFunctionName', { value: this.apiFunction.functionName });
    new cdk.CfnOutput(this, 'ChatFunctionName', { value: this.chatFunction.functionName });
    new cdk.CfnOutput(this, 'IngestFunctionName', { value: this.ingestFunction.functionName });
  }
}
