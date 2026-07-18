from fastapi import APIRouter, FastAPI

app = FastAPI()

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


app.include_router(router)
