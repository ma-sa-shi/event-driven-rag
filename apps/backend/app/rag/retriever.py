"""S3 Vectorsを検索するLangChain Retrieverモジュール"""

import asyncio
from typing import Any

import boto3
from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field


class S3VectorsRetriever(BaseRetriever):
    """
    クエリ文字列をベクトル化し、S3 Vectorsインデックスに対してベクトル検索を行うRetiever
    ingest-fnが登録するmetadataは text, filename, documentId
    ベクトルのkeyをDocument.idとし、RRFでの統合をチャンク単位で機能させる
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    embeddings: Embeddings
    index_arn: str
    top_k: int = 5
    # テスト時は下記clientが使われない為、boto3.client("s3vectors")が実行されない
    client: Any = Field(default_factory=lambda: boto3.client("s3vectors"))

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        # LangChainの仕様上、定義が必須のメソッド(消すと起動エラーになる)
        # Chat-fnが非同期の為、呼び出されるとエラーを発生させる
        raise NotImplementedError("S3VectorsRetrieverは非同期呼び出しのみ対応する")

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        # 検索クエリをベクトルに変換
        vector = await self.embeddings.aembed_query(query)
        # boto3は同期APIの為、別スレッドで実行する
        response = await asyncio.to_thread(
            self.client.query_vectors,
            indexArn=self.index_arn,
            queryVector={"float32": vector},
            topK=self.top_k,
            returnMetadata=True,
            returnDistance=True,
        )
        # LangChain の Document 形式に変換
        return [_to_document(v) for v in response.get("vectors", [])]


def _to_document(vector: dict) -> Document:
    """AWSレスポンス(dict)を LangChain の Document に変換するヘルパー関数"""
    metadata = vector.get("metadata") or {}
    return Document(
        id=vector["key"],
        page_content=metadata.get("text", ""),
        metadata={
            "documentId": metadata.get("documentId"),
            "filename": metadata.get("filename"),
            "distance": vector.get("distance"),
        },
    )
