import io
import json

import pytest

from app.rag.embeddings import EMBEDDING_DIMENSION, BedrockQueryEmbeddings

MODEL = "cohere.embed-v4:0"


class StubBedrockRuntime:
    def __init__(self, payload) -> None:
        self.calls: list[dict] = []
        self._payload = payload

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        return {"body": io.BytesIO(json.dumps(self._payload).encode())}


def build_embeddings(payload) -> tuple[BedrockQueryEmbeddings, StubBedrockRuntime]:
    client = StubBedrockRuntime(payload)
    return BedrockQueryEmbeddings(model=MODEL, client=client), client


def test_embeds_query_as_search_query():
    vector = [0.1] * EMBEDDING_DIMENSION
    embeddings, client = build_embeddings({"embeddings": {"float": [vector]}})

    assert embeddings.embed_query("RAGの設計") == vector
    assert client.calls[0]["modelId"] == MODEL
    assert json.loads(client.calls[0]["body"]) == {
        "texts": ["RAGの設計"],
        # 取込側(search_document)と対になる検索側の指定
        "input_type": "search_query",
        "embedding_types": ["float"],
        "output_dimension": EMBEDDING_DIMENSION,
    }


def test_accepts_flat_embeddings_response():
    vector = [0.2] * EMBEDDING_DIMENSION
    embeddings, _ = build_embeddings({"embeddings": [vector]})

    assert embeddings.embed_query("RAGの設計") == vector


async def test_aembed_query_returns_same_vector():
    """Retrieverは非同期でしか呼ばない。同期実装が非同期経由でも使えること。"""
    vector = [0.3] * EMBEDDING_DIMENSION
    embeddings, _ = build_embeddings({"embeddings": {"float": [vector]}})

    assert await embeddings.aembed_query("RAGの設計") == vector


def test_embed_documents_is_not_supported():
    embeddings, _ = build_embeddings({"embeddings": {"float": []}})

    with pytest.raises(NotImplementedError):
        embeddings.embed_documents(["チャンク"])
