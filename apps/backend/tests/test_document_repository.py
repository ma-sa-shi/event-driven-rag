import pytest

from app.repositories.documents import DocumentRepository, DocumentStatusError
from tests.conftest import TABLE_NAME
from tests.factories import put_document


@pytest.fixture
def repository(aws):
    return DocumentRepository(TABLE_NAME)


def test_create_puts_item_with_uploading_status(repository, aws):
    repository.create(
        user_id="user-a",
        document_id="doc-1",
        filename="spec.pdf",
        s3_key="documents/user-a/doc-1/spec.pdf",
    )

    item = repository.get_owned("user-a", "doc-1")
    assert item["status"] == "uploading"
    assert item["GSI1PK"] == "DOC"
    assert item["GSI1SK"] == "doc-1"
    assert item["createdAt"] == item["updatedAt"]


def test_get_finds_document_via_gsi_regardless_of_owner(repository, aws):
    put_document(aws.table, user_id="user-a", document_id="doc-1")

    assert repository.get("doc-1")["userId"] == "user-a"
    assert repository.get("unknown") is None
    assert repository.get_owned("user-other", "doc-1") is None


def test_update_status_allows_only_permitted_transitions(repository, aws):
    put_document(aws.table, user_id="user-a", document_id="doc-1", status="uploading")

    repository.update_status(
        "user-a", "doc-1", "uploaded", allowed_from=("uploading", "uploaded")
    )
    assert repository.get_owned("user-a", "doc-1")["status"] == "uploaded"

    with pytest.raises(DocumentStatusError):
        repository.update_status(
            "user-a", "doc-1", "uploaded", allowed_from=("uploading",)
        )
    # 失敗した遷移でステータスは変わらない
    assert repository.get_owned("user-a", "doc-1")["status"] == "uploaded"


def test_lists_are_newest_first_and_scoped_by_user(repository, aws):
    put_document(aws.table, user_id="user-a", document_id="doc-1")
    put_document(aws.table, user_id="user-b", document_id="doc-2")
    put_document(aws.table, user_id="user-a", document_id="doc-3")

    assert [d["documentId"] for d in repository.list_recent(limit=50)] == [
        "doc-3",
        "doc-2",
        "doc-1",
    ]
    assert [d["documentId"] for d in repository.list_recent(limit=2)] == [
        "doc-3",
        "doc-2",
    ]
    assert [d["documentId"] for d in repository.list_by_user("user-a", limit=50)] == [
        "doc-3",
        "doc-1",
    ]
