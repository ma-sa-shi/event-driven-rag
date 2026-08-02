# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An internal RAG chat application on AWS serverless infrastructure. The system design document (in Japanese) is in `docs/architecture.md`, and individual architecture decision records are in `docs/adr/` — read them before making design decisions. The codebase is currently an early scaffold; implementation follows the development order defined at the end of the design doc.

Three independent workspaces, each with its own dependencies:

- `apps/frontend/` — Vite + React 19 + TypeScript SPA (React Router, TanStack Query, axios)
- `apps/backend/` — FastAPI app, Python 3.12, managed with `uv`
- `cdk/` — AWS CDK (TypeScript) infrastructure

## Commands

### Root (Makefile)

```bash
make install           # npm install (frontend) + uv sync (backend)
make dev               # run frontend (:5173) and backend (:8000) dev servers together
make lint              # eslint + prettier --check (frontend), ruff check + format --check (backend)
make format            # prettier --write (frontend), ruff --fix + format (backend)
make test              # backend pytest
make docker-build      # build the api-fn image (web target)
make docker-build-chat    # build the chat-fn image (chat target)
make docker-build-worker  # build the ingest-fn image (worker target)
make docker-up         # run the web image on :8000 (stop the native backend first)
make docker-down
```

Day-to-day development is native (uv/npm). Docker exists only to build the production Lambda images and verify the web image starts locally — the backend Dockerfile has three final targets from one shared builder: `web` (Lambda Web Adapter + uvicorn, for api-fn), `chat` (web plus the `chat` dependency group — langgraph/langchain, for chat-fn) and `worker` (awslambdaric plain handler plus the `ingest` dependency group — pypdf, for ingest-fn); CDK selects the target and per-function env vars (see ADR-0003). No local Lambda emulation (SAM/LocalStack/RIE); Lambda-specific behavior is verified in the CDK-deployed dev environment.

### Frontend (`apps/frontend/`)

```bash
npm run dev            # dev server on http://localhost:5173
npm run build          # tsc -b && vite build
npm run lint           # eslint
npm run format         # prettier --write (format:check for CI-style check)
```

### Backend (`apps/backend/`)

```bash
uv sync                                # install deps
uv run uvicorn app.main:app --reload   # dev server on http://localhost:8000
uv run pytest                          # all tests
uv run pytest tests/test_health.py::test_health   # single test
uv run ruff check .                    # lint
uv run ruff format .                   # format
```

### CDK (`cdk/`)

```bash
npm run typecheck      # tsc --noEmit (tsx runs TS directly; no build step)
npm test               # jest (all tests)
npx jest test/cdk.test.ts              # single test file
npx jest -t "SQS Queue Created"        # single test by name
npx cdk synth / diff / deploy
```

All FastAPI routes live under `/api` (matching CloudFront's `/api/*` routing). The Vite dev server proxies `/api` to `http://localhost:8000` (see `vite.config.ts`), so dev is same-origin like production — no CORS middleware. Run both dev servers for local development.

## Architecture

Target architecture (from `docs/architecture.md`; most of it is not yet implemented):

- **SPA + REST API only.** No SSR, no Next.js/OpenNext. SPA is served from S3 via CloudFront; `/api/*` routes through CloudFront to a Lambda Function URL.
- **One FastAPI Docker image deployed to three Lambdas**, split by responsibility:
  - `api-fn` — REST API (auth, document/chat lists, presigned URLs, ingest kickoff). Uses Lambda Web Adapter.
  - `chat-fn` — SSE streaming chat with LangGraph Self-RAG. Only this function loads LangChain libraries. Uses Lambda Web Adapter.
  - `ingest-fn` — text extraction, chunking, embedding, S3 Vectors registration. Plain Lambda handler (no Web Adapter), triggered by SQS with a DLQ.
- **Upload and ingest are separate flows.** Files go directly from SPA to S3 via presigned URLs (never through Lambda). Issuing the upload URL registers the document with status `uploading`; embeddings are generated only when the user explicitly triggers ingest, which enqueues to SQS. Document status: `uploading → uploaded → processing → ingested | failed`.
- **RAG pipeline** (chat-fn): Multi Query → Vector Search (S3 Vectors) → RRF → Cohere Rerank → LLM Generation → Self Evaluation → Retry (max 1).
- **Auth**: Cognito Hosted UI with Authorization Code + PKCE. FastAPI only verifies JWTs via JWKS — never implement password handling or token issuance in the backend.
- **Data**: DynamoDB single-table design (e.g. `PK=USER#123`, `SK=CHAT#<ULID>`) for documents, chats, and messages. IDs are ULIDs; GSI1 (`GSI1PK=DOC|CHAT`, `GSI1SK=<id>`) serves both cross-user lists and ID-only lookups. S3 Vectors metadata: `documentId` (filterable), `text`/`filename` (non-filterable).
- **Zero fixed cost is a hard constraint**: no VPC, no NAT, no ECS/EC2/Aurora, no Provisioned Concurrency.
- **CDK is planned as four stacks**: DataStack, AppStack, EdgeStack, CiStack (all but CiStack are implemented; see `cdk/README.md` for deploy prerequisites like the manual SSM SecureString setup and the `-c appDomain=` second pass). The SPA bucket lives in EdgeStack, not DataStack, because its OAC policy references the distribution.
- **Logging**: Lambda Powertools (structured logging, metrics, tracing); propagate the request ID across services.

## Notes

- The architecture diagram is generated by `docs/diagrams/event_driven_rag.py` (requires `diagrams` + graphviz); regenerate `docs/diagrams/architecture.png` when the architecture changes.
