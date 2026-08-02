# CDK

AWS CDK (TypeScript) によるインフラ定義。スタック構成はDataStack / AppStack / EdgeStack(CiStackは今後実装)。認証のCognitoリソース(User Pool / Hosted UIドメイン / SPAクライアント)はDataStackで、SPA配信用S3バケットはOACのバケットポリシーと同居させるためEdgeStackで管理する。

## コマンド

- `npm run typecheck` — 型チェック(tsxで直接実行するためビルド不要)
- `npm test` — jestユニットテスト
- `npx cdk synth` — CloudFormationテンプレート生成
- `npx cdk diff` — デプロイ済みスタックとの差分表示
- `npx cdk deploy --all` — 全スタックをデプロイ

## デプロイ前準備

### SSM SecureStringパラメータの手動作成(初回のみ)

SecureStringはCloudFormationで作成できないため、AppStackのデプロイ前に手動で作成する(ADR-0008)。

```bash
aws ssm put-parameter --name /event-driven-rag/openai-api-key --type SecureString --value 'sk-...'
aws ssm put-parameter --name /event-driven-rag/cohere-api-key --type SecureString --value '...'
```

CDKはこのパラメータを名前参照してLambdaに読み取り権限を付与し、パラメータ名を環境変数(`OPENAI_API_KEY_PARAMETER_NAME` / `COHERE_API_KEY_PARAMETER_NAME`)で渡す。値はLambda起動時にアプリケーションが取得してキャッシュする。キー更新時は`put-parameter --overwrite`のうえLambdaの実行環境を入れ替える(再デプロイ等)必要がある。

### Docker

AppStackのLambdaはイメージアセット(`apps/backend/`のDockerfile、`web` / `chat` / `worker`ターゲット)としてデプロイ時にビルドされるため、`cdk deploy`にはDockerデーモンが必要。

## デプロイ

```bash
npx cdk deploy --all
```

各スタックは前のスタックのリソースを参照するため、DataStack → AppStack → EdgeStackの順にデプロイされる。

スタック間の参照は`Fn::GetStackOutput`でデプロイ時に解決され、CloudFormationのExportを作らない。参照先のリソースを削除するスタック更新でも、Exportの削除がブロックされることはない。

### CloudFrontドメインの反映(初回のみ)

CognitoのコールバックURLとドキュメント保存用バケットのCORS許可オリジンにはCloudFrontのドメインが必要だが、DataStackからEdgeStackを参照するとスタック間が循環する。そのためドメインはコンテキスト`appDomain`で渡す。初回デプロイ後にEdgeStackの`DistributionDomainName`出力を確認し、次を実行する。

```bash
npx cdk deploy DataStack -c appDomain=dxxxxxxxxxxxxx.cloudfront.net
```

以降のデプロイでも同じ`-c appDomain=...`を付ける。省略するとコールバックURLとCORSがローカル開発向けの設定へ戻る。

### SPAの配信

EdgeStackの`SpaBucketName`出力のバケットへビルド成果物を同期し、CloudFrontのキャッシュを無効化する。

```bash
(cd ../apps/frontend && npm run build)
aws s3 sync ../apps/frontend/dist s3://<SpaBucketName出力> --delete
aws cloudfront create-invalidation --distribution-id <DistributionId出力> --paths '/*'
```

## デプロイ後の設定

### Cognitoユーザーの作成

セルフサインアップは無効のため、ユーザーは管理者が作成する(docs/authorization.md)。作成すると初期パスワード付きの招待メールが送信される。

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <DataStackのUserPoolId出力> \
  --username user@example.com \
  --user-attributes \
    Name=email,Value=user@example.com \
    Name=email_verified,Value=true \
    Name=name,Value='表示名'
```

### ローカル開発の環境変数

Hosted UIのコールバックURLに`http://localhost:5173/auth/callback`を登録済みのため、デプロイ済みCognitoを使ってローカルで認証フローを動かせる。DataStackのCfnOutputの値を次の2箇所へ設定する。

- `apps/frontend/.env.local` — `.env.example`をコピーしてCognitoIssuer / UserPoolClientId / CognitoDomainUrlを設定する
- バックエンド(uvicorn)の環境変数 — JWT検証とDynamoDBアクセスに使う

```bash
export COGNITO_ISSUER=<CognitoIssuer出力>
export COGNITO_CLIENT_ID=<UserPoolClientId出力>
export TABLE_NAME=<TableName出力>
```
