"""SSE配信と、完了後のDynamoDB永続化。

グラフを `stream_mode=["updates", "values"]` で1度だけ流し、
updatesをSSEへ、最後のvaluesを永続化用の最終stateとして使う。
checkpointerを持たない為、状態はこのストリームからしか取れない。
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from itertools import zip_longest
from typing import Any

from langchain_core.documents import Document

from app.logger import logger
from app.rag.runtime import RagRuntime
from app.repositories.chats import ChatRepository

# GraphStateで試行ごとに積み上がるキー。1ノードの更新差分は必ず1試行分の為、
# SSEでは外側のリストを外して「そのノードが出した値」だけを送る
ACCUMULATED_KEYS = frozenset({"queries", "documents", "answer", "grade", "feedback"})


def to_document_payload(document: Document) -> dict:
    """Documentを、SSE・DynamoDB・既存GET APIで共通のshapeへ正規化する。"""
    metadata = document.metadata or {}
    return {
        "documentId": metadata.get("documentId"),
        "filename": metadata.get("filename"),
        "text": document.page_content,
        # Rerank後のスコア。Rerankを通っていない場合はNone
        "score": metadata.get("relevance_score"),
    }


def _serialize_value(key: str, value: Any) -> Any:
    if key in ACCUMULATED_KEYS and isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, list):
        return [to_document_payload(v) if isinstance(v, Document) else v for v in value]
    return value


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _attempts(state: dict) -> list[tuple]:
    """最終stateを試行ごとの行へ展開する。

    ノードによって積み上がる要素数が揃わない場合(失敗分析へ抜けた等)があるため、
    最長のリストに合わせてNoneで埋める。
    """
    return list(
        zip_longest(
            state.get("queries", []),
            state.get("documents", []),
            state.get("answer", []),
            state.get("grade", []),
            state.get("feedback", []),
        )
    )


def persist(
    repository: ChatRepository,
    *,
    user_id: str,
    chat_id: str,
    question: str,
    state: dict,
) -> None:
    """ヘッダーと試行ごとの全出力を書き込む。"""
    answers = state.get("answer") or []
    grades = state.get("grade") or []

    repository.create_chat(
        user_id=user_id,
        chat_id=chat_id,
        question=question,
        final_answer=answers[-1] if answers else None,
        final_grade=grades[-1] if grades else None,
        retry_count=state.get("retry_count", 0),
    )

    rows = _attempts(state)
    for attempt_no, (queries, documents, answer, grade, feedback) in enumerate(rows):
        # failure analysisは最終試行に対する分析のため、最後の行にだけ載せる
        is_last = attempt_no == len(rows) - 1
        repository.put_attempt(
            user_id=user_id,
            chat_id=chat_id,
            attempt_no=attempt_no,
            queries=list(queries or []),
            documents=[to_document_payload(d) for d in documents or []],
            answer=answer,
            grade=grade,
            feedback=feedback,
            failure_analysis=state.get("failure_analysis") if is_last else None,
        )


async def generate_sse(
    *,
    runtime: RagRuntime,
    repository: ChatRepository,
    question: str,
    user_id: str,
    chat_id: str,
    request_id: str,
) -> AsyncGenerator[str, None]:
    """ノードごとのstate更新をSSEで配信し、完了後にdoneイベントを返す。"""
    logger.info("chat stream started", chat_id=chat_id, question=question[:50])

    final_state: dict = {}
    try:
        async for mode, payload in runtime.graph.astream(
            {
                "question": question,
                "user_id": user_id,
                "request_id": request_id,
                "retry_count": 0,
            },
            config=runtime.configurable(user_id=user_id, request_id=request_id),
            stream_mode=["updates", "values"],
        ):
            if mode == "values":
                final_state = payload
                continue
            for node, update in payload.items():
                yield _sse(
                    "update",
                    {
                        "node": node,
                        "state": {k: _serialize_value(k, v) for k, v in update.items()},
                    },
                )

        # フロントがdone受信直後に詳細画面へ遷移できるよう、永続化を終えてから通知する
        await asyncio.to_thread(
            persist,
            repository,
            user_id=user_id,
            chat_id=chat_id,
            question=question,
            state=final_state,
        )
    except Exception:
        # 途中結果は永続化しない(部分的なチャットを一覧へ出さない)
        logger.exception("chat stream failed", chat_id=chat_id)
        yield _sse(
            "error",
            {"message": "チャットの生成に失敗しました。", "requestId": request_id},
        )
        return

    grades = final_state.get("grade") or []
    logger.info("chat stream finished", chat_id=chat_id)
    yield _sse(
        "done",
        {
            "chatId": chat_id,
            "finalGrade": grades[-1] if grades else None,
            "retryCount": final_state.get("retry_count", 0),
        },
    )
