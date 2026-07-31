"""アップロードされたファイルからプレーンテキストを抽出する。

対応形式はPDF / Markdown / txtで、拡張子から判別する。
"""

from io import BytesIO
from pathlib import PurePosixPath

from pypdf import PdfReader

PDF_EXTENSIONS = {".pdf"}
TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | TEXT_EXTENSIONS


class UnsupportedFileTypeError(Exception):
    """対応していない拡張子のファイルを受け取ったことを表す。

    再試行しても成功しない為、呼び出し側はDLQへ送らずfailedで確定させる。
    """


class EmptyDocumentError(Exception):
    """テキストを1文字も抽出できなかったことを表す(画像だけのPDFなど)。"""


def extract_text(*, filename: str, body: bytes) -> str:
    """ファイル名の拡張子から形式を判定してテキストを抽出する。

    Content-Typeはブラウザ依存で信頼できない為、拡張子だけで判定する。

    Args:
        filename: 拡張子を含むファイル名
        body: ファイルのバイト列

    Raises:
        UnsupportedFileTypeError: 対応していない拡張子のとき
        EmptyDocumentError: テキストを1文字も抽出できなかったとき
    """
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in PDF_EXTENSIONS:
        text = _extract_pdf(body)
    elif suffix in TEXT_EXTENSIONS:
        # 文字化けした1文字で取込全体を落とさないよう、不正なバイトは置換する
        text = body.decode("utf-8", errors="replace")
    else:
        raise UnsupportedFileTypeError(f"unsupported file type: {suffix or filename}")

    if not text.strip():
        raise EmptyDocumentError(f"no text extracted from {filename}")
    return text


def _extract_pdf(body: bytes) -> str:
    reader = PdfReader(BytesIO(body))
    # ページ区切りは段落区切りとして扱い、チャンク分割の第一セパレータに合わせる
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)
