"""取込処理のパイプライン。

S3のファイルを読み、テキスト抽出 → チャンク分割 → Embedding生成 → S3 Vectors登録を行い、
ドキュメントのステータスをingestedへ更新する。
SSMからのAPIキー取得やクライアント生成のオーバーヘッドを避けるため、get_ingest_pipeline()はプロセス内でキャッシュする。
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import boto3

from app.ingest.chunking import split_text
from app.ingest.embeddings import CohereEmbedder
from app.ingest.extract import extract_text
from app.ingest.vectors import VectorIndex, vector_key
from app.logger import logger
from app.repositories.documents import DocumentRepository
from app.settings import get_settings
from app.ssm import get_parameter

# 取込完了時に許可する遷移元
INGEST_ALLOWED_FROM = ("processing", "failed", "ingested")


class DocumentNotFoundError(Exception):
    """SQSメッセージが指すドキュメントがDynamoDBに存在しない。"""


@dataclass(frozen=True)
class IngestPipeline:
    bucket_name: str
    repository: DocumentRepository
    embedder: Any
    vector_index: VectorIndex
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

        vectors = self.embedder.embed_documents(chunks)
        self.vector_index.put_chunks(
            document_id=document_id,
            filename=filename,
            chunks=chunks,
            vectors=vectors,
        )
        self._delete_stale_vectors(
            document_id=document_id,
            # 初回取込ではchunkCountを持たないため0で代替する
            # DynamoDBの数値はDecimalで返り、そのままではrange()に渡せない
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
        embedder=CohereEmbedder(
            api_key=get_parameter(settings.cohere_api_key_parameter_name),
            model=settings.cohere_embedding_model,
        ),
        vector_index=VectorIndex(settings.vector_index_arn),
        s3_client=boto3.client("s3"),
    )
