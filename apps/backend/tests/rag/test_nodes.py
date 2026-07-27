"""各ノードの単体テスト。依存はconfigで注入するためmonkeypatchは使わない。"""

import pytest

from app.rag.nodes import (
    FEEDBACK_PREFIX,
    analyze_failure_node,
    generate_answer_node,
    generate_queries_node,
    grade_answer_node,
    retrieve_contexts_node,
)
from tests.rag.fakes import (
    FakeReranker,
    FakeRetriever,
    build_fake_chains,
    make_document,
)


def make_config(**overrides):
    configurable = {"chains": build_fake_chains(), **overrides}
    return {"configurable": configurable}


async def test_generate_queries_first_attempt_sends_no_feedback():
    chains = build_fake_chains(queries=[["q1", "q2", "q3"]])
    config = make_config(chains=chains)

    result = await generate_queries_node({"question": "質問", "retry_count": 0}, config)

    assert result == {"queries": [["q1", "q2", "q3"]], "retry_count": 0}
    assert chains.generate_queries.calls[0]["feedback"] == ""


async def test_generate_queries_retry_increments_count_and_prefixes_feedback():
    chains = build_fake_chains(queries=[["r1", "r2", "r3"]])
    config = make_config(chains=chains)

    result = await generate_queries_node(
        {
            "question": "質問",
            # 既にqueriesが積まれている = 2周目
            "queries": [["q1", "q2", "q3"]],
            "feedback": ["情報が不足"],
            "retry_count": 0,
        },
        config,
    )

    assert result["retry_count"] == 1
    assert result["queries"] == [["r1", "r2", "r3"]]
    assert (
        chains.generate_queries.calls[0]["feedback"] == f"{FEEDBACK_PREFIX}情報が不足"
    )


async def test_generate_queries_uses_latest_feedback():
    chains = build_fake_chains()
    config = make_config(chains=chains)

    await generate_queries_node(
        {
            "question": "質問",
            "queries": [["q1"]],
            "feedback": ["古い指摘", "最新の指摘"],
            "retry_count": 0,
        },
        config,
    )

    assert (
        chains.generate_queries.calls[0]["feedback"] == f"{FEEDBACK_PREFIX}最新の指摘"
    )


async def test_retrieve_contexts_fuses_all_queries_then_reranks():
    a, b, c = (make_document(k) for k in ("a", "b", "c"))
    retriever = FakeRetriever(results={"q1": [a, b], "q2": [b, c]})
    reranker = FakeReranker(top_n=2)
    config = make_config(retriever=retriever, reranker=reranker)

    result = await retrieve_contexts_node(
        {"question": "質問", "queries": [["q1", "q2"]]}, config
    )

    # 全クエリで検索し、RRF後にrerankでtop_n件へ絞る
    assert sorted(retriever.queries) == ["q1", "q2"]
    assert reranker.calls == [(3, "質問")]
    documents = result["documents"][0]
    assert [d.id for d in documents] == ["b", "a"]
    assert documents[0].metadata["relevance_score"] == pytest.approx(0.9)


async def test_retrieve_contexts_searches_only_latest_queries():
    retriever = FakeRetriever(default=[make_document("a")])
    config = make_config(retriever=retriever, reranker=FakeReranker())

    await retrieve_contexts_node(
        {"question": "質問", "queries": [["古いクエリ"], ["新しいクエリ"]]}, config
    )

    assert retriever.queries == ["新しいクエリ"]


async def test_retrieve_contexts_requires_retriever_and_reranker():
    with pytest.raises(ValueError, match="retriever"):
        await retrieve_contexts_node(
            {"question": "質問", "queries": [["q1"]]}, make_config()
        )


async def test_generate_answer_uses_latest_documents():
    chains = build_fake_chains(answers=["回答本文"])
    config = make_config(chains=chains)
    documents = [make_document("a")]

    result = await generate_answer_node(
        {"question": "質問", "documents": [[make_document("old")], documents]}, config
    )

    assert result == {"answer": ["回答本文"]}
    assert chains.generate_answer.calls[0]["context"] == documents


async def test_generate_answer_tolerates_no_documents():
    config = make_config()

    result = await generate_answer_node({"question": "質問", "documents": []}, config)

    assert result == {"answer": ["回答"]}


async def test_grade_answer_returns_grade_and_feedback_as_single_element_lists():
    chains = build_fake_chains(grades=[("useless", "情報が不足")])
    config = make_config(chains=chains)

    result = await grade_answer_node(
        {
            "question": "質問",
            "answer": ["古い回答", "最新の回答"],
            "documents": [[make_document("a")]],
        },
        config,
    )

    assert result == {"grade": ["useless"], "feedback": ["情報が不足"]}
    assert chains.grade_answer.calls[0]["answer"] == "最新の回答"


async def test_analyze_failure_compares_initial_and_latest_attempt():
    chains = build_fake_chains(failure_analysis="必要な情報が存在しない")
    config = make_config(chains=chains)
    initial_docs = [make_document("a")]

    result = await analyze_failure_node(
        {
            "question": "質問",
            "queries": [["初回クエリ"], ["再試行クエリ"]],
            "documents": [initial_docs, [make_document("b")]],
            "feedback": ["初回の指摘", "再試行の指摘"],
            "retry_count": 1,
        },
        config,
    )

    assert result == {"failure_analysis": "必要な情報が存在しない"}
    call = chains.analyze_failure.calls[0]
    assert call["initial_queries"] == ["初回クエリ"]
    assert call["initial_context"] == initial_docs
    assert call["initial_feedback"] == "初回の指摘"
    assert call["retry_feedback"] == "再試行の指摘"
