import io
import json

import pytest

from app.ingest.embeddings import (
    EMBEDDING_DIMENSION,
    MAX_TEXTS_PER_REQUEST,
    BedrockEmbedder,
)

MODEL = "cohere.embed-v4:0"


class StubBedrockRuntime:
    """invoke_modelの呼び出しを記録し、渡されたテキスト数だけベクトルを返す。"""

    def __init__(self, respond=None) -> None:
        self.calls: list[dict] = []
        self._respond = respond or self._default_response

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        texts = json.loads(kwargs["body"])["texts"]
        return {"body": io.BytesIO(json.dumps(self._respond(texts)).encode())}

    @staticmethod
    def _default_response(texts: list[str]) -> dict:
        return {"embeddings": {"float": [[0.1] * EMBEDDING_DIMENSION for _ in texts]}}


def build_embedder(respond=None) -> tuple[BedrockEmbedder, StubBedrockRuntime]:
    client = StubBedrockRuntime(respond)
    return BedrockEmbedder(model=MODEL, client=client), client


def request_body(call: dict) -> dict:
    return json.loads(call["body"])


def test_sends_search_document_request_to_bedrock():
    embedder, client = build_embedder()

    vectors = embedder.embed_documents(["チャンク1", "チャンク2"])

    assert len(vectors) == 2
    assert all(len(vector) == EMBEDDING_DIMENSION for vector in vectors)
    assert len(client.calls) == 1
    assert client.calls[0]["modelId"] == MODEL
    assert request_body(client.calls[0]) == {
        "texts": ["チャンク1", "チャンク2"],
        # 検索側(search_query)と対になる取込側の指定
        "input_type": "search_document",
        "embedding_types": ["float"],
        "output_dimension": EMBEDDING_DIMENSION,
    }


def test_accepts_flat_embeddings_response():
    """1種類だけ指定したときの応答形式は、モデルカードでは配列直下と記述される。"""
    embedder, _ = build_embedder(
        lambda texts: {"embeddings": [[0.2] * EMBEDDING_DIMENSION for _ in texts]}
    )

    vectors = embedder.embed_documents(["チャンク"])

    assert vectors == [[0.2] * EMBEDDING_DIMENSION]


def test_splits_requests_by_api_batch_limit():
    embedder, client = build_embedder()
    texts = [f"チャンク{index}" for index in range(MAX_TEXTS_PER_REQUEST + 5)]

    vectors = embedder.embed_documents(texts)

    # 順序が保たれたまま全チャンク分のベクトルが返る
    assert len(vectors) == len(texts)
    assert len(client.calls) == 2


def test_no_request_for_empty_input():
    embedder, client = build_embedder()

    assert embedder.embed_documents([]) == []
    assert client.calls == []


def test_raises_on_invoke_error():
    """失敗は握りつぶさず、SQSの再試行とDLQ退避に委ねる。"""

    def fail(texts):
        raise RuntimeError("throttled")

    embedder, _ = build_embedder(fail)

    with pytest.raises(RuntimeError):
        embedder.embed_documents(["チャンク"])


def test_raises_when_response_count_does_not_match():
    embedder, _ = build_embedder(
        lambda texts: {"embeddings": {"float": [[0.1] * EMBEDDING_DIMENSION]}}
    )

    with pytest.raises(ValueError):
        embedder.embed_documents(["チャンク1", "チャンク2"])
