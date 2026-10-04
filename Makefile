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
CONTRACT_SRC := quantlab_specs/specs/006-warehouse-experiments/contracts/openapi.yaml
CONTRACT_COPY := backend/contracts/openapi.yaml

.PHONY: help up dev down build seed logs shell docker-shell test smoke check-warehouse hash dump-hash gen-api \
	check-contract sync-contract migrate signals store-test db-shell ch-shell destroy

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

up: ## Build and start the full stack (seed -> backend -> frontend) with preflight checks
	bash scripts/up.sh

dev: ## Local dev: Docker backend + hot-reloading frontend on :5173 (AUTH_BYPASS=1 skips login)
	bash scripts/dev.sh

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
#
# This repo owns the warehouse *schema* (src/quantlab/store). Loading data into
# it -- bars, fundamentals, macro, short interest, universes -- is
# quantlab-data-pipeline's job: `make quantlab-data ARGS="..."` there, e.g.
# `make ingest-fred TARGET=prod` for the VIX and HY spread the S6 gate reads.

migrate: ## Apply pending migrations to both the catalog and the bars store
	$(COMPOSE) run --rm migrate

signals: ## Recompute signals from warehouse bars into the catalog
	$(COMPOSE) run --rm backend python -m quantlab.signals.materialize

store-test: ## Run the schema tests against the live stack (migrations apply and are idempotent)
	$(COMPOSE) run --rm --entrypoint python migrate -m pytest tests -q

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
	# --maxWorkers=2: one jsdom worker per CPU starves the suite badly enough
	# that findBy* queries time out -- six tests fail, none of them real. Capping
	# it is both deterministic and faster. CI runs the identical command.
	docker run --rm quantlab-frontend-test npx vitest run --maxWorkers=2 --minWorkers=1

smoke: ## Run the end-to-end smoke check (health, seeded data, per-rule signals, UI)
	bash scripts/smoke.sh

check-warehouse: ## Assert the API serves the warehouse, not the silent synthetic fallback
	bash scripts/check-warehouse.sh

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
		npx -y openapi-typescript quantlab_specs/specs/006-warehouse-experiments/contracts/openapi.yaml -o frontend/src/api/schema.d.ts

# --- Production: the single Compute Engine VM -------------------------------
#
# Thin wrappers over `gcloud compute ssh --tunnel-through-iap`, so day-two
# operations are the same two words as the local ones. Deploys are NOT here:
# they belong to .github/workflows/deploy.yml, and a Makefile target that also
# deployed would be a second, divergent way to change production.
#
# Set these once in your shell (they match the GitHub repository variables):
#   export GCP_INSTANCE=quantlab GCP_ZONE=europe-west2-c
#
# See docs/DEPLOY.md.

GCP_INSTANCE ?= quantlab
GCP_ZONE     ?=
PROD_DIR     := /opt/quantlab
PROD_COMPOSE := sudo docker compose --env-file $(PROD_DIR)/.env --env-file $(PROD_DIR)/.env.images -f $(PROD_DIR)/docker-compose.prod.yml

# Every target below needs a zone and there is no sane default -- failing here
# beats a gcloud error three layers down.
require-zone:
	@[ -n "$(GCP_ZONE)" ] || { \
		echo "ERROR: set GCP_ZONE (e.g. export GCP_ZONE=europe-west2-c)." >&2; exit 1; }

# $(1) is run on the VM, through the IAP tunnel -- port 22 is closed to the internet.
define prod_ssh
	gcloud compute ssh $(GCP_INSTANCE) --zone $(GCP_ZONE) --tunnel-through-iap --quiet --command "$(1)"
endef

prod-ssh: require-zone ## Open a shell on the production VM (through IAP)
	gcloud compute ssh $(GCP_INSTANCE) --zone $(GCP_ZONE) --tunnel-through-iap

prod-ps: require-zone ## What is running in production
	$(call prod_ssh,cd $(PROD_DIR) && $(PROD_COMPOSE) ps)

prod-logs: require-zone ## Follow production logs (SERVICE=backend to narrow)
	gcloud compute ssh $(GCP_INSTANCE) --zone $(GCP_ZONE) --tunnel-through-iap \
		--command "cd $(PROD_DIR) && $(PROD_COMPOSE) logs -f --tail 100 $(SERVICE)"

prod-ip: require-zone ## Print the VM's external IP
	@gcloud compute instances describe $(GCP_INSTANCE) --zone $(GCP_ZONE) \
		--format='value(networkInterfaces[0].accessConfigs[0].natIP)'

# Once QUANTLAB_SITE_ADDRESS is a hostname, Caddy serves that name and nothing
# else -- a request to the bare IP matches no site block and gets a 404. Set
# PROD_URL (export PROD_URL=https://api.example.com) and these targets follow it;
# the IP fallback is only right for the pre-DNS, plain-HTTP state.
PROD_URL ?=

prod-url: require-zone ## Print the API base URL (PROD_URL if set, else the VM's IP)
	@if [ -n "$(PROD_URL)" ]; then echo "$(PROD_URL)"; \
	else echo "http://$$($(MAKE) -s prod-ip)"; fi

prod-health: require-zone ## Hit the public health endpoint
	@curl -fsS "$$($(MAKE) -s prod-url)/api/v1/health"; echo

prod-check: require-zone ## Assert production serves the warehouse, not the synthetic fallback
	@BACKEND_URL="$$($(MAKE) -s prod-url)" bash scripts/check-warehouse.sh

# Loading production data (and `coverage`) runs from quantlab-data-pipeline
# over its IAP tunnel: `make tunnel`, then `make quantlab-data TARGET=prod ARGS="..."`.

prod-signals: require-zone ## Recompute production signals from warehouse bars
	$(call prod_ssh,cd $(PROD_DIR) && $(PROD_COMPOSE) exec -T backend python -m quantlab.signals.materialize)

prod-restart: require-zone ## Restart the production stack (systemd unit, survives reboot)
	$(call prod_ssh,sudo systemctl restart quantlab && sleep 5 && systemctl is-active quantlab)

prod-rollback: require-zone ## Roll production back to the previous image tags
	$(call prod_ssh,cd $(PROD_DIR) && sudo cp .env.images.prev .env.images && sudo systemctl restart quantlab)
	@echo "rolled back; check with 'make prod-ps'"

.PHONY: require-zone prod-ssh prod-ps prod-logs prod-ip prod-url prod-health prod-check \
	prod-signals prod-restart prod-rollback
