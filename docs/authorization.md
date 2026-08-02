# Authentication / Authorization 設計

- 親ドキュメント: [architecture.md](./architecture.md)

architecture.mdの認証設計の詳細を扱う。認証基盤の選定理由はADR-0004に、トークンの保存先の判断はADR-0010に記載する。

## 設計方針

本システムでは、認証をAmazon Cognitoに委譲し、FastAPIはJWTの検証のみを行う。

- 認証方式はOAuth 2.0 Authorization Code Flow + PKCEを採用する
- SPAは`react-oidc-context`で実装する
- トークンはlocalStorageに保存する
- FastAPIはJWKSによるアクセストークンの検証のみを行い、パスワード管理やトークン発行、セッション管理を実装しない

## 認証フロー

```text
SPA（未認証）
    │ ⓪code_verifierを生成し、SHA-256でハッシュ化したcode_challengeをCognitoの認可エンドポイントへリクエストする。
    │
    ▼
Cognito Hosted UI
    │ ①emailとpasswordで認証に成功したら認可コードを付加してredirect_uriへリダイレクトする。
    ▼
/auth/callback?code=...
    │ ②認可コードとcode_verifierをトークンエンドポイントへ送信する。
    ▼
Cognito Token Endpoint
    │ ③code_verifierがcode_challengeと一致することを検証し、後述するaccess_token, id_token, refresh_tokenを発行する。
    ▼
SPA
    │ ④JWTをlocalStorageに保存する。AuthorizationヘッダにJWTを付与してリクエストする。
    ▼
FastAPI
      ⑤JWKSで署名検証し、`iss` / `client_id` / `exp` / `token_use=access`を検証する。`sub`をuser_idとして利用。
```

---

## ユーザー登録

- ユーザーによるサインアップを行わず、管理者がCognitoにユーザーを作成し、Cognitoが有効期限7日の初期パスワード付きの招待メールを送信する。
- 招待メールを受け取ったユーザーは恒久パスワードを設定する。

## IdP連携

導入期はCognitoによるemailとpasswordによる認証とし、Google Workspace / Entra ID等のSAML / OIDC連携は必要になった時点で追加する。\
標準OIDCクライアントを採用しているため、IdP追加時のSPA側の変更は設定のみで済む。

---

## トークン

| Token | 有効期限 | 用途 |
|-------|---------|------|
| Access Token | 1時間（Cognitoのデフォルト値） | APIリクエストの`Authorization`ヘッダに使われる |
| ID Token | 1時間（Cognitoのデフォルト値） | SPAでの表示名・メールアドレス表示のみに使われる |
| Refresh Token | 30日 | Access TokenとID Tokenの自動更新に使われる |

- Access TokenとID Tokenは`react-oidc-context`の`automaticSilentRenew`で自動更新する
- Refresh TokenがlocalStorageにタブを閉じても保持されるため、更新はrefresh token grantで行われる。iframeによるサイレントサインインは使わず、サードパーティCookieをブラウザがブロックする影響を受けない
- Refresh Token失効時のみHosted UIへ再リダイレクトする

---

## SPA実装

`react-oidc-context`を利用する。設定値は`apps/frontend/src/auth/userManager.ts`の`UserManager`へ集約し、`AuthProvider`とaxiosのインターセプタで同一インスタンスを共有する。認可コードの受け口は`/auth/callback`とし、スコープは`openid email profile`とする。profileは表示名の取得に必要である。

### ライブラリ選定理由

Authorization Code FlowやPKCEを自前実装するセキュリティリスクが高く、ライブラリに委譲する方が安全と判断した。また、`react-oidc-context`はReact向けに`AuthProvider`とフックの`useAuth`を提供しており、認証状態をコンポーネントツリーに自然に統合できる。標準OIDCクライアントであるため、将来IdPを変更する際もCognitoにロックインされず、SPA側の変更は設定のみで済む。

### 採用しなかった代替案

| 代替案 | 見送り理由 |
|--------|-----------|
| AWS Amplify (Auth) | 認証機能のためにAmplifyの設定体系と重いランタイム一式を持ち込むことになるため |
| amazon-cognito-identity-js | ログインフォームを自作する案であり、Hosted UIの採用と合致しないため |
| PKCE自前実装 | Authorization Code Flow + PKCEを自作するとセキュリティリスクが高まるため |

---

## トークン保存

`oidc-client-ts`の`WebStorageStateStore`を用いてlocalStorageへ保存する。リロードと複数タブでセッションを維持することを優先した判断である。採用理由、XSSリスクの受容範囲、sessionStorageやHttpOnly Cookieとの比較はADR-0010に記載する。

XSSによるトークン窃取への対策のうち、Content Security Policyの設定は未実装である。

---

## サインアウト

- ヘッダーにサインアウトを配置する（独立ルートは設けない）
- localStorageのトークンを破棄し、Cognitoの`/logout`エンドポイントへリダイレクトしてHosted UIのセッションも破棄する
- logout後は`/`へ戻す

---

## バックエンド検証

FastAPIでは以下のみを行う。

- JWKS（`/.well-known/jwks.json`）による署名検証。鍵はプロセス内でキャッシュする
- `iss`（User Pool）、`client_id`、`exp`、`token_use=access`の検証
- `sub`をuser_idとして利用する

検証対象はアクセストークンでありIDトークンではない。IDトークンはユーザーの属性をSPAへ伝えるためのものであり、API呼び出しの認可に用いるトークンではないためである。Cognitoのアクセストークンは`aud`を持たないため、宛先の検証は`client_id`と`token_use`のクレームで行う。

---

## 認可（Authorization）

- 認証済みユーザーは全ユーザーのチャット履歴・ドキュメントを閲覧できる
- 更新系（アップロード、取込、チャット作成、削除）は本人のリソースのみ
- 管理者ロールは当面設けない。ユーザー管理はCognitoコンソールで行う

### 閲覧を全ユーザーへ開放する理由

本システムの目的は社内ナレッジの共有であり、誰がどの資料をどう問い合わせたかを相互に参照できることが価値になる。閲覧を本人のみに制限すると、同じ質問が繰り返され、蓄積した回答が再利用されない。

このため閲覧範囲は次の前提の上で開放する。

- 利用者はCognitoに登録された社内ユーザーのみであり、招待制で管理者が作成する
- 部門機密や個人情報を含む文書は投入しない運用とする
- 更新と削除は本人のリソースに限定し、他ユーザーのデータを変更できないようにする

閲覧範囲を絞る要件が生じた場合は、DynamoDBのキー設計上ユーザー単位での絞り込みが可能であるため、一覧取得のクエリと認可判定の追加で対応する。
