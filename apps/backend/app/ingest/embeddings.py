"""Cohere Embed APIでチャンクのベクトルを生成する。

chat-fnの検索側(app/rag/runtime.py)と同じモデル・同じ次元数を使う。
検索側はlangchain-cohereのCohereEmbeddingsを利用するが、workerイメージには
LangChainを入れない方針(ADR-0003)のため、既定依存のhttpxでREST APIを直接呼ぶ。
"""

import httpx

COHERE_EMBED_URL = "https://api.cohere.com/v2/embed"
# S3 Vectorsインデックスの次元数(data-stack.tsのdimensionと一致させる)
EMBEDDING_DIMENSION = 1536
# Cohere Embed APIの1リクエストあたりのテキスト数上限
MAX_TEXTS_PER_REQUEST = 96
# Embedding生成は数秒かかるため、httpxの既定(5秒)では短い
REQUEST_TIMEOUT_SECONDS = 60.0


class CohereEmbedder:
    """取込対象チャンクをsearch_documentとしてベクトル化する。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimension: int = EMBEDDING_DIMENSION,
        client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._dimension = dimension
        self._client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_TEXTS_PER_REQUEST):
            batch = texts[start : start + MAX_TEXTS_PER_REQUEST]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self._client.post(
            COHERE_EMBED_URL,
            headers=self._headers,
            json={
                "model": self._model,
                "texts": texts,
                # 検索クエリ側はsearch_queryで埋め込まれる。取込側は文書として埋め込む
                "input_type": "search_document",
                "embedding_types": ["float"],
                # embed-v4.0は出力次元を選べるため、インデックスの次元数を明示する
                "output_dimension": self._dimension,
            },
        )
        # 失敗はSQSの再試行に任せる(3回失敗でDLQへ退避)
        response.raise_for_status()
        embeddings = response.json()["embeddings"]["float"]
        if len(embeddings) != len(texts):
            raise ValueError(
                f"cohere returned {len(embeddings)} embeddings for {len(texts)} texts"
            )
        return embeddings
