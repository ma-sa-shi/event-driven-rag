"""SSEストリーミングチャットのエンドポイント。

chat-fnのみが公開し、api-fnのイメージには含めない(ADR-0003)。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from ulid import ULID

from app.auth import get_current_user_id
from app.dependencies import get_chat_repository, get_quota_repository
from app.logger import logger
from app.rag.runtime import RagRuntime, get_rag_runtime
from app.rag.stream import generate_sse
from app.repositories.chats import ChatRepository
from app.repositories.quota import QuotaExceededError, QuotaRepository

router = APIRouter(prefix="/chats")


class ChatStreamRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.post("/stream")
async def stream_chat(
    request: Request,
    body: ChatStreamRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
    quota_repository: Annotated[QuotaRepository, Depends(get_quota_repository)],
    runtime: Annotated[RagRuntime, Depends(get_rag_runtime)],
) -> StreamingResponse:
    """1問1答のチャットを実行し、ノード毎の出力をSSEで配信する。"""
    # chatIdはULIDのため、採番時点で一覧の並び順が確定する
    chat_id = str(ULID())
    request_id = request.state.request_id
    logger.append_keys(user_id=user_id, chat_id=chat_id)

    # Bedrockを呼ぶ前に消費する。ストリームの途中で失敗しても消費分は戻さない(ADR-0017)
    try:
        quota = quota_repository.consume(user_id)
    except QuotaExceededError as error:
        logger.warning("chat quota exceeded", used=error.status.used)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"本日の利用上限({error.status.limit}回)に達しました。"
                "日付が変わると再び送信できます。"
            ),
        ) from error
    logger.info("chat quota consumed", used=quota.used, limit=quota.limit)

    return StreamingResponse(
        generate_sse(
            runtime=runtime,
            repository=repository,
            question=body.question,
            user_id=user_id,
            chat_id=chat_id,
            request_id=request_id,
        ),
        media_type="text/event-stream",
        # レスポンスをCloudfrontでキャッシュしない
        headers={"Cache-Control": "no-cache"},
    )
