"""ingest-fnのSQSハンドラーの結合テスト。

S3とDynamoDBはmoto、Cohere APIとS3 Vectorsはスタブへ差し替える。
"""

import json
from types import SimpleNamespace

import boto3
import pytest
from botocore.exceptions import ClientError

from app.ingest.embeddings import EMBEDDING_DIMENSION
from app.ingest.extract import UnsupportedFileTypeError
from app.ingest.pipeline import DocumentNotFoundError, IngestPipeline
from app.ingest.vectors import VectorIndex
from app.ingest_handler import handler
from app.repositories.documents import DocumentRepository
from tests.conftest import BUCKET_NAME, TABLE_NAME, VECTOR_INDEX_ARN
from tests.factories import put_document
from tests.ingest.test_vectors import StubS3VectorsClient

USER_ID = "user-123"
DOCUMENT_ID = "01JDOC0000000000000000000"
FILENAME = "設計書.txt"
S3_KEY = f"documents/{USER_ID}/{DOCUMENT_ID}/{FILENAME}"


class StubEmbedder:
    """Cohere APIを呼ばず、テキスト数ぶんの固定ベクトルを返す。"""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[0.1] * EMBEDDING_DIMENSION for _ in texts]


@pytest.fixture
def vectors_client():
    return StubS3VectorsClient()


@pytest.fixture
def embedder():
    return StubEmbedder()


@pytest.fixture
def pipeline(aws, monkeypatch, embedder, vectors_client):
    """S3 / DynamoDBは実挙動(moto)のまま、外部APIだけスタブ化したpipelineを注入する。"""
    pipeline = IngestPipeline(
        bucket_name=BUCKET_NAME,
        repository=DocumentRepository(TABLE_NAME),
        embedder=embedder,
        vector_index=VectorIndex(VECTOR_INDEX_ARN, client=vectors_client),
        s3_client=boto3.client("s3"),
    )
    monkeypatch.setattr(
        "app.ingest_handler.get_ingest_pipeline", lambda: pipeline, raising=True
    )
    return pipeline


@pytest.fixture
def lambda_context():
    """Powertoolsのinject_lambda_contextが参照する属性だけを持つダミー。"""
    return SimpleNamespace(
        function_name="ingest-fn",
        memory_limit_in_mb=1024,
        invoked_function_arn=(
            "arn:aws:lambda:ap-northeast-1:123456789012:function:ingest-fn"
        ),
        aws_request_id="lambda-request-id",
    )


def build_event(
    *, document_id: str = DOCUMENT_ID, s3_key: str = S3_KEY, request_id: str = "req-1"
) -> dict:
    return {
        "Records": [
            {
                "messageId": "message-1",
                "body": json.dumps(
                    {
                        "documentId": document_id,
                        "userId": USER_ID,
                        "s3Key": s3_key,
                        "requestId": request_id,
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    }


def upload(aws, body: bytes, key: str = S3_KEY) -> None:
    aws.s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=body)


def get_document(aws) -> dict:
    return aws.table.get_item(
        Key={"PK": f"USER#{USER_ID}", "SK": f"DOC#{DOCUMENT_ID}"}
    )["Item"]


def test_registers_vectors_and_marks_document_ingested(
    aws, pipeline, embedder, vectors_client, lambda_context
):
    put_document(
        aws.table,
        user_id=USER_ID,
        document_id=DOCUMENT_ID,
        filename=FILENAME,
        status="processing",
    )
    upload(aws, "取込対象の本文".encode())

    handler(build_event(), lambda_context)

    assert embedder.texts == ["取込対象の本文"]
    assert vectors_client.put_calls[0]["vectors"] == [
        {
            "key": f"{DOCUMENT_ID}#0",
            "data": {"float32": [0.1] * EMBEDDING_DIMENSION},
            "metadata": {
                "documentId": DOCUMENT_ID,
                "text": "取込対象の本文",
                "filename": FILENAME,
            },
        }
    ]
    document = get_document(aws)
    assert document["status"] == "ingested"
    assert int(document["chunkCount"]) == 1


def test_splits_long_document_into_multiple_vectors(
    aws, pipeline, vectors_client, lambda_context
):
    put_document(
        aws.table,
        user_id=USER_ID,
        document_id=DOCUMENT_ID,
        filename=FILENAME,
        status="processing",
    )
    upload(aws, ("段落。" * 400).encode())

    handler(build_event(), lambda_context)

    keys = [vector["key"] for vector in vectors_client.put_calls[0]["vectors"]]
    assert len(keys) > 1
    assert keys[0] == f"{DOCUMENT_ID}#0"
    assert int(get_document(aws)["chunkCount"]) == len(keys)


def test_reingest_deletes_leftover_vectors(
    aws, pipeline, vectors_client, lambda_context
):
    """再取込でチャンク数が減った場合、余った古いベクトルを削除する。"""
    put_document(
        aws.table,
        user_id=USER_ID,
        document_id=DOCUMENT_ID,
        filename=FILENAME,
        status="processing",
        chunk_count=4,
    )
    upload(aws, "短くなった本文".encode())

    handler(build_event(), lambda_context)

    assert vectors_client.delete_calls == [
        {
            "indexArn": VECTOR_INDEX_ARN,
            "keys": [f"{DOCUMENT_ID}#1", f"{DOCUMENT_ID}#2", f"{DOCUMENT_ID}#3"],
        }
    ]
    assert int(get_document(aws)["chunkCount"]) == 1


def test_reingest_without_leftovers_does_not_delete(
    aws, pipeline, vectors_client, lambda_context
):
    put_document(
        aws.table,
        user_id=USER_ID,
        document_id=DOCUMENT_ID,
        filename=FILENAME,
        status="processing",
        chunk_count=1,
    )
    upload(aws, "同じくらいの本文".encode())

    handler(build_event(), lambda_context)

    assert vectors_client.delete_calls == []


def test_marks_failed_and_reraises_when_file_is_missing(
    aws, pipeline, lambda_context, vectors_client
):
    """例外を再送出することでSQSが再試行し、最終的にDLQへ退避する。"""
    put_document(
        aws.table,
        user_id=USER_ID,
        document_id=DOCUMENT_ID,
        filename=FILENAME,
        status="processing",
    )

    with pytest.raises(ClientError):
        handler(build_event(), lambda_context)

    assert get_document(aws)["status"] == "failed"
    assert vectors_client.put_calls == []


def test_marks_failed_for_unsupported_file_type(aws, pipeline, lambda_context):
    put_document(
        aws.table,
        user_id=USER_ID,
        document_id=DOCUMENT_ID,
        filename="sheet.xlsx",
        status="processing",
    )
    upload(aws, b"binary", key=f"documents/{USER_ID}/{DOCUMENT_ID}/sheet.xlsx")

    with pytest.raises(UnsupportedFileTypeError):
        handler(
            build_event(s3_key=f"documents/{USER_ID}/{DOCUMENT_ID}/sheet.xlsx"),
            lambda_context,
        )

    assert get_document(aws)["status"] == "failed"


def test_marks_failed_when_embedding_api_fails(
    aws, pipeline, embedder, lambda_context, monkeypatch
):
    put_document(
        aws.table,
        user_id=USER_ID,
        document_id=DOCUMENT_ID,
        filename=FILENAME,
        status="processing",
    )
    upload(aws, "本文".encode())

    def fail(texts):
        raise RuntimeError("cohere is unavailable")

    monkeypatch.setattr(embedder, "embed_documents", fail)

    with pytest.raises(RuntimeError):
        handler(build_event(), lambda_context)

    assert get_document(aws)["status"] == "failed"


def test_unknown_document_raises_without_creating_item(aws, pipeline, lambda_context):
    """DynamoDBに存在しないドキュメントのメッセージでもfailed更新で新規作成しない。"""
    with pytest.raises(DocumentNotFoundError):
        handler(build_event(), lambda_context)

    response = aws.table.get_item(
        Key={"PK": f"USER#{USER_ID}", "SK": f"DOC#{DOCUMENT_ID}"}
    )
    assert "Item" not in response
