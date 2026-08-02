import * as path from "node:path";
import * as cdk from "aws-cdk-lib/core";
import { Construct } from "constructs";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as ecr from "aws-cdk-lib/aws-ecr";
import { Platform } from "aws-cdk-lib/aws-ecr-assets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { SqsEventSource } from "aws-cdk-lib/aws-lambda-event-sources";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { DataStack } from "./data-stack";

// SecureStringはCloudFormationで作成できない為、パラメータ本体は手動作成する
// 手順はcdk/README.mdに記載
// CDKは名前参照で読み取り権限のみ付与し、
// CDK上ではパラメータ名のみを参照して読み取り権限を付与し、Lambdaには値ではなくパラメータ名を環境変数として渡す（ADR-0008）
export const OPENAI_API_KEY_PARAMETER_NAME = "/event-driven-rag/openai-api-key";
export const COHERE_API_KEY_PARAMETER_NAME = "/event-driven-rag/cohere-api-key";

// API Gatewayの統合タイムアウトの上限は、サービスクォータ
// `Maximum integration timeout in milliseconds`(L-E5AE38E3)で決まる。既定は29秒である。
// api-fnのLambdaタイムアウトは30秒だが、統合側は上限の29秒で打ち切る
export const API_INTEGRATION_TIMEOUT = cdk.Duration.seconds(29);
// SSEはストリーム全体が統合タイムアウトに収まる必要がある。
// chat-fnのLambdaタイムアウト300秒に合わせるにはクォータの引き上げが要る。引き上げ後に300秒へ変更する
export const CHAT_INTEGRATION_TIMEOUT = cdk.Duration.seconds(29);

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
  public readonly restApi: apigateway.RestApi;

  constructor(scope: Construct, id: string, props: AppStackProps) {
    super(scope, id, props);

    const { dataStack } = props;

    // CI/CD用の常設リポジトリ
    // CIが build → push → update-function-code で使う
    // 現時点のLambdaは下記のイメージアセット(bootstrapのアセットリポジトリ)を参照する
    this.repository = new ecr.Repository(this, "Repository", {
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });

    const backendPath = path.join(__dirname, "..", "..", "apps", "backend");

    // web: Lambda Web Adapter + uvicorn(api-fn)
    const webImage = lambda.DockerImageCode.fromImageAsset(backendPath, {
      target: "web",
      platform: Platform.LINUX_AMD64,
    });

    // chat: webにLangGraph / LangChainを追加した構成(chat-fn)。
    // RAG関連ライブラリはイメージサイズが大きくapi-fnのコールドスタートを長くする為、分離する
    const chatImage = lambda.DockerImageCode.fromImageAsset(backendPath, {
      target: "chat",
      platform: Platform.LINUX_AMD64,
    });
    // worker: awslambdaricによる軽量ハンドラ構成(ingest-fn)
    const workerImage = lambda.DockerImageCode.fromImageAsset(backendPath, {
      target: "worker",
      platform: Platform.LINUX_AMD64,
    });

    const openaiApiKeyParameter =
      ssm.StringParameter.fromSecureStringParameterAttributes(
        this,
        "OpenaiApiKeyParameter",
        { parameterName: OPENAI_API_KEY_PARAMETER_NAME },
      );
    const cohereApiKeyParameter =
      ssm.StringParameter.fromSecureStringParameterAttributes(
        this,
        "CohereApiKeyParameter",
        { parameterName: COHERE_API_KEY_PARAMETER_NAME },
      );

    // --- REST API Lambda (api-fn) ---
    // 認証、一覧、presigned URL発行、取込開始のSQS送信
    this.apiFunction = new lambda.DockerImageFunction(this, "ApiFunction", {
      code: webImage,
      memorySize: 512,
      timeout: cdk.Duration.seconds(30),
      environment: {
        TABLE_NAME: dataStack.table.tableName,
        DOCUMENTS_BUCKET_NAME: dataStack.documentsBucket.bucketName,
        INGEST_QUEUE_URL: dataStack.ingestQueue.queueUrl,
        COGNITO_ISSUER: dataStack.userPool.userPoolProviderUrl,
        COGNITO_CLIENT_ID: dataStack.userPoolClient.userPoolClientId,
        POWERTOOLS_SERVICE_NAME: "api",
        POWERTOOLS_LOG_LEVEL: "INFO",
      },
    });

    dataStack.table.grantReadWriteData(this.apiFunction);
    // 署名付きURLはLambdaロールの権限で署名される為、発行対象の操作権限が必要
    dataStack.documentsBucket.grantReadWrite(this.apiFunction);
    dataStack.ingestQueue.grantSendMessages(this.apiFunction);

    // --- チャット Lambda (chat-fn) ---
    // LangGraph Self-RAGによるSSEストリーミングチャット
    this.chatFunction = new lambda.DockerImageFunction(this, "ChatFunction", {
      code: chatImage,
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
        // 統合のResponseTransferMode STREAMとセットで必要(片方のみではバッファリングされる)
        AWS_LWA_INVOKE_MODE: "response_stream",
        POWERTOOLS_SERVICE_NAME: "chat",
        POWERTOOLS_LOG_LEVEL: "INFO",
      },
    });

    dataStack.table.grantReadWriteData(this.chatFunction);
    this.chatFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "s3vectors:GetIndex",
          "s3vectors:QueryVectors",
          "s3vectors:GetVectors",
        ],
        resources: [dataStack.vectorIndex.attrIndexArn],
      }),
    );
    openaiApiKeyParameter.grantRead(this.chatFunction);
    cohereApiKeyParameter.grantRead(this.chatFunction);

    // --- ドキュメント取込 Worker Lambda (ingest-fn) ---
    // テキスト抽出 → チャンク分割 → embedding → S3 Vectors登録(SQSトリガー)
    this.ingestFunction = new lambda.DockerImageFunction(
      this,
      "IngestFunction",
      {
        code: workerImage,
        memorySize: 1024,
        // SQSの可視性タイムアウト900秒以内に収める
        timeout: cdk.Duration.seconds(600),
        environment: {
          TABLE_NAME: dataStack.table.tableName,
          DOCUMENTS_BUCKET_NAME: dataStack.documentsBucket.bucketName,
          VECTOR_BUCKET_ARN: dataStack.vectorBucket.attrVectorBucketArn,
          VECTOR_INDEX_ARN: dataStack.vectorIndex.attrIndexArn,
          COHERE_API_KEY_PARAMETER_NAME,
          POWERTOOLS_SERVICE_NAME: "ingest",
          POWERTOOLS_LOG_LEVEL: "INFO",
        },
      },
    );

    // 1ドキュメントの処理が長いため1メッセージずつ起動する
    this.ingestFunction.addEventSource(
      new SqsEventSource(dataStack.ingestQueue, { batchSize: 1 }),
    );

    dataStack.table.grantReadWriteData(this.ingestFunction);
    dataStack.documentsBucket.grantRead(this.ingestFunction);
    this.ingestFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "s3vectors:GetIndex",
          "s3vectors:PutVectors",
          // 再取込でチャンク数が減ったときの余剰ベクトル削除用
          "s3vectors:DeleteVectors",
        ],
        resources: [dataStack.vectorIndex.attrIndexArn],
      }),
    );
    cohereApiKeyParameter.grantRead(this.ingestFunction);

    // --- API Gateway ---
    // api-fnとchat-fnの唯一の公開経路。CloudFrontの`/api/*`のオリジンになる。
    // CloudFrontのみを許可するリソースポリシーは張らず、
    // 直接アクセスはオーソライザとスロットリングでLambda起動前に止める(ADR-0011)
    this.restApi = new apigateway.RestApi(this, "RestApi", {
      // CloudFrontを前段に置く為、エッジ最適化ではなくリージョナルにする
      endpointTypes: [apigateway.EndpointType.REGIONAL],
      deployOptions: {
        stageName: "prod",
        // 想定は月400〜600チャットであり、通常利用が当たる水準ではない
        throttlingRateLimit: 20,
        throttlingBurstLimit: 40,
      },
    });

    // Lambda起動前にJWTを検証する。FastAPI側の検証は残し、認可(誰のデータか)はアプリで行う(ADR-0004)
    const authorizer = new apigateway.CognitoUserPoolsAuthorizer(
      this,
      "CognitoAuthorizer",
      { cognitoUserPools: [dataStack.userPool] },
    );
    const authorized: apigateway.MethodOptions = {
      authorizer,
      authorizationType: apigateway.AuthorizationType.COGNITO,
      // Cognitoオーソライザは既定でIDトークンとして検証する為、
      // アクセストークンを送る本システムでは指定しないと全て401になる。
      // authorizationScopesを指定するとアクセストークンのscopeクレームで検証する。
      // SPAが要求するスコープはopenid / email / profileであり、共通するopenidを要求する
      authorizationScopes: ["openid"],
    };

    const apiIntegration = new apigateway.LambdaIntegration(this.apiFunction, {
      timeout: API_INTEGRATION_TIMEOUT,
    });
    // SSEはSTREAMを指定しないとレスポンス全体が揃うまで送出されない
    const chatIntegration = new apigateway.LambdaIntegration(
      this.chatFunction,
      {
        responseTransferMode: apigateway.ResponseTransferMode.STREAM,
        timeout: CHAT_INTEGRATION_TIMEOUT,
      },
    );

    // FastAPIのルートは全て`/api`配下にある(CloudFrontの`/api/*`と一致させる為)
    const apiResource = this.restApi.root.addResource("api");

    // ヘルスチェックは無認証。オーソライザを付けない唯一のルート
    apiResource.addResource("health").addMethod("GET", apiIntegration);

    // `/api/chats`直下にchat-fnとapi-fnの両方のルートがある為、
    // `/api/{proxy+}`だけでは足りず、chats配下を明示的に分岐させる。
    // API Gatewayはグリーディパスより具体的なリソースを優先する
    const chats = apiResource.addResource("chats");
    chats.addResource("stream").addMethod("POST", chatIntegration, authorized);
    chats.addMethod("ANY", apiIntegration, authorized);
    chats.addResource("{proxy+}").addMethod("ANY", apiIntegration, authorized);

    apiResource
      .addResource("{proxy+}")
      .addMethod("ANY", apiIntegration, authorized);

    new cdk.CfnOutput(this, "EcrRepositoryUri", {
      value: this.repository.repositoryUri,
    });
    new cdk.CfnOutput(this, "ApiFunctionName", {
      value: this.apiFunction.functionName,
    });
    new cdk.CfnOutput(this, "ChatFunctionName", {
      value: this.chatFunction.functionName,
    });
    new cdk.CfnOutput(this, "IngestFunctionName", {
      value: this.ingestFunction.functionName,
    });
  }
}
