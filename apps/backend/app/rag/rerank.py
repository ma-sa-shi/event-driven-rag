"""BedrockのRerank APIでRRF統合済みのドキュメントを絞り込む。

langchain-awsはRerank APIを統合していない為、boto3で直接呼ぶ。
Rerank APIはbedrock-runtimeではなくbedrock-agent-runtimeに属する。
"""

import asyncio
from typing import Any

import boto3
from langchain_core.documents import Document


class BedrockReranker:
    """CohereRerankと同じacompress_documentsのインターフェースを保つ。"""

    def __init__(self, *, model: str, top_n: int, client: Any = None) -> None:
        self._model = model
        self._top_n = top_n
        self._client = client or boto3.client("bedrock-agent-runtime")

    async def acompress_documents(
        self, documents: list[Document], query: str
    ) -> list[Document]:
        if not documents:
            return []

        # boto3は同期APIの為、別スレッドで実行する
        response = await asyncio.to_thread(
            self._client.rerank,
            queries=[{"type": "TEXT", "textQuery": {"text": query}}],
            sources=[
                {
                    "type": "INLINE",
                    "inlineDocumentSource": {
                        "type": "TEXT",
                        "textDocument": {"text": doc.page_content},
                    },
                }
                for doc in documents
            ],
            rerankingConfiguration={
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "modelConfiguration": {"modelArn": self._model_arn()},
                    "numberOfResults": min(self._top_n, len(documents)),
                },
            },
        )
        # レスポンスは順位順のindexのみを返す。本文は渡した側で引き当てる
        return [
            _with_score(documents[result["index"]], result["relevanceScore"])
            for result in response["results"]
        ]

    def _model_arn(self) -> str:
        """Rerank APIはモデルIDではなくARNを取るため、クライアントのリージョンから組み立てる。"""
        return (
            f"arn:aws:bedrock:{self._client.meta.region_name}::"
            f"foundation-model/{self._model}"
        )


def _with_score(document: Document, score: float) -> Document:
    """SSEのsourcesイベントが読むrelevance_scoreをmetadataへ載せる。"""
    return Document(
        id=document.id,
        page_content=document.page_content,
        metadata={**document.metadata, "relevance_score": score},
    )
