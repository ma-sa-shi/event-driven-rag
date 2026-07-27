import os
from dataclasses import dataclass
from functools import lru_cache


# 生成後に値を書き換えられないようにする
@dataclass(frozen=True)
class Settings:
    cognito_issuer: str
    cognito_client_id: str
    table_name: str
    # 関数ごとに必要な環境変数が異なるため、未設定でも空文字でフォールバックする
    documents_bucket_name: str
    ingest_queue_url: str
    vector_index_arn: str
    openai_api_key_parameter_name: str
    cohere_api_key_parameter_name: str
    openai_answer_model: str
    openai_utility_model: str
    cohere_embedding_model: str
    cohere_rerank_model: str


# キャッシュ化により、os.environの読み込みを1回だけにする
@lru_cache
def get_settings() -> Settings:
    return Settings(
        cognito_issuer=os.environ["COGNITO_ISSUER"],
        cognito_client_id=os.environ["COGNITO_CLIENT_ID"],
        table_name=os.environ["TABLE_NAME"],
        documents_bucket_name=os.environ.get("DOCUMENTS_BUCKET_NAME", ""),
        ingest_queue_url=os.environ.get("INGEST_QUEUE_URL", ""),
        vector_index_arn=os.environ.get("VECTOR_INDEX_ARN", ""),
        openai_api_key_parameter_name=os.environ.get(
            "OPENAI_API_KEY_PARAMETER_NAME", ""
        ),
        cohere_api_key_parameter_name=os.environ.get(
            "COHERE_API_KEY_PARAMETER_NAME", ""
        ),
        openai_answer_model=os.environ.get("OPENAI_ANSWER_MODEL", "gpt-5.4-mini"),
        openai_utility_model=os.environ.get("OPENAI_UTILITY_MODEL", "gpt-5.4-nano"),
        cohere_embedding_model=os.environ.get("COHERE_EMBEDDING_MODEL", "embed-v4.0"),
        cohere_rerank_model=os.environ.get("COHERE_RERANK_MODEL", "rerank-v4.0-fast"),
    )
