"""
Self-RAGのワークフローを構成する5つのノード定義

chains, retriever, rerankerは 'config["configurable"]' で受け取る
各ノード関数名は SSE イベントの識別子に利用され、変更するとフロントエンドやDynamoDBに影響する
テスト時は `config` にモックを注入するだけで、外部API（AWS/OpenAI/Cohere）への通信無しでMockテスト可能
"""

from langchain_core.runnables import RunnableConfig

from app.logger import logger
from app.rag.chains import RagChains
from app.rag.state import GraphState
from app.rag.utils import reciprocal_rank_fusion

# 再試行時のフィードバック用接頭辞
# プロンプトに空の見出しを残さず、再試行時のみラベルを渡すためにノードで付与する
FEEDBACK_PREFIX = "フィードバック: "


def _configurable(config: RunnableConfig, key: str):
    """configから依存オブジェクトを取得する内部ヘルパー"""
    value = config.get("configurable", {}).get(key)
    if value is None:
        raise ValueError(f"configurableに{key}が設定されていません。")
    return value


def _chains(config: RunnableConfig) -> RagChains:
    """configからRagChainsを取得する内部ヘルパー"""
    return _configurable(config, "chains")


async def generate_queries_node(state: GraphState, config: RunnableConfig) -> dict:
    """質問から複数の検索クエリを抽出する"""
    question = state["question"]
    retry_count = state.get("retry_count", 0)
    feedback = state.get("feedback")

    # 2周目以降はretry_countをインクリメント
    if state.get("queries"):
        retry_count += 1

    feedback_text = f"{FEEDBACK_PREFIX}{feedback[-1]}" if feedback else ""

    queries = await _chains(config).generate_queries.ainvoke(
        {"question": question, "feedback": feedback_text}, config=config
    )

    logger.info(
        "generate_queries_node finished",
        retry_count=retry_count,
        question=question[:50],
        feedback=feedback[-1].replace("\n", " ")[:50] if feedback else None,
        queries=queries,
    )
    return {"queries": [queries], "retry_count": retry_count}


async def retrieve_contexts_node(state: GraphState, config: RunnableConfig) -> dict:
    """クエリごとにベクトル検索し、RRFで統合してからRerankで上位へ絞る"""
    retriever = _configurable(config, "retriever")
    reranker = _configurable(config, "reranker")

    queries = state["queries"][-1]

    # .map()でクエリ数分の検索を非同期で並列実行する
    raw_docs = await retriever.map().ainvoke(queries, config=config)
    total_raw_count = sum(len(docs) for docs in raw_docs)

    # Reciprocal Rank Fusion (RRF) で検索結果を統合・スコアリング
    fused_docs = reciprocal_rank_fusion(raw_docs)

    # Cohere Rerankで上位のドキュメントへ絞り込み
    selected_docs = await reranker.acompress_documents(fused_docs, state["question"])

    logger.info(
        "retrieve_contexts_node finished",
        queries=queries,
        retrieved=total_raw_count,
        fused=len(fused_docs),
        selected=len(selected_docs),
        sources=[doc.metadata.get("filename") for doc in selected_docs],
    )
    return {"documents": [list(selected_docs)]}


async def generate_answer_node(state: GraphState, config: RunnableConfig) -> dict:
    """検索済みコンテキストのみを根拠に回答を生成する"""
    current_docs = state["documents"][-1] if state.get("documents") else []
    answer = await _chains(config).generate_answer.ainvoke(
        {"question": state["question"], "context": current_docs}, config=config
    )

    logger.info(
        "generate_answer_node finished",
        retry_count=state.get("retry_count", 0),
        sources=[doc.metadata.get("filename") for doc in current_docs],
        answer=answer.replace("\n", " ")[:50],
    )
    return {"answer": [answer]}


async def grade_answer_node(state: GraphState, config: RunnableConfig) -> dict:
    """生成された回答を自己評価する"""
    result = await _chains(config).grade_answer.ainvoke(
        {
            "question": state["question"],
            "answer": state["answer"][-1],
            "context": state["documents"][-1],
        },
        config=config,
    )

    logger.info(
        "grade_answer_node finished",
        retry_count=state.get("retry_count", 0),
        grade=result.grade,
        feedback=(result.feedback or "").replace("\n", " ")[:50] or None,
    )
    return {"grade": [result.grade], "feedback": [result.feedback]}


async def analyze_failure_node(state: GraphState, config: RunnableConfig) -> dict:
    """再試行しても十分な回答が得られなかった原因を分析する"""
    analysis = await _chains(config).analyze_failure.ainvoke(
        {
            "question": state["question"],
            "initial_queries": state["queries"][0],
            "initial_context": state["documents"][0],
            "initial_feedback": state["feedback"][0],
            "retry_feedback": state["feedback"][-1],
        },
        config=config,
    )

    logger.warning(
        "analyze_failure_node finished",
        retry_count=state.get("retry_count", 0),
        analysis=(analysis or "").replace("\n", " ")[:50] or None,
    )
    return {"failure_analysis": analysis}
