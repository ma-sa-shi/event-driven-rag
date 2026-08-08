"""RAGパイプラインをオフラインで動かすためのスタブ。

OpenAI / Cohere / S3 Vectorsへは一切アクセスせず、
ノードとグラフの分岐だけを検証できるようにする。
"""

from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from app.rag.chains import RagChains
from app.rag.state import GradeAnswer


class FakeChain:
    """呼び出し順に決められた値を返すチェーン。

    要素を使い切ったあとは最後の値を返し続けるため、
    リトライ回数を気にせず「最終的にこうなる」だけを書ける。
    """

    def __init__(self, *results: Any) -> None:
        self.results = list(results)
        self.calls: list[dict] = []

    async def ainvoke(self, inputs: dict, config: Any = None) -> Any:
        self.calls.append(inputs)
        index = min(len(self.calls) - 1, len(self.results) - 1)
        return self.results[index]


def build_fake_chains(
    *,
    queries: list[list[str]] | None = None,
    answers: list[str] | None = None,
    grades: list[tuple[str, str]] | None = None,
    failure_analysis: str = "ベクトルストアに必要な情報が存在しない。",
) -> RagChains:
    """デフォルトは「1回で useful」になる組み合わせ。"""
    return RagChains(
        generate_queries=FakeChain(*(queries or [["クエリ1", "クエリ2", "クエリ3"]])),
        generate_answer=FakeChain(*(answers or ["回答"])),
        grade_answer=FakeChain(
            *(
                GradeAnswer(grade=grade, feedback=feedback)
                for grade, feedback in (grades or [("useful", "根拠が十分")])
            )
        ),
        analyze_failure=FakeChain(failure_analysis),
    )


def make_document(key: str, *, document_id: str = "doc-1", text: str | None = None):
    return Document(
        id=key,
        page_content=text if text is not None else f"{key}の本文",
        metadata={"documentId": document_id, "filename": f"{document_id}.pdf"},
    )


class FakeRetriever(BaseRetriever):
    """クエリごとに固定の検索結果を返すretriever。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    results: dict[str, list[Document]] = Field(default_factory=dict)
    default: list[Document] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)

    async def _aget_relevant_documents(self, query: str, *, run_manager=None):
        self.queries.append(query)
        return self.results.get(query, self.default)

    def _get_relevant_documents(self, query: str, *, run_manager=None):
        raise NotImplementedError


class FakeReranker:
    """上位top_n件へ絞り、relevance_scoreを降順で付与する。"""

    def __init__(self, top_n: int = 5) -> None:
        self.top_n = top_n
        self.calls: list[tuple[int, str]] = []

    async def acompress_documents(self, documents, query: str):
        self.calls.append((len(documents), query))
        selected = list(documents)[: self.top_n]
        return [
            Document(
                id=doc.id,
                page_content=doc.page_content,
                metadata={**doc.metadata, "relevance_score": 0.9 - 0.1 * rank},
            )
            for rank, doc in enumerate(selected)
        ]
