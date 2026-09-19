# QuantLab signal viewer demo — Docker tooling.
# Host prerequisites: Docker (with Compose v2) and GNU make. Nothing else.
#
# Repository layout: specs live in quantlab_specs/ (specs only, no code);
# the runnable demo lives here at the repository root.

.DEFAULT_GOAL := help

COMPOSE := docker compose

# Service that `make docker-shell` drops you into (override: make docker-shell SERVICE=frontend)
SERVICE ?= backend

# The OpenAPI contract is authored once under quantlab_specs/. backend/contracts/
# holds a copy only because the backend image's build context is backend/ and so
# cannot reach outside it; `make check-contract` guards the two against drift.
CONTRACT_SRC := quantlab_specs/specs/002-signal-viewer-demo/contracts/openapi.yaml
CONTRACT_COPY := backend/contracts/openapi.yaml

# Symbols for `make ingest` (override: make ingest SYMBOLS="VOD.LON BP.LON")
SYMBOLS ?= AAPL.US MSFT.US HSBA.LON
START   ?= 2015-01-01
END     ?=
PROVIDERS ?= yahoo stooq

.PHONY: help up down build seed logs shell docker-shell test smoke hash dump-hash gen-api \
	check-contract sync-contract migrate ingest coverage signals store-test db-shell \
	ch-shell destroy

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

up: ## Build and start the full stack (seed -> backend -> frontend) with preflight checks
	bash scripts/up.sh

down: ## Stop and remove containers, KEEPING ingested data
	$(COMPOSE) down

destroy: ## DESTRUCTIVE: remove containers AND every volume, including ingested history
	@echo "This permanently deletes the ClickHouse bars and the Postgres catalog."
	@printf 'Type "destroy" to confirm: ' && read ans && [ "$$ans" = "destroy" ] || \
		{ echo "aborted"; exit 1; }
	$(COMPOSE) down -v

build: ## Build the backend and frontend images
	$(COMPOSE) build

seed: ## Re-run the synthetic demo seed (SQLite; --profile is a compose-level flag)
	$(COMPOSE) --profile demo run --rm seed

# --- Historical data warehouse (ClickHouse bars + Postgres catalog) ----------

migrate: ## Apply pending migrations to both the catalog and the bars store
	$(COMPOSE) run --rm ingest migrate

ingest: ## Ingest real history (override SYMBOLS/START/END/PROVIDERS)
	$(COMPOSE) run --rm ingest ingest $(SYMBOLS) \
		--start $(START) $(if $(END),--end $(END),) --providers $(PROVIDERS)

coverage: ## What is in the store, where it came from, and how well it compresses
	$(COMPOSE) run --rm ingest coverage

signals: ## Recompute signals from warehouse bars into the catalog
	$(COMPOSE) run --rm backend python -m quantlab.signals.materialize

store-test: ## Run the store test suite against the live stack
	$(COMPOSE) run --rm --entrypoint python ingest -m pytest tests/test_store.py -q

db-shell: ## psql into the Postgres catalog
	$(COMPOSE) exec postgres psql -U quantlab -d quantlab

ch-shell: ## clickhouse-client into the bars store
	$(COMPOSE) exec clickhouse clickhouse-client --user quantlab --password quantlab \
		--database quantlab

logs: ## Follow service logs
	$(COMPOSE) logs -f

docker-shell: ## Open an interactive shell in a running container (SERVICE=backend by default)
	bash scripts/docker-shell.sh $(SERVICE)

shell: docker-shell ## Alias for docker-shell

test: check-contract ## Run backend pytest and frontend vitest inside containers (no host toolchain needed)
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

check-contract: ## Fail if backend/contracts/openapi.yaml has drifted from the authored spec
	@diff -u $(CONTRACT_SRC) $(CONTRACT_COPY) >/dev/null 2>&1 || { \
		echo "ERROR: $(CONTRACT_COPY) has drifted from the authored contract"; \
		echo "       $(CONTRACT_SRC)"; \
		echo "       Run 'make sync-contract' to refresh the in-image copy." >&2; \
		diff -u $(CONTRACT_SRC) $(CONTRACT_COPY) >&2 || true; exit 1; }
	@echo "contract copy is in sync with $(CONTRACT_SRC)"

sync-contract: ## Refresh backend/contracts/openapi.yaml from the authored spec
	cp $(CONTRACT_SRC) $(CONTRACT_COPY)
	@echo "synced $(CONTRACT_COPY) <- $(CONTRACT_SRC)"

gen-api: ## Regenerate frontend/src/api/schema.d.ts from the OpenAPI contract (node runs in a container)
	docker run --rm -v "$(CURDIR)":/work -w /work node:22 \
		npx -y openapi-typescript quantlab_specs/specs/002-signal-viewer-demo/contracts/openapi.yaml -o frontend/src/api/schema.d.ts
