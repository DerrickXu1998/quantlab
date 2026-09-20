# Architecture

**Structure verified against the tree at commit `44d4181`. Warehouse figures measured against
the running stack on 2026-09-20 ~11:45 UTC.** Where the code and the older docs disagreed, the
code won.

This document has two jobs: describe the hierarchy of the application, and say which data
sources are ingested. Treat those differently. **The hierarchy is stable; the ingest figures are
a photograph of live state and go stale quickly** — an earlier draft recorded a warehouse
holding only synthetic bars and was overtaken by a real ingest within the hour. §7 carries the
numbers, and [§7d](#7d-refresh-these-numbers-yourself) carries the commands to re-derive them.
Prefer running those.

---

## 1. The hierarchy, top down

Four tiers. The rule that keeps them apart is constitutional, not stylistic:
`quantlab_specs/` holds specifications and contracts and **no code**; runnable code lives at the
repository root.

```
quantlab/
├── quantlab_specs/          TIER 0  specification workspace — no code, ever
│   ├── .specify/            Spec Kit toolchain + constitution
│   └── specs/               numbered features; contracts/openapi.yaml is authored here
│
├── src/quantlab/            TIER 1  the research library (installable, standalone)
│   ├── providers/           8 data source adapters
│   ├── universe/            3 universe list sources
│   ├── indicators/          per-symbol technical indicators
│   ├── derived/             cross-sectional / external-source features
│   ├── store/               the warehouse: migrations, ingest, readers, seeding
│   ├── engine.py            FeatureEngine — schedules features, enforces lag
│   ├── registry.py          plugin registries (providers, universes, indicators, derived)
│   ├── streaming.py         replay publisher → Kafka
│   └── cli.py               `quantlab` — 12 subcommands
│
├── backend/src/quantlab/    TIER 2  the demo application (a *separate* package)
│   ├── api/                 FastAPI: app, routes, Pydantic schemas
│   ├── storage/             two seams: StorageBackend + ExperimentStore
│   ├── signals/             signal rule registry + engine (3 builtin rules)
│   ├── research/            runner, performance, typed errors
│   ├── replay/              deterministic replay engine + portfolio simulator
│   ├── streaming/           Kafka consumer → live replay
│   └── synthetic/           generator for the zero-setup demo dataset
│
└── frontend/src/            TIER 3  the UI
    ├── chrome/              AppShell + hash router (6 destinations)
    ├── quantlab/            terminal surface: views, panels, charts, chrome, feed
    ├── workspace/           Dockview docking workspace (Signal Viewer)
    ├── workbench/           model catalog, run config, results
    └── api/                 generated types + typed client
```

### Why two packages both called `quantlab`

`src/quantlab` and `backend/src/quantlab` are **different distributions that share a name**.
Both declare `name = "quantlab"`, version `0.1.0`. They are never installed into the same
environment: each Dockerfile has its own build context, copies its own `src/`, and runs
`pip install .` — so an image contains exactly one of them.

Only three names collide, and **none of them is shared code**:

| Name | `src/quantlab` (library) | `backend/src/quantlab` (app) |
|---|---|---|
| `__init__.py` | 91 lines — the public API surface | empty — a bare namespace |
| `config.py` | 167 lines | 121 lines, unrelated |
| `indicators/` | 81 indicators over 5 modules, pandas-based | 4 functions in one file, numpy only |

The two `indicators` packages share **zero files**. `momentum.py`, `trend.py`,
`volatility.py`, `volume.py` and `statistics.py` exist only in the library; `registry.py` and
`builtins.py` only in the backend. The backend's four (`sma`, `rsi`, `rolling_max`,
`rolling_min`) are a deliberate minimal reimplementation so the API image never needs pandas —
the backend has **zero** pandas imports, against the library's pandas-and-pyarrow core.

That split is the whole point. The library fetches, ingests and computes features; the backend
reads the warehouse and serves it. The API image carries no provider stack, no pandas and no
yfinance.

This is load-bearing before you edit either: `from quantlab.indicators import ...` resolves to
two entirely different implementations depending on which image you are in, and neither package
can import the other.

---

## 2. Runtime topology

Eight compose services across four profiles. The base stack is four containers; everything else
is opt-in, which is what keeps the zero-setup demo honest.

| Service | Profile | Image | Ports | Role |
|---|---|---|---|---|
| `postgres` | base | `postgres:17-alpine` | 5432 | catalog: instruments, signals, provenance, experiments |
| `clickhouse` | base | `clickhouse-server:24.8-alpine` | 8123, 9000 | `price_bars` — the bar store |
| `backend` | base | `./backend` | 8000 | FastAPI |
| `frontend` | base | `./frontend` | 8080 | nginx over the built bundle |
| `migrate` | base | `quantlab-ingest` | — | applies migrations, then exits |
| `ingest` | `ingest` | `quantlab-ingest` | — | the library + provider stack |
| `seed` | `demo` | `./backend` | — | writes the synthetic SQLite demo |
| `redpanda` | `streaming` | `redpanda:v24.3.18` | 19092 | Kafka API for streamed replay |

Volumes: `quantlab-chdata`, `quantlab-pgdata`, `quantlab-cache`, `quantlab-data`, `quantlab-kafka`.

The ingest image carries pandas, requests and yfinance. The backend image deliberately does
**not** — it reads the warehouse, it never fetches from a provider.

### Dev vs container

Vite proxies `/api` → `localhost:8000`, so `npm run dev` on 5173 runs against the containerised
backend. Port 8080 serves the built bundle and can lag behind the source.

---

## 3. The two datasets, and the seam that hides them

Every API handler is dataset-agnostic. Which store answers is decided **once at startup** by
whether `QUANTLAB_DB_URL` and `QUANTLAB_CH_URL` are set:

```
                     ┌─────────────────────────────┐
  QUANTLAB_DB_URL +  │                             │
  QUANTLAB_CH_URL ──▶│  WarehouseBackend           │  ClickHouse bars + Postgres catalog
  both set           │                             │
                     └─────────────────────────────┘
                     ┌─────────────────────────────┐
  neither set ──────▶│  SqliteBackend              │  one synthetic file, no services
                     └─────────────────────────────┘
```

Two **separate** protocols, because on the warehouse they are different database systems:

- **`StorageBackend`** — *which dataset am I reading?* `health`, `list_instruments`, `get_prices`,
  `list_signals`, `load_bars_for`, `earliest_bar_dates`, `corporate_actions`, `instrument_ids`,
  `ingest_run_ids`.
- **`ExperimentStore`** — *where do my experiments live?* `save_run`, `get_run`, `get_run_signals`,
  `list_runs`, `set_run_name`, `delete_run`.

Experiment output is written to `experiment_runs` / `experiment_signals`, never to the `signals`
table. That separation is deliberate: experiment rows would insert cleanly into the materialised
signal cache and then surface in the Signal Viewer as if they were curated output.

The demo path is guarded by test: `backend/tests/unit/test_demo_fallback.py` makes `psycopg` and
`clickhouse_connect` unimportable and asserts the app still boots and runs a full experiment.

---

## 4. Request flow

```
  frontend ── fetch /api/v1/* ──▶ FastAPI routes  (thin adapters, zero analytics)
                                        │
                        ┌───────────────┼────────────────┐
                        ▼               ▼                ▼
                 StorageBackend   ExperimentStore   signals.registry
                        │               │                │
              ClickHouse/Postgres   experiment_*     3 builtin rules
                 or SQLite            tables
                        │
                        └──▶ research.runner ──▶ research.performance
                             (warm-up load,        (trades, equity,
                              signal compute)       Sharpe, drawdown)
```

**Fourteen operations** on `/api/v1`, contract version `0.5.0`:

`GET /health` · `GET /instruments` · `GET /instruments/{symbol}/prices` · `GET /signals` ·
`GET /models` · `POST /runs` · `GET /runs` · `GET /runs/{id}` · `PATCH /runs/{id}` ·
`DELETE /runs/{id}` · `GET /runs/{id}/performance` · `GET /runs/{id}/replay/stream` ·
`GET /runs/{id}/replay/summary` · `GET /replay/live/stream`

The contract is authored once at
`quantlab_specs/specs/006-warehouse-experiments/contracts/openapi.yaml`. `backend/contracts/`
holds a copy only because the Docker build context cannot reach outside `backend/`;
`make check-contract` fails the build if they drift, and `npm run gen:api` generates
`frontend/src/api/schema.d.ts` from the same file. **An endpoint invented in the UI will not
typecheck.**

### Where computation is allowed to live

All of it is in the backend. The frontend renders and does not reduce — Sharpe, drawdown, win
rate, equity curves and trade pairing are all computed in `research/performance.py` and served.
This is Constitution V, and it is a merge gate, not a preference.

---

## 5. Two research paths: batch and streamed

```
BATCH     POST /runs ──▶ runner (loads start−lookback for warm-up) ──▶ signals
                     ──▶ GET /runs/{id}/performance ──▶ trades, equity, metrics
                     ──▶ GET /runs/{id}/replay/stream ──▶ SSE re-read of a stored run

STREAMED  clickhouse ──▶ quantlab replay-publish ──▶ redpanda ──▶ GET /replay/live/stream
           (warehouse)    (ingest image)          (quantlab.bars)  (SSE)
```

Both emit the same event types — `bar`, `signal`, `fill`, `equity`, `summary` — and share
`replay.engine.summary_event`.

**The invariant is `live == batch`.** Signal rules are causal, so recomputing on a growing window
yields the signals a batch run stores. `backend/tests/lookahead/` proves `compute` on truncated
history is identical, and the unit suite asserts the reconciliation directly. Bars before `start`
are warm-up: they feed lookback and emit nothing.

Without `QUANTLAB_KAFKA_BROKERS` the live endpoint answers a clean 503 and every other route is
unaffected; `kafka-python` is imported lazily so the API boots without a bus.

---

## 6. Frontend hierarchy

A hash router with **six flat destinations** — not react-router, because six flat routes and a
handful of handoff params do not justify the dependency or forcing every test into a
`MemoryRouter`.

```
main.tsx → ThemeProvider → App → SplashScreen (once) → AppShell
                                                          │
   ┌──────────┬───────────┬───────────┬─────────┬─────────┴──┬────────────┐
 overview   research   strategies    replay    market      execution
   │            │           │          │          │             │
 Overview   Signal      Strategy    Replay    Indicators   Execution
   View     Viewer       Lab         View        View         View
            (Dockview)                                     (simulated)
```

`#/` and `#/lab` are mapped forward as legacy aliases and rewritten to the canonical hash.

`research` is the original Dockview docking workspace — draggable, splittable, serialisable
panels, layout persisted under `quantlab-workspace-layout`. The other five are the terminal
surface under `src/quantlab/`, which scopes its near-black palette by redefining the same design
tokens on a `.quantlab` root rather than touching `<html>`, so the two coexist without either
theme leaking.

Charts are split by need: `lightweight-charts` for candles, hand-rendered DPR-aware canvas
(`charts/useCanvas2d.ts` + `draw.ts`) for equity curves, RSI, MACD and sparklines. Canvas cannot
resolve `hsl(var(--x))`, so `draw.ts` reads design tokens off the live element rather than
duplicating hex values.

---

## 7. Data sources: adapters vs. actually ingested

This is the part most likely to be misread, so it is stated twice.

### 7a. What is in the warehouse right now

**Snapshot taken 2026-09-20 ~11:45 UTC. This is live state and it moves — re-run the queries
in [§7d](#7d-refresh-these-numbers-yourself) rather than trusting the figures below.**
An earlier draft of this document recorded 26,075 rows from a single synthetic run and
concluded that no real data had ever been ingested. That was true when measured and wrong
forty minutes later.

| | |
|---|---|
| `price_bars` rows | **1,768,107** |
| Instruments with bars | **624** |
| Catalog instruments | 649 — 531 XNYS, 98 XLON, 20 unassigned |
| Date range | 2010-01-04 → 2026-09-18 |
| On disk | 40.7 MiB across 845 active parts — transient; re-measured at 497 parts minutes later as background merges ran |
| Materialised signals | 285,990 |
| Corporate actions | **0** |

Bars by source:

| Source | Rows | Instruments | Range |
|---|---:|---:|---|
| **`yahoo`** | 1,725,075 | 594 | 2010-01-04 → 2026-09-18 |
| `synthetic` | 26,075 | 25 | 2022-01-03 → 2025-12-31 |
| **`boe`** | 16,957 | 5 | 2010-01-04 → 2026-09-17 |

Currency split — USD 1,385,389 rows / 529 instruments, GBP 378,497 / 94, EUR 4,221 / 1. Both
target markets are populated with real listings (`AAPL.US`, `ABT.US`, `AAL.LON`, `ABF.LON`),
so the GBX → GBP normalisation path is exercised by real data rather than only by fixtures.

Ingest runs recorded in the catalog:

| Source | Status | Runs | Symbols OK | Rows |
|---|---|---:|---:|---:|
| `multi` (yahoo → stooq chain) | ok | 6 | 503 | 1,355,093 |
| `multi` | partial | 2 | 91 | 369,982 |
| `synthetic` | ok | 3 | 75 | 78,225 |
| `boe` | partial | 1 | 5 | 16,957 |
| `multi` | failed | 2 | 0 | 0 |
| `test` | running | 12 | 0 | 0 |

`multi` means the provider fallback chain `["yahoo", "stooq"]`; the `source` column on each bar
records which adapter actually answered, which is why ClickHouse attributes the rows to
`yahoo`.

**Two failures worth knowing.** Run 17 hit
`Code: 252. Too many partitions for single INSERT block` — a 2015→2026 backfill is ~130 monthly
partitions against ClickHouse's default cap of 100. That is **already fixed**:
`store/bars.py:107` `partition_chunks()` splits a payload into blocks of at most
`MAX_PARTITIONS_PER_INSERT` calendar months, which is why the later runs spanning 2010→2026
succeeded. Run 17 is a historical artefact, not an open bug. Run 39 failed with
`5 symbols returned no data` — a provider miss, not infrastructure.

**Still zero corporate actions.** `ingest_corporate_actions` is implemented and Yahoo is the
only free source of UK actions, but it has not been run. The consequence is that the
unadjusted-price warning — surfaced by `RunResults` and persisted on every experiment — has
never fired against real data. Splits in this history are currently invisible.

### 7b. Adapters that exist and are wired

Eight providers and three universe sources are registered and discoverable via
`quantlab sources`. Rate limits are enforced by a per-source token bucket whose daily caps
persist to disk across restarts.

The **Used?** column is the difference between "an adapter exists" and "rows are in the
warehouse because of it".

| Source | Adapter | Used? | Key? | Enforced limit | Gives you | Licence posture |
|---|---|---|---|---|---|---|
| **Stooq** | `providers/stooq.py` | fallback only | no | 120/min | Daily OHLCV, US + UK, 30+ yr | No published terms. Research use only; **not redistributable** |
| **Yahoo** | `providers/yahoo.py` | **yes — 1.73M rows** | no | 4/min | OHLCV + **corporate actions**, metadata | Unofficial endpoint; personal use only. Breaks periodically |
| **SEC EDGAR** | `providers/sec_edgar.py` | no | no | 540/min | US fundamentals (XBRL), Form 3/4/5 | **US public domain.** Requires contact User-Agent |
| **Companies House** | `providers/companies_house.py` | no | yes | 120/min (600/5min) | UK statutory accounts (iXBRL) | Crown copyright, normally OGL |
| **OpenFIGI** | `providers/openfigi.py` | no | optional | 25/min (→250 keyed) | Ticker ↔ FIGI ↔ ISIN ↔ SEDOL | Free, no stated usage limits |
| **BoE IADB** | `providers/boe.py` | **yes — 16,957 rows** | no | 60/min | GBP/USD, Bank Rate | Reusable with attribution |
| **FRED** | `providers/fred.py` | no | yes | 100/min | US macro series | Free key; some series carry third-party restrictions |
| **CSV** | `providers/csvfile.py` | no | no | — | Local files | Whatever the source carried |

Universe sources: `nasdaqtrader` (US listings), `lse` (LSE report file, supplied by path),
`static` (a bundled FTSE fallback list).

Signal rules registered in the backend: `sma-crossover@1.0.0` (lookback 51, scale-free),
`rsi-threshold@1.0.0` (16, scale-free), `breakout-20d@1.0.0` (21, price-scaled).

### 7d. Refresh these numbers yourself

Every figure in §7a came from these four commands. Run them instead of trusting the table —
the warehouse is live state, and a document is a photograph of it.

```bash
# Bars by source, with coverage and date range.
curl -s --user "$CH_USER:$CH_PASS" --data-binary "
  SELECT source, count() rows, uniqExact(instrument_id) instruments,
         min(toDate(ts)) from_date, max(toDate(ts)) to_date
  FROM quantlab.price_bars_current
  GROUP BY source ORDER BY rows DESC FORMAT PrettyCompact" http://localhost:8123/

# Physical footprint. A large parts count means merges are behind.
curl -s --user "$CH_USER:$CH_PASS" --data-binary "
  SELECT table, formatReadableSize(sum(bytes_on_disk)) disk, sum(rows) rows, count() parts
  FROM system.parts WHERE database='quantlab' AND active
  GROUP BY table FORMAT PrettyCompact" http://localhost:8123/

# Ingest provenance: what was attempted, what landed, what failed.
docker compose exec -T postgres psql -U quantlab -d quantlab -c "
  SELECT source, kind, status, count(*) runs, sum(symbols_ok) sym_ok, sum(rows_written) rows
  FROM ingest_runs GROUP BY 1,2,3 ORDER BY rows DESC NULLS LAST;"

# Catalog shape.
docker compose exec -T postgres psql -U quantlab -d quantlab -c "
  SELECT (SELECT count(*) FROM instruments)        AS instruments,
         (SELECT count(*) FROM signals)            AS signals,
         (SELECT count(*) FROM corporate_actions)  AS corporate_actions,
         (SELECT count(*) FROM universe_snapshots) AS snapshots;"
```

Two rules when reading the results:

- **Always query `price_bars_current`, never `price_bars`.** The view applies `FINAL`. The raw
  table is a `ReplacingMergeTree` whose dedup happens at merge time, so a re-ingested range read
  raw comes back multiplied.
- **`source` on a bar is the adapter that answered**, which is not the same as `ingest_runs.source`
  — the latter records the chain that was requested (`multi`), the former which link in it won.

### 7c. The licensing line that matters

Stooq and Yahoo are unofficial and carry **no redistribution rights**. They are fine for
development and internal research. Before anything is published or served to a third party, the
UK side must move to a licensed feed. Each adapter documents this at its definition site and is
swappable without core changes.

`docs/DATA_SOURCES.md` carries the full evaluation, including the eight commercial sources that
were assessed and rejected, and the UK/US asymmetry in what is free.

---

## 8. Correctness machinery

| Concern | Mechanism |
|---|---|
| Look-ahead | Every external feature declares a `lag` the engine enforces; `test_no_indicator_looks_ahead` recomputes on truncated history. `ichimoku` is the one documented exception |
| Point-in-time | Fundamentals stamped at filing date, never period end. `experiment_signals` has a CHECK constraint that `data_window_end <= date` |
| Warm-up | Runs load from `start − lookback`, report only in-window signals — otherwise the first ~51 days look silently empty |
| Re-ingest | `ReplacingMergeTree(run_id)`. **Reads must go through `price_bars_current`**; dedup happens at merge time, so a raw read of a re-ingested range comes back doubled |
| Currency | GBX → GBP at the adapter boundary. Mixing them is a 100× error, not a formatting choice |
| Reproducibility | Runs record effective parameters, `instrument_ids`, `ingest_run_ids` and dataset; `re_runnable` goes false when the recorded dataset is not the active one |
| Survivorship | Universe membership snapshotted append-only on every refresh. There is no free retroactive fix |
| Unadjusted prices | Corporate actions inside a window are **reported and persisted**, never silently applied |

---

## 9. Known gaps

1. **No corporate actions ingested** — 0 rows, so the unadjusted-price warning has never fired
   against real history. `ingest_corporate_actions` exists and Yahoo is the only free source of
   UK actions; it simply has not been run. Until it is, splits in this data are invisible and
   any signal sitting on an ex-date is suspect.
2. **`make test` fails in containers.** Compose sets `QUANTLAB_CH_URL` on the `backend` service,
   so `--no-deps` points the app at an absent ClickHouse and every data route 503s. Unset the two
   warehouse vars and the same container is green (**204 passed / 10 skipped**). The gate
   currently cannot distinguish a real regression from an absent warehouse.
3. **Ingest coverage is uneven.** Six of eight adapters have never written a row: SEC EDGAR,
   Companies House, OpenFIGI, FRED and CSV are wired and untested against the warehouse, and
   Stooq has only ever been a fallback behind Yahoo. The US/UK fundamentals halves of the
   platform are unexercised.
4. **No intraday.** The schema is ready (`ts` is `DateTime64`); free sources cap intraday history
   too short to model on. Adding a licensed minute feed is an adapter, not a migration.
5. **No backtester.** Feature generation and strategy simulation are kept separate deliberately.
   `research/performance.py` is a long-only, equal-weight, zero-cost mark-to-market — it ships
   its own `assumptions[]` in the payload and is explicitly not tradeable.

---

## 10. Test surface

| Suite | Count | Where measured |
|---|---|---|
| Root library (`tests/`) | 115 passed, 11 skipped | host venv |
| Backend (`backend/tests/`) | 203 passed, 11 skipped | host venv |
| Backend (`backend/tests/`) | 204 passed, 10 skipped | container, warehouse vars unset |
| Frontend (`frontend/tests/`) | 197 passed (20 files) | host |

The one-test difference between host and container is a Postgres-parameterised case that skips
when no catalog is reachable — the suite is designed so the demo path never requires a database.

Backend tests are split `unit/`, `contract/`, `lookahead/`. Contract tests drive their
assertions from the authored OpenAPI document rather than restating it, so the tests fail when
the document and the app drift apart.

---

## 11. Configuration

Read from the environment; **values live in `.env`, which is gitignored and must stay that way.**

`docker-compose.yml` substitutes rather than hardcodes: `${QUANTLAB_CH_URL:-clickhouse://…@clickhouse:8123/quantlab}`.
Unset, every service uses the local containers; set, they follow the override. Compose reads
`.env` automatically, so a value there redirects the whole stack.

**Set `QUANTLAB_DB_URL` and `QUANTLAB_CH_URL` together or not at all.** Setting only the
ClickHouse URL points the bar store at one environment while the catalog stays in another:
instruments resolve, every price query returns empty, and nothing errors. Setting neither is
worse in a different way — `select_backend()` falls back to the synthetic demo *silently* and
serves fictitious instruments and prices that look entirely real.

`make check-warehouse` (`scripts/check-warehouse.sh`) is the guard for both. It asserts the
dataset the API reports, that the catalog is populated, and that the first instrument actually
returns bars — which is the assertion that catches a split bar-store/catalog pair. Run it after
every deploy; `BACKEND_URL` and `EXPECT_DATASET` make it work against any environment.

| Variable | Effect |
|---|---|
| `QUANTLAB_DB_URL` | Postgres catalog. With `QUANTLAB_CH_URL`, selects the warehouse |
| `QUANTLAB_CH_URL` | ClickHouse bar store |
| `QUANTLAB_DB` / `QUANTLAB_DB_PATH` | SQLite demo path (default `/data/quantlab.db`) |
| `QUANTLAB_PG_POOL_MAX` | Catalog connections held per instance (default 5) |
| `QUANTLAB_CH_POOL_MAX` | Bar-store clients held per instance (default 5) |
| `QUANTLAB_POOL_TIMEOUT` | Seconds a request waits for a connection (default 10.0) |
| `QUANTLAB_KAFKA_BROKERS` | Live replay bus. Unset → live endpoint 503s, nothing else changes |
| `QUANTLAB_KAFKA_TOPIC` | Default `quantlab.bars` |
| `QUANTLAB_OFFLINE=1` | Any cache miss raises instead of hitting the network. The test suite runs under this |
| `QUANTLAB_PLUGIN_PATH` | Extra plugin directories |
| `OPENFIGI_API_KEY`, `FRED_API_KEY`, `COMPANIES_HOUSE_API_KEY` | Provider keys |

## Related documents

- `docs/DATA_SOURCES.md` — full source evaluation, including what was rejected and why
- `docs/STORAGE.md` — why ClickHouse and Postgres are split the way they are
- `docs/INDICATORS.md` — the indicator suite and scale classes
- `docs/SIGNAL_VIEWER_DEMO.md` — running the zero-setup demo
- `quantlab_specs/.specify/memory/constitution.md` — the rules the above enforce
