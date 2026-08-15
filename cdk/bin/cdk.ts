#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { AppStack } from '../lib/app-stack';
import { CertificateStack } from '../lib/certificate-stack';
import { CiStack } from '../lib/ci-stack';
import { DataStack } from '../lib/data-stack';
import { EdgeStack } from '../lib/edge-stack';

const app = new cdk.App();

const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION };

// 公開ドメイン。既定値はcdk.jsonのcontextにあり、通常は指定不要
const appDomain = app.node.tryGetContext('appDomain') as string | undefined;
if (!appDomain) {
  throw new Error(
    'appDomainコンテキストが未設定です。cdk.jsonの既定値か -c appDomain=... で指定してください',
  );
}

// CloudFrontへ関連付けられる証明書はus-east-1のものに限られる為、このスタックだけ
// リージョンを分ける。EdgeStackからの参照はcdk.jsonのdefaultCrossStackReferencesにより
// デプロイ時に解決される為、リージョンを跨いでも受け渡し用のリソースは増えない
const certificateStack = new CertificateStack(app, 'CertificateStack', {
  env: { account: env.account, region: 'us-east-1' },
  domainName: appDomain,
});

const dataStack = new DataStack(app, 'DataStack', { env });

const appStack = new AppStack(app, 'AppStack', { env, dataStack });

const edgeStack = new EdgeStack(app, 'EdgeStack', {
  env,
  appStack,
  customDomain: { domainName: appDomain, certificate: certificateStack.certificate },
});

new CiStack(app, 'CiStack', { env, dataStack, appStack, edgeStack });
