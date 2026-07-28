import pytest

from app.ingest.chunking import CHUNK_OVERLAP, CHUNK_SIZE, split_text


def test_short_text_becomes_single_chunk():
    assert split_text("短い本文") == ["短い本文"]


def test_empty_text_produces_no_chunks():
    assert split_text("") == []
    assert split_text("   \n\n  ") == []


def test_every_chunk_fits_in_chunk_size():
    text = "\n\n".join(f"段落{index}。" + "本文" * 100 for index in range(10))

    chunks = split_text(text)

    assert len(chunks) > 1
    assert all(len(chunk) <= CHUNK_SIZE for chunk in chunks)


def test_prefers_paragraph_separator():
    """chunk_sizeに収まる段落は、段落の途中で切られない。"""
    paragraphs = [f"段落{index}" * 30 for index in range(6)]

    chunks = split_text("\n\n".join(paragraphs), chunk_size=200, chunk_overlap=0)

    for paragraph in paragraphs:
        assert any(paragraph in chunk for chunk in chunks)


def test_consecutive_chunks_overlap():
    text = " ".join(f"word{index}" for index in range(200))

    chunks = split_text(text, chunk_size=100, chunk_overlap=30)

    assert len(chunks) > 1
    # 末尾30文字程度が次のチャンクの先頭に現れる
    assert chunks[1].split(" ")[0] in chunks[0]


def test_splits_text_without_any_separator():
    """区切り文字を持たない連続文字列も必ずchunk_size以内に収める。"""
    chunks = split_text("あ" * 1200)

    assert len(chunks) > 1
    assert all(len(chunk) <= CHUNK_SIZE for chunk in chunks)
    assert "".join(chunks).count("あ") >= 1200


def test_recombines_all_content_without_overlap():
    text = "\n".join(f"行{index}" for index in range(50))

    chunks = split_text(text, chunk_size=40, chunk_overlap=0)

    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_default_settings_match_ported_pipeline():
    assert (CHUNK_SIZE, CHUNK_OVERLAP) == (500, 50)


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        split_text("本文", chunk_size=100, chunk_overlap=100)
