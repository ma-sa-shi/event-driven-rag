"""POST /api/chats/stream の統合テスト。

RagRuntimeをdependency_overridesで差し替え、OpenAI, Cohere, S3 Vectorsへ一切アクセスせずにSSEとDynamoDBへの永続化を検証する
"""

import json
from dataclasses import replace
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.metrics import ANSWERS_GRADED, CHAT_RETRIES
from app.rag.graph import build_graph
from app.rag.runtime import RagRuntime, get_rag_runtime
from app.rag.stream import generate_sse
from app.repositories.chats import ChatRepository
from app.settings import get_settings
from tests.conftest import TABLE_NAME, emitted_metrics
from tests.factories import put_quota
from tests.rag.fakes import (
    FakeReranker,
    FakeRetriever,
    build_fake_chains,
    make_document,
)

client = TestClient(app)


def headers(token: str) -> dict:
    """指定されたトークンからAuthorizationヘッダーを生成するヘルパー関数。"""
    return {"Authorization": f"Bearer {token}"}


def make_runtime(chains=None, documents=None) -> RagRuntime:
    """テスト用のRagRuntimeを生成する。"""
    return RagRuntime(
        graph=build_graph(),
        chains=chains or build_fake_chains(),
        retriever=FakeRetriever(default=documents or [make_document("chunk-1")]),
        reranker=FakeReranker(),
    )


@pytest.fixture
def override_runtime():
    """テストごとにRagRuntimeを差し替え、終了時に必ず元へ戻す。

    yieldする_installにRagRuntimeを渡すとdependency_overridesへ登録され、
    テスト終了後にfixtureが登録を解除する。
    """

    def _install(runtime: RagRuntime) -> RagRuntime:
        app.dependency_overrides[get_rag_runtime] = lambda: runtime
        return runtime

    yield _install
    app.dependency_overrides.pop(get_rag_runtime, None)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """SSE形式のレスポンス文字列をパースし、(event名, data辞書)のリストへ変換する。"""
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def post_stream(make_token, question: str = "設計方針は?", token: str | None = None):
    """POST /api/chats/stream へリクエストを送信するヘルパー関数。"""
    return client.post(
        "/api/chats/stream",
        json={"question": question},
        headers=headers(token or make_token()),
    )


def test_sse_emits_one_update_per_node_then_done(make_token, aws, override_runtime):
    """正常系: グラフ内の各ノード実行ごとにupdateイベントが発火し、最後にdoneイベントで終了するか。"""
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
    """updateイベントペイロードが、全ノードの累積状態ではなく、ノードが出力した差分ステートのみに整形されているか。"""
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
    """doneイベント受信時点で、DynamoDBへの永続化が完了しており、GET APIから即座にチャット履歴が引けるか。"""
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
    """DynamoDBの仕様上floatを受け付けないため、テーブル直接参照でDecimalへ安全に変換・保存されているか。"""
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
    """回答精度不足でリトライ(retryCount > 0)が発生した場合、試行ごとの履歴が保存され、最後の試行のみに失敗分析が載るか。"""
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
    """例外発生時: グラフ実行中にエラーが起きると、errorイベントを配信し、DynamoDBへ途中の不整合データが保存されないか。"""

    class ExplodingChain:
        async def ainvoke(self, inputs, config=None):
            raise RuntimeError("OpenAIが応答しません")

    chains = replace(build_fake_chains(), generate_queries=ExplodingChain())
    override_runtime(make_runtime(chains=chains))

    events = parse_sse(post_stream(make_token).text)

    assert [name for name, _ in events] == ["error"]
    _, error = events[0]
    assert error["requestId"]
    # 途中結果は保存しない。消費済みのQuotaは失敗しても戻さない為、残る
    items = aws.table.scan()["Items"]
    assert [item for item in items if not item["SK"].startswith("QUOTA#")] == []


def test_emits_grade_and_retry_metrics_on_completion(
    make_token, aws, override_runtime, capsys
):
    """gradeはディメンションで数える為、リトライ件数とは別のEMFで発行する。"""
    override_runtime(
        make_runtime(
            chains=build_fake_chains(
                queries=[["q1", "q2", "q3"], ["r1", "r2", "r3"]],
                answers=["不十分な回答", "十分な回答"],
                grades=[("useless", "情報が不足"), ("useful", "十分")],
            )
        )
    )

    post_stream(make_token)

    metrics = {
        metric.name: metric for metric in emitted_metrics(capsys.readouterr().out)
    }
    assert metrics[ANSWERS_GRADED].dimensions == {"grade": "useful"}
    assert metrics[ANSWERS_GRADED].value == [1]
    assert metrics[CHAT_RETRIES].value == [1]
    assert "grade" not in metrics[CHAT_RETRIES].dimensions


def test_emits_no_metrics_when_graph_fails(make_token, aws, override_runtime, capsys):
    class ExplodingChain:
        async def ainvoke(self, inputs, config=None):
            raise RuntimeError("OpenAIが応答しません")

    override_runtime(
        make_runtime(
            chains=replace(build_fake_chains(), generate_queries=ExplodingChain())
        )
    )

    post_stream(make_token)

    assert emitted_metrics(capsys.readouterr().out) == []


async def test_emits_no_metrics_when_client_disconnects(aws, capsys):
    """SSEを最後まで読まずに切断された場合、完走していない為メトリクスを出さない。"""
    stream = generate_sse(
        runtime=make_runtime(),
        repository=ChatRepository(TABLE_NAME),
        question="設計方針は?",
        user_id="user-123",
        chat_id="01JCHAT000000000000000000",
        request_id="req-1",
    )
    await anext(stream)
    await stream.aclose()

    assert emitted_metrics(capsys.readouterr().out) == []


def test_requires_authentication(aws, override_runtime):
    """未認証リクエスト: Authorizationヘッダーがない場合は401エラーを返すか。"""
    override_runtime(make_runtime())

    res = client.post("/api/chats/stream", json={"question": "質問"})

    assert res.status_code == 401


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "あ" * 2001}])
def test_rejects_invalid_question(make_token, aws, override_runtime, body):
    """バリデーションエラー: リクエストボディが不正（空・文字数超過など）の場合は422エラーを返すか。"""
    override_runtime(make_runtime())

    res = client.post("/api/chats/stream", json=body, headers=headers(make_token()))

    assert res.status_code == 422


def test_上限に達したユーザーは429で拒否されグラフを実行しない(
    make_token, aws, override_runtime
):
    """上限へ達した状態はusedの直接書き込みで作る。上限回数分のチャットは流さない。"""
    chains = build_fake_chains()
    override_runtime(make_runtime(chains=chains))
    put_quota(aws.table, user_id="user-123", used=get_settings().chat_daily_quota)

    res = post_stream(make_token)

    assert res.status_code == 429
    assert "本日の利用上限" in res.json()["detail"]
    # Bedrockを呼ぶ前に止める
    assert chains.generate_queries.calls == []


def test_チャットの成功で当日の利用回数が1増える(make_token, aws, override_runtime):
    override_runtime(make_runtime())

    post_stream(make_token)

    quota = client.get("/api/users/user-123/quota", headers=headers(make_token()))
    assert quota.json()["used"] == 1
