from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import boto3
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from moto import mock_aws

from app.settings import get_settings

ISSUER = "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_test"
CLIENT_ID = "test-client-id"
TABLE_NAME = "test-table"
BUCKET_NAME = "test-documents-bucket"
QUEUE_NAME = "test-ingest-queue"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("COGNITO_ISSUER", ISSUER)
    monkeypatch.setenv("COGNITO_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("DOCUMENTS_BUCKET_NAME", BUCKET_NAME)
    # 実URLはawsフィクスチャがキュー作成後に上書きする
    monkeypatch.setenv("INGEST_QUEUE_URL", "https://sqs.invalid/placeholder")
    # motoが実クレデンシャルへフォールバックしないようダミーを設定
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# 鍵生成が重いためセッションで1度だけ生成する
@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def mock_jwks(monkeypatch, rsa_key):
    """JWKSエンドポイントへのアクセスをテスト用公開鍵の返却に差し替える。"""
    signing_key = SimpleNamespace(key=rsa_key.public_key())
    monkeypatch.setattr(
        PyJWKClient, "get_signing_key_from_jwt", lambda self, token: signing_key
    )


@pytest.fixture
def make_token(rsa_key):
    """クレームを差し替え可能なCognitoアクセストークン形式のJWTファクトリ。"""

    def _make(
        *,
        sub="user-123",
        issuer=ISSUER,
        client_id=CLIENT_ID,
        token_use="access",
        expires_in=3600,
        key=None,
    ):
        now = datetime.now(UTC)
        claims = {
            "sub": sub,
            "iss": issuer,
            "client_id": client_id,
            "token_use": token_use,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        }
        return jwt.encode(claims, key or rsa_key, algorithm="RS256")

    return _make


@pytest.fixture
def aws(env, monkeypatch):
    """moto上にテーブル・バケット・キューを作成し、AWSアクセスをモック化する。"""
    with mock_aws():
        table = boto3.resource("dynamodb").create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3")
        s3.create_bucket(
            Bucket=BUCKET_NAME,
            CreateBucketConfiguration={"LocationConstraint": "ap-northeast-1"},
        )
        sqs = boto3.client("sqs")
        queue_url = sqs.create_queue(QueueName=QUEUE_NAME)["QueueUrl"]
        monkeypatch.setenv("INGEST_QUEUE_URL", queue_url)
        get_settings.cache_clear()
        yield SimpleNamespace(table=table, s3=s3, sqs=sqs, queue_url=queue_url)


@pytest.fixture
def dynamodb_table(aws):
    return aws.table
