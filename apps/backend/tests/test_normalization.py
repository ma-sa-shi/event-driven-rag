from app.normalization import normalize_for_embedding


def test_normalizes_fullwidth_alphanumerics_to_halfwidth():
    assert normalize_for_embedding("ＲＡＧチャット２０２６") == "RAGチャット2026"


def test_normalizes_halfwidth_katakana_to_fullwidth():
    assert normalize_for_embedding("ﾊﾞｯｸｱｯﾌﾟ") == "バックアップ"


def test_ingest_text_and_query_converge_on_the_same_form():
    """表記が揺れた取込テキストと検索クエリを同じベクトル空間へ載せる。"""
    assert normalize_for_embedding("ＲＡＧ　の設計") == normalize_for_embedding(
        "RAG の設計"
    )


def test_is_idempotent():
    normalized = normalize_for_embedding("ＲＡＧ　の設計")

    assert normalize_for_embedding(normalized) == normalized


def test_flattens_circled_numbers():
    """規程の項番号が潰れるため、格納テキストへは適用しない(app/normalization.py)。"""
    assert normalize_for_embedding("①休暇") == "1休暇"
