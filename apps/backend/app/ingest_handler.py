"""ingest-fn のエントリポイント。

Dockerfileの worker ターゲットで awslambdaric により呼び出される。
SQSによってトリガーされる通常のLambdaハンドラーとして動作する（LWAやFastAPIは不使用）。

取込に失敗した場合はドキュメントをfailedにして例外を再送出する。
SQSはbatchSize=1の為、そのメッセージだけが再試行され、maxReceiveCount(3)を超えるとDLQへ退避する。
"""

import json

from app.ingest.pipeline import get_ingest_pipeline
from app.logger import logger
from app.repositories.documents import DocumentStatusError

FAILED_ALLOWED_FROM = ("processing", "failed", "ingested")


# logger.inject_lambda_contextはLambda Powertools のデコレータで
# Lambdaのコンテキスト情報(function_nameやLambdaランタイムが生成するaws_request_id等)を自動的にログに付与
@logger.inject_lambda_context
def handler(event, context):
    """Records を取り出し1件ずつ_process_recordに渡して実行する関数"""
    records = event.get("Records", [])
    logger.info("received ingest message(s)", record_count=len(records))
    for record in records:
        _process_record(record)


def _process_record(record: dict) -> None:
    message = json.loads(record["body"])
    document_id = message["documentId"]
    user_id = message["userId"]
    # api-fnが発番したRequest IDを引き継ぎ、取込完了までログを追跡する
    logger.append_keys(request_id=message.get("requestId"), document_id=document_id)

    pipeline = get_ingest_pipeline()
    try:
        chunk_count = pipeline.run(
            document_id=document_id,
            user_id=user_id,
            s3_key=message["s3Key"],
        )
        logger.info("document ingest completed", chunk_count=chunk_count)
    except Exception:
        logger.exception("document ingest failed")
        _mark_failed(pipeline, user_id=user_id, document_id=document_id)
        raise
    finally:
        logger.remove_keys(["request_id", "document_id"])


def _mark_failed(pipeline, *, user_id: str, document_id: str) -> None:
    """
    ドキュメントのステータスを failed に更新する処理
    取込失敗のraiseを上書きしない為にステータス更新処理自体が失敗しても例外を外に漏らさない
    """
    try:
        pipeline.repository.update_status(
            user_id, document_id, "failed", allowed_from=FAILED_ALLOWED_FROM
        )
    except DocumentStatusError:
        logger.warning("could not mark document as failed")
    except Exception:
        logger.exception("failed to update document status")
