# システム設計書: 社内RAGチャットアプリ

## 目次

- [1. 概要](#1-概要)
  - [1.1 背景・目的](#11-背景目的)
  - [1.2 設計方針](#12-設計方針)
- [2. システム全体構成](#2-システム全体構成)
- [3. フロントエンド設計](#3-フロントエンド設計)
  - [3.1 技術スタック](#31-技術スタック)
  - [3.2 画面構成・ルーティング](#32-画面構成ルーティング)
  - [3.3 配信構成](#33-配信構成)
- [4. 認証設計](#4-認証設計)
- [5. バックエンド設計](#5-バックエンド設計)
  - [5.1 構成方針](#51-構成方針)
  - [5.2 api-fn](#52-api-fn)
  - [5.3 chat-fn](#53-chat-fn)
  - [5.4 ingest-fn](#54-ingest-fn)
- [6. 処理フロー](#6-処理フロー)
  - [6.1 アップロードフロー](#61-アップロードフロー)
  - [6.2 取込フロー](#62-取込フロー)
- [7. RAGパイプライン](#7-ragパイプライン)
  - [7.1 処理フロー](#71-処理フロー)
  - [7.2 使用モデル](#72-使用モデル)
  - [7.3 パラメータ](#73-パラメータ)
- [8. データ設計](#8-データ設計)
  - [8.1 DynamoDB](#81-dynamodb)
  - [8.2 S3](#82-s3)
  - [8.3 S3 Vectors](#83-s3-vectors)
- [9. インフラ設計](#9-インフラ設計)
  - [9.1 CDKスタック構成](#91-cdkスタック構成)
  - [9.2 CloudFront](#92-cloudfront)
  - [9.3 API Gateway](#93-api-gateway)
  - [9.4 シークレット管理](#94-シークレット管理)
- [10. 運用設計](#10-運用設計)
  - [10.1 ロギング・モニタリング](#101-ロギングモニタリング)
  - [10.2 CI/CD](#102-cicd)
- [11. コスト](#11-コスト)
  - [11.1 コスト方針](#111-コスト方針)
  - [11.2 想定コスト](#112-想定コスト)
- [12. 開発計画](#12-開発計画)
- [13. 関連ドキュメント](#13-関連ドキュメント)

## 1. 概要

### 1.1 背景・目的

本システムは、社内ドキュメントを対象としたRAGチャットアプリである。AWSのサーバーレスサービスを中心に構成し、社内ナレッジの共有を目的とする。

RAGパイプラインは既存実装 `ai_app/src/backend/services/rag` を移植し、本構成に合わせて補完する。

### 1.2 設計方針

設計方針を3つの観点に分けて示す。個々の判断の根拠と代替案は[docs/adr/](./adr/)にADRとして記録しており、一覧は[13. 関連ドキュメント](#13-関連ドキュメント)にまとめている。

アーキテクチャ

- SPA + REST APIを基本とし、SSRを採用しない
- バックエンドはFastAPIへ集約し、Lambdaは責務ごとに分離する
- ファイルはSPAからS3へ直接アップロードする
- UploadとIngestを分離し、Embedding生成はユーザーの取込アクションで開始する

採用技術

- LLMとEmbeddingはOpenAI API
- ベクトル検索はS3 Vectors
- データストアはDynamoDB
- 認証はCognito

開発・運用

- 既存のRAG実装を移植して再利用する
- VPCを利用せず、固定費を極力ゼロにする
- 運用をシンプルに保つ

## 2. システム全体構成

システム全体の構成を次に示す。ブラウザからの経路は、認証、画面とAPI、ファイルアップロードの3つに分かれる。

```text
                          Browser
                    (Vite + React SPA)
            │              │                    │
  Hosted UI │              │        署名付きPUT (Upload)
            ▼              ▼                    ▼
        Cognito       CloudFront          S3 (Documents)
               ┌───────────┴───────────┐
               ▼                       ▼
        S3 (Static SPA)       API Gateway
                            (/api/*, Authorizer)
                                 │
               ┌─────────────────┴─────────────────┐
               ▼                                   ▼
           api-fn                            chat-fn
        (REST API)                      (SSE Streaming)
               │
               ▼
              SQS
               │
               ▼
          ingest-fn
               │
      ┌────────┼─────────┐
      ▼        ▼         ▼
 DynamoDB     S3     S3 Vectors
```

ブラウザはまずCognitoのHosted UIで認証を行う。以降はCloudFrontを経由し、SPAの静的ファイル取得とAPI呼び出しを行う。パスが`/api/*`のリクエストはAPI Gatewayへ転送され、REST APIはapi-fn、ストリーミングチャットはchat-fnが処理する。API GatewayのCognitoオーソライザが、Lambdaを起動する前にアクセストークンを検証する。

ファイルは署名付きURLを使ってブラウザからS3へ直接アップロードする。ドキュメントの取込はapi-fnがSQSへメッセージを送信し、ingest-fnが非同期で実行してDynamoDB、S3、S3 Vectorsへ書き込む。

## 3. フロントエンド設計

### 3.1 技術スタック

フロントエンドは次の技術で構成する。

- Vite
- React
- TypeScript
- React Router
- TanStack Query

TanStack Queryは、ドキュメント一覧やチャット履歴などサーバー状態のキャッシュに利用する。

### 3.2 画面構成・ルーティング

画面とルーティングは次のとおり。

| Path | 画面 |
|------|------|
| / | RAGチャット + 全ユーザーのチャット履歴 |
| /chat/{chat_id} | チャット詳細。チャット履歴から遷移する |
| /user/{user_id} | ユーザー情報 + そのユーザーのチャット履歴 + アップロード履歴 |
| /documents | ドキュメント管理。一覧・アップロード・取込を行う |
| /auth/callback | Cognito Hosted UIからのリダイレクトを受け、認可コードをトークンへ交換する |

未認証時は`/auth/callback`を除く全ルートでHosted UIへリダイレクトする。

チャット履歴は、社内のナレッジ共有を目的として全ユーザーに公開する。

チャット詳細には、回答の試行ごとに次の全出力を表示する。

- 生成クエリ
- 検索ドキュメント
- 回答
- 評価。gradeとfeedbackを含む
- 失敗分析。リトライ上限到達時のみ生成される

参照ドキュメントにはリンクを付加し、S3上の原本を閲覧用の署名付きGET URLで直接開けるようにする。

### 3.3 配信構成

SPAはビルドした静的ファイルをS3へ配置し、CloudFrontから配信する。SSRは採用しない。

## 4. 認証設計

認証にはCognito User PoolのHosted UIを利用し、フローはAuthorization Code + PKCE（Proof Key for Code Exchange）とする。PKCEはSPA向けのOAuth拡張であり、認可コードの盗用を防ぐ。

認証フローを次に示す。

```text
SPA
↓
Cognito Hosted UI
↓
Authorization Code + PKCE
↓
Access Token
↓
Authorization Header
↓
FastAPI
```

SPAはHosted UIで認証したあと、取得したAccess TokenをAuthorization Headerに含めFastAPIを呼び出す。

FastAPIではJWKS（JSON Web Key Set）によるJWT検証のみを行う。JWKSはJWTの署名検証に利用する公開鍵の集合である。パスワード管理やJWT発行は実装しない。user_idにはJWTの`sub`を利用し、独自ヘッダによるユーザー識別は行わない。

ユーザー登録、トークンの取り扱い、ライブラリ選定、認可範囲の詳細設計は[authorization.md](./authorization.md)で管理する。トークンの保存先の判断は[ADR-0010](./adr/0010-token-storage-localstorage.md)に記載する。

## 5. バックエンド設計

### 5.1 構成方針

FastAPIを1つのDockerイメージとして管理し、責務ごとに3つのLambdaへデプロイする。環境変数などFunctionごとの差分はCDKで設定する。

api-fnとchat-fnでは、HTTPサーバーであるFastAPIをそのままLambdaで動かすためにLambda Web Adapterを利用する。Dockerfileはビルダー共通のまま、最終ステージを次の3ターゲットに分け、CDKがFunctionごとにターゲットを選択する(ADR-0003参照)。

| ターゲット | Function | 構成 |
|-----------|----------|------|
| web | api-fn | Lambda Web Adapter + uvicorn |
| chat | chat-fn | webに`chat`依存グループ(LangGraph / LangChain)を追加 |
| worker | ingest-fn | Adapterなし。awslambdaric + `ingest`依存グループ(pypdf) |

### 5.2 api-fn

REST APIを担当するFunctionである。次のAPIを提供する。

- 認証API
- ドキュメント一覧。全ユーザー横断とユーザー別
- チャット一覧。全ユーザー横断とユーザー別
- チャット詳細。試行ごとの全出力を返す
- ユーザー情報
- 署名付きURL発行。アップロード用PUTと閲覧用GET
- アップロード完了登録
- 取込開始

### 5.3 chat-fn

RAGチャットを担当するFunctionである。LangGraphによるSelf-RAGを実行し、処理の進行をSSE（Server-Sent Events）で配信する。SSEはサーバーからクライアントへイベントを継続配信するHTTP通信方式である。

LangChain系ライブラリは容量が大きいため、chat-fnのみでロードする。

既存実装 `ai_app/src/backend/services/rag` を移植する。移植時の差し替えは次のとおり。

| 対象 | 移植元 | 本構成 |
|------|--------|--------|
| Retriever | Chroma | S3 Vectors |
| チャット永続化 | MySQL | DynamoDB |
| ユーザー識別 | X-User-Idヘッダ | JWTの`sub` |

チャットは1問1答とし、複数ターンの会話は行わない。履歴を文脈として利用せず、各質問を独立して処理する。

SSEはLangGraphのnodeごとのstate更新を配信する。トークン単位の配信は行わない。

ストリームは`POST /api/chats/stream`で配信し、認証はAuthorizationヘッダーで行う。ブラウザ標準のEventSourceを使わない理由は[ADR-0012](./adr/0012-sse-post-with-authorization-header.md)に記載する。

### 5.4 ingest-fn

ドキュメントの取込を担当するFunctionである。SQSイベントから起動し、次の処理を順に実行する。

- テキスト抽出
- チャンク生成
- Embedding生成
- S3 Vectors登録

対応ファイル形式はPDF、Markdown、txtとする。PDFのテキスト抽出にはpypdfを利用する。

チャンクは1チャンク500文字、オーバーラップ50文字とし、段落、行、単語、文字の順に粗い区切りから分割する。Embeddingはchat-fnの検索側と同じCohere Embed 4（`embed-v4.0`、1536次元）を使い、取込側は`input_type`に`search_document`を指定する。

HTTPリクエストを受けないFunctionのため、Lambda Web Adapterは利用せず通常のLambda Handlerで実装する。chat-fnが利用するLangChain系ライブラリはイメージに含めないため、チャンク生成とEmbedding呼び出しはRAGパイプラインとコードを共有せず、ingest-fn側に独自実装を持つ。

各チャンクのベクトルは`<documentId>#<チャンク番号>`をkeyとして登録する。取込に成功したドキュメントはチャンク数をDynamoDBへ保持し、再取込でチャンク数が減った場合は余剰のベクトルを削除する。

取込に失敗した場合はドキュメントを`failed`にしたうえで例外を送出する。SQSは1メッセージずつ処理し、3回失敗したメッセージはDLQへ退避する。

## 6. 処理フロー

アップロードと取込は分離し、それぞれ独立したフローとする。

### 6.1 アップロードフロー

ファイルはLambdaを経由せず、SPAからS3へ直接アップロードする。フローは次の3ステップで構成される。

```text
① 署名付きURL取得

SPA
    │
    ▼
api-fn

status = uploading

② Upload

SPA
    │
 PUT
    ▼
S3

③ Upload完了登録

SPA
    │
    ▼
api-fn

status = uploaded
```

SPAはまずapi-fnからアップロード用の署名付きURLを取得する。api-fnはこのときドキュメントをuploadingステータスで登録する。アップロードが完了しないドキュメントを後から監視でき、CloudTrailやログとの突き合わせも容易になる。

SPAは取得したURLへファイルをPUTし、最後にapi-fnへ完了を登録する。この時点でステータスがuploadedになる。

### 6.2 取込フロー

Embedding生成はS3へのアップロードをトリガーとせず、ユーザーが取込アクションを実行したときに開始する。

```text
SPA
↓
api-fn
↓
SQS
↓
ingest-fn
```

api-fnは取込リクエストを受けるとSQSへメッセージを送信し、ingest-fnがそれを受けて非同期に処理する。処理に失敗したメッセージはDLQ（Dead Letter Queue）へ退避する。

ドキュメントのステータスは次のように遷移する。

```text
uploading
    ↓
uploaded
    ↓
processing
    ↓
ingested または failed
```

取込中はprocessingとなり、成功すればingested、失敗すればfailedで終了する。failedのドキュメントは再度取込を開始できる。

## 7. RAGパイプライン

チャットの回答生成には、LangGraphで実装したSelf-RAGを採用する。生成した回答を自己評価し、品質が不十分な場合は再試行する。

### 7.1 処理フロー

パイプラインの処理フローを次に示す。

```text
Query
    ↓
Multi Query
    ↓
Vector Search
    ↓
RRF
    ↓
Cohere Rerank
    ↓
LLM Generation
    ↓
Self Evaluation
    ↓
Retry (Max 1)
    ↓
Answer
```

質問からMulti Queryで複数の検索クエリを生成し、クエリごとにS3 Vectorsでベクトル検索を行う。検索結果はRRF（Reciprocal Rank Fusion）で統合し、上位ドキュメントをCohere Rerankで関連度順に絞り込んだうえでLLMが回答を生成する。生成結果は自己評価し、不十分であれば最大1回リトライする。

### 7.2 使用モデル

使用するモデルは次のとおり。

| 用途 | モデル |
|------|--------|
| 回答生成 | GPT-5.4 mini |
| クエリ生成 / 自己評価 / 失敗分析 | GPT-5.4 nano |
| Embedding | Cohere Embed 4 |
| Rerank | Cohere Rerank 4 Fast |

回答生成モデルは、GPT-5.6 Lunaとの比較検討を継続中である。

### 7.3 パラメータ

パラメータは移植元の実装に準拠する。

- Multi Query: 3〜5クエリを生成する
- Vector Search: クエリごとにk=5で、全ユーザーのドキュメントを横断検索する
- RRF: k=60で統合し、上位20件を残す
- Cohere Rerank: RRF上位20件から5件に絞る
- Self Evaluation: useful / useless / hallucinationの3値とfeedbackを返す
- Retry: 最大1回。上限到達時はfailure analysisを生成して終了する

## 8. データ設計

### 8.1 DynamoDB

DynamoDBはシングルテーブル設計とし、次の4エンティティを1つのテーブルで管理する。

- Users
- Documents
- Chat
- Chat Messages

キーの例を次に示す。

```text
PK = USER#123
SK = CHAT#01K0R9WJH2T4Q6ZB8XN3E5VM7C
```

ドキュメントとチャットのIDにはULIDを利用する。ULIDは先頭にミリ秒精度のタイムスタンプを持ち、辞書順がそのまま作成時刻順となる。ユーザーを表すPKと、エンティティ種別およびIDを表すSKの組み合わせで、ユーザー単位の作成時刻順一覧を実現する。

全ユーザー横断のチャット履歴一覧はGSI（Global Secondary Index）で取得する。GSIはテーブルとは別のキーで検索するための二次インデックスであり、ChatとDocumentsで共用する。

```text
Chat:
  GSI1PK = CHAT
  GSI1SK = <chatId>

Document:
  GSI1PK = DOC
  GSI1SK = <documentId>
```

チャット一覧は `GSI1PK = CHAT`、ドキュメント一覧は `GSI1PK = DOC` をQueryして取得する。ScanやユーザーごとのQueryの繰り返しは行わない。GSI1SKはULIDのため、一覧は作成時刻順に並ぶ。チャット詳細や閲覧用署名付きURL発行のように、IDだけを条件とした所有者を問わない取得も同じGSIのQueryで行う。

ユーザー情報はCognitoをマスタとし、サインイン時に表示名とメールアドレスをDynamoDBへ書き込む。これは`/user/{user_id}`画面の表示に使うキャッシュである。

チャットは生成クエリ、検索ドキュメント、回答、評価、失敗分析を保存する。

### 8.2 S3

S3は次の2用途で利用する。

- SPAの静的ファイル配信
- アップロードされたドキュメントの保存

### 8.3 S3 Vectors

S3 VectorsはEmbeddingの保存とベクトル検索に利用する。Embeddingは、テキストを意味を保った固定長の数値ベクトルへ変換したものである。意味が近いテキストほどベクトル空間上で近くに位置するため、コサイン類似度で関連度を測れる。インデックスの次元数はCohere Embed 4に合わせて1536、距離計算はコサイン類似度とする。次元数はインデックス作成後に変更できないため、Embeddingモデルを変更する場合はインデックスを作り直す。

各ベクトルには次のMetadataを付与する。

| Key | フィルタ | 用途 |
|-----|---------|------|
| documentId | 可能 | ドキュメント削除時のベクトル特定 |
| text | 不可 | チャンク本文。検索結果から回答生成に利用する |
| filename | 不可 | 回答の出典表示 |

textとfilenameはフィルタ不可のMetadataとして登録する。フィルタ不可のMetadataはインデックス作成後に変更できないため、インデックス定義で指定する。

検索は全ユーザーのドキュメントを横断し、ユーザーによるフィルタは行わない。

## 9. インフラ設計

### 9.1 CDKスタック構成

インフラはAWS CDKで管理し、DataStack、AppStack、EdgeStack、CiStackの4スタックへ分割する(CiStackは未実装。[12. 開発計画](#12-開発計画)を参照)。

分割の基準はリソースのライフサイクルである。ユーザーやドキュメントが蓄積されるステートフルなリソースをDataStackへまとめ、入れ替えの多いアプリケーション層と分離する。認証のCognitoも、ユーザーが蓄積されるためDataStackで管理する。

SPA配信用S3バケットは例外としてEdgeStackで管理する。アクセス制御にOACを用いるため、バケットポリシーがCloudFrontディストリビューションを参照するからである。

#### appDomainによる循環参照の回避

スタック間の依存は EdgeStack → AppStack → DataStack の一方向である。CloudFrontはAPI Gatewayを参照し、LambdaはDynamoDBやS3を参照する。

一方、CognitoのコールバックURLとドキュメント保存用S3バケットのCORS許可オリジンには、CloudFrontのドメイン名が必要となる。ここでDataStackがEdgeStackを参照すると、上記の依存と合わせて循環する。

そのためドメイン名はスタック間で受け渡さず、CDKコンテキストの`appDomain`として外部から与える。初回はEdgeStackを構築し、払い出されたドメイン名を指定してDataStackを再デプロイする(手順は`cdk/README.md`)。

環境は1ステージのみとする。dev/prodの分離はせず、開発スピードを優先する。

### 9.2 CloudFront

CloudFrontはパスに応じて3つのOriginへ振り分ける。

```text
/                  → S3
/api/chats/stream  → API Gateway (chat-fn)
/api/*             → API Gateway (api-fn)
```

ルートパスはSPAの静的ファイルを配信するS3へルーティングする。`/api/*`はAPI Gatewayへ送る。API側の2つのビヘイビアは同一のAPI Gatewayを指すが、SSEのチャットとその他のRESTでタイムアウトと圧縮の要件が異なるため、設定違いのOriginとして分け、`/api/chats/stream`を先に評価する。バックエンドのどちらのLambdaへ渡すかはAPI Gatewayが決める。

API向けのビヘイビアはキャッシュを無効にし、`Host`以外の全ビューワーヘッダーをOriginへ転送する。これによりCognitoのアクセストークンを載せた`Authorization`ヘッダーが、API Gatewayのオーソライザとバックエンドの両方へ届く。`Host`を落とすのは、API GatewayがHostでAPIを識別するためである。

SSEのストリーミングは、Lambda、Lambda Web Adapter、API Gateway、CloudFrontのいずれかがレスポンスをバッファリングすると成立しない。chat-fnの経路へ次の設定を行う。

| 対象 | 設定 | 理由 |
|------|------|------|
| chat-fn | `AWS_LWA_INVOKE_MODE=response_stream` | Lambda Web Adapterをストリーミングモードで動作させる |
| API Gateway | Response Transfer Mode: STREAM | 既定の`BUFFERED`ではレスポンス全体が揃うまで送出されず、ストリーミングにならない |
| API Gateway | 統合タイムアウト: 29秒 | ストリーム全体の上限。サービスクォータの既定値であり、引き上げの承認後に300秒へ変更する |
| CloudFront | Origin Response Timeout: 60秒 | イベントとイベントの間隔の上限。ストリーム全体の上限ではない |
| CloudFront | Origin KeepAlive Timeout: 20秒 | Originとの接続を維持し、イベントごとの再接続を避ける |
| CloudFront | 圧縮: 無効 | レスポンスをバッファリングし、イベントの到達を遅らせるため |

ストリーム全体の上限は統合タイムアウトであり、CloudFrontの60秒はイベント間隔の上限として働く。KeepAliveはOriginとの接続を維持し、イベントごとの再接続を避ける。

SPAはクライアントサイドルーティングを行うため、`/chats/{chatId}`のようなパスに対応するオブジェクトはS3に存在しない。拡張子を持たないリクエストのURIを`/index.html`へ書き換えるCloudFront Functionを、S3向けのビヘイビアにのみ適用する。CloudFrontのカスタムエラーレスポンスはディストリビューション全体へ適用され、APIが返すエラーレスポンスまで書き換えてしまうため利用しない。

### 9.3 API Gateway

API Gatewayはapi-fnとchat-fnの唯一の公開経路であり、CloudFrontの`/api/*`のOriginとなる。エンドポイントは、前段にCloudFrontを置くためリージョナルとする。Lambda Function URLを使わない理由は[ADR-0011](./adr/0011-api-gateway-migration.md)に記載する。

役割は、Lambdaを起動する前に不正なリクエストを止めることである。Cognito User Poolオーソライザが`Authorization`ヘッダーのアクセストークンを検証し、無効なトークンのリクエストはLambdaへ到達しない。オーソライザを適用しないのは無認証の`/api/health`のみである。各メソッドには認可スコープ`openid`を指定する。指定しない場合、オーソライザはトークンをIDトークンとして検証するため、アクセストークンを送る本システムでは全て401となる。ステージにはレート20リクエスト/秒、バースト40リクエストのスロットリングを設定し、有効なトークンを用いた大量リクエストにも上限を設ける。

リソースは、FastAPIのルート構成に合わせて次のとおり定義する。

```text
/api/health          GET   → api-fn (認可なし)
/api/chats/stream    POST  → chat-fn
/api/chats           ANY   → api-fn
/api/chats/{proxy+}  ANY   → api-fn
/api/{proxy+}        ANY   → api-fn
```

統合はLambdaプロキシ統合を用い、パスの解決はFastAPIが行う。`/api/chats`配下にはchat-fnとapi-fnの両方のルートがあるため、グリーディパスだけでは振り分けられない。API Gatewayはグリーディパスより具体的なリソースを優先するため、`/api/chats/stream`を個別のリソースとして定義し、残りをグリーディパスで受ける。

オーソライザによる検証はトークンの正当性までであり、要求されたドキュメントやチャットが本人のものかという認可はapi-fnとchat-fnで判定する。バックエンドのJWT検証は残す。

### 9.4 シークレット管理

OpenAIとCohereのAPIキーは、SSM Parameter StoreのSecureStringパラメータで管理する。値はLambdaの初回参照時に取得し、実行環境が再利用される間はキャッシュした値を用いる。

パラメータ名は`/event-driven-rag/openai-api-key`と`/event-driven-rag/cohere-api-key`で、CloudFormationがSecureStringを作成できないため手動で作成する(手順は`cdk/README.md`)。CDKはLambdaへ読み取り権限を付与し、パラメータ名を環境変数で渡す。

## 10. 運用設計

### 10.1 ロギング・モニタリング

ロギングとモニタリングにはLambda Powertoolsを利用し、次の機能を使う。

- Structured Logging
- Metrics
- Tracing

Request IDを全サービスで引き継ぎ、1リクエストの処理をサービス横断で追跡できるようにする。

### 10.2 CI/CD

CI/CDはGitHub Actionsで構成する。

フロントエンドのデプロイフローを次に示す。

```text
Build
↓
S3 Sync
↓
CloudFront Invalidation
```

ビルドした静的ファイルをS3へ同期し、CloudFrontのキャッシュを無効化して反映する。

バックエンドのデプロイフローを次に示す。

```text
Docker Build
↓
ECR Push
↓
Lambda Update
```

DockerイメージをビルドしてECRへプッシュし、3つのLambdaを新しいイメージへ更新する。

## 11. コスト

### 11.1 コスト方針

固定費ゼロを優先し、次のリソースを利用しない。

- VPC
- NAT Gateway
- ECS
- EC2
- Aurora

Provisioned Concurrencyも利用しない。応答遅延が問題になった場合のみ、chat-fnへの適用を検討する。

### 11.2 想定コスト

ADR-0001で置いた前提である月400件から600件のチャットを想定した場合のインフラコストは次のとおり。

| Service | Cost |
|---------|------:|
| Lambda | <$1 |
| API Gateway | <$0.1 |
| DynamoDB | ~$0.5 |
| S3 | ~$0.5 |
| S3 Vectors | ~$0.5 |
| CloudFront | Free Tier |
| Cognito | Free Tier |
| SQS | Free Tier |

合計は約$1〜2/月となる。

OpenAIとCohereのAPIは上記とは別に従量課金となる。Self-RAGは1チャットで最大8回のLLM呼び出しが発生するため、補助チェーンにはnano系モデルを使いコストを抑える。

## 12. 開発計画

次の4フェーズの順に実装する。

1. 基盤: CDK → Vite + React → Cognito
2. API: api-fn → chat-fn
3. ドキュメント管理: Upload → Ingest → S3 Vectors
4. RAGと配信: LangGraph → CloudFront → CI/CD

## 13. 関連ドキュメント

設計判断の根拠、代替案、トレードオフは次のADRに記録している。

- [ADR-0001: サーバーレス構成による固定費ゼロ方針](./adr/0001-serverless-zero-fixed-cost.md)
- [ADR-0002: SPAの静的配信を採用、SSR不採用](./adr/0002-spa-no-ssr.md)
- [ADR-0003: 単一のDockerfileから責務別に3つのLambdaをビルドする](./adr/0003-single-dockerfile-three-lambdas.md)
- [ADR-0004: Cognito Hosted UI採用、バックエンドはJWT検証のみ](./adr/0004-cognito-jwt-verification-only.md)
- [ADR-0005: ベクトルDBにS3 Vectorsを採用](./adr/0005-s3-vectors.md)
- [ADR-0006: チャット永続化をDynamoDBシングルテーブルへ差し替え](./adr/0006-dynamodb-single-table.md)
- [ADR-0007: 署名付きURLによる直接アップロードと取込の分離](./adr/0007-upload-ingest-separation.md)
- [ADR-0008: APIキー管理にSSM Parameter Storeを採用](./adr/0008-ssm-parameter-store.md)
- [ADR-0009: Lambda Function URLをCloudFront OACで保護しない](./adr/0009-function-url-no-oac.md) — ADR-0011により失効
- [ADR-0010: トークンをlocalStorageへ保存する](./adr/0010-token-storage-localstorage.md)
- [ADR-0011: api-fnとchat-fnの公開経路をAPI Gatewayへ移行する](./adr/0011-api-gateway-migration.md)
- [ADR-0012: チャットのSSEをPOSTとAuthorizationヘッダーで配信する](./adr/0012-sse-post-with-authorization-header.md)

認証の詳細設計は次のドキュメントで管理する。

- [authorization.md](./authorization.md)
