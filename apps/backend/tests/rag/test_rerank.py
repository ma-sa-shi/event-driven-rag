from app.rag.rerank import BedrockReranker
from tests.rag.fakes import make_document

MODEL = "cohere.rerank-v3-5:0"
REGION = "ap-northeast-1"


class StubBedrockAgentRuntime:
    """rerankの呼び出しを記録し、指定した順位を返す。"""

    def __init__(self, order: list[tuple[int, float]]) -> None:
        self.calls: list[dict] = []
        self._order = order
        self.meta = type("Meta", (), {"region_name": REGION})()

    def rerank(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "results": [
                {"index": index, "relevanceScore": score}
                for index, score in self._order
            ]
        }


def build_reranker(order, top_n=5) -> tuple[BedrockReranker, StubBedrockAgentRuntime]:
    client = StubBedrockAgentRuntime(order)
    return BedrockReranker(model=MODEL, top_n=top_n, client=client), client


async def test_reorders_documents_and_attaches_score():
    documents = [make_document(f"doc-1#{index}") for index in range(3)]
    reranker, _ = build_reranker([(2, 0.9), (0, 0.5)])

    selected = await reranker.acompress_documents(documents, "質問")

    assert [doc.id for doc in selected] == ["doc-1#2", "doc-1#0"]
    assert [doc.metadata["relevance_score"] for doc in selected] == [0.9, 0.5]
    # 本文とmetadataは渡したドキュメントのまま保たれる
    assert selected[0].page_content == documents[2].page_content
    assert selected[0].metadata["filename"] == documents[2].metadata["filename"]


async def test_sends_query_and_documents_with_model_arn():
    documents = [make_document("doc-1#0")]
    reranker, client = build_reranker([(0, 0.9)])

    await reranker.acompress_documents(documents, "質問")

    request = client.calls[0]
    assert request["queries"] == [{"type": "TEXT", "textQuery": {"text": "質問"}}]
    assert request["sources"] == [
        {
            "type": "INLINE",
            "inlineDocumentSource": {
                "type": "TEXT",
                "textDocument": {"text": documents[0].page_content},
            },
        }
    ]
    configuration = request["rerankingConfiguration"]["bedrockRerankingConfiguration"]
    assert configuration["modelConfiguration"]["modelArn"] == (
        f"arn:aws:bedrock:{REGION}::foundation-model/{MODEL}"
    )


async def test_caps_requested_results_at_document_count():
    """numberOfResultsが候補数を超えるとRerank APIが検証エラーを返す。"""
    reranker, client = build_reranker([(0, 0.9)], top_n=5)

    await reranker.acompress_documents([make_document("doc-1#0")], "質問")

    configuration = client.calls[0]["rerankingConfiguration"][
        "bedrockRerankingConfiguration"
    ]
    assert configuration["numberOfResults"] == 1


async def test_no_call_for_empty_documents():
    reranker, client = build_reranker([])

    assert await reranker.acompress_documents([], "質問") == []
    assert client.calls == []
