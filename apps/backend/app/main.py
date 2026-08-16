import importlib.util
import json
import uuid
from typing import Any

from fastapi import APIRouter, FastAPI, Request

from app.logger import logger
from app.routers import chats, documents, users
from app.tracer import restore_trace_context, traced_request

# 末尾スラッシュの自動リダイレクトを無効化する。
# 307のLocationはリクエストのHostから組み立てられ、CloudFrontはOriginへのHostとして
# API Gatewayのexecute-apiドメインを渡す為、有効なままではオリジンがクライアントへ漏れる。
# execute-apiのエンドポイントは直接到達可能である(ADR-0011)ため、ドメインの露出そのものを避ける。
app = FastAPI(redirect_slashes=False)


def _lambda_context(request: Request) -> dict[str, Any]:
    """Lambda Web Adapterが転送するLambda contextを取り出す。

    request IDとX-RayのトレースIDは、どちらもこのヘッダーからしか得られない。
    """
    header = request.headers.get("x-amzn-lambda-context")
    if not header:
        return {}
    try:
        context = json.loads(header)
    except json.JSONDecodeError:
        return {}
    return context if isinstance(context, dict) else {}


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """全リクエストに追跡用のRequest IDを採番し、ログ・トレース・レスポンスヘッダーへ付与する。

    Lambda contextのaws_request_idを引き継ぎ、無い場合はUUIDで代替する。
    """
    context = _lambda_context(request)
    # ローカル実行などLambda contextがない場合はUUIDで代替する
    request_id = context.get("request_id") or str(uuid.uuid4())
    request.state.request_id = request_id
    logger.append_keys(request_id=request_id)
    restore_trace_context(context.get("xray_trace_id"))

    with traced_request("## request", request_id):
        response = await call_next(request)

    response.headers["X-Request-Id"] = request_id
    logger.info(
        "request completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
    )
    return response


router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


router.include_router(users.router)
router.include_router(documents.router)
router.include_router(chats.router)

# コールドスタートの短縮の為、環境内に langgraph ライブラリが存在する場合のみ chat_stream ルーターをロード
if importlib.util.find_spec("langgraph") is not None:
    from app.routers import chat_stream

    router.include_router(chat_stream.router)

app.include_router(router)
