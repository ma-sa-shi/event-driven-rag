import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from ulid import ULID

from app.main import app
from tests.conftest import BUCKET_NAME
from tests.factories import put_document

client = TestClient(app)


def headers(token: str, **extra: str) -> dict:
    return {"Authorization": f"Bearer {token}", **extra}


def create_upload_url(token: str, filename: str = "spec.pdf"):
    return client.post(
        "/api/documents/upload-url", json={"filename": filename}, headers=headers(token)
    )


def get_document_item(table, user_id: str, document_id: str) -> dict | None:
    res = table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"DOC#{document_id}"})
    return res.get("Item")


def ulid_at(second: int) -> str:
    """指定秒のタイムスタンプを持つULIDを返す。ランダム部を含むため呼ぶ度に異なる。"""
    return str(ULID.from_datetime(datetime(2026, 7, 23, 10, 0, second, tzinfo=UTC)))


def test_upload_url_issuance_registers_uploading_document(make_token, aws):
    res = create_upload_url(make_token(sub="user-abc"), "仕様書.pdf")
    assert res.status_code == 201

    body = res.json()
    document_id = body["documentId"]
    assert BUCKET_NAME in body["uploadUrl"]
    assert document_id in body["uploadUrl"]
    # ローカル実行時のRequest IDはUUIDへフォールバックして必ず付与される
    assert res.headers["X-Request-Id"]

    item = get_document_item(aws.table, "user-abc", document_id)
    assert item is not None
    assert item["status"] == "uploading"
    assert item["filename"] == "仕様書.pdf"
    assert item["s3Key"] == f"documents/user-abc/{document_id}/仕様書.pdf"
    assert item["GSI1PK"] == "DOC"
    assert item["GSI1SK"] == document_id


def test_complete_upload_sets_status_uploaded(make_token, aws):
    token = make_token(sub="user-abc")
    document_id = create_upload_url(token).json()["documentId"]

    res = client.post(f"/api/documents/{document_id}/complete", headers=headers(token))
    assert res.status_code == 204
    assert get_document_item(aws.table, "user-abc", document_id)["status"] == "uploaded"


def test_complete_upload_is_idempotent(make_token, aws):
    token = make_token(sub="user-abc")
    document_id = create_upload_url(token).json()["documentId"]
    client.post(f"/api/documents/{document_id}/complete", headers=headers(token))

    res = client.post(f"/api/documents/{document_id}/complete", headers=headers(token))
    assert res.status_code == 204


def test_complete_unknown_document_returns_404(make_token, aws):
    res = client.post(
        "/api/documents/unknown-doc/complete", headers=headers(make_token())
    )
    assert res.status_code == 404


def test_complete_other_users_document_returns_404(make_token, aws):
    document_id = create_upload_url(make_token(sub="user-abc")).json()["documentId"]

    res = client.post(
        f"/api/documents/{document_id}/complete",
        headers=headers(make_token(sub="user-other")),
    )
    assert res.status_code == 404


def test_complete_from_processed_status_returns_409(make_token, aws):
    put_document(aws.table, user_id="user-abc", document_id="doc-1", status="ingested")

    res = client.post(
        "/api/documents/doc-1/complete", headers=headers(make_token(sub="user-abc"))
    )
    assert res.status_code == 409


def test_start_ingest_sends_sqs_message_and_sets_processing(make_token, aws):
    token = make_token(sub="user-abc")
    document_id = create_upload_url(token).json()["documentId"]
    client.post(f"/api/documents/{document_id}/complete", headers=headers(token))

    lambda_context = json.dumps({"request_id": "req-123"})
    res = client.post(
        f"/api/documents/{document_id}/ingest",
        headers=headers(token, **{"x-amzn-lambda-context": lambda_context}),
    )
    assert res.status_code == 202
    assert res.json() == {"documentId": document_id, "status": "processing"}
    assert res.headers["X-Request-Id"] == "req-123"
    assert (
        get_document_item(aws.table, "user-abc", document_id)["status"] == "processing"
    )

    messages = aws.sqs.receive_message(QueueUrl=aws.queue_url, MaxNumberOfMessages=10)
    bodies = [json.loads(m["Body"]) for m in messages["Messages"]]
    assert bodies == [
        {
            "documentId": document_id,
            "userId": "user-abc",
            "s3Key": f"documents/user-abc/{document_id}/spec.pdf",
            "requestId": "req-123",
        }
    ]


def test_ingest_before_upload_complete_returns_409(make_token, aws):
    token = make_token(sub="user-abc")
    document_id = create_upload_url(token).json()["documentId"]

    res = client.post(f"/api/documents/{document_id}/ingest", headers=headers(token))
    assert res.status_code == 409


def test_double_ingest_returns_409(make_token, aws):
    put_document(
        aws.table, user_id="user-abc", document_id="doc-1", status="processing"
    )

    res = client.post(
        "/api/documents/doc-1/ingest", headers=headers(make_token(sub="user-abc"))
    )
    assert res.status_code == 409


def test_failed_document_can_be_reingested(make_token, aws):
    put_document(aws.table, user_id="user-abc", document_id="doc-1", status="failed")

    res = client.post(
        "/api/documents/doc-1/ingest", headers=headers(make_token(sub="user-abc"))
    )
    assert res.status_code == 202
    assert get_document_item(aws.table, "user-abc", "doc-1")["status"] == "processing"


def test_download_url_available_for_other_users_document(make_token, aws):
    put_document(
        aws.table, user_id="user-abc", document_id="doc-1", filename="共有資料.pdf"
    )

    res = client.get(
        "/api/documents/doc-1/download-url",
        headers=headers(make_token(sub="user-other")),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["filename"] == "共有資料.pdf"
    assert BUCKET_NAME in body["downloadUrl"]
    assert "doc-1" in body["downloadUrl"]


def test_download_url_unknown_document_returns_404(make_token, aws):
    res = client.get(
        "/api/documents/unknown-doc/download-url", headers=headers(make_token())
    )
    assert res.status_code == 404


def test_document_list_is_cross_user_newest_first(make_token, aws):
    doc1, doc2, doc3 = ulid_at(1), ulid_at(2), ulid_at(3)
    put_document(aws.table, user_id="user-a", document_id=doc1)
    put_document(aws.table, user_id="user-b", document_id=doc2)
    put_document(aws.table, user_id="user-a", document_id=doc3)

    res = client.get("/api/documents", headers=headers(make_token()))
    assert res.status_code == 200
    docs = res.json()
    assert [d["documentId"] for d in docs] == [doc3, doc2, doc1]
    assert docs[0]["userId"] == "user-a"
    assert docs[0]["status"] == "uploaded"


def test_document_list_respects_limit(make_token, aws):
    doc1, doc2, doc3 = ulid_at(1), ulid_at(2), ulid_at(3)
    for document_id in (doc1, doc2, doc3):
        put_document(aws.table, user_id="user-a", document_id=document_id)

    res = client.get("/api/documents?limit=2", headers=headers(make_token()))
    assert [d["documentId"] for d in res.json()] == [doc3, doc2]


def test_user_document_list_returns_only_own_documents(make_token, aws):
    doc1, doc2 = ulid_at(1), ulid_at(2)
    put_document(aws.table, user_id="user-a", document_id=doc1)
    put_document(aws.table, user_id="user-b", document_id=doc2)

    res = client.get("/api/users/user-a/documents", headers=headers(make_token()))
    assert res.status_code == 200
    assert [d["documentId"] for d in res.json()] == [doc1]


def test_missing_token_returns_401(aws):
    assert client.get("/api/documents").status_code == 401
    assert (
        client.post("/api/documents/upload-url", json={"filename": "a"}).status_code
        == 401
    )
