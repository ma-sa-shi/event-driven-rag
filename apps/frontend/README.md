# frontend

Vite + React 19 SPA served from S3 via CloudFront. `/api/*` is routed to the
backend by CloudFront in production, and by the Vite dev server proxy locally,
so requests are same-origin in both (no CORS needed).

## Setup

```bash
npm install
```

Cognito settings are read from `.env.local` at build time; see `.env.example`.

## Run dev server

```bash
npm run dev
```

Listens on http://localhost:5173 and proxies `/api` to http://localhost:8000,
so the backend dev server has to be running too (`make dev` starts both).

## Test

```bash
npm test                       # vitest run
npm run test:watch             # watch mode
npx vitest run test/lib/sse.test.ts          # single file
npx vitest run -t "コメント行を読み飛ばす"    # single test by name
```

Tests live under `test/`, mirroring the `src/` layout. They run in jsdom with
React Testing Library. Vitest globals are not injected — import `describe` /
`it` / `expect` / `vi` from `vitest` in each file.

## Build

```bash
npm run build
```

`tsc -b` type-checks `src/`, `vite.config.ts` and `test/` (one tsconfig each,
wired through the references in `tsconfig.json`), then Vite bundles into `dist/`.

## Lint / Format

```bash
npm run lint
npm run format                 # format:check for a CI-style check
```
