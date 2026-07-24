import pytest

from app.repositories.chats import ChatRepository
from tests.conftest import TABLE_NAME
from tests.factories import put_attempt, put_chat


@pytest.fixture
def repository(aws):
    return ChatRepository(TABLE_NAME)


def test_get_finds_chat_via_gsi_regardless_of_owner(repository, aws):
    put_chat(aws.table, user_id="user-a", chat_id="chat-1")

    assert repository.get("chat-1")["userId"] == "user-a"
    assert repository.get("unknown") is None


def test_lists_are_newest_first_and_scoped_by_user(repository, aws):
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
    put_chat(aws.table, user_id="user-a", chat_id="chat-1")
    put_attempt(aws.table, user_id="user-a", chat_id="chat-1", attempt_no=0)
    put_attempt(aws.table, user_id="user-a", chat_id="chat-1", attempt_no=1)
    put_attempt(aws.table, user_id="user-a", chat_id="chat-2", attempt_no=0)

    attempts = repository.list_attempts("user-a", "chat-1")
    assert [a["attemptNo"] for a in attempts] == [0, 1]
