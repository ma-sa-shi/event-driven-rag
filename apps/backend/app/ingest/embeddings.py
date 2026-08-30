"""Bedrock経由でCohere Embed v4を呼び、チャンクのベクトルを生成する。

chat-fnの検索側(app/rag/embeddings.py)と同じモデル・同じ次元数を使う。
workerイメージにはLangChainを入れない方針(ADR-0003)のため、既定依存のboto3で
InvokeModelを直接呼ぶ。
"""

import json
from typing import Any

import boto3

from app.tracer import tracer

# S3 Vectorsインデックスの次元数(data-stack.tsのdimensionと一致させる)
EMBEDDING_DIMENSION = 1536
# Cohere Embed v4の1リクエストあたりのテキスト数上限
MAX_TEXTS_PER_REQUEST = 96


def parse_embeddings(payload: dict[str, Any]) -> list[list[float]]:
    """InvokeModelのレスポンスからfloatベクトルの配列を取り出す。

    embedding_typesを1種類だけ指定した場合の戻り値は、Bedrockのモデルカードでは
    `embeddings`直下の配列、Cohereの応答形式では`embeddings.float`と記述が割れている。
    どちらで返っても同じ配列を取り出せるようにする。
    """
    embeddings = payload["embeddings"]
    if isinstance(embeddings, dict):
        return embeddings["float"]
    return embeddings


class BedrockEmbedder:
    """取込対象チャンクをsearch_documentとしてベクトル化する。"""

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

    # ベクトルはセグメントの上限(64KB)を超える為、戻り値は記録しない
    @tracer.capture_method(capture_response=False)
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_TEXTS_PER_REQUEST):
            batch = texts[start : start + MAX_TEXTS_PER_REQUEST]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        # 失敗はSQSの再試行に任せる(3回失敗でDLQへ退避)
        response = self._client.invoke_model(
            modelId=self._model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(
                {
                    "texts": texts,
                    # 検索クエリ側はsearch_queryで埋め込まれる。取込側は文書として埋め込む
                    "input_type": "search_document",
                    "embedding_types": ["float"],
                    # embed-v4は出力次元を選べるため、インデックスの次元数を明示する
                    "output_dimension": self._dimension,
                }
            ),
        )
        embeddings = parse_embeddings(json.loads(response["body"].read()))
        if len(embeddings) != len(texts):
            raise ValueError(
                f"bedrock returned {len(embeddings)} embeddings for {len(texts)} texts"
            )
        return embeddings
