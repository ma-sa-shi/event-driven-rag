import importlib.util
import json
import uuid

from fastapi import APIRouter, FastAPI, Request

from app.logger import logger
from app.routers import chats, documents, users

app = FastAPI()


def _lambda_request_id(request: Request) -> str | None:
    """Lambda Web Adapterが転送するLambda contextからrequest IDを取り出す。"""
    header = request.headers.get("x-amzn-lambda-context")
    if not header:
        return None
    try:
        return json.loads(header).get("request_id")
    except (json.JSONDecodeError, AttributeError):
        return None


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """
    全リクエストに対して追跡用のRequest IDを採番し、ログとレスポンスヘッダーに付与する
    - @app.middleware("http"): 全てのHTTPリクエストに対して実行する割り込み処理（ミドルウェア）
    - request (Request): リクエスト情報（ヘッダー、URL、ボディ等）
    - call_next: 次の処理(ルーター関数)へリクエストを渡す為の非同期関数
    """
    # ローカル実行などLambda contextがない場合はUUIDで代替する
    request_id = _lambda_request_id(request) or str(uuid.uuid4())
    request.state.request_id = request_id
    logger.append_keys(request_id=request_id)
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
