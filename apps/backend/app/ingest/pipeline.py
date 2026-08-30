"""取込処理のパイプライン。

S3のファイルを読み、テキスト抽出 → チャンク分割 → Embedding生成 → S3 Vectors登録を行い、
ドキュメントのステータスをingestedへ更新する。
クライアント生成のオーバーヘッドを避けるため、get_ingest_pipeline()はプロセス内でキャッシュする。
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import boto3

from app.ingest.chunking import split_text
from app.ingest.embeddings import BedrockEmbedder
from app.ingest.extract import extract_text
from app.logger import logger
from app.normalization import normalize_for_embedding
from app.repositories.documents import DocumentRepository
from app.settings import get_settings
from app.vectors import VectorIndex, vector_key

# 取込完了時に許可する遷移元
INGEST_ALLOWED_FROM = ("processing", "failed", "ingested")


class DocumentNotFoundError(Exception):
    """SQSメッセージが指すドキュメントがDynamoDBに存在しない。"""


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class IngestPipeline:
    bucket_name: str
    repository: DocumentRepository
    embedder: Embedder
    vector_index: VectorIndex
    # boto3のクライアントは動的に生成され、型を付けられない
    s3_client: Any

    def run(self, *, document_id: str, user_id: str, s3_key: str) -> int:
        """1ドキュメントを取り込み、登録したチャンク数を返す。"""
        document = self.repository.get_owned(user_id, document_id)
        if document is None:
            raise DocumentNotFoundError(f"document not found: {document_id}")
        filename = document["filename"]

        body = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)[
            "Body"
        ].read()
        text = extract_text(filename=filename, body=body)
        chunks = split_text(text)
        logger.info("document text extracted", chunk_count=len(chunks))

        # 埋め込み入力だけを正規化し、metadataへは原文のチャンクを格納する
        vectors = self.embedder.embed_documents(
            [normalize_for_embedding(chunk) for chunk in chunks]
        )
        # 登録前にchunkCountを引き上げ、途中で失敗しても削除APIが消し漏らさないようにする
        self.repository.reserve_chunk_count(user_id, document_id, len(chunks))
        self.vector_index.put_chunks(
            document_id=document_id,
            filename=filename,
            chunks=chunks,
            vectors=vectors,
        )
        self._delete_stale_vectors(
            document_id=document_id,
            # 初回取込ではchunkCountを持たない。Decimalのままではrange()へ渡せない
            previous_count=int(document.get("chunkCount", 0)),
            current_count=len(chunks),
        )

        self.repository.update_status(
            user_id,
            document_id,
            "ingested",
            allowed_from=INGEST_ALLOWED_FROM,
            chunk_count=len(chunks),
        )
        return len(chunks)

    def _delete_stale_vectors(
        self, *, document_id: str, previous_count: int, current_count: int
    ) -> None:
        """再取込でチャンク数が減ったときに、余った古いベクトルを削除する。

        既存keyは上書きされるため、超過分だけを消せば良い
        ListVectorsにprefix絞り込みがない為、前回のチャンク数から削除対象を決める
        """
        if previous_count <= current_count:
            return
        keys = [
            vector_key(document_id, index)
            for index in range(current_count, previous_count)
        ]
        self.vector_index.delete_keys(keys)
        logger.info("stale vectors deleted", deleted_count=len(keys))


@lru_cache
def get_ingest_pipeline() -> IngestPipeline:
    settings = get_settings()
    return IngestPipeline(
        bucket_name=settings.documents_bucket_name,
        repository=DocumentRepository(settings.table_name),
        embedder=BedrockEmbedder(model=settings.bedrock_embedding_model),
        vector_index=VectorIndex(settings.vector_index_arn),
        s3_client=boto3.client("s3"),
    )
