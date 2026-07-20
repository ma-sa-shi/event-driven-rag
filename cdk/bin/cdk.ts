#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { DataStack } from '../lib/data-stack';

const app = new cdk.App();

new DataStack(app, 'DataStack', {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION },
});
