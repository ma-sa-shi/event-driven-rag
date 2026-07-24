import os
from dataclasses import dataclass
from functools import lru_cache


# 生成後に値を書き換えられないようにする
@dataclass(frozen=True)
class Settings:
    cognito_issuer: str
    cognito_client_id: str
    table_name: str
    documents_bucket_name: str
    ingest_queue_url: str


# キャッシュ化により、os.environの読み込みを1回だけにする
@lru_cache
def get_settings() -> Settings:
    return Settings(
        cognito_issuer=os.environ["COGNITO_ISSUER"],
        cognito_client_id=os.environ["COGNITO_CLIENT_ID"],
        table_name=os.environ["TABLE_NAME"],
        documents_bucket_name=os.environ["DOCUMENTS_BUCKET_NAME"],
        ingest_queue_url=os.environ["INGEST_QUEUE_URL"],
    )
