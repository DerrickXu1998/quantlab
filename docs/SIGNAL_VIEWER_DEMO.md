# QuantLab — Dockerized Signal Viewer on Synthetic Data

A one-command demo stack: a deterministic, fully synthetic market dataset is generated and
seeded into SQLite, trading signals are computed by versioned rule plugins, and a read-only
web UI lets you browse and filter every signal with its price-history context.

> **All data in this project is synthetic and fictitious.** The instruments (e.g. `ZZTRND`,
> `ZZMEAN`), prices, and signals are generated locally by a seeded random number generator.
> Nothing here is real market data or investment advice.

## Prerequisites

- Docker (with Compose v2)
- GNU Make

Nothing else is required on the host — no Python, Node, or database installs.

## Quick start

```bash
make up       # build images, run the one-shot seed, start backend + frontend
make smoke    # wait for health, assert the DB is seeded and signals exist
```

Run these from the repository root. `make up` is safe to re-run — a port that one
of its own containers already publishes is not treated as a conflict.

Then open the UI at **http://localhost:8080**. The API is served at
`http://localhost:8000/api/v1` (see `quantlab_specs/specs/006-warehouse-experiments/contracts/openapi.yaml`).

## Make targets

| Target          | What it does                                                              |
| --------------- | ------------------------------------------------------------------------- |
| `make up`       | Preflight checks (Docker reachable, ports 8000/8080 free of foreign processes), then build + start seed → backend → frontend; waits for the backend healthcheck. Idempotent |
| `make down`     | Stop and remove all containers and the `quantlab-data` volume             |
| `make smoke`    | End-to-end check: backend healthy, DB seeded, every starter rule fired, UI returns 200 |
| `make test`     | Run backend pytest (unit + contract + look-ahead) and frontend vitest inside containers |
| `make seed`     | Re-run the one-shot seed (deletes and regenerates the SQLite DB)          |
| `make logs`     | Follow service logs                                                       |
| `make docker-shell` | Interactive shell inside a running container — `bash` in **backend** by default; `make docker-shell SERVICE=frontend` for the nginx container. Starts the stack first if it is not up. `make shell` is an alias |
| `make build`    | Build the backend and frontend images                                     |
| `make dump-hash`| SHA-256 of the ordered dump of every table — two fresh `make up` runs produce the identical hash |
| `make gen-api`  | Regenerate the frontend's typed API client from the OpenAPI contract      |
| `make check-contract` | Fail if `backend/contracts/openapi.yaml` has drifted from the authored spec (runs as part of `make test`) |
| `make sync-contract`  | Refresh `backend/contracts/openapi.yaml` from the authored spec           |

## What runs

- **seed** — one-shot job: generates ≥ 3 years of weekday OHLCV bars for 12 fictitious
  instruments across trending / mean-reverting / volatile regimes, then computes signals
  from three starter rule plugins (`sma-crossover`, `rsi-threshold`, `breakout-20d`).
  Generation is fully deterministic: no wall-clock, per-instrument seeds derived from the
  symbol, so a fresh `make up` always produces a byte-identical database.
- **backend** — FastAPI service (`:8000`) exposing instruments, price bars, and signals
  with filtering, sorting, and pagination, plus a runtime model catalog and an
  experiment-run endpoint. The catalog is assembled from the plugin registry on every
  request, so registering a rule is enough for it to appear and be runnable — no
  frontend change. A run executes a chosen model with chosen parameters over a chosen
  slice of instruments and dates, and is stored with full provenance (model name and
  version, effective parameters, selection, window) so it is reproducible. Experiment
  output lives in its own tables and never enters the seeded signal set.
- **frontend** — React SPA behind nginx (`:8080`), arranged as a dockable workspace: the
  filters, signal list, and price chart are panels that can be dragged to split, resized,
  tabbed together, floated, closed and reopened. The layout is saved per browser and can be
  reset to the default at any time; an unreadable or outdated saved layout falls back to the
  default rather than failing. The chart is an interactive candlestick view (OHLC + volume,
  pan/zoom, hover readout) with the selected signal marked. Workbench panels add a model
  catalog, a run configuration form generated from each model's declared parameter
  metadata, and a results view that always reports coverage alongside the signal count.
  Supports light and dark mode, defaulting to the OS preference. Below tablet width the panels stack instead of docking.
  `/api/` is reverse-proxied to the backend.

## Validation

`quantlab_specs/specs/005-signal-research-workbench/quickstart.md` covers the workbench;
`quantlab_specs/specs/002-signal-viewer-demo/quickstart.md` contains six runnable scenarios (clean setup,
cross-run determinism via `make dump-hash`, dataset coverage, UI/API count consistency,
re-derivation and look-ahead test suites, and backend-down UI behavior). `make test` runs
the full backend and frontend suites inside Docker containers.
