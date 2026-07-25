"""DynamoDBへテストデータを直接投入するヘルパー。

書き込みAPIがapi-fnにないエンティティ(Chat / Chat Messages)のシードと、
任意のステータスを持つDocumentの準備に使う。キー構造はRepositoryと同一。
"""

from datetime import UTC, datetime


def put_document(
    table,
    *,
    user_id: str,
    document_id: str,
    filename: str = "doc.pdf",
    status: str = "uploaded",
    created_at: str | None = None,
) -> dict:
    now = created_at or datetime.now(UTC).isoformat()
    item = {
        "PK": f"USER#{user_id}",
        "SK": f"DOC#{document_id}",
        "GSI1PK": "DOC",
        "GSI1SK": document_id,
        "documentId": document_id,
        "userId": user_id,
        "filename": filename,
        "s3Key": f"documents/{user_id}/{document_id}/{filename}",
        "status": status,
        "createdAt": now,
        "updatedAt": now,
    }
    table.put_item(Item=item)
    return item


def put_chat(
    table,
    *,
    user_id: str,
    chat_id: str,
    question: str = "質問",
    final_answer: str | None = "回答",
    final_grade: str | None = "useful",
    retry_count: int = 0,
    created_at: str | None = None,
) -> dict:
    item = {
        "PK": f"USER#{user_id}",
        "SK": f"CHAT#{chat_id}",
        "GSI1PK": "CHAT",
        "GSI1SK": chat_id,
        "chatId": chat_id,
        "userId": user_id,
        "question": question,
        "finalAnswer": final_answer,
        "finalGrade": final_grade,
        "retryCount": retry_count,
        "createdAt": created_at or datetime.now(UTC).isoformat(),
    }
    table.put_item(Item=item)
    return item


def put_attempt(
    table,
    *,
    user_id: str,
    chat_id: str,
    attempt_no: int,
    queries: list[str] | None = None,
    documents: list[dict] | None = None,
    answer: str | None = "回答",
    grade: str | None = "useful",
    feedback: str | None = "根拠が十分",
    failure_analysis: str | None = None,
) -> dict:
    item = {
        "PK": f"USER#{user_id}",
        "SK": f"MSG#{chat_id}#{attempt_no}",
        "chatId": chat_id,
        "attemptNo": attempt_no,
        "queries": queries or ["クエリ1", "クエリ2", "クエリ3"],
        "documents": documents or [],
        "answer": answer,
        "grade": grade,
        "feedback": feedback,
        "failureAnalysis": failure_analysis,
    }
    table.put_item(Item=item)
    return item
