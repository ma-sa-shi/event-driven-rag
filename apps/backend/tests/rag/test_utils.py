from app.rag.utils import reciprocal_rank_fusion
from tests.rag.fakes import make_document


def test_dedups_by_document_id_and_ranks_by_fused_score():
    a, b, c = (make_document(k) for k in ("a", "b", "c"))
    # bは2クエリで上位に現れるため、片方で1位のaより上に来る
    fused = reciprocal_rank_fusion([[a, b], [b, c]])

    assert [d.id for d in fused] == ["b", "a", "c"]


def test_top_n_limits_result_size():
    docs = [make_document(f"doc-{i}") for i in range(10)]

    assert len(reciprocal_rank_fusion([docs], top_n=3)) == 3


def test_keeps_document_instances_so_metadata_survives():
    doc = make_document("a")

    assert reciprocal_rank_fusion([[doc]])[0] is doc


def test_no_results_yields_empty_list():
    assert reciprocal_rank_fusion([[], []]) == []
