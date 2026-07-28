import pytest

from app.ingest.extract import (
    EmptyDocumentError,
    UnsupportedFileTypeError,
    extract_text,
)


def build_pdf(text: str) -> bytes:
    """テキストを1つ持つ最小構成のPDFを組み立てる。

    バイナリのフィクスチャをリポジトリに置かずにPDF抽出を検証するため、
    xrefのオフセットまで含めて正しいPDFをその場で生成する。
    """
    content = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET\n".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length "
        + str(len(content)).encode()
        + b" >>\nstream\n"
        + content
        + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return bytes(out)


def test_extracts_text_from_pdf():
    text = extract_text(filename="設計書.pdf", body=build_pdf("Hello RAG"))

    assert "Hello RAG" in text


@pytest.mark.parametrize("filename", ["notes.md", "notes.markdown", "notes.txt"])
def test_decodes_text_formats_as_utf8(filename):
    assert extract_text(filename=filename, body="# 見出し".encode()) == "# 見出し"


def test_replaces_invalid_utf8_instead_of_failing():
    """1バイトの文字化けで取込全体を失敗させない。"""
    text = extract_text(filename="notes.txt", body=b"ok \xff bytes")

    assert text.startswith("ok ")
    assert "bytes" in text


def test_extension_is_case_insensitive():
    assert extract_text(filename="NOTES.TXT", body=b"body") == "body"


def test_rejects_unsupported_extension():
    with pytest.raises(UnsupportedFileTypeError):
        extract_text(filename="sheet.xlsx", body=b"anything")


def test_rejects_file_without_extension():
    with pytest.raises(UnsupportedFileTypeError):
        extract_text(filename="README", body=b"anything")


def test_rejects_document_without_text():
    """画像だけのPDFなど、抽出結果が空のものは取込対象にしない。"""
    with pytest.raises(EmptyDocumentError):
        extract_text(filename="empty.txt", body=b"   \n\n  ")
