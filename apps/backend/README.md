# backend

FastAPI application shared by the three Lambdas (`api-fn` / `chat-fn` / `ingest-fn`).
All routes are served under `/api` to match the CloudFront `/api/*` routing.

## Setup

```bash
uv sync
```

## Run dev server

```bash
uv run uvicorn app.main:app --reload
```

Listens on http://localhost:8000. The frontend dev server proxies `/api` here,
so requests are same-origin in development (no CORS needed).

## Test

```bash
uv run pytest
```

## Lint / Format

```bash
uv run ruff check .
uv run ruff format .
```

## Docker

The `Dockerfile` here builds the production image deployed to the three
Lambdas (Lambda Web Adapter included; per-function CMD/env are set in CDK).
To verify it builds and starts locally, run from the repo root:

```bash
docker compose up --build backend
```

Serves http://localhost:8000 — stop the native dev server first (same port).
This is only a startup check; day-to-day development stays native (`uv`).
