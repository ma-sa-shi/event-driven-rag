import pytest
from langchain_core.embeddings import Embeddings

from app.rag.retriever import S3VectorsRetriever

INDEX_ARN = (
    "arn:aws:s3vectors:ap-northeast-1:123456789012:bucket/vectors/index/documents"
)
# Cohere embed-v4.0の次元数
DIMENSION = 1536


class StubEmbeddings(Embeddings):
    """埋め込みAPIの代わりに固定長ベクトルを返す。"""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def aembed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.1] * DIMENSION

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class StubS3VectorsClient:
    def __init__(self, vectors: list[dict]) -> None:
        self.vectors = vectors
        self.calls: list[dict] = []

    def query_vectors(self, **kwargs):
        self.calls.append(kwargs)
        return {"vectors": self.vectors}


@pytest.fixture
def embeddings():
    return StubEmbeddings()


async def test_query_vectors_receives_embedded_query_and_index_arn(embeddings):
    client = StubS3VectorsClient([])
    retriever = S3VectorsRetriever(
        embeddings=embeddings, index_arn=INDEX_ARN, top_k=5, client=client
    )

    await retriever.ainvoke("検索クエリ")

    assert embeddings.queries == ["検索クエリ"]
    assert client.calls == [
        {
            "indexArn": INDEX_ARN,
            "queryVector": {"float32": [0.1] * DIMENSION},
            "topK": 5,
            "returnMetadata": True,
            "returnDistance": True,
        }
    ]


async def test_maps_vectors_to_documents_keyed_by_vector_key(embeddings):
    client = StubS3VectorsClient(
        [
            {
                "key": "doc-1#0",
                "distance": 0.12,
                "metadata": {
                    "documentId": "doc-1",
                    "filename": "設計書.pdf",
                    "text": "チャンク本文",
                },
            }
        ]
    )
    retriever = S3VectorsRetriever(
        embeddings=embeddings, index_arn=INDEX_ARN, client=client
    )

    documents = await retriever.ainvoke("検索クエリ")

    assert len(documents) == 1
    document = documents[0]
    # RRFはdoc.idで名寄せするため、チャンク単位で一意なvector keyを使う
    assert document.id == "doc-1#0"
    assert document.page_content == "チャンク本文"
    assert document.metadata == {
        "documentId": "doc-1",
        "filename": "設計書.pdf",
        "distance": 0.12,
    }


async def test_missing_metadata_falls_back_to_empty_content(embeddings):
    client = StubS3VectorsClient([{"key": "doc-1#0"}])
    retriever = S3VectorsRetriever(
        embeddings=embeddings, index_arn=INDEX_ARN, client=client
    )

    document = (await retriever.ainvoke("検索クエリ"))[0]

    assert document.page_content == ""
    assert document.metadata["documentId"] is None


async def test_parallel_map_searches_every_query(embeddings):
    client = StubS3VectorsClient([])
    retriever = S3VectorsRetriever(
        embeddings=embeddings, index_arn=INDEX_ARN, client=client
    )

    results = await retriever.map().ainvoke(["q1", "q2", "q3"])

    assert len(results) == 3
    assert sorted(embeddings.queries) == ["q1", "q2", "q3"]
