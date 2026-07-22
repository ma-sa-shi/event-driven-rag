"""CognitoアクセストークンのJWT検証。

JWKSによる署名検証と`iss` / `client_id` / `exp` / `token_use=access`の検証のみを行い、
トークン発行やセッション管理は実装しない(ADR-0004、docs/authorization.md)。
"""

import logging

# Least Recently Used Cacheは、functools モジュールが提供する関数の結果をキャッシュするデコレータ
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# Authorization ヘッダーが存在しない場合、FastAPIは自動的に 403 Forbidden エラーを発生する
# auto_error=False: Authorizationヘッダなしを403ではなく401で返す
_bearer = HTTPBearer(auto_error=False)


# JWKSの公開鍵取得をプロセス内でキャッシュする
@lru_cache
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        # HTTP仕様（RFC 7235 / RFC 6750）に準拠し、クライアントに正しい認証方式を通知・指示するため
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    if credentials is None:
        logger.warning("JWT rejected: Authorization header missing")
        raise _unauthorized()

    token = credentials.credentials
    jwks_client = _jwks_client(f"{settings.cognito_issuer}/.well-known/jwks.json")
    # デジタル署名の確認
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.cognito_issuer,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        logger.warning("JWT rejected: %s", exc)
        raise _unauthorized() from None

    # JWTの内容検証
    # Cognitoのアクセストークンはaudを持たず、client_id / token_useクレームで検証する
    if claims.get("token_use") != "access":
        logger.warning("JWT rejected: token_use=%s", claims.get("token_use"))
        raise _unauthorized()
    if claims.get("client_id") != settings.cognito_client_id:
        logger.warning("JWT rejected: unexpected client_id")
        raise _unauthorized()

    return claims["sub"]
