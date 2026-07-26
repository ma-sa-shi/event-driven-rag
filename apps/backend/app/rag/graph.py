"""Self-RAGワークフローのグラフ定義。

再試行は1回までで、再試行数の上限を変えるなら `retry_count == 1` の判定を変える
checkpointerは付けず、状態はグラフ実行の戻り値(stream_mode="values")から取得する
"""

from langgraph.graph import END, StateGraph

from app.logger import logger
from app.rag.nodes import (
    analyze_failure_node,
    generate_answer_node,
    generate_queries_node,
    grade_answer_node,
    retrieve_contexts_node,
)
from app.rag.state import GraphState


def decide_to_finish(state: GraphState) -> str:
    """評価結果から次の遷移先を決める。"""
    retry_count = state.get("retry_count", 0)
    current_grade = state["grade"][-1]

    if current_grade == "useful":
        logger.info("decide_to_finish: grade is useful")
        return "finish"

    if retry_count == 1:
        logger.info("decide_to_finish: reached max retry", grade=current_grade)
        return "force_finish"

    logger.info("decide_to_finish: retry", grade=current_grade, retry_count=retry_count)
    return "retry"


def build_graph():
    workflow = StateGraph(GraphState)

    workflow.add_node(generate_queries_node)
    workflow.add_node(retrieve_contexts_node)
    workflow.add_node(generate_answer_node)
    workflow.add_node(grade_answer_node)
    workflow.add_node(analyze_failure_node)

    workflow.set_entry_point("generate_queries_node")
    workflow.add_edge("generate_queries_node", "retrieve_contexts_node")
    workflow.add_edge("retrieve_contexts_node", "generate_answer_node")
    workflow.add_edge("generate_answer_node", "grade_answer_node")

    workflow.add_conditional_edges(
        "grade_answer_node",
        decide_to_finish,
        {
            "finish": END,
            "force_finish": "analyze_failure_node",
            "retry": "generate_queries_node",
        },
    )
    workflow.add_edge("analyze_failure_node", END)

    return workflow.compile()
