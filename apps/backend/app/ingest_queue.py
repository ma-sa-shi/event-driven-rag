import json

import boto3


class IngestQueue:
    """取込要求をingest-fnへ渡すSQSキュー。"""

    def __init__(self, queue_url: str) -> None:
        self._queue_url = queue_url
        self._client = boto3.client("sqs")

    # 呼び出し側に必ず引数名を書かせ、似た文字列引数の順序間違いを防ぐ
    def send(
        self, *, document_id: str, user_id: str, s3_key: str, request_id: str
    ) -> None:
        # request_idはRequest ID伝搬のために載せ、ingest-fnがログへ引き継ぐ
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(
                {
                    "documentId": document_id,
                    "userId": user_id,
                    "s3Key": s3_key,
                    "requestId": request_id,
                },
                # 日本語などをエスケープせず、日本語のままJSON変換
                ensure_ascii=False,
            ),
        )
