"""Bedrock経由でCohere Embed v4を呼び、検索クエリをベクトル化する。

生成するベクトルが既存インデックスと噛み合うよう、次元数と応答の解釈は取込側と
共有する。langchain-awsのBedrockEmbeddingsはEmbed v4の応答形式に追随できていない為、
boto3のInvokeModelを直接呼ぶ。
"""

import json
from typing import Any

import boto3
from langchain_core.embeddings import Embeddings

from app.ingest.embeddings import EMBEDDING_DIMENSION, parse_embeddings


class BedrockQueryEmbeddings(Embeddings):
    """検索クエリをsearch_queryとしてベクトル化するLangChain Embeddings実装。"""

    def __init__(
        self,
        *,
        model: str,
        dimension: int = EMBEDDING_DIMENSION,
        client: Any = None,
    ) -> None:
        self._model = model
        self._dimension = dimension
        self._client = client or boto3.client("bedrock-runtime")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # 文書の埋め込みはingest-fnの担当であり、chat-fnからは呼ばれない
        raise NotImplementedError("chat-fnは検索クエリのみを埋め込む")

    def embed_query(self, text: str) -> list[float]:
        response = self._client.invoke_model(
            modelId=self._model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(
                {
                    "texts": [text],
                    # 取込側はsearch_documentで埋め込まれる。検索側はクエリとして埋め込む
                    "input_type": "search_query",
                    "embedding_types": ["float"],
                    "output_dimension": self._dimension,
                }
            ),
        )
        return parse_embeddings(json.loads(response["body"].read()))[0]
