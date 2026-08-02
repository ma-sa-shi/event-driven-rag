# ADR-0003: 単一のDockerfileから責務別に3つのLambdaをビルドする

- Status: Accepted
- Date: 2026-07-18
- Updated: 2026-07-31

## Context

バックエンドはFastAPIへ集約するが、REST API、SSEストリーミングチャット、ドキュメント取込では、要求されるタイムアウト、メモリ、依存ライブラリが大きく異なる。特にLangChain, LangGraphライブラリはimportに時間がかかり、全てのFunctionで読み込むとコールドスタートが遅くなる。

課題は、デプロイ単位の管理コストと責務ごとの分離をどう両立するかである。

## Decision

FastAPIを1つのコードベース・1つのDockerfileで管理し、api-fn、chat-fn、ingest-fnの3つのLambdaへデプロイする。Dockerfileはビルダーステージを共有したまま最終ステージを3ターゲットへ分け、CDKがFunctionごとにビルドターゲットとメモリ・タイムアウト・環境変数を指定する。

| ターゲット | Function | 構成 | 追加依存 |
|-----------|----------|------|---------|
| web | api-fn | Lambda Web Adapter + uvicorn | なし |
| chat | chat-fn | web + LangGraph + LangChain | chat |
| worker | ingest-fn | LWAなしのプレーンハンドラ | ingest, worker |

api-fnとchat-fnはHTTPリクエストを受けるため、FastAPIをそのままLambdaで動かすLambda Web Adapterを利用し、ingest-fnはSQSトリガーで起動しHTTPを受けないため利用しない。

依存管理は`pyproject.toml`1つのままで、ターゲットごとにインストールする依存グループだけが異なる。api-fnのイメージにはLangGraphが存在しないため、`app/main.py`はLangGraphの有無を判定し、存在する場合のみチャットのルーターを読み込む。

この分離により、import時間とイメージサイズは次のようになる。

| Function | import時間 | イメージサイズ |
|----------|-----------|---------------|
| api-fn | 約0.7秒 | 292MB |
| ingest-fn | 約0.4秒 | 295MB |
| chat-fn | 約2.5秒 | 464MB |

import時間はローカル環境で`python -X importtime`により計測した。Lambdaの初回起動に近づけるため、`.pyc`を事前生成した上でファイルキャッシュを落とした状態で測っている。Lambda上のinit durationは計測していない。chat-fnとの差である約1.8秒はLangChain, LangGraphのimportが占めており、api-fnとingest-fnはこれを負担しない。

イメージサイズの差である約170MBは、コールドスタートには直結しないが、ECRのストレージ費用とイメージ更新の転送量に効く。

## Consequences

メリット

- Dockerfileと依存定義が1つで済む
- Functionごとにメモリ、タイムアウト、同時実行数を調整できる
- api-fnとingest-fnはLangChain, LangGraphを読み込まず、コールドスタートが軽い

デメリット・制約

- 最終ターゲットが3つに増え、Dockerfileの構造が複雑になる
- ingest-fnはLangChain, LangGraphを入れないため、チャンク分割を自前実装する必要がある
- 1回のリリースで3つのFunctionを更新する必要がある

## Alternatives

### 単一Lambdaへ全責務を集約

デプロイと管理は最も単純になる。しかし、LangChainの読み込みが全リクエストのコールドスタートを遅くし、SSEと取込で異なるタイムアウト設定を1つのFunctionで両立できない。SQSトリガーとHTTPの混在も、次の問題を招く。

- SQSトリガーは失敗時に例外を送出してDLQへ退避させる設計であるのに対し、HTTPは例外を捕捉して500を返す必要があり、同一アプリで両立しない
- 取込の同時実行がAPIと同じ同時実行枠を消費し、APIのスロットリングを招く

### ZIPパッケージとLambda Layer

コンテナイメージを使わず、ZIPパッケージとLayerの組み合わせでも構成できる。chat-fnの依存は展開後185MBであり、Lambdaの250MB制限には収まる。しかしFunctionごとに依存構成が異なるため、Layerの作成と割り当てを3通り管理することになる。コンテナイメージであれば1つのDockerfileでターゲットを分けるだけで済み、Lambda Web Adapterもイメージへ同梱できるため不採用とした。

### 責務ごとにDockerfileを分ける

各Dockerfileが単純になり、Function間でビルドが独立する。chat-fnの依存を更新してもapi-fnのイメージに影響しない。しかし、Dockerfileと依存定義が3つに分かれ、ソースツリーも分ける場合、settings.pyのような共有設定が3箇所へ複製される。共通パッケージへ切り出せば防げるが、パッケージ管理の手間が増える。
