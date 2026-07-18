"""architecture.md のサーバーレス構成図を生成するスクリプト。

実行方法:
    pip install diagrams  # 要 graphviz (dot)
    python docs/diagrams/event-driven-rag.py

docs/diagrams/architecture.png が生成される。
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import SQS
from diagrams.aws.network import CloudFront
from diagrams.aws.security import Cognito
from diagrams.aws.storage import S3
from diagrams.onprem.client import Client

graph_attr = {
    "fontsize": "20",
    "pad": "0.5",
    "splines": "spline",
}

with Diagram(
    "Event-driven RAG Architecture",
    filename="docs/diagrams/architecture",
    show=False,
    direction="LR",
    graph_attr=graph_attr,
):
    browser = Client("Browser\n(Vite + React SPA)")
    cognito = Cognito("Cognito User Pool\n(Hosted UI + PKCE)")

    with Cluster("Edge"):
        cloudfront = CloudFront("CloudFront")

    spa_bucket = S3("S3\n(Static SPA)")

    with Cluster("Backend (FastAPI on Lambda)"):
        api_fn = Lambda("api-fn\n(REST API)")
        chat_fn = Lambda("chat-fn\n(SSE / Self-RAG)")

    with Cluster("Ingest (Async)"):
        queue = SQS("SQS\n(+ DLQ)")
        ingest_fn = Lambda("ingest-fn\n(Extract / Chunk / Embed)")

    with Cluster("Data Store"):
        dynamodb = Dynamodb("DynamoDB\n(Single Table)")
        raw_bucket = S3("S3\n(Raw Files)")
        vectors = S3("S3 Vectors\n(Embedding)")

    # 認証: SPA -> Cognito Hosted UI -> Access Token
    browser >> Edge(label="Auth (Code + PKCE)", style="dashed") >> cognito

    # 配信: CloudFront で SPA と API を振り分け
    browser >> cloudfront
    cloudfront >> Edge(label="/") >> spa_bucket
    cloudfront >> Edge(label="/api/* (Function URL)") >> api_fn
    cloudfront >> Edge(label="/api/* (Function URL)") >> chat_fn

    # アップロード: presigned URL で S3 へ直接 PUT
    browser >> Edge(label="presigned PUT", style="dashed") >> raw_bucket

    # 取込: api-fn -> SQS -> ingest-fn -> 各ストア
    api_fn >> queue >> ingest_fn
    ingest_fn >> [dynamodb, raw_bucket, vectors]

    # API / チャット処理のデータアクセス
    api_fn >> Edge(label="documents / chats") >> dynamodb
    chat_fn >> Edge(label="vector search") >> vectors
    chat_fn >> Edge(label="messages") >> dynamodb
