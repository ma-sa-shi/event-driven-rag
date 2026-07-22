from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def post_me(token: str | None, body: dict):
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    return client.post("/api/users/me", json=body, headers=headers)


def get_profile(table, user_id: str) -> dict | None:
    res = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"})
    return res.get("Item")


def test_サインイン時の登録でプロフィールが保存される(make_token, dynamodb_table):
    res = post_me(
        make_token(sub="user-abc"),
        {"displayName": "山田 太郎", "email": "taro@example.com"},
    )
    assert res.status_code == 204

    item = get_profile(dynamodb_table, "user-abc")
    assert item is not None
    assert item["displayName"] == "山田 太郎"
    assert item["email"] == "taro@example.com"
    assert item["createdAt"] == item["updatedAt"]


def test_再登録は上書きされcreatedAtは維持される(make_token, dynamodb_table):
    token = make_token(sub="user-abc")
    post_me(token, {"displayName": "旧名", "email": "old@example.com"})
    created_at = get_profile(dynamodb_table, "user-abc")["createdAt"]

    res = post_me(token, {"displayName": "新名", "email": "new@example.com"})
    assert res.status_code == 204

    item = get_profile(dynamodb_table, "user-abc")
    assert item["displayName"] == "新名"
    assert item["email"] == "new@example.com"
    assert item["createdAt"] == created_at


def test_トークンなしは401(dynamodb_table):
    res = post_me(None, {"displayName": "山田 太郎", "email": "taro@example.com"})
    assert res.status_code == 401


def test_表示名が空の場合は422(make_token, dynamodb_table):
    res = post_me(make_token(), {"displayName": "", "email": "taro@example.com"})
    assert res.status_code == 422
