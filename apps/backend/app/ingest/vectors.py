"""S3 Vectorsインデックスへのベクトル登録・削除。

metadataはfilterable=documentId、non-filterable=text / filename(architecture.md 8.3)。
vector keyは`<documentId>#<チャンク番号>`とし、chat-fnのRetrieverが
チャンク単位でRRFの名寄せに使う(app/rag/retriever.py)。
"""

from typing import Any

import boto3

# PutVectors / DeleteVectorsのAPI上限は500件。
# 1ベクトルは1536次元 + チャンク本文を含み1リクエストが大きくなるため控えめにする
MAX_VECTORS_PER_REQUEST = 100


def vector_key(document_id: str, chunk_index: int) -> str:
    return f"{document_id}#{chunk_index}"


class VectorIndex:
    def __init__(self, index_arn: str, client: Any | None = None) -> None:
        self._index_arn = index_arn
        self._client = client or boto3.client("s3vectors")

    def put_chunks(
        self,
        *,
        document_id: str,
        filename: str,
        chunks: list[str],
        vectors: list[list[float]],
    ) -> None:
        """チャンクとベクトルを対応付けて登録する。同じkeyへの登録は上書きになる。"""
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")

        items = [
            {
                "key": vector_key(document_id, index),
                "data": {"float32": vector},
                "metadata": {
                    "documentId": document_id,
                    "text": chunk,
                    "filename": filename,
                },
            }
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        for batch in _batched(items):
            self._client.put_vectors(indexArn=self._index_arn, vectors=batch)

    def delete_keys(self, keys: list[str]) -> None:
        for batch in _batched(keys):
            self._client.delete_vectors(indexArn=self._index_arn, keys=batch)


def _batched(items: list) -> list[list]:
    return [
        items[start : start + MAX_VECTORS_PER_REQUEST]
        for start in range(0, len(items), MAX_VECTORS_PER_REQUEST)
    ]
