# syntax=docker/dockerfile:1
# Single FastAPI codebase deployed to three Lambdas (api-fn / chat-fn / ingest-fn).
# One shared builder, two final targets (CDK selects the target per function):
# - web:    api-fn / chat-fn. Lambda Web Adapter extension + uvicorn CMD.
#           chat-fn: CDK sets AWS_LWA_INVOKE_MODE=response_stream for SSE.
# - worker: ingest-fn. Plain Lambda handler via awslambdaric — no adapter.
#           (The adapter extension has no disable flag and would block init
#           waiting for a web server that never starts.)
# Locally the web target runs as a plain HTTP server: the extension is inert
# outside the Lambda runtime.

FROM public.ecr.aws/docker/library/python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Adds awslambdaric on top of the shared venv (worker group only)
FROM builder AS worker-builder
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --group worker

# ---- web: api-fn / chat-fn (Lambda Web Adapter + uvicorn) ----
FROM public.ecr.aws/docker/library/python:3.12-slim AS web

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /app
COPY --from=builder /app/.venv ./.venv
COPY app ./app

# AWS_LWA_PORT aligns the adapter with uvicorn (adapter default is 8080).
ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8000 \
    AWS_LWA_PORT=8000 \
    AWS_LWA_READINESS_CHECK_PATH=/api/health

EXPOSE 8000

# Each Lambda sandbox serves one request at a time; a single worker suffices.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- worker: ingest-fn (no adapter; runtime interface client) ----
FROM public.ecr.aws/docker/library/python:3.12-slim AS worker

WORKDIR /app
COPY --from=worker-builder /app/.venv ./.venv
COPY app ./app

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["/app/.venv/bin/python", "-m", "awslambdaric"]
CMD ["app.ingest_handler.handler"]
