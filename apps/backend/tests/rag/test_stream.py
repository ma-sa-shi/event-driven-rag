"""summarize_usageの集計ロジックの検証。

LLMのトークン数はコールバックが持つ値をそのまま通すだけの為、
EmbeddingとRerankの回数を最終stateから正しく復元できるかを主に確かめる。
"""

from langchain_core.callbacks import UsageMetadataCallbackHandler

from app.rag.stream import summarize_usage
from tests.rag.fakes import make_document


def build_handler(usage: dict) -> UsageMetadataCallbackHandler:
    handler = UsageMetadataCallbackHandler()
    handler.usage_metadata = usage
    return handler


def test_リトライなしのチャットは1試行分を数える():
    state = {
        "queries": [["クエリ1", "クエリ2", "クエリ3"]],
        "documents": [[make_document("chunk-1")]],
    }

    usage = summarize_usage(build_handler({}), state)

    assert usage["embedding_calls"] == 3
    assert usage["embedding_query_chars"] == len("クエリ1") * 3
    assert usage["rerank_calls"] == 1


def test_リトライしたチャットは全試行を合算する():
    state = {
        "queries": [["クエリ1", "クエリ2"], ["クエリ3", "クエリ4", "クエリ5"]],
        "documents": [[make_document("chunk-1")], [make_document("chunk-2")]],
    }

    usage = summarize_usage(build_handler({}), state)

    assert usage["embedding_calls"] == 5
    assert usage["rerank_calls"] == 2


def test_モデル別のトークン数はコールバックの値をそのまま載せる():
    handler = build_handler(
        {"jp.amazon.nova-2-lite-v1:0": {"input_tokens": 1200, "output_tokens": 300}}
    )

    usage = summarize_usage(handler, {})

    assert usage["models"]["jp.amazon.nova-2-lite-v1:0"]["input_tokens"] == 1200
    assert usage["embedding_calls"] == 0
    assert usage["rerank_calls"] == 0
