"""RAGパイプラインのgraphと依存コンポーネントの構築。

boto3クライアントの生成や各コンポーネントの初期化に伴うオーバーヘッドを防ぐ為、
get_rag_runtime()は初回呼び出し時のみ実行し、プロセス内でキャッシュする。
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.rag.chains import RagChains, build_chains
from app.rag.embeddings import BedrockQueryEmbeddings
from app.rag.graph import build_graph
from app.rag.rerank import BedrockReranker
from app.rag.retriever import S3VectorsRetriever
from app.settings import get_settings

# リランク後にLLMへ渡すドキュメント件数
RERANK_TOP_N = 5
# ベクトル検索時の1クエリ当たりの取得件数
RETRIEVER_TOP_K = 5


# @dataclass(frozen=True): 初期化後、属性の書き換え禁止
@dataclass(frozen=True)
class RagRuntime:
    graph: Any
    chains: RagChains
    retriever: Any
    reranker: Any

    def configurable(self, *, user_id: str, request_id: str) -> dict:
        """各ノードへ依存コンポーネントとリクエスト情報を渡すconfigを組み立てる。

        Args:
            user_id: ユーザーID(JWTのsub)
            request_id: リクエストID

        Returns:
            graph.astream()にそのまま渡せるconfig
        """
        return {
            "configurable": {
                "chains": self.chains,
                "retriever": self.retriever,
                "reranker": self.reranker,
                "user_id": user_id,
                "request_id": request_id,
            }
        }


@lru_cache
def get_rag_runtime() -> RagRuntime:
    """初回呼び出し時にRagRuntimeを構築し、以降はlru_cacheの結果を返す。"""
    settings = get_settings()
    return RagRuntime(
        graph=build_graph(),
        chains=build_chains(
            answer_model=settings.bedrock_answer_model,
            utility_model=settings.bedrock_utility_model,
        ),
        retriever=S3VectorsRetriever(
            embeddings=BedrockQueryEmbeddings(model=settings.bedrock_embedding_model),
            index_arn=settings.vector_index_arn,
            top_k=RETRIEVER_TOP_K,
        ),
        reranker=BedrockReranker(
            model=settings.bedrock_rerank_model, top_n=RERANK_TOP_N
        ),
    )
