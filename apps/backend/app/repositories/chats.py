from datetime import UTC, datetime
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

# DynamoDBはfloatを受け付けないため、スコアはDecimalへ丸めて格納する
SCORE_PRECISION = 6


def _to_decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(round(float(value), SCORE_PRECISION)))


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

    def create_chat(
        self,
        *,
        user_id: str,
        chat_id: str,
        question: str,
        final_answer: str | None,
        final_grade: str | None,
        retry_count: int,
    ) -> dict:
        """チャットのヘッダを1件書き込む。一覧・詳細の入口になる。"""
        item = {
            "PK": f"USER#{user_id}",
            "SK": f"CHAT#{chat_id}",
            "GSI1PK": "CHAT",
            "GSI1SK": chat_id,
            "chatId": chat_id,
            "userId": user_id,
            "question": question,
            "finalAnswer": final_answer,
            "finalGrade": final_grade,
            "retryCount": retry_count,
            "createdAt": datetime.now(UTC).isoformat(),
        }
        self._table.put_item(Item=item)
        return item

    def put_attempt(
        self,
        *,
        user_id: str,
        chat_id: str,
        attempt_no: int,
        queries: list[str],
        documents: list[dict],
        answer: str | None,
        grade: str | None,
        feedback: str | None,
        failure_analysis: str | None = None,
    ) -> dict:
        """1試行ぶんの全出力を書き込む。attemptNoは0始まり。"""
        item = {
            "PK": f"USER#{user_id}",
            "SK": f"MSG#{chat_id}#{attempt_no}",
            "chatId": chat_id,
            "attemptNo": attempt_no,
            "queries": queries,
            "documents": [
                {**doc, "score": _to_decimal(doc.get("score"))} for doc in documents
            ],
            "answer": answer,
            "grade": grade,
            "feedback": feedback,
            "failureAnalysis": failure_analysis,
        }
        self._table.put_item(Item=item)
        return item

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
