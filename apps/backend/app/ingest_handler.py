"""ingest-fn entrypoint, invoked by awslambdaric (Dockerfile worker target).

Runs as a plain Lambda handler triggered by SQS — no Web Adapter, no FastAPI.
Text extraction / chunking / embedding / S3 Vectors registration will be
implemented in a later issue; for now the handler only logs received messages.
"""

import logging

logger = logging.getLogger(__name__)
# The Lambda runtime already attaches a handler to the root logger, so
# logging.basicConfig() is a no-op here; set the level directly instead.
logger.setLevel(logging.INFO)


def handler(event, context):
    records = event.get("Records", [])
    logger.info("received %d ingest message(s)", len(records))
    for record in records:
        logger.info("messageId=%s body=%s", record.get("messageId"), record.get("body"))
    # Partial-batch response shape; empty means every record succeeded.
    return {"batchItemFailures": []}
