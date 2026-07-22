from datetime import UTC, datetime

import boto3


class UserRepository:
    """DynamoDBシングルテーブルのUsersエンティティを扱う。

    ユーザー情報はCognitoがマスタで、ここにはユーザー画面表示用の
    キャッシュ(表示名・メールアドレス)を保存する。
    """

    def __init__(self, table_name: str) -> None:
        self._table = boto3.resource("dynamodb").Table(table_name)

    def upsert_profile(self, user_id: str, display_name: str, email: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
            UpdateExpression=(
                "SET displayName = :display_name, email = :email, "
                "updatedAt = :now, createdAt = if_not_exists(createdAt, :now)"
            ),
            ExpressionAttributeValues={
                ":display_name": display_name,
                ":email": email,
                ":now": now,
            },
        )
