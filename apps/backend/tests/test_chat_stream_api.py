"""POST /api/chats/stream の統合テスト。

RagRuntimeをdependency_overridesで差し替え、OpenAI, Cohere, S3 Vectorsへ一切アクセスせずにSSEとDynamoDBへの永続化を検証する
"""

import json
from dataclasses import replace
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rag.graph import build_graph
from app.rag.runtime import RagRuntime, get_rag_runtime
from tests.rag.fakes import (
    FakeReranker,
    FakeRetriever,
    build_fake_chains,
    make_document,
)

client = TestClient(app)


def headers(token: str) -> dict:
    """指定されたトークンからAuthorizationヘッダーを生成するヘルパー関数"""
    return {"Authorization": f"Bearer {token}"}


def make_runtime(chains=None, documents=None) -> RagRuntime:
    """テスト用のRagRuntimeを生成する"""
    return RagRuntime(
        graph=build_graph(),
        chains=chains or build_fake_chains(),
        retriever=FakeRetriever(default=documents or [make_document("chunk-1")]),
        reranker=FakeReranker(),
    )


@pytest.fixture
def override_runtime():
    """
    テストごとにRagRuntimeを差し替え、終了時に必ず元に戻すクリーンアップ処理付きフィクスチャ
    override_runtime()に渡される引数は_install()に渡されて実行され、テスト後にクリーンアップする
    """

    def _install(runtime: RagRuntime) -> RagRuntime:
        app.dependency_overrides[get_rag_runtime] = lambda: runtime
        return runtime

    yield _install
    app.dependency_overrides.pop(get_rag_runtime, None)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """SSE形式のレスポンス文字列をパースし、(event名, data辞書)のリストへ変換する"""
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def post_stream(make_token, question: str = "設計方針は?", token: str | None = None):
    """POST /api/chats/stream へリクエストを送信するヘルパー関数"""
    return client.post(
        "/api/chats/stream",
        json={"question": question},
        headers=headers(token or make_token()),
    )


def test_sse_emits_one_update_per_node_then_done(make_token, aws, override_runtime):
    """正常系: グラフ内の各ノード実行ごとにupdateイベントが発火し、最後にdoneイベントで終了するか"""
    override_runtime(make_runtime())

    res = post_stream(make_token)

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(res.text)
    assert [name for name, _ in events] == [
        "update",
        "update",
        "update",
        "update",
        "done",
    ]
    assert [payload["node"] for _, payload in events[:-1]] == [
        "generate_queries_node",
        "retrieve_contexts_node",
        "generate_answer_node",
        "grade_answer_node",
    ]

    _, done = events[-1]
    assert done["finalGrade"] == "useful"
    assert done["retryCount"] == 0
    assert done["chatId"]


def test_update_events_unwrap_accumulated_state_and_normalize_documents(
    make_token, aws, override_runtime
):
    """updateイベントペイロードが、全ノードの累積状態ではなく、ノードが出力した差分ステートのみに整形されているか"""
    override_runtime(
        make_runtime(
            chains=build_fake_chains(queries=[["q1", "q2", "q3"]], answers=["回答本文"])
        )
    )

    events = parse_sse(post_stream(make_token).text)
    by_node = {payload["node"]: payload["state"] for _, payload in events[:-1]}

    # 試行ごとに積み上がるキーは、そのノードが出した1試行ぶんだけを配信する
    assert by_node["generate_queries_node"] == {
        "queries": ["q1", "q2", "q3"],
        "retry_count": 0,
    }
    assert by_node["generate_answer_node"] == {"answer": "回答本文"}
    assert by_node["grade_answer_node"] == {
        "grade": "useful",
        "feedback": "根拠が十分",
    }
    assert by_node["retrieve_contexts_node"]["documents"] == [
        {
            "documentId": "doc-1",
            "filename": "doc-1.pdf",
            "text": "chunk-1の本文",
            "score": 0.9,
        }
    ]


def test_result_is_persisted_before_done_and_readable_via_get_chat(
    make_token, aws, override_runtime
):
    """doneイベント受信時点で、DynamoDBへの永続化が完了しており、GET APIから即座にチャット履歴が引けるか"""
    override_runtime(
        make_runtime(
            chains=build_fake_chains(queries=[["q1", "q2", "q3"]], answers=["回答本文"])
        )
    )
    token = make_token(sub="user-a")

    _, done = parse_sse(post_stream(make_token, token=token).text)[-1]
    chat_id = done["chatId"]

    # doneを受けた直後に詳細を引けること(永続化はdone送信より前に完了している必要がある)
    res = client.get(f"/api/chats/{chat_id}", headers=headers(token))
    assert res.status_code == 200
    chat = res.json()
    assert chat["userId"] == "user-a"
    assert chat["question"] == "設計方針は?"
    assert chat["finalAnswer"] == "回答本文"
    assert chat["finalGrade"] == "useful"
    assert chat["retryCount"] == 0

    assert len(chat["attempts"]) == 1
    attempt = chat["attempts"][0]
    assert attempt["attemptNo"] == 0
    assert attempt["queries"] == ["q1", "q2", "q3"]
    assert attempt["answer"] == "回答本文"
    assert attempt["grade"] == "useful"
    assert attempt["failureAnalysis"] is None
    assert attempt["documents"] == [
        {
            "documentId": "doc-1",
            "filename": "doc-1.pdf",
            "text": "chunk-1の本文",
            "score": 0.9,
        }
    ]


def test_scores_are_stored_as_decimal(make_token, aws, override_runtime):
    """DynamoDBの仕様上floatを受け付けないため、テーブル直接参照でDecimalへ安全に変換・保存されているか"""
    override_runtime(make_runtime())
    token = make_token(sub="user-a")

    _, done = parse_sse(post_stream(make_token, token=token).text)[-1]

    item = aws.table.get_item(
        Key={"PK": "USER#user-a", "SK": f"MSG#{done['chatId']}#0"}
    )["Item"]
    # DynamoDBはfloatを受け付けないため、Decimalへ丸めて保存する
    assert item["documents"][0]["score"] == Decimal("0.9")


def test_retry_persists_one_row_per_attempt_with_failure_analysis_last(
    make_token, aws, override_runtime
):
    """回答精度不足でリトライ(retryCount > 0)が発生した場合、試行ごとの履歴が保存され、最後の試行のみに失敗分析が載るか"""
    override_runtime(
        make_runtime(
            chains=build_fake_chains(
                queries=[["q1", "q2", "q3"], ["r1", "r2", "r3"]],
                answers=["不十分な回答", "まだ不十分な回答"],
                grades=[("useless", "情報が不足"), ("useless", "やはり不足")],
                failure_analysis="ベクトルストアに必要な情報が存在しない。",
            )
        )
    )
    token = make_token(sub="user-a")

    events = parse_sse(post_stream(make_token, token=token).text)
    _, done = events[-1]
    assert done["retryCount"] == 1
    # リトライ上限失敗後に analyze_failure_node が実行されていること
    assert [payload["node"] for _, payload in events[:-1]][-1] == "analyze_failure_node"

    chat = client.get(f"/api/chats/{done['chatId']}", headers=headers(token)).json()
    assert chat["retryCount"] == 1
    assert chat["finalAnswer"] == "まだ不十分な回答"
    attempts = chat["attempts"]
    assert [a["queries"] for a in attempts] == [
        ["q1", "q2", "q3"],
        ["r1", "r2", "r3"],
    ]
    # failureAnalysisは最終試行の行にだけ載る
    assert [a["failureAnalysis"] for a in attempts] == [
        None,
        "ベクトルストアに必要な情報が存在しない。",
    ]


def test_graph_failure_emits_error_event_and_persists_nothing(
    make_token, aws, override_runtime
):
    """例外発生時: グラフ実行中にエラーが起きると、errorイベントを配信し、DynamoDBへ途中の不整合データが保存されないか"""

    class ExplodingChain:
        async def ainvoke(self, inputs, config=None):
            raise RuntimeError("OpenAIが応答しません")

    chains = replace(build_fake_chains(), generate_queries=ExplodingChain())
    override_runtime(make_runtime(chains=chains))

    events = parse_sse(post_stream(make_token).text)

    assert [name for name, _ in events] == ["error"]
    _, error = events[0]
    assert error["requestId"]
    # 途中結果は保存しない
    assert aws.table.scan()["Items"] == []


def test_requires_authentication(aws, override_runtime):
    """未認証リクエスト: Authorizationヘッダーがない場合は401エラーを返すか"""
    override_runtime(make_runtime())

    res = client.post("/api/chats/stream", json={"question": "質問"})

    assert res.status_code == 401


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "あ" * 2001}])
def test_rejects_invalid_question(make_token, aws, override_runtime, body):
    """バリデーションエラー: リクエストボディが不正（空・文字数超過など）の場合は422エラーを返すか"""
    override_runtime(make_runtime())

    res = client.post("/api/chats/stream", json=body, headers=headers(make_token()))

    assert res.status_code == 422
