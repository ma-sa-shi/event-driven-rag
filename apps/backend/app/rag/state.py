"""
Self-RAGのデータ定義

【Graph Stateは履歴を保持する】
- queries, documents, answer, grade, feedbackは'operator.add'により、
  試行ごとに値が上書きされず、リストに追加される
- そのため、各ノードは要素を1つのリストでラップして返す（例: `{"queries": [queries]}`）

【データの格納形式と取得方法】
- 二重リスト (list[list[...]]): queries, documents
- 一重リスト (list[str]): answer, grade, feedback
- 取得例: 最新の試行結果は[-1]、初回の試行は [0]で参照。

※ retry_countのみ、蓄積されず通常の int 値として上書きされる

LLMに渡すスキーマはBaseModelで出力を誘導
Graph Stateは差分dictの積み上げ式であり、未実行ノードのキーが
存在しない状態を表現する必要がある為、TypedDictを使用
"""

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.documents import Document
from pydantic import BaseModel, Field


class MultiQuery(BaseModel):
    """
    LLMが生成する複数の検索クエリ
    Field(...): 必須フィールド制約
    """

    queries: list[str] = Field(
        ..., min_length=3, max_length=5, description="LLMが生成する検索クエリ"
    )


class GradeAnswer(BaseModel):
    """LLMによる回答の自己評価"""

    grade: Literal["useful", "useless", "hallucination"] = Field(
        ..., description="質問に対する回答の評価"
    )
    feedback: str = Field(..., description="評価理由")


class GraphState(TypedDict):
    """ワークフローの状態

    Attributes:
        question: ユーザーからの質問
        queries: 試行ごとの検索クエリ
        documents: 試行ごとの検索・リランク済みドキュメント
        answer: 試行ごとの回答
        grade: 試行ごとの評価
        feedback: 試行ごとの評価理由
        retry_count: ループ回数。初回は0で、再試行のたびに1増える
        failure_analysis: 十分な回答が得られなかった場合の分析結果
        user_id: ユーザーID(JWTのsub)
        request_id: リクエストID
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
