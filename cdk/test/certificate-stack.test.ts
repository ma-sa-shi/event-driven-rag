import * as cdk from 'aws-cdk-lib/core';
import { Template } from 'aws-cdk-lib/assertions';
import { CertificateStack } from '../lib/certificate-stack';
import { normalizeAssetHashes } from './helpers';

const DOMAIN_NAME = 'rag.business-efficiency.pro';

let template: Template;

beforeAll(() => {
  const app = new cdk.App();
  const stack = new CertificateStack(app, 'TestCertificateStack', {
    env: { account: '123456789012', region: 'us-east-1' },
    domainName: DOMAIN_NAME,
  });
  template = Template.fromStack(stack);
});

describe('ACM証明書', () => {
  test('公開ドメインの証明書をDNS検証で1つ作成する', () => {
    template.resourceCountIs('AWS::CertificateManager::Certificate', 1);
    template.hasResourceProperties('AWS::CertificateManager::Certificate', {
      DomainName: DOMAIN_NAME,
      ValidationMethod: 'DNS',
    });
  });

  test('DNSリソースを作らない', () => {
    // DNSはお名前.comに置く為、検証用CNAMEは手動登録となる(ADR-0013)
    template.resourceCountIs('AWS::Route53::HostedZone', 0);
    template.resourceCountIs('AWS::Route53::RecordSet', 0);
  });
});

test('スナップショット', () => {
  expect(normalizeAssetHashes(template)).toMatchSnapshot();
});
