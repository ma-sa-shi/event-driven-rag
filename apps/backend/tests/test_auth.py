from typing import Annotated

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user_id
from tests.conftest import ISSUER

# DynamoDB等に依存せずJWT検証だけを確かめるための最小アプリ
app = FastAPI()


@app.get("/protected")
def protected(user_id: Annotated[str, Depends(get_current_user_id)]):
    return {"user_id": user_id}


client = TestClient(app)


def get(token: str | None):
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    return client.get("/protected", headers=headers)


def test_有効なトークンでsubがuser_idになる(make_token):
    res = get(make_token(sub="user-abc"))
    assert res.status_code == 200
    assert res.json() == {"user_id": "user-abc"}


def test_ヘッダなしは401(make_token):
    res = get(None)
    assert res.status_code == 401
    assert res.headers["WWW-Authenticate"] == "Bearer"


def test_JWTでない文字列は401():
    assert get("not-a-jwt").status_code == 401


def test_別の鍵で署名されたトークンは401(make_token):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert get(make_token(key=other_key)).status_code == 401


def test_期限切れトークンは401(make_token):
    assert get(make_token(expires_in=-60)).status_code == 401


def test_発行者が異なるトークンは401(make_token):
    res = get(make_token(issuer=f"{ISSUER}-other"))
    assert res.status_code == 401


def test_client_idが異なるトークンは401(make_token):
    assert get(make_token(client_id="other-client")).status_code == 401


@pytest.mark.parametrize("token_use", ["id", None])
def test_アクセストークン以外は401(make_token, token_use):
    assert get(make_token(token_use=token_use)).status_code == 401
