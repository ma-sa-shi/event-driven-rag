"""Self-RAGを構成する4つのLCELチェーンの組み立て。

APIキーはSSMから解決した値をコンストラクタ引数で渡す。
import時にモデルを生成するとキーなしの環境(api-fnやテスト)でimportが失敗する為、
必ずファクトリ経由で生成する。
"""

from dataclasses import dataclass

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

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


def build_chains(*, api_key: str, answer_model: str, utility_model: str) -> RagChains:
    """回答生成用と補助用の2モデルで4チェーンを組み立てる。

    Args:
        api_key: OpenAI APIキー(SSMから解決した値)
        answer_model: 回答生成に使うモデル
        utility_model: クエリ生成・評価・失敗分析に使う軽量モデル

    Returns:
        4つのチェーンをまとめたRagChains
    """
    answer_llm = ChatOpenAI(model=answer_model, api_key=api_key)
    utility_llm = ChatOpenAI(model=utility_model, api_key=api_key)

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
