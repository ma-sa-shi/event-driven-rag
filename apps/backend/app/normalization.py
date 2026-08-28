"""埋め込み入力の文字正規化。

取込側(app/ingest/pipeline.py)と検索側(app/rag/retriever.py)は、必ず同じ正規化を通した
テキストをCohere Embedへ渡す。片側だけ変えるとベクトル空間がずれ、検索精度が落ちても
表面化しないため、両者でこの関数を共有する。
正規化するのは埋め込み入力だけで、S3 Vectorsへ格納するtextは原文のまま残す。NFKCは①を1、
㈱を(株)へ潰すため、回答の引用まで正規化を持ち込まない(architecture.md 5.4)。
変換規則を変えると登録済みのベクトルだけが旧規則のまま残るため、変更時は
全ドキュメントの再取込が必要になる。
"""

import unicodedata


def normalize_for_embedding(text: str) -> str:
    return unicodedata.normalize("NFKC", text)
