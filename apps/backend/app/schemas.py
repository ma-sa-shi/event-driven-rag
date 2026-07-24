"""複数のルーターで共有するレスポンススキーマ。

一覧・詳細のいずれからも参照されるモデルのみここに置く。
エンドポイント固有のリクエスト/レスポンスは各ルーターに定義する。
"""

from pydantic import BaseModel, Field


class DocumentResponse(BaseModel):
    document_id: str = Field(alias="documentId")
    user_id: str = Field(alias="userId")
    filename: str
    status: str
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class ChatSummaryResponse(BaseModel):
    chat_id: str = Field(alias="chatId")
    user_id: str = Field(alias="userId")
    question: str
    final_answer: str | None = Field(alias="finalAnswer", default=None)
    final_grade: str | None = Field(alias="finalGrade", default=None)
    retry_count: int = Field(alias="retryCount", default=0)
    created_at: str = Field(alias="createdAt")
