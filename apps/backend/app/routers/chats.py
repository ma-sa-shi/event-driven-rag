from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import get_current_user_id
from app.dependencies import get_chat_repository
from app.repositories.chats import ChatRepository
from app.schemas import ChatSummaryResponse

router = APIRouter(prefix="/chats")


class RetrievedDocumentResponse(BaseModel):
    document_id: str | None = Field(alias="documentId", default=None)
    filename: str | None = None
    text: str | None = None
    score: float | None = None


class ChatAttemptResponse(BaseModel):
    attempt_no: int = Field(alias="attemptNo")
    queries: list[str] = []
    documents: list[RetrievedDocumentResponse] = []
    answer: str | None = None
    grade: str | None = None
    feedback: str | None = None
    failure_analysis: str | None = Field(alias="failureAnalysis", default=None)


class ChatDetailResponse(ChatSummaryResponse):
    attempts: list[ChatAttemptResponse]


@router.get("")
def list_chats(
    _caller_id: Annotated[str, Depends(get_current_user_id)],
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ChatSummaryResponse]:
    """全ユーザーのチャット一覧を新しい順で返す。"""
    return [
        ChatSummaryResponse.model_validate(i) for i in repository.list_recent(limit)
    ]


@router.get("/{chat_id}")
def get_chat(
    chat_id: str,
    _caller_id: Annotated[str, Depends(get_current_user_id)],
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
) -> ChatDetailResponse:
    """チャット詳細を試行ごとの全ての出力を返す。"""
    chat = repository.get(chat_id)
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="chat not found")
    attempts = repository.list_attempts(chat["userId"], chat_id)
    return ChatDetailResponse.model_validate({**chat, "attempts": attempts})
