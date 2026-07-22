from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.auth import get_current_user_id
from app.repositories.users import UserRepository
from app.settings import Settings, get_settings

router = APIRouter(prefix="/users")


class UpsertProfileRequest(BaseModel):
    # 値はCognitoのIDトークンclaims由来のため形式検証はしない
    display_name: str = Field(alias="displayName", min_length=1)
    email: str = Field(min_length=1)


def get_user_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserRepository:
    return UserRepository(settings.table_name)


@router.post("/me", status_code=status.HTTP_204_NO_CONTENT)
def upsert_me(
    body: UpsertProfileRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    repository: Annotated[UserRepository, Depends(get_user_repository)],
) -> None:
    """サインイン時にSPAから呼ばれ、Cognitoの表示名とメールをキャッシュする(冪等)。"""
    repository.upsert_profile(user_id, body.display_name, body.email)
