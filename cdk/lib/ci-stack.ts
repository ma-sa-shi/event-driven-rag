import * as cdk from "aws-cdk-lib/core";
import { Construct } from "constructs";
import * as iam from "aws-cdk-lib/aws-iam";
import { AppStack } from "./app-stack";
import { DataStack } from "./data-stack";
import { EdgeStack } from "./edge-stack";

const GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com";
const GITHUB_OIDC_AUDIENCE = "sts.amazonaws.com";

// GitHubは2026-07-15以降に作成されたリポジトリのOIDCトークンで、subクレームに
// ownerとrepositoryの数値IDを含める(immutable subject claims)。
// 本リポジトリは2026-07-18作成の為この形式であり、名前だけの旧形式を書くと
// AssumeRoleWithWebIdentityが失敗する。
// IDの確認: gh api /repos/<owner>/<repo> --jq '{id, owner_id: .owner.id}'
const GITHUB_OWNER = "ma-sa-shi";
const GITHUB_OWNER_ID = 265779122;
const GITHUB_REPOSITORY_NAME = "event-driven-rag";
const GITHUB_REPOSITORY_ID = 1304510072;
const DEPLOY_BRANCH = "main";

export const DEPLOY_SUBJECT = `repo:${GITHUB_OWNER}@${GITHUB_OWNER_ID}/${GITHUB_REPOSITORY_NAME}@${GITHUB_REPOSITORY_ID}:ref:refs/heads/${DEPLOY_BRANCH}`;

// ワークフローがARNを組み立てられるよう物理名を固定する
export const DEPLOY_ROLE_NAME = "event-driven-rag-github-actions";

export interface CiStackProps extends cdk.StackProps {
  dataStack: DataStack;
  appStack: AppStack;
  edgeStack: EdgeStack;
}

/**
 * CI/CD基盤スタック。
 * GitHub ActionsがOIDCで引き受けるデプロイ用ロールを管理する。
 * ワークフローは`cdk deploy`を行わずSPA同期とLambdaのイメージ更新だけを担う為、
 * 権限はその2フローに必要な操作へ限定する。
 */
export class CiStack extends cdk.Stack {
  public readonly deployRole: iam.Role;

  constructor(scope: Construct, id: string, props: CiStackProps) {
    super(scope, id, props);

    const { dataStack, appStack, edgeStack } = props;

    // L2のOpenIdConnectProviderはCustom Resource用のLambdaを増やす為、L1を直接使う。
    // thumbprintListは省略する(IAMがGitHubの証明書から取得する)
    const oidcProvider = new iam.CfnOIDCProvider(this, "GithubOidcProvider", {
      url: GITHUB_OIDC_URL,
      clientIdList: [GITHUB_OIDC_AUDIENCE],
    });

    // subはワイルドカードを使わず完全一致にし、他リポジトリ・他ブランチからの引き受けを塞ぐ
    const githubPrincipal = new iam.WebIdentityPrincipal(oidcProvider.attrArn, {
      StringEquals: {
        "token.actions.githubusercontent.com:aud": GITHUB_OIDC_AUDIENCE,
        "token.actions.githubusercontent.com:sub": DEPLOY_SUBJECT,
      },
    });

    this.deployRole = new iam.Role(this, "DeployRole", {
      roleName: DEPLOY_ROLE_NAME,
      assumedBy: githubPrincipal,
      description: "GitHub Actions deploy role (SPA sync / Lambda image update)",
    });

    // --- SPA配信(Build → S3 Sync → CloudFront Invalidation) ---
    // s3 syncは差分判定でバケット一覧とオブジェクト取得を行う
    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["s3:ListBucket", "s3:GetBucketLocation"],
        resources: [edgeStack.spaBucket.bucketArn],
      }),
    );
    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        // --deleteで消える古いアセットがある為DeleteObjectも要る
        actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
        resources: [edgeStack.spaBucket.arnForObjects("*")],
      }),
    );
    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["cloudfront:CreateInvalidation"],
        resources: [edgeStack.distribution.distributionArn],
      }),
    );

    // --- バックエンド(Docker Build → ECR Push → Lambda Update) ---
    // GetAuthorizationTokenはリソース単位のスコープを取れない唯一の操作
    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["ecr:GetAuthorizationToken"],
        resources: ["*"],
      }),
    );
    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
          // buildxのキャッシュ参照で既存イメージを読む
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ],
        resources: [appStack.repository.repositoryArn],
      }),
    );
    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        // GetFunctionConfigurationは更新完了を待つwaiterが使う
        actions: [
          "lambda:UpdateFunctionCode",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
        ],
        resources: [
          appStack.apiFunction.functionArn,
          appStack.chatFunction.functionArn,
          appStack.ingestFunction.functionArn,
        ],
      }),
    );

    // --- スタック出力の読み取り ---
    // バケット名や関数名をGitHub側へ複製せず、デプロイのたびに出力から取得する
    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["cloudformation:DescribeStacks"],
        resources: [dataStack, appStack, edgeStack].map((stack) =>
          this.formatArn({
            service: "cloudformation",
            resource: "stack",
            // スタックARNの末尾はCloudFormationが払い出すUUIDになる
            resourceName: `${stack.stackName}/*`,
          }),
        ),
      }),
    );

    new cdk.CfnOutput(this, "DeployRoleArn", {
      value: this.deployRole.roleArn,
    });
  }
}
