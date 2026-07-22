import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    cognito_issuer: str
    cognito_client_id: str
    table_name: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        cognito_issuer=os.environ["COGNITO_ISSUER"],
        cognito_client_id=os.environ["COGNITO_CLIENT_ID"],
        table_name=os.environ["TABLE_NAME"],
    )
