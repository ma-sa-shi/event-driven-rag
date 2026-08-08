from dataclasses import dataclass

from langchain_core.documents import Document


@dataclass
class _FusedDocument:
    document: Document
    score: float = 0.0


def reciprocal_rank_fusion(
    retriever_outputs: list[list[Document]], k: int = 60, top_n: int = 20
) -> list[Document]:
    """複数クエリの検索結果を相互順位融合(RRF)で1本に統合する。

    同一ドキュメントはdoc.idで名寄せする。kは順位差の影響を緩める定数。
    """
    fused: dict[str, _FusedDocument] = {}

    for docs in retriever_outputs:
        for rank, doc in enumerate(docs):
            entry = fused.setdefault(doc.id, _FusedDocument(document=doc))
            entry.score += 1 / (rank + k)

    ranked = sorted(fused.values(), key=lambda entry: entry.score, reverse=True)
    return [entry.document for entry in ranked[:top_n]]
