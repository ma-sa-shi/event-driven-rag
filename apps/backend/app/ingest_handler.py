"""ingest-fn のエントリポイント
Dockerfileの worker ターゲットで awslambdaric により呼び出される。
SQSによってトリガーされる通常のLambdaハンドラーとして動作する（Web AdapterやFastAPIは不使用）。
テキスト抽出 / チャンク分割 / Embedding / S3 Vectors への登録は後で実装予定。
現時点では、ハンドラーは受信したメッセージのログ出力のみを行う。
"""

import logging

logger = logging.getLogger(__name__)
# Lambdaの実行環境がすでにルートロガーにハンドラーを追加しているため、
# logging.basicConfig() は効果がない（no-op）。そのため直接ログレベルを設定する。
logger.setLevel(logging.INFO)


def handler(event, context):
    records = event.get("Records", [])
    logger.info("received %d ingest message(s)", len(records))
    for record in records:
        logger.info("messageId=%s body=%s", record.get("messageId"), record.get("body"))
    # バッチの一部失敗用レスポンス形式。空の場合はすべてのレコードが成功したことを意味する。
    return {"batchItemFailures": []}
