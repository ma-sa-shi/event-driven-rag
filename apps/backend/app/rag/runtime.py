"""
RAGパイプラインのgraph・依存コンポーネントの構築モジュール

AWS SSMからのAPIキー取得や各コンポーネントの初期化に伴うオーバーヘッドを防ぐ為、
get_rag_runtime() は初回呼び出し時のみ実行し、プロセス内でキャッシュする
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from langchain_cohere import CohereEmbeddings, CohereRerank

from app.rag.chains import RagChains, build_chains
from app.rag.graph import build_graph
from app.rag.retriever import S3VectorsRetriever
from app.settings import get_settings
from app.ssm import get_parameter

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
        """config引数経由でコンポーネントやコンテキストを各ノードに注入"""
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
    """
    RagRuntimeのインスタンスを取得する
    初回実行時にキャッシュ
    """
    settings = get_settings()
    openai_api_key = get_parameter(settings.openai_api_key_parameter_name)
    cohere_api_key = get_parameter(settings.cohere_api_key_parameter_name)

    embeddings = CohereEmbeddings(
        model=settings.cohere_embedding_model, cohere_api_key=cohere_api_key
    )
    return RagRuntime(
        graph=build_graph(),
        chains=build_chains(
            api_key=openai_api_key,
            answer_model=settings.openai_answer_model,
            utility_model=settings.openai_utility_model,
        ),
        retriever=S3VectorsRetriever(
            embeddings=embeddings,
            index_arn=settings.vector_index_arn,
            top_k=RETRIEVER_TOP_K,
        ),
        reranker=CohereRerank(
            model=settings.cohere_rerank_model,
            top_n=RERANK_TOP_N,
            cohere_api_key=cohere_api_key,
        ),
    )
