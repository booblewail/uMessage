# uMessage developer commands. `make help` lists them.

API_HOST := 127.0.0.1
API_PORT ?= 8000
FRONTEND_PORT ?= 3000
INBOX_URL ?= http://127.0.0.1:$(FRONTEND_PORT)/inbox

.PHONY: help dev install migrate test lint open-inbox google-auth

help:
	@echo "make dev      start backend + frontend and open the inbox (UMESSAGE_MODE=demo make dev: fakes)"
	@echo "make test     run the backend test suite"
	@echo "make lint     ruff check + format check, frontend type-check, lint and build"
	@echo "make migrate  apply database migrations"
	@echo "make google-auth  sign in to Google once, so plans can go on your calendar"
	@echo "make install  install backend and frontend dependencies"

# First run: create .env from the example with a freshly generated API_TOKEN.
.env:
	@sed "s/^API_TOKEN=.*/API_TOKEN=$$(openssl rand -hex 32)/" .env.example > .env
	@echo "Created .env with a new API_TOKEN (edit it to change settings)."

backend/.venv: backend/pyproject.toml backend/uv.lock
	cd backend && uv sync
	@touch $@

frontend/node_modules: frontend/package.json frontend/package-lock.json
	cd frontend && npm install --no-audit --no-fund
	@touch $@

install: backend/.venv frontend/node_modules

migrate: .env backend/.venv
	cd backend && uv run alembic upgrade head

# One uvicorn worker only (the Message Source sync must run exactly once), bound to 127.0.0.1.
# Ctrl-C stops both servers.
dev: .env install migrate
	@echo "Starting uMessage: API http://$(API_HOST):$(API_PORT), inbox $(INBOX_URL)"
	@trap 'kill 0' INT TERM EXIT; \
	( cd backend && exec uv run uvicorn --factory app.main:build_app \
	    --host $(API_HOST) --port $(API_PORT) --reload --reload-dir app ) & \
	( cd frontend && exec npm run dev -- --hostname 127.0.0.1 --port $(FRONTEND_PORT) ) & \
	$(MAKE) --no-print-directory open-inbox & \
	wait

# Wait until both servers answer, then open the inbox in a browser (or just print its URL).
open-inbox:
	@for _ in $$(seq 1 120); do \
	  curl -fsS -o /dev/null http://$(API_HOST):$(API_PORT)/api/health 2>/dev/null \
	    && curl -fsS -o /dev/null $(INBOX_URL) 2>/dev/null && break; \
	  sleep 1; \
	done; \
	echo "uMessage inbox: $(INBOX_URL)"; \
	if [ "$$(uname)" = Darwin ]; then open $(INBOX_URL); \
	elif command -v xdg-open >/dev/null 2>&1; then xdg-open $(INBOX_URL) >/dev/null 2>&1; fi

# Opens Google's sign-in in the browser; saves the sign-in to GOOGLE_TOKEN_PATH (see README).
google-auth: backend/.venv
	cd backend && uv run python -m scripts.google_auth

test: backend/.venv
	cd backend && uv run pytest

lint: backend/.venv frontend/node_modules
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run type-check && npm run lint && npm run build
