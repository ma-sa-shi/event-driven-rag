import * as cdk from "aws-cdk-lib/core";
import { Construct } from "constructs";
import * as acm from "aws-cdk-lib/aws-certificatemanager";

export interface CertificateStackProps extends cdk.StackProps {
  domainName: string;
}

/**
 * SPAの公開ドメイン用の証明書スタック。
 * CloudFrontへ関連付けられる証明書はus-east-1のものに限られる為、
 * このスタックだけ他とリージョンを分ける(architecture.md 9.1)。
 * DNSはお名前.comで管理する為(ADR-0013)、検証用CNAMEの登録は手動となり、
 * 登録が済むまでスタックの作成は完了しない(手順はcdk/README.md)。
 */
export class CertificateStack extends cdk.Stack {
  public readonly certificate: acm.Certificate;

  constructor(scope: Construct, id: string, props: CertificateStackProps) {
    super(scope, id, props);

    this.certificate = new acm.Certificate(this, "Certificate", {
      domainName: props.domainName,
      validation: acm.CertificateValidation.fromDns(),
    });

    new cdk.CfnOutput(this, "CertificateArn", {
      value: this.certificate.certificateArn,
    });
  }
}
