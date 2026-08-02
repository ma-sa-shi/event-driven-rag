# ADR-0009: Lambda Function URLをCloudFront OACで保護しない

- Status: Accepted
- Date: 2026-07-29
- Updated: 2026-07-31

## Context

CloudFrontから、api-fnとchat-fnの2つのLambda Function URLへ`/api/*`をルーティングする。Function URLはインターネットに公開されるHTTPSエンドポイントであるため、CloudFrontを経由しない直接アクセスをどう扱うかを決める必要がある。

CloudFrontにはOrigin Access Control (OAC)があり、オリジンへのアクセスを特定のディストリビューションからのみに限定できる。一方、本システムの認証は、SPAがCognitoで取得したアクセストークンを`Authorization: Bearer`ヘッダーで送り、FastAPIがJWTを検証する方式であり、詳細はADR-0004に記載する。課題は、OACによるオリジン保護とBearerトークン認証が両立するかである。

## Decision

Function URLのAuthTypeをNONEのままとし、OACを適用しない。不正なデータアクセスはCognito JWT検証によって防ぐ。

理由は、OACのSigV4署名が`Authorization`ヘッダーを使うため、同じヘッダーでBearerトークンを運ぶ本システムと両立しないことである。OACの署名動作は3種類あり、いずれも成立しない。

| 署名動作 | 挙動 | 本システムでの結果 |
|---------|------|-----------------|
| always | CloudFrontが常にSigV4署名を`Authorization`ヘッダーへ書き込む | ビューワーが送ったBearerトークンが上書きされ、JWT検証が通らない |
| no-override | ビューワーが`Authorization`ヘッダーを持つ場合は署名しない | APIリクエストは常にBearerトークンを持つため署名されず、AuthTypeがAWS_IAMのFunction URLに拒否される |
| never | 署名しない | Function URLをAuthType NONEにする必要があり、直接アクセスを防げない。OACを適用する意味がない |

加えて、OACとLambdaの組み合わせではPOSTとPUTでSPA側にAWS署名相当の処理が必要となり、実装コストに見合わない。

SPA配信用S3バケットにはOACを適用する。こちらはビューワーの`Authorization`ヘッダーを使わないため制約を受けない。

### 併せて行う対策

本決定は、Function URLのドメインが第三者に知られないことを前提とする。ドメインは推測困難な文字列であるが、シークレットとして管理される値ではない。露出を減らす対策を次の通り行う。

- FastAPIの`redirect_slashes`を無効化し、末尾スラッシュの自動リダイレクトを止める。307レスポンスのLocationヘッダーからFunction URLのドメインが判明するため
- Function URLをCfnOutputへ出力しない。CI/CDのログやスタックの出力から読み取られる経路を減らす

## Consequences

メリット

- SPAは標準的なBearerトークン送信のみでAPIを呼び出せる
- SPAがリクエストボディのハッシュ計算を行う必要がない
- ローカル開発でバックエンドへ直接アクセスする経路と、CloudFront経由の経路で認証方式が一致する

デメリット・制約

- Function URLがインターネットから直接到達可能なまま残る
- CloudFrontのビヘイビアやキャッシュ設定による制御を迂回できる
- ドメインが判明した場合、Lambdaの実行回数を消費させられる

データを返すルートは全てJWT検証を要求し、無認証は`/api/health`のみである。残るのは費用のリスクである。

見直し条件

- 直接アクセスによる費用が問題になった場合はAPI Gatewayを検討する
- 認証方式をBearerトークンから変更する場合はOACを再検討する

## Alternatives

### OACを適用し、JWTを独自ヘッダーで運ぶ

`Authorization`ヘッダーの代わりに`X-Auth-Token`などの独自ヘッダーでアクセストークンを送れば、OACのSigV4署名と共存できる。Function URLを完全に非公開にできるが、バックエンドの認証処理とSPAの実装を標準的でない形へ変更する必要がある。得られる保護に対して変更範囲が大きいため不採用とした。

### CloudFrontのカスタムヘッダーによる共有シークレット

CloudFrontがオリジンリクエストへ固定の秘密ヘッダーを付与し、バックエンドが検証する方式である。SigV4署名を伴わないため、`Authorization`ヘッダーと競合しない。

ただし検証はバックエンド、即ちLambdaの起動後に行われる。直接アクセスをアプリケーションレベルで拒否できるだけであり、呼び出し課金は発生する。シークレットの保管とローテーションの運用も増えるため不採用とした。

### API Gatewayを前段に配置する

Cognito JWTオーソライザによりLambdaの起動前に不正なトークンを拒否でき、ステージのスロットリングでレートの上限も設定できる。費用のリスクに対する根本的な対策となる。

不採用の理由は次の2点である。

- 現時点で、Lambda起動前の拒否やレート制限を必要とする事象が発生していない
- SSEは中間層が増えるほどバッファリングやタイムアウトで壊れやすい。CloudFrontだけでもタイムアウト、KeepAlive、圧縮の3項目を調整しており、設定はarchitecture.mdの9.2に記載する。もう1層挟む複雑さに見合う利点が現時点ではない

加えて、SSEを配信するchat-fnへ適用するにはレスポンスストリーミングが必要となるが、対応するREST APIはCDKのL2コンストラクトが未対応であり、本構成での動作を検証できていない。

[REST APIが2025年11月にレスポンスストリーミングへ対応した](https://aws.amazon.com/about-aws/whats-new/2025/11/api-gateway-response-streaming-rest-apis/)ことで、技術的な障壁は下がりつつある。CDKの対応が進んだ時点で再検討する。
