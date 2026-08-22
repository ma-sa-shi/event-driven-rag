# ADR-0013: 独自ドメインはサブドメインで公開し、DNSをお名前.comに置く

- Status: Accepted
- Date: 2026-08-09

## Context

保有しているドメイン`business-efficiency.pro`でアプリケーションを公開する。取得先はお名前.comである。

現在はCloudFrontのデフォルトドメイン(`dxxxxxxxxxxxxx.cloudfront.net`)で配信している。この構成には運用上の負担が1つある。CognitoのコールバックURLとドキュメント保存用S3バケットのCORS許可オリジンにはCloudFrontのドメインが必要だが、DataStackからEdgeStackを参照すると循環参照になる。そのためドメインをコンテキスト`appDomain`で外から渡し、初回はEdgeStackを構築してから払い出されたドメイン名でDataStackを再デプロイしている(architecture.md 9.1)。独自ドメインであればこの値がデプロイ前に確定する。

論点は、ドメインをapexで公開するか、サブドメインで公開するかである。apexはCNAMEを設定できず、CloudFrontへ向けるには、Route53のALIASレコード、エニーキャスト静的IPへのAレコード、ALIAS/ANAME相当の機能を持つDNSサービスへのネームサーバー移管のいずれかが要る。お名前.comのDNSレコード設定はALIAS/ANAMEを提供していない。

ADR-0001で固定費ゼロを方針としており、architecture.md 11.2のとおりインフラ費用の固定分は約$0.4/月である。apexで公開するために月額の固定費を負うかが判断の分かれ目となる。

## Decision

SPAの公開ドメインをサブドメイン`rag.business-efficiency.pro`とし、DNSはお名前.comのDNSレコード設定に置く。Route53のホストゾーンは作成しない。

- CloudFrontの代替ドメイン名にサブドメインを設定する
- ACM証明書はus-east-1でDNS検証により発行し、検証用CNAMEをお名前.comへ登録する
- サブドメインのCNAMEをCloudFrontのディストリビューションドメインへ向ける
- apexは使用しない

採用理由は次の3点である。

- 固定費が増えない。ACM証明書、CloudFrontの代替ドメイン名、お名前.comのDNSレコード設定はいずれも追加料金がなく、ADR-0001の方針を保てる
- サブドメインは素のCNAMEで解決でき、DNSサービスの独自機能に依存しない
- `appDomain`がデプロイ前に確定し、CloudFrontを構築してからDataStackを再デプロイする手順が不要になる

## Consequences

メリット

- 公開URLが自前のドメインになり、CloudFrontのデフォルトドメインを共有せずに済む
- `appDomain`が固定値になり、初回デプロイの2パスがなくなる

デメリット・制約

- apexでアクセスできない。ブラウザへ`business-efficiency.pro`と入力しても到達しない
- ACM証明書のリージョンがus-east-1に固定される。他スタックのリージョンと異なるため、証明書用のスタックを分けてリージョンを跨いだ参照が必要になる
- DNSレコードがCDKの管理外になる。証明書の検証レコードとサブドメインのCNAMEはお名前.comのコンソールで手動設定し、手順を`cdk/README.md`へ残す必要がある

見直し条件

- apexでの公開が要件になった場合。その時点でネームサーバーをCNAMEフラット化に対応したDNSへ移すか、Route53のホストゾーンとALIASレコードを採用する

## Alternatives

### apex + Route53のALIASレコード

apexをCloudFrontへ向ける標準的な手段であり、AWS内で完結するためDNSもCDKで管理できる。しかしパブリックホストゾーンに月$0.50の固定費が発生する。ADR-0001が排除している常時課金される固定リソースに該当する。システム全体で月$1〜2の構成に対し、ドメイン1つのためにホストゾーンを持つ利点が、固定費を作る対価に見合わないため不採用とした。

### apex + CloudFrontのエニーキャスト静的IP

2025年4月にapexドメイン向けのエニーキャスト静的IPが提供され、Aレコードでapexを向けられるようになった。ただしIPリスト1つあたり月$3,000であり、本システムの規模とは桁が合わないため不採用とした。

### ネームサーバーをCloudflareへ移してapexを使う

CloudflareのDNSは無料プランでもCNAMEフラット化に対応しており、apexをCloudFrontへ向けられる。固定費も発生しない。しかしドメインの取得先とDNSの管理先が分かれ、依存するサービスが1つ増える。apexでの公開が要件ではない現状では、移す理由がないため不採用とした。apexが必要になった場合の第一候補として残す。

### CloudFrontのデフォルトドメインのまま運用する

追加の作業も費用も発生しない。しかし`appDomain`の2パスデプロイが残り続け、保有しているドメインを活かせない。独自ドメインの導入コストが小さいため不採用とした。
