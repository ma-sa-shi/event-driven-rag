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

## TypeScript Code Style

### Readability

- Optimize for the reader, not for line count.
- Prefer explicit `if` statements and block bodies when compact expressions reduce readability.
- Avoid nested ternary operators and nested arrow functions.
- Name every branch when handling finite sets of cases such as string unions, enums, or state machines.
- Prefer code that can be understood by reading top-to-bottom without mentally expanding expressions.
- Widely-shared ecosystem idioms that clearly communicate intent are not considered clever shortcuts. Do not use this exception to justify complex expressions or compressed business logic.
- Prefer early returns over deeply nested control flow.
- Introduce well-named intermediate variables when an expression performs multiple logical steps.

### Simplicity

- Introduce intermediate variables only to clarify intent or separate logical steps.
- Avoid unnecessary wrapper functions or abstractions.
- Avoid adding abstractions before they solve a real problem.
- Keep related code together. Split files only when responsibilities clearly diverge.

### Comments

Comments are the exception, not the default.

Prefer expressive names, types, and structure over comments.

Write comments only when the reason, constraint, or invariant cannot be inferred from the code.

Good comments explain:

- design constraints
- cross-module contracts
- platform or framework behavior that surprises experienced developers
- intentional deviations from the obvious implementation

Do not comment:

- what the code already says
- function summaries
- parameter descriptions
- control flow
- language or library basics

Python docstrings follow the same principles:

- A module docstring carries the why: constraints, cross-module contracts, and intentional deviations from the obvious implementation.
- A function docstring is a single line, and only when the name, types, and signature cannot fully express the contract.
- Do not write `Args:` / `Returns:` sections that merely repeat parameter names and type annotations.
- Write a `Raises:` section only when callers need to know about a specific exception as part of the function contract.

Keep comments concise (normally 1–3 lines).

If an explanation requires a paragraph, move it to CLAUDE.md (project rules) or docs/architecture.md / ADR (architectural rationale) and reference it instead.

## Python Code Style

Applies to `apps/backend/`.

### Data shapes

- Prefer named structures when values have semantic meaning.
- Prefer `dataclass` or `NamedTuple` for internal models. Use `TypedDict` for dictionary-shaped external data such as JSON.
- Avoid anonymous or loosely typed nested dictionaries when the schema is part of the contract. Define explicit types instead.
- Fully parameterize container types. Avoid incomplete annotations such as `list` or `dict`.
- Use `Any` only at boundaries where precise typing is not practical (for example, interacting with untyped third-party libraries).
- Prefer named field access over positional indexing when the data has semantic fields.

### State and loops

- Prefer comprehensions and built-in transformations over manual accumulation when practical.
- Avoid synchronizing multiple mutable variables that represent the same state.
- Avoid maintaining duplicate mutable state. Prefer recomputing derived values unless caching is required for performance.
- When an algorithm requires non-obvious state management, document the invariant or constraint that must be preserved.
- Prefer introducing a new local variable instead of reassigning parameters.

## Japanese Writing Quality

When generating Japanese text (including comments, documentation, ADRs, issues, PR descriptions, and commit messages), prioritize natural Japanese over literal translation from English.

### Writing Principles

- Do not translate English expressions literally. Preserve the meaning while using natural Japanese.
- Prefer wording commonly used in Japanese technical documentation.
- Follow the terminology and writing style already established in this repository.
- Avoid introducing unnatural or novel expressions when a standard Japanese equivalent exists.
- Prioritize readability and clarity over preserving the original English sentence structure.

### Self-Review Before Writing

Review the text from the perspective of a native Japanese reader.

Verify that:

- The text does not read like a literal translation from English.
- The wording is natural and idiomatic for Japanese readers.
- Terminology is consistent throughout the document and with the rest of the repository.
- The sentences are easy to read and understand without awkward phrasing.

If there is a more natural way to express the same meaning in Japanese, prefer that wording over a literal translation.

## Notes

- The architecture diagram is generated by `docs/diagrams/event_driven_rag.py` (requires `diagrams` + graphviz); regenerate `docs/diagrams/architecture.png` when the architecture changes.
