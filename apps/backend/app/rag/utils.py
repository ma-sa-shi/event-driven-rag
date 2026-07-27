from langchain_core.documents import Document


def reciprocal_rank_fusion(
    retriever_outputs: list[list[Document]], k: int = 60, top_n: int = 20
) -> list[Document]:
    """複数クエリの検索結果を相互順位融合(RRF)で1本に統合する。

    Args:
        retriever_outputs: クエリごとの検索結果
        k: 順位の影響を緩めるRRFの定数
        top_n: 返すドキュメント数

    Returns:
        スコア降順のドキュメント。同一ドキュメントはdoc.idで名寄せされる
    """
    # { doc_id: {score: スコア, document: Documentオブジェクト} }
    doc_score_map: dict[str, dict] = {}

    for docs in retriever_outputs:
        for rank, doc in enumerate(docs):
            if doc.id not in doc_score_map:
                doc_score_map[doc.id] = {"score": 0.0, "document": doc}
            doc_score_map[doc.id]["score"] += 1 / (rank + k)

    sorted_items = sorted(
        doc_score_map.items(),
        key=lambda x: x[1]["score"],
        reverse=True,  # 降順
    )

    return [item[1]["document"] for item in sorted_items[:top_n]]
