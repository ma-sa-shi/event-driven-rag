"""Self-RAGのデータ定義。

Graph Stateは試行ごとの履歴を保持する。
queries, documents, answer, grade, feedbackは`operator.add`により値が上書きされずリストへ追加される為、
各ノードは要素を1つのリストでラップして返す(例: `{"queries": [queries]}`)。
格納形式は二重リスト(list[list[...]])がqueriesとdocuments、一重リスト(list[str])がanswer・grade・feedbackで、
最新の試行結果は[-1]、初回の試行は[0]で参照する。retry_countのみ蓄積されず通常のint値として上書きされる。

型の使い分けは、LLMに渡すスキーマはBaseModelで出力を誘導し、
Graph Stateは差分dictの積み上げ式で未実行ノードのキーが存在しない状態を表現する必要がある為TypedDictとする。
"""

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.documents import Document
from pydantic import BaseModel, Field


class MultiQuery(BaseModel):
    """LLMが生成する複数の検索クエリ。

    generate_queries_nodeのwith_structured_outputで使う出力スキーマ。
    """

    queries: list[str] = Field(
        ..., min_length=3, max_length=5, description="LLMが生成する検索クエリ"
    )


class GradeAnswer(BaseModel):
    """LLMによる回答の自己評価。"""

    grade: Literal["useful", "useless", "hallucination"] = Field(
        ..., description="質問に対する回答の評価"
    )
    feedback: str = Field(..., description="評価理由")


class GraphState(TypedDict):
    """Self-RAGワークフローがノード間で受け渡す状態。

    queries・documents・answer・grade・feedbackは試行ごとに1要素ずつ積み上がる。
    retry_countは初回が0で、再試行のたびに1増える。
    failure_analysisは再試行しても十分な回答が得られなかった場合のみ設定される。
    user_idはJWTのsub。
    """

    question: str
    queries: Annotated[list[list[str]], operator.add]
    documents: Annotated[list[list[Document]], operator.add]
    answer: Annotated[list[str], operator.add]
    grade: Annotated[list[str], operator.add]
    feedback: Annotated[list[str], operator.add]
    retry_count: int
    failure_analysis: str
    user_id: str
    request_id: str
