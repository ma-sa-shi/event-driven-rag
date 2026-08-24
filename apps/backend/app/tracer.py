"""X-Rayトレースの共有インスタンスと、サブセグメントを開くヘルパー。

Tracerはlogger.pyと同様にプロセス内で1つを共有する。
Lambda外(ローカル開発・pytest)ではPowertoolsがX-Ray SDKごと無効化する為、
トレース処理は全てダミーのサブセグメントになり、外部への送信も起きない。

patch_allは導入済みのライブラリを全て走査してコールドスタートを伸ばす為、対象を絞る。
botocoreがDynamoDB / S3 / SQS / S3 Vectors / SSM、httpxがCohereのEmbedding呼び出しを覆う。

chat-fnではPOWERTOOLS_TRACE_DISABLEDによりTracerを無効化している。RAGパイプラインが
検索を並行実行し、X-Ray SDKのスレッドローカルなコンテキストが壊れる為である(ADR-0014)。
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from aws_lambda_powertools import Tracer

# LambdaランタイムがX-Rayのトレースコンテキストを渡す環境変数。X-Ray SDKはここから親を組み立てる
LAMBDA_TRACE_HEADER_KEY = "_X_AMZN_TRACE_ID"

tracer = Tracer(patch_modules=("botocore", "httpx"))


def restore_trace_context(xray_trace_id: str | None) -> None:
    """Lambda Web Adapterが転送するトレースIDから、X-Ray SDKのトレースコンテキストを復元する。

    LWAはX-Rayのトレースヘッダーをアプリへ転送せず、Lambdaランタイムが呼び出しごとに更新する
    `_X_AMZN_TRACE_ID`もアプリのプロセスからは見えない。唯一の入力が`x-amzn-lambda-context`の
    トレースIDである為、これをX-Ray SDKが読む環境変数へ書き戻して親セグメントの足場を作る。

    SDKは保持中のセグメントとトレースIDが変わると、それまでのサブセグメントを破棄して
    組み立て直す。FastAPIが同期の依存関係を動かすワーカースレッドからも同じ環境変数を読む為、
    スレッドを跨いでも同一トレースに紐づく。
    """
    if xray_trace_id:
        os.environ[LAMBDA_TRACE_HEADER_KEY] = xray_trace_id


@contextmanager
def traced_request(name: str, request_id: str) -> Iterator[None]:
    """request IDをアノテーションに付けたサブセグメントの中で処理を実行する。

    アノテーションはX-Rayの検索キーになる為、ログのrequest_idからトレースを引ける。
    トレースコンテキストを復元できなかった場合はサブセグメントがNoneで返るため、その場合は何もしない。
    """
    with tracer.provider.in_subsegment(name=name) as subsegment:
        if subsegment is not None:
            subsegment.put_annotation("request_id", request_id)
        yield
