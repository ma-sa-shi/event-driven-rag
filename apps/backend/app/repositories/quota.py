"""チャットの1日あたり利用回数を管理するQuotaエンティティ。

ソートキーにJSTの日付を含める為、日付が変わると別アイテムになり、
残数を戻す処理を持たない。過去分はTTLで自動的に消える。
"""

from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import boto3
from boto3.dynamodb.conditions import Attr

# 上限のリセット境界は利用者の体感に合わせ、UTCではなくJSTの日付で切る
JST = timezone(timedelta(hours=9))

# 当日分を消し始めないよう、TTLは日付が変わった後に十分な余裕を持たせる
QUOTA_RETENTION_DAYS = 2


class QuotaStatus(NamedTuple):
    limit: int
    used: int


class QuotaExceededError(Exception):
    """上限に達しており消費できないことを表す。"""

    def __init__(self, status: QuotaStatus) -> None:
        super().__init__("daily chat quota exceeded")
        self.status = status


def _today() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def _expires_at(today: str) -> int:
    """当日のJST 0時からQUOTA_RETENTION_DAYS後をTTLとするepoch秒。"""
    day_start = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=JST)
    return int((day_start + timedelta(days=QUOTA_RETENTION_DAYS)).timestamp())


class QuotaRepository:
    """DynamoDBシングルテーブルのQuotaエンティティを扱う。

    アイテムは`SK=QUOTA#<JSTの日付>`で、属性はusedとexpiresAtのみ。
    書き込みはchat-fnのconsumeだけが行い、api-fnは読み取りのみ。
    """

    def __init__(self, table_name: str, daily_limit: int) -> None:
        self._table = boto3.resource("dynamodb").Table(table_name)
        self._daily_limit = daily_limit

    def consume(self, user_id: str) -> QuotaStatus:
        """当日分を1回消費する。

        判定と加算を1回の条件付き更新で行う為、同時にリクエストが来ても
        上限を超えて消費されることはない。

        Raises:
            QuotaExceededError: 既に上限へ達している場合
        """
        today = _today()
        try:
            response = self._table.update_item(
                Key={"PK": f"USER#{user_id}", "SK": f"QUOTA#{today}"},
                UpdateExpression=(
                    "SET expiresAt = if_not_exists(expiresAt, :expiresAt) ADD used :one"
                ),
                ConditionExpression=Attr("used").not_exists()
                | Attr("used").lt(self._daily_limit),
                ExpressionAttributeValues={
                    ":one": 1,
                    ":expiresAt": _expires_at(today),
                },
                ReturnValues="UPDATED_NEW",
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise QuotaExceededError(self.get_status(user_id)) from None

        return QuotaStatus(
            limit=self._daily_limit, used=int(response["Attributes"]["used"])
        )

    def get_status(self, user_id: str) -> QuotaStatus:
        """当日分の利用状況を返す。まだ1度も使っていない場合はused=0とする。"""
        response = self._table.get_item(
            Key={"PK": f"USER#{user_id}", "SK": f"QUOTA#{_today()}"}
        )
        item = response.get("Item")
        return QuotaStatus(
            limit=self._daily_limit, used=int(item["used"]) if item else 0
        )
