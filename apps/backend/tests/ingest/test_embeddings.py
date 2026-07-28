import json

import httpx
import pytest

from app.ingest.embeddings import (
    COHERE_EMBED_URL,
    EMBEDDING_DIMENSION,
    MAX_TEXTS_PER_REQUEST,
    CohereEmbedder,
)

MODEL = "embed-v4.0"


def build_embedder(handler) -> tuple[CohereEmbedder, list[httpx.Request]]:
    """Cohere APIを呼ばずにリクエスト内容を記録するembedderを組み立てる。"""
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(record))
    return (
        CohereEmbedder(api_key="test-key", model=MODEL, client=client),
        requests,
    )


def respond_with_vectors(request: httpx.Request) -> httpx.Response:
    texts = json.loads(request.content)["texts"]
    return httpx.Response(
        200,
        json={"embeddings": {"float": [[0.1] * EMBEDDING_DIMENSION for _ in texts]}},
    )


def test_sends_search_document_request_to_cohere():
    embedder, requests = build_embedder(respond_with_vectors)

    vectors = embedder.embed_documents(["チャンク1", "チャンク2"])

    assert len(vectors) == 2
    assert all(len(vector) == EMBEDDING_DIMENSION for vector in vectors)
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == COHERE_EMBED_URL
    assert request.headers["Authorization"] == "Bearer test-key"
    payload = json.loads(request.content)
    assert payload == {
        "model": MODEL,
        "texts": ["チャンク1", "チャンク2"],
        # 検索側(search_query)と対になる取込側の指定
        "input_type": "search_document",
        "embedding_types": ["float"],
        "output_dimension": EMBEDDING_DIMENSION,
    }


def test_splits_requests_by_api_batch_limit():
    embedder, requests = build_embedder(respond_with_vectors)
    texts = [f"チャンク{index}" for index in range(MAX_TEXTS_PER_REQUEST + 5)]

    vectors = embedder.embed_documents(texts)

    # 順序が保たれたまま全チャンク分のベクトルが返る
    assert len(vectors) == len(texts)
    assert len(requests) == 2


def test_no_request_for_empty_input():
    embedder, requests = build_embedder(respond_with_vectors)

    assert embedder.embed_documents([]) == []
    assert requests == []


def test_raises_on_api_error():
    """失敗は握りつぶさず、SQSの再試行とDLQ退避に委ねる。"""
    embedder, _ = build_embedder(lambda request: httpx.Response(429, json={}))

    with pytest.raises(httpx.HTTPStatusError):
        embedder.embed_documents(["チャンク"])


def test_raises_when_response_count_does_not_match():
    embedder, _ = build_embedder(
        lambda request: httpx.Response(
            200, json={"embeddings": {"float": [[0.1] * EMBEDDING_DIMENSION]}}
        )
    )

    with pytest.raises(ValueError):
        embedder.embed_documents(["チャンク1", "チャンク2"])
