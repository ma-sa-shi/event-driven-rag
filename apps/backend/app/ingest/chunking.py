"""抽出テキストを検索単位のチャンクへ分割する。

langchain-text-splittersはlangchain-coreを引き込みworkerイメージを重くする為、自前実装する(ADR-0003)。
"""

# 1チャンクの最大文字数と文脈を維持するために隣接チャンク間で重複させる文字数
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
# 分割に使用するセパレータの優先順位
SEPARATORS = ("\n\n", "\n", " ", "")


def split_text(
    text: str,
    *,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    return _split(text, SEPARATORS, chunk_size, chunk_overlap)


def _split(
    text: str, separators: tuple[str, ...], chunk_size: int, chunk_overlap: int
) -> list[str]:
    separator, remaining = _select_separator(text, separators)
    # separator == ""のときは1文字ごとのリストlist[text]を返す
    pieces = text.split(separator) if separator else list(text)

    chunks: list[str] = []
    # chunk_sizeに収まる断片はまとめてから結合し、細切れのチャンクを作らない
    mergeable: list[str] = []
    for piece in pieces:
        if len(piece) <= chunk_size:
            mergeable.append(piece)
            continue
        # 長すぎる断片は、より細かいセパレータで分割し直す
        chunks.extend(_merge(mergeable, separator, chunk_size, chunk_overlap))
        mergeable = []
        chunks.extend(_split(piece, remaining, chunk_size, chunk_overlap))
    chunks.extend(_merge(mergeable, separator, chunk_size, chunk_overlap))
    return chunks


def _select_separator(
    text: str, separators: tuple[str, ...]
) -> tuple[str, tuple[str, ...]]:
    """テキストに含まれる最も粗いセパレータと、それより細かいセパレータ群を返す。"""
    for index, separator in enumerate(separators):
        # separator == ""はどのseparatorでもマッチしなかった場合のフォールバック
        if separator == "" or separator in text:
            return separator, separators[index + 1 :]
    return "", ()


def _merge(
    pieces: list[str], separator: str, chunk_size: int, chunk_overlap: int
) -> list[str]:
    """断片をchunk_sizeまで詰め込み、末尾chunk_overlap分を次のチャンクへ引き継ぐ。"""
    chunks: list[str] = []
    current: list[str] = []
    # currentをseparatorで連結したときの長さ
    total = 0

    for piece in pieces:
        length = _joined_length(current, piece, separator)
        if total + length > chunk_size and current:
            chunks.append(separator.join(current).strip())
            # オーバーラップ分だけ残るまで先頭から捨てる
            # 次の断片が入る余地も確保する(1断片がchunk_sizeを占める場合は空になる)
            while current and (total > chunk_overlap or total + length > chunk_size):
                dropped = current.pop(0)
                total -= len(dropped) + (len(separator) if current else 0)
        current.append(piece)
        total += length

    if current:
        chunks.append(separator.join(current).strip())
    # 空白のみの断片はstripの結果として空文字になるため取り除く
    return [chunk for chunk in chunks if chunk]


def _joined_length(current: list[str], piece: str, separator: str) -> int:
    return len(piece) + (len(separator) if current else 0)
