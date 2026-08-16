"""Lambda Web Adapterが転送するLambda contextの取り回しに関するテスト。

request IDとX-RayのトレースIDは、どちらも`x-amzn-lambda-context`からしか得られない。
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tracer import LAMBDA_TRACE_HEADER_KEY

client = TestClient(app)

TRACE_HEADER = (
    "Root=1-65c0ffee-0123456789abcdef01234567;Parent=53995c3f42cd8ad8;Sampled=1"
)


@pytest.fixture(autouse=True)
def isolate_trace_context(monkeypatch):
    """トレースコンテキストはプロセスの環境変数を介して渡る為、テスト間で持ち越さない。"""
    monkeypatch.setenv(LAMBDA_TRACE_HEADER_KEY, "")


def lambda_context_header(**context) -> dict[str, str]:
    return {"x-amzn-lambda-context": json.dumps(context)}


def test_uses_lambda_request_id_for_tracking():
    res = client.get(
        "/api/health", headers=lambda_context_header(request_id="lambda-request-id")
    )

    assert res.headers["X-Request-Id"] == "lambda-request-id"


def test_restores_xray_trace_context_from_lambda_context():
    """LWAはX-Rayのトレースヘッダーを転送しない為、Lambda contextの値から復元する。"""
    client.get(
        "/api/health",
        headers=lambda_context_header(
            request_id="lambda-request-id", xray_trace_id=TRACE_HEADER
        ),
    )

    assert os.environ[LAMBDA_TRACE_HEADER_KEY] == TRACE_HEADER


def test_generates_request_id_without_lambda_context():
    """ローカル実行ではLambda contextが無く、トレースコンテキストも復元しない。"""
    res = client.get("/api/health")

    assert res.headers["X-Request-Id"]
    assert os.environ[LAMBDA_TRACE_HEADER_KEY] == ""


def test_ignores_broken_lambda_context():
    res = client.get("/api/health", headers={"x-amzn-lambda-context": "not-json"})

    assert res.status_code == 200
    assert res.headers["X-Request-Id"]
    assert os.environ[LAMBDA_TRACE_HEADER_KEY] == ""
