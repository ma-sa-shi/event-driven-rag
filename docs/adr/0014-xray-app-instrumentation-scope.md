# ADR-0014: X-Rayのアプリ内計装をapi-fnとingest-fnに限定する

- Status: Accepted
- Date: 2026-08-16

## Context

architecture.md 10.1はLambda PowertoolsのStructured Logging・Metrics・Tracingの3機能を使うと定めている。Tracingの導入にあたっては、3つのLambdaとAPI Gatewayのステージでアクティブトレースを有効にし、アプリ内にもサブセグメントを追加する方針で実装した。しかしデプロイして実測したところ、2つの制約が明らかになった。

### Lambda Web Adapter配下ではトレースコンテキストを受け取れない

ingest-fnは通常のLambda Handlerであり、X-Ray SDKはランタイムが用意したコンテキストをそのまま使える。一方、api-fnとchat-fnはLambda Web Adapterの配下でuvicornの子プロセスとして動く。Lambda Web Adapterがアプリへ転送するのは`x-amzn-request-context`と`x-amzn-lambda-context`の2ヘッダーだけであり、X-Rayのトレースヘッダーは転送しない。さらに、ランタイムが呼び出しごとに更新する`_X_AMZN_TRACE_ID`も、起動済みの子プロセスからは参照できない。そのためSDKは親セグメントを組み立てられず、サブセグメントは破棄される。

ただし、`x-amzn-lambda-context`のJSONはトレースIDを含む。`main.py`のミドルウェアは既にこのヘッダーからRequest IDを取り出しているため、同じ場所からトレースIDも取得できる。

### 並行実行するとX-Ray SDKのコンテキストが壊れる

chat-fnのRAGパイプラインは、`retriever.map()`でMulti Queryの5クエリを並行に検索する。そして各コルーチンは、Cohereの埋め込みAPIをhttpxで呼ぶ。一方、X-Ray SDK for Pythonのコンテキストはスレッドローカルにトレースエンティティのスタックを持つ。そのため、1つのスレッドで複数のコルーチンがサブセグメントを開閉すると、このスタックが壊れる。

デプロイ環境での実測結果は次のとおりである。

- `AlreadyEndedException: Already ended segment and subsegment cannot be modified.`がlangchain-cohereの埋め込み呼び出しへ伝播し、LangChainが4秒待って再試行した
- アプリが作ったサブセグメントは1つも送信されず、自動計装されたS3 Vectors・DynamoDB・SSM・CohereのサブセグメントだけがX-Rayへ届いた。しかもそれらは、いずれも存在しない親を指す孤児になった

一方、同じ実装でもapi-fnはリクエスト全体のサブセグメントを、ingest-fnはハンドラーと取込4段のサブセグメントを正しく記録した。どちらも計装した処理が逐次だからである。

## Decision

X-Rayのアプリ内計装はapi-fnとingest-fnに限定し、chat-fnでは`POWERTOOLS_TRACE_DISABLED`によりTracerを無効化する。ただしアクティブトレースは3関数とも有効のままとし、Lambda自身のセグメントは記録する。

また、api-fnのトレースコンテキストは、`x-amzn-lambda-context`のトレースIDをX-Ray SDKが参照する環境変数へ書き戻して復元する。

chat-fnで計装を行わない理由は次の3点である。

- 監視のための計装が、LLM呼び出しへ例外を持ち込み応答時間を延ばした。つまり、得られる情報より副作用の方が重い
- サブセグメントは実際には届いておらず、計装の価値がそもそも出ていない
- Lambdaのセグメントは残るため、サービスマップ・関数単位のレイテンシ・エラー率は失われない。またノードごとの所要時間は、各ノードが出す構造化ログで追える

## Consequences

メリット

- チャットの応答経路にトレースが干渉しない
- 届かないサブセグメントを作り続けることがなくなる
- 追加の依存や独自のコンテキスト管理を持ち込まずに済む。実際、chat-fn側の対処は環境変数1つである

デメリット・制約

- chat-fnのDynamoDB・S3 Vectors・Cohere呼び出しの所要時間をX-Rayで確認できない。ただし、チャットの内訳はログで追える
- 3つのLambdaで計装の粒度が揃わない
- api-fnのコンテキスト復元は、プロセスの環境変数を介する。これはLambdaが1つの実行環境で1呼び出しずつ処理するために成立する方式であり、コールドスタートとウォームスタートを含む複数のリクエストでトレースが混ざらないことは実測で確認している

見直し条件

- aws-xray-sdk-pythonがasyncioでのコンテキスト伝播に対応した場合、chat-fnの計装を再検討する
- AWS Distro for OpenTelemetryへ移行する場合は、コンテキスト伝播の仕組みごと入れ替わるため、この判断を前提から見直す

## Alternatives

### AsyncContextへ差し替える

X-Ray SDKは`AsyncContext`を提供しており、トレースエンティティをタスクローカルに持つ。task factoryが並行タスクへエンティティのリストを複製するため、`asyncio.gather`によるスタックの破壊は防げる。

しかし採用しなかった。理由は、`asyncio.to_thread`の配下でコンテキストを失うことである。`AsyncContext`は`asyncio.current_task()`を前提としており、ワーカースレッドではNoneになる。しかもboto3は同期APIであり、S3 Vectorsの検索もDynamoDBの永続化も別スレッドで実行する。そのため、チャットで最も見たい呼び出しのサブセグメントが捨てられる。つまり、並行するHTTP呼び出しの計装と引き換えに、より重要な可視性を失う。加えて、`LambdaContext`を置き換えるとセグメントの生成も自前で行う必要がある。

### chat-fnでhttpxの計装だけを外す

例外は、並行実行されるhttpxの計装から発生している。一方でノード単位のサブセグメントは逐次であるため、httpxを計装対象から外せば残せる。

しかし採用しなかった。理由は、「並行実行する箇所へ計装を足さない」という制約をコードで強制できないことである。RAGパイプラインは今後もノードの追加や並列化が見込まれるため、`asyncio.gather`を1つ足した時点で同じ例外が戻る。そもそも、監視のための仕組みがアプリケーションの書き方を縛る状態は避けたい。

### 計装を残したまま例外を抑止する

例外はSDKの内部で送出されるため、アプリケーション側に捕捉点がない。また`AWS_XRAY_CONTEXT_MISSING`は、コンテキスト不在時の扱いを変える設定であり、この例外には効かない。したがって抑止する手段がなく、選択肢にならない。
