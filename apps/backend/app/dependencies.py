"""複数のルーターで共有するFastAPI DIファクトリ。"""

from typing import Annotated

from fastapi import Depends

from app.ingest_queue import IngestQueue
from app.repositories.chats import ChatRepository
from app.repositories.documents import DocumentRepository
from app.repositories.users import UserRepository
from app.settings import Settings, get_settings
from app.storage import DocumentStorage


def get_document_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentRepository:
    return DocumentRepository(settings.table_name)


def get_chat_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatRepository:
    return ChatRepository(settings.table_name)


def get_user_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserRepository:
    return UserRepository(settings.table_name)


def get_document_storage(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentStorage:
    return DocumentStorage(settings.documents_bucket_name)


def get_ingest_queue(
    settings: Annotated[Settings, Depends(get_settings)],
) -> IngestQueue:
    return IngestQueue(settings.ingest_queue_url)
