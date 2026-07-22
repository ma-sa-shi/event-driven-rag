import * as cdk from 'aws-cdk-lib/core';
import { Construct } from 'constructs';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3vectors from 'aws-cdk-lib/aws-s3vectors';
import * as sqs from 'aws-cdk-lib/aws-sqs';

/**
 * データ層スタック。
 * DynamoDBシングルテーブル、S3バケット、S3 Vectors、取込用SQS、
 * 認証のCognito User Poolを管理する。
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

    // Users / Documents / Chat / Chat Messages を1テーブルで管理するシングルテーブル
    this.table = new dynamodb.Table(this, 'Table', {
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // 全ユーザー横断一覧用。ChatはGSI1PK=CHAT、DocumentはGSI1PK=DOCで共用する
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI1',
      partitionKey: { name: 'GSI1PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI1SK', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // SPA配信用。CloudFront OACからの読み取り許可はEdgeStackで設定する
    this.spaBucket = new s3.Bucket(this, 'SpaBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // ドキュメント保存用。SPAからpresigned URLで直接PUT/GETする
    this.documentsBucket = new s3.Bucket(this, 'DocumentsBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      cors: [
        {
          // TODO: EdgeStackでCloudFrontドメイン確定後にallowedOriginsを絞る
          allowedMethods: [s3.HttpMethods.PUT, s3.HttpMethods.GET],
          allowedOrigins: ['*'],
          allowedHeaders: ['*'],
        },
      ],
    });

    this.vectorBucket = new s3vectors.CfnVectorBucket(this, 'VectorBucket');

    this.vectorIndex = new s3vectors.CfnIndex(this, 'VectorIndex', {
      vectorBucketArn: this.vectorBucket.attrVectorBucketArn,
      dataType: 'float32',
      // text-embedding-3-largeの次元数
      dimension: 3072,
      distanceMetric: 'cosine',
      metadataConfiguration: {
        // 作成後に変更できない。text=チャンク本文、filename=出典表示用。
        // filterableなmetadataはdocumentIdのみ(書き込み時に付与)
        nonFilterableMetadataKeys: ['text', 'filename'],
      },
    });

    this.ingestDeadLetterQueue = new sqs.Queue(this, 'IngestDeadLetterQueue', {
      retentionPeriod: cdk.Duration.days(14),
    });

    this.ingestQueue = new sqs.Queue(this, 'IngestQueue', {
      // ingest-fnの想定最大実行時間(Lambda上限15分)に合わせる
      visibilityTimeout: cdk.Duration.seconds(900),
      deadLetterQueue: {
        queue: this.ingestDeadLetterQueue,
        maxReceiveCount: 3,
      },
    });

    // 認証。管理者がユーザーを作成し招待メールを送る運用のためセルフサインアップは無効
    // (詳細はdocs/authorization.md、ADR-0004)
    this.userPool = new cognito.UserPool(this, 'UserPool', {
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

    // prefixはグローバル一意制約があるためアカウントIDで衝突を避ける
    this.userPoolDomain = this.userPool.addDomain('HostedUiDomain', {
      cognitoDomain: { domainPrefix: `event-driven-rag-${this.account}` },
    });

    // SPA用パブリッククライアント。シークレットなしのAuthorization Code + PKCE
    this.userPoolClient = this.userPool.addClient('SpaClient', {
      generateSecret: false,
      preventUserExistenceErrors: true,
      oAuth: {
        flows: { authorizationCodeGrant: true },
        // profileは表示名(name)の取得に必要
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
        // TODO: EdgeStack実装時にCloudFrontドメインのURLを追加する
        callbackUrls: ['http://localhost:5173/auth/callback'],
        logoutUrls: ['http://localhost:5173'],
      },
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(30),
    });

    new cdk.CfnOutput(this, 'TableName', { value: this.table.tableName });
    new cdk.CfnOutput(this, 'SpaBucketName', { value: this.spaBucket.bucketName });
    new cdk.CfnOutput(this, 'DocumentsBucketName', { value: this.documentsBucket.bucketName });
    new cdk.CfnOutput(this, 'VectorBucketArn', { value: this.vectorBucket.attrVectorBucketArn });
    new cdk.CfnOutput(this, 'VectorIndexArn', { value: this.vectorIndex.attrIndexArn });
    new cdk.CfnOutput(this, 'IngestQueueUrl', { value: this.ingestQueue.queueUrl });
    new cdk.CfnOutput(this, 'UserPoolId', { value: this.userPool.userPoolId });
    new cdk.CfnOutput(this, 'UserPoolClientId', { value: this.userPoolClient.userPoolClientId });
    // SPAのVITE_COGNITO_AUTHORITYとバックエンドのCOGNITO_ISSUERに使う
    new cdk.CfnOutput(this, 'CognitoIssuer', { value: this.userPool.userPoolProviderUrl });
    // SPAのVITE_COGNITO_DOMAIN(サインアウトの/logoutリダイレクト)に使う
    new cdk.CfnOutput(this, 'CognitoDomainUrl', { value: this.userPoolDomain.baseUrl() });
  }
}
