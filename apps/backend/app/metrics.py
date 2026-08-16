"""ビジネスメトリクスの共有インスタンスとメトリクス名。

名前空間はPOWERTOOLS_METRICS_NAMESPACEから解決される。
CloudWatchのカスタムメトリクスは無料枠が10シリーズ(メトリクス名とディメンションの組み合わせ)である為、
発行はここに定義した5種・計7シリーズに限る(architecture.md 10.1)。
"""

from aws_lambda_powertools import Metrics

metrics = Metrics()

# ingest-fn
DOCUMENTS_INGESTED = "DocumentsIngested"
DOCUMENT_INGEST_FAILURES = "DocumentIngestFailures"
INGESTED_CHUNKS = "IngestedChunks"

# chat-fn
ANSWERS_GRADED = "AnswersGraded"
CHAT_RETRIES = "ChatRetries"
