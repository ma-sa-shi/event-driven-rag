import * as cdk from 'aws-cdk-lib/core';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { AppStack } from '../lib/app-stack';
import { CiStack, DEPLOY_ROLE_NAME, DEPLOY_SUBJECT } from '../lib/ci-stack';
import { DataStack } from '../lib/data-stack';
import { EdgeStack } from '../lib/edge-stack';
import { normalizeAssetHashes } from './helpers';

const OIDC_CLAIM_PREFIX = 'token.actions.githubusercontent.com';

let template: Template;

beforeAll(() => {
  const app = new cdk.App();
  const dataStack = new DataStack(app, 'TestDataStack');
  const appStack = new AppStack(app, 'TestAppStack', { dataStack });
  const edgeStack = new EdgeStack(app, 'TestEdgeStack', { appStack, dataStack });
  const ciStack = new CiStack(app, 'TestCiStack', {
    dataStack,
    appStack,
    edgeStack,
  });
  template = Template.fromStack(ciStack);
});

// デプロイロールのインラインポリシーのステートメント一覧
function policyStatements() {
  const policies = template.findResources('AWS::IAM::Policy');
  const [policy] = Object.values(policies);
  return policy.Properties.PolicyDocument.Statement as {
    Action: string | string[];
    Resource: unknown;
  }[];
}

function statementFor(action: string) {
  const matched = policyStatements().filter((statement) =>
    [statement.Action].flat().includes(action),
  );
  expect(matched).toHaveLength(1);
  return matched[0];
}

describe('OIDCプロバイダ', () => {
  test('GitHub Actionsのプロバイダが作成される', () => {
    template.resourceCountIs('AWS::IAM::OIDCProvider', 1);
    template.hasResourceProperties('AWS::IAM::OIDCProvider', {
      Url: 'https://token.actions.githubusercontent.com',
      ClientIdList: ['sts.amazonaws.com'],
    });
  });

  test('Custom Resourceを使わない(Lambdaを作らない)', () => {
    template.resourceCountIs('AWS::Lambda::Function', 0);
  });
});

describe('デプロイロールの信頼ポリシー', () => {
  test('OIDCプロバイダからのWebIdentityのみを受け入れる', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      RoleName: DEPLOY_ROLE_NAME,
      AssumeRolePolicyDocument: {
        Statement: [
          Match.objectLike({
            Action: 'sts:AssumeRoleWithWebIdentity',
            Effect: 'Allow',
            Principal: {
              Federated: { 'Fn::GetAtt': ['GithubOidcProvider', 'Arn'] },
            },
          }),
        ],
      },
    });
  });

  test('audとsubをリポジトリとブランチで完全一致に制限する', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      AssumeRolePolicyDocument: {
        Statement: [
          Match.objectLike({
            Condition: {
              StringEquals: {
                [`${OIDC_CLAIM_PREFIX}:aud`]: 'sts.amazonaws.com',
                [`${OIDC_CLAIM_PREFIX}:sub`]: DEPLOY_SUBJECT,
              },
            },
          }),
        ],
      },
    });
  });

  test('subはimmutable subject claims形式で、ワイルドカードを含まない', () => {
    // 2026-07-15以降に作成されたリポジトリはowner IDとrepository IDをsubに含む。
    // 旧形式のままだとAssumeRoleWithWebIdentityが失敗する
    expect(DEPLOY_SUBJECT).toBe(
      'repo:ma-sa-shi@265779122/event-driven-rag@1304510072:ref:refs/heads/main',
    );
    expect(DEPLOY_SUBJECT).not.toContain('*');
  });

  test('StringLikeによる緩い条件を持たない', () => {
    const roles = template.findResources('AWS::IAM::Role');
    const [role] = Object.values(roles);
    const [statement] = role.Properties.AssumeRolePolicyDocument.Statement;
    expect(Object.keys(statement.Condition)).toEqual(['StringEquals']);
  });
});

describe('デプロイロールの権限', () => {
  test('Resourceが*なのはecr:GetAuthorizationTokenだけ', () => {
    // GetAuthorizationTokenはリソース単位のスコープを取れない。
    // それ以外が*に広がる退行を防ぐ
    const wildcard = policyStatements().filter(
      (statement) => statement.Resource === '*',
    );
    expect(wildcard).toHaveLength(1);
    expect(wildcard[0].Action).toBe('ecr:GetAuthorizationToken');
  });

  test('SPAバケットへの同期に必要な権限を持つ', () => {
    expect(statementFor('s3:ListBucket').Action).toEqual(
      expect.arrayContaining(['s3:GetBucketLocation', 's3:ListBucket']),
    );
    expect(statementFor('s3:PutObject').Action).toEqual(
      expect.arrayContaining([
        's3:DeleteObject',
        's3:GetObject',
        's3:PutObject',
      ]),
    );
  });

  test('CloudFrontはCreateInvalidationのみ許可する', () => {
    const statement = statementFor('cloudfront:CreateInvalidation');
    expect(statement.Action).toBe('cloudfront:CreateInvalidation');
  });

  test('ECRのpush権限は常設リポジトリへスコープされる', () => {
    const statement = statementFor('ecr:PutImage');
    expect(statement.Resource).not.toBe('*');
    expect(JSON.stringify(statement.Resource)).toContain('Repository');
  });

  test('Lambdaの更新は3関数へスコープされる', () => {
    const statement = statementFor('lambda:UpdateFunctionCode');
    expect(statement.Resource).toHaveLength(3);
    const resources = JSON.stringify(statement.Resource);
    for (const fn of ['ApiFunction', 'ChatFunction', 'IngestFunction']) {
      expect(resources).toContain(fn);
    }
  });

  test('DescribeStacksは3スタックへスコープされる', () => {
    const statement = statementFor('cloudformation:DescribeStacks');
    expect(statement.Resource).toHaveLength(3);
    const resources = JSON.stringify(statement.Resource);
    for (const stackName of ['TestDataStack', 'TestAppStack', 'TestEdgeStack']) {
      expect(resources).toContain(`stack/${stackName}/*`);
    }
  });

  test('cdk deployは行わない為、CloudFormationの更新権限を持たない', () => {
    const actions = policyStatements().flatMap((statement) =>
      [statement.Action].flat(),
    );
    expect(actions).not.toContain('cloudformation:CreateStack');
    expect(actions).not.toContain('cloudformation:UpdateStack');
    expect(actions).not.toContain('sts:AssumeRole');
    expect(actions).not.toContain('iam:PassRole');
  });
});

describe('出力', () => {
  test('DeployRoleArnを出力する', () => {
    template.hasOutput('DeployRoleArn', {
      Value: { 'Fn::GetAtt': [Match.stringLikeRegexp('DeployRole'), 'Arn'] },
    });
  });
});

test('スナップショット', () => {
  expect(normalizeAssetHashes(template)).toMatchSnapshot();
});
