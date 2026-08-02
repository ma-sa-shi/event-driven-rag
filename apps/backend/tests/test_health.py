import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "path", ["/api/health/", "/api/documents/", "/api/chats/", "/api/users/"]
)
def test_trailing_slash_does_not_redirect(path):
    """末尾スラッシュを307で誘導しない。

    307のLocationはHostから組み立てられ、CloudFront経由ではAPI Gatewayの
    execute-apiドメインが露出する。app側でリダイレクトを無効化していることを固定する。
    """
    res = client.get(path, follow_redirects=False)
    assert res.status_code == 404
    assert "location" not in res.headers
