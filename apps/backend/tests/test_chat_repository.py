from decimal import Decimal

import pytest

from app.repositories.chats import ChatRepository
from tests.conftest import TABLE_NAME
from tests.factories import put_attempt, put_chat


@pytest.fixture
def repository(aws):
    """DynamoDBテーブルがセットアップされたChatRepositoryインスタンスを生成する。"""
    return ChatRepository(TABLE_NAME)


def test_create_chat_writes_keys_that_both_list_queries_use(repository):
    """create_chatで保存したデータが、ID検索(get)とユーザー別一覧(list_by_user)の双方から取得できるか。"""
    repository.create_chat(
        user_id="user-a",
        chat_id="chat-1",
        question="質問",
        final_answer="回答",
        final_grade="useful",
        retry_count=1,
    )

    # GSI1経由の横断一覧と、PK/SK経由のユーザー別一覧の両方から引ける
    chat = repository.get("chat-1")
    assert chat["userId"] == "user-a"
    assert chat["question"] == "質問"
    assert chat["finalAnswer"] == "回答"
    assert chat["finalGrade"] == "useful"
    assert chat["retryCount"] == 1
    assert chat["createdAt"]
    assert repository.list_by_user("user-a", limit=50) == [chat]


def test_put_attempt_stores_scores_as_decimal(repository):
    """DynamoDBの仕様上floatが使えない為、ドキュメントの検索スコア(float)がDecimal型へ自動変換・保存されるか。"""
    repository.put_attempt(
        user_id="user-a",
        chat_id="chat-1",
        attempt_no=0,
        queries=["q1", "q2"],
        documents=[
            {
                "documentId": "doc-1",
                "filename": "設計書.pdf",
                "text": "本文",
                # DynamoDBはfloatを受け付けないため丸めたDecimalへ変換する
                "score": 0.98765432,
            },
            {
                "documentId": "doc-2",
                "filename": "手順書.pdf",
                "text": "本文",
                "score": None,
            },
        ],
        answer="回答",
        grade="useless",
        feedback="情報が不足",
    )

    attempt = repository.list_attempts("user-a", "chat-1")[0]
    assert attempt["attemptNo"] == 0
    assert attempt["queries"] == ["q1", "q2"]
    assert attempt["documents"][0]["score"] == Decimal("0.987654")
    assert attempt["documents"][1]["score"] is None
    assert attempt["failureAnalysis"] is None


def test_attempts_of_one_chat_are_ordered_by_attempt_no(repository):
    """同一チャット内の複数試行が、attemptNo順に正しくソートされて取得できるか。"""
    for attempt_no in (0, 1):
        repository.put_attempt(
            user_id="user-a",
            chat_id="chat-1",
            attempt_no=attempt_no,
            queries=["q"],
            documents=[],
            answer="回答",
            grade="useless",
            feedback="情報が不足",
            failure_analysis="原因" if attempt_no == 1 else None,
        )

    attempts = repository.list_attempts("user-a", "chat-1")
    assert [a["attemptNo"] for a in attempts] == [0, 1]
    assert [a["failureAnalysis"] for a in attempts] == [None, "原因"]


def test_get_finds_chat_via_gsi_regardless_of_owner(repository, aws):
    """getメソッドが所有者を指定しなくてもGSI1経由でチャットを取得できるか。"""
    put_chat(aws.table, user_id="user-a", chat_id="chat-1")

    assert repository.get("chat-1")["userId"] == "user-a"
    assert repository.get("unknown") is None


def test_lists_are_newest_first_and_scoped_by_user(repository, aws):
    """全体新着一覧(list_recent)とユーザー別一覧(list_by_user)が、作成日時の新しい順で取得できるか。"""
    put_chat(aws.table, user_id="user-a", chat_id="chat-1")
    put_chat(aws.table, user_id="user-b", chat_id="chat-2")
    put_chat(aws.table, user_id="user-a", chat_id="chat-3")

    assert [c["chatId"] for c in repository.list_recent(limit=50)] == [
        "chat-3",
        "chat-2",
        "chat-1",
    ]
    assert [c["chatId"] for c in repository.list_recent(limit=1)] == ["chat-3"]
    assert [c["chatId"] for c in repository.list_by_user("user-a", limit=50)] == [
        "chat-3",
        "chat-1",
    ]


def test_list_attempts_returns_only_target_chat_in_order(repository, aws):
    """list_attemptsが別チャットの試行データを混入させず、対象チャットの試行のみを正しい順序で返すか。"""
    put_chat(aws.table, user_id="user-a", chat_id="chat-1")
    put_attempt(aws.table, user_id="user-a", chat_id="chat-1", attempt_no=0)
    put_attempt(aws.table, user_id="user-a", chat_id="chat-1", attempt_no=1)
    put_attempt(aws.table, user_id="user-a", chat_id="chat-2", attempt_no=0)

    attempts = repository.list_attempts("user-a", "chat-1")
    assert [a["attemptNo"] for a in attempts] == [0, 1]
