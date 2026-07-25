from datetime import UTC, datetime

import boto3
from boto3.dynamodb.conditions import Attr, Key


class DocumentStatusError(Exception):
    """現在のステータスからは許可されない遷移。"""


class DocumentRepository:
    """DynamoDBシングルテーブルのDocumentsエンティティを扱う。

    ステータス遷移: uploading → uploaded → processing → ingested | failed
    SK・GSI1SKのdocumentIdはULIDのため、辞書順がそのまま作成時刻順になる。
    """

    def __init__(self, table_name: str) -> None:
        self._table = boto3.resource("dynamodb").Table(table_name)

    def create(
        self, *, user_id: str, document_id: str, filename: str, s3_key: str
    ) -> dict:
        now = datetime.now(UTC).isoformat()
        item = {
            "PK": f"USER#{user_id}",
            "SK": f"DOC#{document_id}",
            "GSI1PK": "DOC",
            "GSI1SK": document_id,
            "documentId": document_id,
            "userId": user_id,
            "filename": filename,
            "s3Key": s3_key,
            "status": "uploading",
            "createdAt": now,
            "updatedAt": now,
        }
        self._table.put_item(Item=item)
        return item

    def get_owned(self, user_id: str, document_id: str) -> dict | None:
        """本人のドキュメントを取得する。ステータス更新系の所有チェックに使う。"""
        res = self._table.get_item(
            Key={"PK": f"USER#{user_id}", "SK": f"DOC#{document_id}"}
        )
        return res.get("Item")

    def get(self, document_id: str) -> dict | None:
        """所有者を問わずdocumentIdで取得する。閲覧用presigned URL発行に使う。"""
        res = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq("DOC")
            & Key("GSI1SK").eq(document_id),
        )
        items = res["Items"]
        return items[0] if items else None

    def list_recent(self, limit: int) -> list[dict]:
        res = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq("DOC"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return res["Items"]

    def list_by_user(self, user_id: str, limit: int) -> list[dict]:
        res = self._table.query(
            KeyConditionExpression=Key("PK").eq(f"USER#{user_id}")
            & Key("SK").begins_with("DOC#"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return res["Items"]

    def update_status(
        self,
        user_id: str,
        document_id: str,
        new_status: str,
        *,
        allowed_from: tuple[str, ...],
    ) -> None:
        """条件付き更新でステータスを遷移させる。

        現在のステータスがallowed_from外の場合はDocumentStatusErrorを送出する。
        """
        try:
            self._table.update_item(
                Key={"PK": f"USER#{user_id}", "SK": f"DOC#{document_id}"},
                UpdateExpression="SET #status = :status, updatedAt = :now",
                ConditionExpression=Attr("status").is_in(list(allowed_from)),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":status": new_status,
                    ":now": datetime.now(UTC).isoformat(),
                },
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise DocumentStatusError(
                f"transition to {new_status} requires status in {allowed_from}"
            ) from None
