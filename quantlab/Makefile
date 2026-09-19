# QuantLab signal viewer demo — Docker tooling.
# Host prerequisites: Docker (with Compose v2) and GNU make. Nothing else.

.DEFAULT_GOAL := help

COMPOSE := docker compose

.PHONY: help up down build seed logs test smoke hash dump-hash gen-api

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

up: ## Build and start the full stack (seed -> backend -> frontend) with preflight checks
	@command -v docker >/dev/null 2>&1 || { \
		echo "ERROR: 'docker' CLI not found. Install Docker Desktop (or Docker Engine) and retry." >&2; exit 1; }
	@docker info >/dev/null 2>&1 || { \
		echo "ERROR: Docker daemon is not reachable. Start Docker Desktop (or the docker service) and retry." >&2; exit 1; }
	@docker compose version >/dev/null 2>&1 || { \
		echo "ERROR: 'docker compose' (Compose v2) is not available. Upgrade Docker and retry." >&2; exit 1; }
	@for port in 8000 8080; do \
		busy=""; \
		if command -v lsof >/dev/null 2>&1; then \
			lsof -nP -iTCP:$$port -sTCP:LISTEN >/dev/null 2>&1 && busy=yes; \
		elif command -v nc >/dev/null 2>&1; then \
			nc -z 127.0.0.1 $$port >/dev/null 2>&1 && busy=yes; \
		fi; \
		if [ -n "$$busy" ]; then \
			echo "ERROR: host port $$port is already in use. Stop the process bound to it (e.g. 'lsof -nP -iTCP:$$port -sTCP:LISTEN' to find it) and retry 'make up'." >&2; exit 1; \
		fi; \
	done
	$(COMPOSE) up --build -d
	@echo "Waiting for backend to become healthy..."; \
	for i in $$(seq 1 90); do \
		cid=$$($(COMPOSE) ps -q backend 2>/dev/null); \
		status=$$(docker inspect --format '{{.State.Health.Status}}' $$cid 2>/dev/null || true); \
		if [ "$$status" = "healthy" ]; then echo "backend is healthy"; break; fi; \
		if [ $$i -eq 90 ]; then \
			echo "ERROR: backend did not become healthy in time. Recent backend logs:" >&2; \
			$(COMPOSE) logs --tail 50 backend >&2; exit 1; \
		fi; \
		sleep 2; \
	done
	@echo "Stack is up. UI: http://localhost:8080  API: http://localhost:8000"

down: ## Stop and remove all containers and the quantlab-data volume (clean reseed on next up)
	$(COMPOSE) down -v

build: ## Build the backend and frontend images
	$(COMPOSE) build

seed: ## Re-run the one-shot seed service (deletes and regenerates the SQLite DB)
	$(COMPOSE) run --rm seed

logs: ## Follow service logs
	$(COMPOSE) logs -f

test: ## Run backend pytest and frontend vitest inside containers (no host toolchain needed)
	$(COMPOSE) build backend
	$(COMPOSE) run --rm --no-deps backend python -m pytest -q
	docker build --target build -t quantlab-frontend-test ./frontend
	docker run --rm quantlab-frontend-test npx vitest run

smoke: ## Run the end-to-end smoke check (health, seeded data, per-rule signals, UI)
	bash scripts/smoke.sh

dump-hash: ## SHA-256 of the ordered dump of every table in the SQLite DB (determinism proof)
	@$(COMPOSE) exec -T backend python -c 'import os, sqlite3; \
		db = os.environ.get("QUANTLAB_DB") or os.environ.get("QUANTLAB_DB_PATH") or "/data/quantlab.db"; \
		con = sqlite3.connect(db); \
		tables = [r[1] for r in con.execute("SELECT type, name FROM sqlite_master ORDER BY name") if r[0] == "table" and not r[1].startswith("sqlite_")]; \
		[(print("-- table: " + t), [print("|".join("" if v is None else str(v) for v in row)) for row in con.execute("SELECT * FROM \"%s\" ORDER BY rowid" % t)]) for t in tables]' \
		| { command -v sha256sum >/dev/null 2>&1 && sha256sum || shasum -a 256; }

hash: dump-hash ## Alias for dump-hash

gen-api: ## Regenerate frontend/src/api/schema.d.ts from the OpenAPI contract (node runs in a container)
	docker run --rm -v "$(CURDIR)":/work -w /work node:22 \
		npx -y openapi-typescript specs/002-signal-viewer-demo/contracts/openapi.yaml -o frontend/src/api/schema.d.ts
