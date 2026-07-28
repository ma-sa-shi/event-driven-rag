"""ingest-fnのドキュメント取込処理。

テキスト抽出 → チャンク分割 → Embedding生成 → S3 Vectors登録を担当する。
worker イメージにはLangChain系ライブラリを入れない方針(ADR-0003)のため、
chat-fn側のRAG実装(app/rag)とはコードを共有せず、軽量な実装を持つ。
"""
