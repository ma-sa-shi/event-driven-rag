import * as cdk from 'aws-cdk-lib/core';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { DataStack } from '../lib/data-stack';

let template: Template;

beforeAll(() => {
  const app = new cdk.App();
  const stack = new DataStack(app, 'TestDataStack');
  template = Template.fromStack(stack);
});

describe('DynamoDB', () => {
  test('PK/SKのシングルテーブルがオンデマンドで作成される', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      BillingMode: 'PAY_PER_REQUEST',
      KeySchema: [
        { AttributeName: 'PK', KeyType: 'HASH' },
        { AttributeName: 'SK', KeyType: 'RANGE' },
      ],
    });
  });

  test('横断一覧用のGSI1が定義される', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      GlobalSecondaryIndexes: [
        {
          IndexName: 'GSI1',
          KeySchema: [
            { AttributeName: 'GSI1PK', KeyType: 'HASH' },
            { AttributeName: 'GSI1SK', KeyType: 'RANGE' },
          ],
          Projection: { ProjectionType: 'ALL' },
        },
      ],
    });
  });

  test('スタック削除時にテーブルも削除される', () => {
    template.hasResource('AWS::DynamoDB::Table', {
      DeletionPolicy: 'Delete',
    });
  });
});

describe('S3', () => {
  test('SPA配信用とドキュメント保存用の2バケットが作成される', () => {
    template.resourceCountIs('AWS::S3::Bucket', 2);
  });

  test('全バケットでパブリックアクセスをブロックする', () => {
    const buckets = template.findResources('AWS::S3::Bucket');
    for (const bucket of Object.values(buckets)) {
      expect(bucket.Properties.PublicAccessBlockConfiguration).toEqual({
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      });
    }
  });

  test('ドキュメントバケットにpresigned PUT/GET用のCORSが設定される', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      CorsConfiguration: {
        CorsRules: [
          {
            AllowedMethods: ['PUT', 'GET'],
            AllowedOrigins: ['*'],
            AllowedHeaders: ['*'],
          },
        ],
      },
    });
  });
});

describe('S3 Vectors', () => {
  test('ベクトルバケットが作成される', () => {
    template.resourceCountIs('AWS::S3Vectors::VectorBucket', 1);
  });

  test('text-embedding-3-large向けのインデックスが作成される', () => {
    template.hasResourceProperties('AWS::S3Vectors::Index', {
      VectorBucketArn: Match.anyValue(),
      DataType: 'float32',
      Dimension: 3072,
      DistanceMetric: 'cosine',
      MetadataConfiguration: {
        NonFilterableMetadataKeys: ['text', 'filename'],
      },
    });
  });
});

describe('SQS', () => {
  test('取込キューとDLQの2キューが作成される', () => {
    template.resourceCountIs('AWS::SQS::Queue', 2);
  });

  test('取込キューはDLQへのリドライブと可視性タイムアウトを設定する', () => {
    template.hasResourceProperties('AWS::SQS::Queue', {
      VisibilityTimeout: 900,
      RedrivePolicy: {
        maxReceiveCount: 3,
        deadLetterTargetArn: Match.anyValue(),
      },
    });
  });

  test('DLQは14日間メッセージを保持する', () => {
    template.hasResourceProperties('AWS::SQS::Queue', {
      MessageRetentionPeriod: 1209600,
    });
  });
});

describe('Cognito', () => {
  test('セルフサインアップ無効・email/name必須のUser Poolが作成される', () => {
    template.hasResourceProperties('AWS::Cognito::UserPool', {
      AdminCreateUserConfig: { AllowAdminCreateUserOnly: true },
      AutoVerifiedAttributes: ['email'],
      UsernameAttributes: ['email'],
      Schema: Match.arrayWith([
        Match.objectLike({ Name: 'email', Required: true, Mutable: true }),
        Match.objectLike({ Name: 'name', Required: true, Mutable: true }),
      ]),
    });
  });

  test('スタック削除時にUser Poolも削除される', () => {
    template.hasResource('AWS::Cognito::UserPool', {
      DeletionPolicy: 'Delete',
    });
  });

  test('Hosted UIドメインが作成される', () => {
    template.resourceCountIs('AWS::Cognito::UserPoolDomain', 1);
  });

  test('SPAクライアントはシークレットなしのAuthorization Code + PKCEを設定する', () => {
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      GenerateSecret: false,
      AllowedOAuthFlows: ['code'],
      AllowedOAuthFlowsUserPoolClient: true,
      AllowedOAuthScopes: ['openid', 'email', 'profile'],
      CallbackURLs: ['http://localhost:5173/auth/callback'],
      LogoutURLs: ['http://localhost:5173'],
      PreventUserExistenceErrors: 'ENABLED',
    });
  });

  test('トークン有効期限はaccess/id 1時間、refresh 30日を設定する', () => {
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      AccessTokenValidity: 60,
      IdTokenValidity: 60,
      RefreshTokenValidity: 43200,
      TokenValidityUnits: {
        AccessToken: 'minutes',
        IdToken: 'minutes',
        RefreshToken: 'minutes',
      },
    });
  });
});

test('スナップショット', () => {
  expect(template.toJSON()).toMatchSnapshot();
});
