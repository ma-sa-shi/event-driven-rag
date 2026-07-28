from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import boto3
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from moto import mock_aws

from app.ingest.pipeline import get_ingest_pipeline
from app.rag.runtime import get_rag_runtime
from app.settings import get_settings
from app.ssm import get_parameter

ISSUER = "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_test"
CLIENT_ID = "test-client-id"
TABLE_NAME = "test-table"
BUCKET_NAME = "test-documents-bucket"
QUEUE_NAME = "test-ingest-queue"
VECTOR_INDEX_ARN = (
    "arn:aws:s3vectors:ap-northeast-1:123456789012:bucket/test-vectors/index/test-index"
)
OPENAI_API_KEY_PARAMETER_NAME = "/event-driven-rag/test-openai-api-key"
COHERE_API_KEY_PARAMETER_NAME = "/event-driven-rag/test-cohere-api-key"


# autouse=Trueにより、テスト関数に引数(env)を書かなくても、test/の全テスト実行前に自動で呼ばれる
# monkeypatchにより、テスト実行中だけ一時的に設定を書き換える
@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("COGNITO_ISSUER", ISSUER)
    monkeypatch.setenv("COGNITO_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("DOCUMENTS_BUCKET_NAME", BUCKET_NAME)
    # motoがQueue作成後に発行した本物のダミーURLで上書きする
    monkeypatch.setenv("INGEST_QUEUE_URL", "https://sqs.invalid/placeholder")
    monkeypatch.setenv("VECTOR_INDEX_ARN", VECTOR_INDEX_ARN)
    monkeypatch.setenv("OPENAI_API_KEY_PARAMETER_NAME", OPENAI_API_KEY_PARAMETER_NAME)
    monkeypatch.setenv("COHERE_API_KEY_PARAMETER_NAME", COHERE_API_KEY_PARAMETER_NAME)
    # motoが本物のAWS鍵を使って実AWSリソースにリクエストしないようダミーを設定
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    _clear_caches()
    yield
    _clear_caches()


def _clear_caches() -> None:
    """プロセス内キャッシュがテスト間で漏れないようまとめてクリアする。"""
    get_settings.cache_clear()
    get_parameter.cache_clear()
    get_rag_runtime.cache_clear()
    get_ingest_pipeline.cache_clear()


@pytest.fixture(scope="session")
def rsa_key():
    """
    テスト全体で使い回すJWT署名用のRSA秘密鍵
    生成コストが高い為sessionスコープ
    """
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def mock_jwks(monkeypatch, rsa_key):
    """CognitoのJWKSエンドポイントへの外部HTTP通信を遮断し、ローカルのRSA公開鍵を返すようモック化する"""
    signing_key = SimpleNamespace(key=rsa_key.public_key())
    monkeypatch.setattr(
        PyJWKClient, "get_signing_key_from_jwt", lambda self, token: signing_key
    )


@pytest.fixture
def make_token(rsa_key):
    """クレーム（subやexp等）を自由にカスタマイズしてCognitoアクセストークン（JWT）を生成するファクトリ関数"""

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
    """moto上でDynamoDB, S3, SQSのリソースを自動生成し、AWSアクセスを完全モック化する"""
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
        # SimpleNamespaceによりドット記法を使える(aws.table.put_item(...))
        yield SimpleNamespace(table=table, s3=s3, sqs=sqs, queue_url=queue_url)


@pytest.fixture
def dynamodb_table(aws):
    return aws.table
