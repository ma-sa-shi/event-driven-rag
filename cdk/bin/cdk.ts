#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { AppStack } from '../lib/app-stack';
import { CiStack } from '../lib/ci-stack';
import { DataStack } from '../lib/data-stack';
import { EdgeStack } from '../lib/edge-stack';

const app = new cdk.App();

const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION };

const dataStack = new DataStack(app, 'DataStack', { env });

const appStack = new AppStack(app, 'AppStack', { env, dataStack });

const edgeStack = new EdgeStack(app, 'EdgeStack', { env, appStack });

new CiStack(app, 'CiStack', { env, dataStack, appStack, edgeStack });
