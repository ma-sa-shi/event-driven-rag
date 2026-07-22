from fastapi import APIRouter, FastAPI

from app.routers import users

app = FastAPI()

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


router.include_router(users.router)
app.include_router(router)
