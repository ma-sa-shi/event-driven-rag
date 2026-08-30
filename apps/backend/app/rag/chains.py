"""Self-RAGを構成する4つのLCELチェーンの組み立て。

モデルの呼び出しはBedrockのConverse API経由で行う。import時にモデルを生成すると
リージョン未設定の環境(api-fnやテスト)でimportが失敗する為、必ずファクトリ経由で生成する。
"""

from dataclasses import dataclass

from langchain_aws import ChatBedrockConverse
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable

from app.rag.prompts import (
    analyze_failure_prompt,
    generate_answer_prompt,
    generate_queries_prompt,
    grade_answer_prompt,
)
from app.rag.state import GradeAnswer, MultiQuery


@dataclass(frozen=True)
class RagChains:
    generate_queries: Runnable
    generate_answer: Runnable
    grade_answer: Runnable
    analyze_failure: Runnable


def build_chains(*, answer_model: str, utility_model: str) -> RagChains:
    """回答生成用と補助用の2モデルで4チェーンを組み立てる。

    utility_modelはクエリ生成・回答評価・失敗分析に使う。
    """
    # SSEはトークンではなくノード単位のstate更新を配信する(app/rag/stream.py)ため、
    # LLMのトークンストリーミングは使わない。明示しないと自動判定の警告が毎回出る
    answer_llm = ChatBedrockConverse(model=answer_model, disable_streaming=True)
    utility_llm = ChatBedrockConverse(model=utility_model, disable_streaming=True)

    return RagChains(
        generate_queries=(
            generate_queries_prompt
            | utility_llm.with_structured_output(MultiQuery)
            | (lambda x: x.queries)
        ),
        generate_answer=generate_answer_prompt | answer_llm | StrOutputParser(),
        grade_answer=grade_answer_prompt
        | utility_llm.with_structured_output(GradeAnswer),
        analyze_failure=analyze_failure_prompt | utility_llm | StrOutputParser(),
    )
