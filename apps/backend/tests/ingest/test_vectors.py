import pytest

from app.ingest.vectors import MAX_VECTORS_PER_REQUEST, VectorIndex, vector_key

INDEX_ARN = (
    "arn:aws:s3vectors:ap-northeast-1:123456789012:bucket/vectors/index/documents"
)
DIMENSION = 1536


class StubS3VectorsClient:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    def put_vectors(self, **kwargs):
        self.put_calls.append(kwargs)

    def delete_vectors(self, **kwargs):
        self.delete_calls.append(kwargs)


@pytest.fixture
def client():
    return StubS3VectorsClient()


def test_vector_key_matches_retriever_convention():
    # chat-fn側のRRFはこのkeyでチャンクを名寄せする
    assert vector_key("doc-1", 0) == "doc-1#0"


def test_put_chunks_registers_metadata(client):
    index = VectorIndex(INDEX_ARN, client=client)

    index.put_chunks(
        document_id="doc-1",
        filename="設計書.pdf",
        chunks=["本文1", "本文2"],
        vectors=[[0.1] * DIMENSION, [0.2] * DIMENSION],
    )

    assert len(client.put_calls) == 1
    call = client.put_calls[0]
    assert call["indexArn"] == INDEX_ARN
    assert call["vectors"] == [
        {
            "key": "doc-1#0",
            "data": {"float32": [0.1] * DIMENSION},
            "metadata": {
                "documentId": "doc-1",
                "text": "本文1",
                "filename": "設計書.pdf",
            },
        },
        {
            "key": "doc-1#1",
            "data": {"float32": [0.2] * DIMENSION},
            "metadata": {
                "documentId": "doc-1",
                "text": "本文2",
                "filename": "設計書.pdf",
            },
        },
    ]


def test_put_chunks_splits_into_api_sized_batches(client):
    index = VectorIndex(INDEX_ARN, client=client)
    count = MAX_VECTORS_PER_REQUEST + 1

    index.put_chunks(
        document_id="doc-1",
        filename="doc.txt",
        chunks=[f"本文{i}" for i in range(count)],
        vectors=[[0.1] * DIMENSION for _ in range(count)],
    )

    assert [len(call["vectors"]) for call in client.put_calls] == [
        MAX_VECTORS_PER_REQUEST,
        1,
    ]


def test_put_chunks_rejects_mismatched_lengths(client):
    index = VectorIndex(INDEX_ARN, client=client)

    with pytest.raises(ValueError):
        index.put_chunks(
            document_id="doc-1",
            filename="doc.txt",
            chunks=["本文1", "本文2"],
            vectors=[[0.1] * DIMENSION],
        )


def test_delete_keys_splits_into_api_sized_batches(client):
    index = VectorIndex(INDEX_ARN, client=client)
    keys = [vector_key("doc-1", i) for i in range(MAX_VECTORS_PER_REQUEST + 2)]

    index.delete_keys(keys)

    assert [len(call["keys"]) for call in client.delete_calls] == [
        MAX_VECTORS_PER_REQUEST,
        2,
    ]
    assert client.delete_calls[0]["indexArn"] == INDEX_ARN


def test_no_api_call_for_empty_input(client):
    index = VectorIndex(INDEX_ARN, client=client)

    index.put_chunks(document_id="doc-1", filename="doc.txt", chunks=[], vectors=[])
    index.delete_keys([])

    assert client.put_calls == []
    assert client.delete_calls == []
