import * as cdk from 'aws-cdk-lib/core';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3vectors from 'aws-cdk-lib/aws-s3vectors';
import * as sqs from 'aws-cdk-lib/aws-sqs';

/**
 * データ層スタック。
 * DynamoDBシングルテーブル、S3バケット、S3 Vectors、取込用SQSを管理する。
 */
export class DataStack extends cdk.Stack {
  public readonly table: dynamodb.Table;
  public readonly spaBucket: s3.Bucket;
  public readonly documentsBucket: s3.Bucket;
  public readonly vectorBucket: s3vectors.CfnVectorBucket;
  public readonly vectorIndex: s3vectors.CfnIndex;
  public readonly ingestQueue: sqs.Queue;
  public readonly ingestDeadLetterQueue: sqs.Queue;

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

    new cdk.CfnOutput(this, 'TableName', { value: this.table.tableName });
    new cdk.CfnOutput(this, 'SpaBucketName', { value: this.spaBucket.bucketName });
    new cdk.CfnOutput(this, 'DocumentsBucketName', { value: this.documentsBucket.bucketName });
    new cdk.CfnOutput(this, 'VectorBucketArn', { value: this.vectorBucket.attrVectorBucketArn });
    new cdk.CfnOutput(this, 'VectorIndexArn', { value: this.vectorIndex.attrIndexArn });
    new cdk.CfnOutput(this, 'IngestQueueUrl', { value: this.ingestQueue.queueUrl });
  }
}
