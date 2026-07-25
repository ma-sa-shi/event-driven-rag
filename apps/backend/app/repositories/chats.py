import boto3
from boto3.dynamodb.conditions import Key


class ChatRepository:
    """DynamoDBシングルテーブルのChat / Chat Messagesエンティティを扱う。

    書き込みはchat-fnが行い、api-fnは読み取りのみ。アイテム構造は次のとおり。

    - Chat:    SK=CHAT#<chatId>、GSI1PK=CHAT、GSI1SK=<chatId>
               question / finalAnswer / finalGrade / retryCount / createdAt
    - Attempt: SK=MSG#<chatId>#<attemptNo>
               queries / documents / answer / grade / feedback / failureAnalysis

    chatIdはULIDのため、辞書順がそのまま作成時刻順になる。
    """

    def __init__(self, table_name: str) -> None:
        self._table = boto3.resource("dynamodb").Table(table_name)

    def get(self, chat_id: str) -> dict | None:
        """所有者を問わずchatIdで取得する。チャット詳細画面の入口。"""
        res = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq("CHAT") & Key("GSI1SK").eq(chat_id),
        )
        items = res["Items"]
        return items[0] if items else None

    def list_recent(self, limit: int) -> list[dict]:
        res = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq("CHAT"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return res["Items"]

    def list_by_user(self, user_id: str, limit: int) -> list[dict]:
        res = self._table.query(
            KeyConditionExpression=Key("PK").eq(f"USER#{user_id}")
            & Key("SK").begins_with("CHAT#"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return res["Items"]

    def list_attempts(self, user_id: str, chat_id: str) -> list[dict]:
        res = self._table.query(
            KeyConditionExpression=Key("PK").eq(f"USER#{user_id}")
            & Key("SK").begins_with(f"MSG#{chat_id}#"),
        )
        return res["Items"]
