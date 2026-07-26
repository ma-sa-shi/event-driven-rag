"""グラフ全体の3フロー(一発成功 / 1回リトライ / リトライ上限)を検証する。"""

from app.rag.graph import build_graph
from tests.rag.fakes import (
    FakeReranker,
    FakeRetriever,
    build_fake_chains,
    make_document,
)


async def run_graph(chains, question: str = "質問") -> dict:
    graph = build_graph()
    return await graph.ainvoke(
        {
            "question": question,
            "user_id": "user-1",
            "request_id": "req-1",
            "retry_count": 0,
        },
        config={
            "configurable": {
                "chains": chains,
                "retriever": FakeRetriever(default=[make_document("a")]),
                "reranker": FakeReranker(),
            }
        },
    )


async def test_useful_on_first_attempt_finishes_without_retry():
    chains = build_fake_chains(
        answers=["最初の回答"], grades=[("useful", "根拠が十分")]
    )

    state = await run_graph(chains)

    assert state["retry_count"] == 0
    assert state["grade"] == ["useful"]
    assert state["answer"] == ["最初の回答"]
    assert len(state["queries"]) == 1
    assert "failure_analysis" not in state


async def test_useless_then_useful_retries_once():
    chains = build_fake_chains(
        queries=[["q1", "q2", "q3"], ["r1", "r2", "r3"]],
        answers=["不十分な回答", "十分な回答"],
        grades=[("useless", "情報が不足"), ("useful", "根拠が十分")],
    )

    state = await run_graph(chains)

    assert state["retry_count"] == 1
    assert state["grade"] == ["useless", "useful"]
    assert state["answer"] == ["不十分な回答", "十分な回答"]
    assert state["queries"] == [["q1", "q2", "q3"], ["r1", "r2", "r3"]]
    # 成功で終わったため失敗分析は走らない
    assert "failure_analysis" not in state


async def test_second_failure_forces_finish_with_failure_analysis():
    chains = build_fake_chains(
        answers=["回答1", "回答2"],
        grades=[("useless", "情報が不足"), ("hallucination", "根拠がない")],
        failure_analysis="ベクトルストアに必要な情報が存在しない。",
    )

    state = await run_graph(chains)

    # リトライは1回まで。2回目の失敗で必ず打ち切る
    assert state["retry_count"] == 1
    assert state["grade"] == ["useless", "hallucination"]
    assert state["failure_analysis"] == "ベクトルストアに必要な情報が存在しない。"
    assert len(state["queries"]) == 2


async def test_updates_stream_emits_nodes_in_pipeline_order():
    chains = build_fake_chains()
    graph = build_graph()

    nodes = []
    async for mode, payload in graph.astream(
        {"question": "質問", "retry_count": 0},
        config={
            "configurable": {
                "chains": chains,
                "retriever": FakeRetriever(default=[make_document("a")]),
                "reranker": FakeReranker(),
            }
        },
        stream_mode=["updates", "values"],
    ):
        if mode == "updates":
            nodes.extend(payload.keys())

    assert nodes == [
        "generate_queries_node",
        "retrieve_contexts_node",
        "generate_answer_node",
        "grade_answer_node",
    ]
