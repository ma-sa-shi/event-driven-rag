"""LangGraphによるSelf-RAGパイプライン(chat-fn専用)。

このパッケージはchatグループの依存(langgraph / langchain-*)を必要とする。
api-fn / ingest-fnのイメージには入っていないため、app.main は
langgraphの有無を見て条件付きでルーターを取り込む。
"""
