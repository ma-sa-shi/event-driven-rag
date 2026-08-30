"""QuotaRepositoryの消費と参照の検証。

上限に達したことの確認に上限回数分の消費を繰り返す必要はない。
アイテムのusedを直接書き込めば同じ状態を作れる。
"""

from datetime import datetime

import pytest

from app.repositories.quota import JST, QuotaExceededError, QuotaRepository
from tests.conftest import TABLE_NAME
from tests.factories import put_quota, today_jst

USER_ID = "user-123"


def quota_item(table, user_id: str = USER_ID) -> dict | None:
    res = table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"QUOTA#{today_jst()}"})
    return res.get("Item")


def test_初回の消費でアイテムが作られる(dynamodb_table):
    repository = QuotaRepository(TABLE_NAME, daily_limit=20)

    status = repository.consume(USER_ID)

    assert status.used == 1
    assert status.limit == 20
    assert quota_item(dynamodb_table)["used"] == 1


def test_消費するたびにusedが増える(dynamodb_table):
    repository = QuotaRepository(TABLE_NAME, daily_limit=20)

    repository.consume(USER_ID)
    status = repository.consume(USER_ID)

    assert status.used == 2


def test_上限に達していると消費できない(dynamodb_table):
    put_quota(dynamodb_table, user_id=USER_ID, used=20)
    repository = QuotaRepository(TABLE_NAME, daily_limit=20)

    with pytest.raises(QuotaExceededError) as error:
        repository.consume(USER_ID)

    assert error.value.status.used == 20
    # 拒否した分をusedへ加算しない
    assert quota_item(dynamodb_table)["used"] == 20


def test_上限の1つ手前までは消費できる(dynamodb_table):
    put_quota(dynamodb_table, user_id=USER_ID, used=19)
    repository = QuotaRepository(TABLE_NAME, daily_limit=20)

    assert repository.consume(USER_ID).used == 20


def test_未使用のユーザーはused0を返す(dynamodb_table):
    repository = QuotaRepository(TABLE_NAME, daily_limit=20)

    assert repository.get_status("誰も使っていないID") == (20, 0)


def test_TTLは初回の消費でだけ設定する(dynamodb_table):
    repository = QuotaRepository(TABLE_NAME, daily_limit=20)

    repository.consume(USER_ID)
    expires_at = quota_item(dynamodb_table)["expiresAt"]
    repository.consume(USER_ID)

    assert quota_item(dynamodb_table)["expiresAt"] == expires_at


def test_TTLは当日の日付境界より後になる(dynamodb_table):
    repository = QuotaRepository(TABLE_NAME, daily_limit=20)

    repository.consume(USER_ID)

    tomorrow_start = (
        datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        + 86400
    )
    assert quota_item(dynamodb_table)["expiresAt"] >= tomorrow_start


def test_ユーザーごとに独立して数える(dynamodb_table):
    repository = QuotaRepository(TABLE_NAME, daily_limit=20)

    repository.consume("user-a")
    repository.consume("user-a")
    repository.consume("user-b")

    assert repository.get_status("user-a").used == 2
    assert repository.get_status("user-b").used == 1
