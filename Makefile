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

# Symbols for `make ingest` (override: make ingest SYMBOLS="VOD.LON BP.LON")
SYMBOLS ?= AAPL.US MSFT.US HSBA.LON
START   ?= 2015-01-01
END     ?=
PROVIDERS ?= yahoo stooq

.PHONY: help up down build seed logs shell docker-shell test smoke check-warehouse hash dump-hash gen-api \
	check-contract sync-contract migrate ingest seed-warehouse ingest-macro map-identifiers coverage signals store-test \
	replay-publish db-shell ch-shell destroy

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

seed-warehouse: ## Seed the warehouse with deterministic synthetic bars (no network)
	$(COMPOSE) run --rm ingest seed-synthetic

# BoE macro history (FX fixings, Bank Rate, gilt yield, M4 growth) as
# pseudo-instrument bars. Long default start: sterling history is the point.
MACRO_START ?= 2010-01-01

ingest-macro: ## Load BoE macro series as pseudo-instrument bars (override MACRO_START/END)
	$(COMPOSE) run --rm ingest ingest-macro \
		--start $(MACRO_START) $(if $(END),--end $(END),)

# OpenFIGI identifier mappings: keyless at 25 req/min x 10 jobs, so the full
# warehouse takes a few minutes. Resumable by default (--only-missing).
MAP_LIMIT ?=
MAP_ALL ?=

map-identifiers: ## Map warehouse instruments to OpenFIGI identifiers (override MAP_LIMIT/MAP_ALL=--all)
	$(COMPOSE) run --rm ingest map-identifiers \
		$(if $(MAP_LIMIT),--limit $(MAP_LIMIT),) $(MAP_ALL)

coverage: ## What is in the store, where it came from, and how well it compresses
	$(COMPOSE) run --rm ingest coverage

signals: ## Recompute signals from warehouse bars into the catalog
	$(COMPOSE) run --rm backend python -m quantlab.signals.materialize

# Kafka brokers for `make replay-publish` (in-compose address; from the host use localhost:19092)
KAFKA_BROKERS ?= redpanda:9092
TOPIC ?=
PACE_MS ?=

replay-publish: ## Publish warehouse bars to the Kafka replay topic (needs --profile streaming up)
	$(COMPOSE) run --rm \
		-e QUANTLAB_KAFKA_BROKERS=$(KAFKA_BROKERS) \
		$(if $(TOPIC),-e QUANTLAB_KAFKA_TOPIC=$(TOPIC),) \
		ingest replay-publish \
		--symbols $(SYMBOLS) --start $(START) $(if $(END),--end $(END),) \
		$(if $(PACE_MS),--pace-ms $(PACE_MS),)

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

prod-health: require-zone ## Hit the public health endpoint
	@curl -fsS "http://$$($(MAKE) -s prod-ip)/api/v1/health"; echo

prod-check: require-zone ## Assert production serves the warehouse, not the synthetic fallback
	@BACKEND_URL="http://$$($(MAKE) -s prod-ip)" bash scripts/check-warehouse.sh

prod-coverage: require-zone ## What production has ingested, and how well it compresses
	$(call prod_ssh,cd $(PROD_DIR) && $(PROD_COMPOSE) --profile ingest run --rm ingest coverage)

# Ingest reaches the network and is never part of a deploy, so it is run by hand.
# Overrides match the local targets: make prod-ingest SYMBOLS="AAPL.US" START=2015-01-01
prod-ingest: require-zone ## Ingest history on the production VM (override SYMBOLS/START/END/PROVIDERS)
	$(call prod_ssh,cd $(PROD_DIR) && $(PROD_COMPOSE) --profile ingest run --rm ingest \
		ingest $(SYMBOLS) --start $(START) $(if $(END),--end $(END),) --providers $(PROVIDERS))

prod-signals: require-zone ## Recompute production signals from warehouse bars
	$(call prod_ssh,cd $(PROD_DIR) && $(PROD_COMPOSE) exec -T backend python -m quantlab.signals.materialize)

prod-restart: require-zone ## Restart the production stack (systemd unit, survives reboot)
	$(call prod_ssh,sudo systemctl restart quantlab && sleep 5 && systemctl is-active quantlab)

prod-rollback: require-zone ## Roll production back to the previous image tags
	$(call prod_ssh,cd $(PROD_DIR) && sudo cp .env.images.prev .env.images && sudo systemctl restart quantlab)
	@echo "rolled back; check with 'make prod-ps'"

.PHONY: require-zone prod-ssh prod-ps prod-logs prod-ip prod-health prod-check \
	prod-coverage prod-ingest prod-signals prod-restart prod-rollback
