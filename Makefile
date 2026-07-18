.PHONY: install dev dev-frontend dev-backend lint format test docker-build docker-up docker-down

install: ## Install frontend + backend dependencies
	cd apps/frontend && npm install
	cd apps/backend && uv sync

# Recursive make with -j2 runs both servers concurrently with interleaved
# output; Ctrl-C stops both.
dev: ## Run frontend (:5173) and backend (:8000) dev servers
	$(MAKE) -j2 dev-frontend dev-backend

dev-frontend:
	cd apps/frontend && npm run dev

dev-backend:
	cd apps/backend && uv run uvicorn app.main:app --reload

lint:
	cd apps/frontend && npm run lint && npm run format:check
	cd apps/backend && uv run ruff check . && uv run ruff format --check .

format:
	cd apps/frontend && npm run format
	cd apps/backend && uv run ruff check --fix . && uv run ruff format .

test:
	cd apps/backend && uv run pytest

docker-build: ## Build the Lambda-deployable backend image
	docker compose build backend

docker-up: ## Run the backend image on :8000 (stop the native backend first)
	docker compose up --build backend

docker-down:
	docker compose down
