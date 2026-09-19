# Research: Dockerized Signal Viewer on Synthetic Data

**Feature**: `002-signal-viewer-demo` | **Date**: 2026-09-19

All decisions below resolve the Technical Context section of plan.md. No open questions
remain.

## R1 — Container orchestration behind the Makefile

- **Decision**: Docker Compose v2 (`docker compose`), driven by root `Makefile` targets:
  `make up` (build + seed + start), `make down`, `make seed`, `make logs`, `make test`,
  `make smoke`.
- **Rationale**: The spec mandates "only Docker and make on the host" (FR-002). Compose is
  bundled with modern Docker Desktop/Engine, declaratively models the three services
  (seed one-shot → backend → frontend), supports healthchecks and dependency ordering
  (`depends_on: condition: service_completed_successfully`), and needs no extra tooling.
- **Alternatives considered**: Plain `docker run` scripts in the Makefile (rejected: manual
  networking/ordering, fragile); Kubernetes/minikube (rejected: massive overkill for a
  single-user local demo, violates YAGNI).

## R2 — Backend framework and typed contract mechanism

- **Decision**: FastAPI + Pydantic v2 + Uvicorn; `contracts/openapi.yaml` is the authored
  single source of truth; the FastAPI app is checked against it by a contract test, and
  the frontend client is generated with `openapi-typescript`.
- **Rationale**: Constitution V requires a versioned, schema-defined boundary typed on both
  sides. FastAPI emits OpenAPI natively from Pydantic models; an explicit authored
  `openapi.yaml` (compared in CI via contract test) prevents accidental contract drift,
  and `openapi-typescript` gives the frontend compile-time types with zero hand-mirroring.
- **Alternatives considered**: Flask + hand-written schemas (rejected: no native typing/
  OpenAPI); GraphQL (rejected: heavier, and a simple read-only REST surface needs no query
  language); letting FastAPI generate the only copy of the spec (rejected: no authored
  source of truth to diff against).

## R3 — Storage

- **Decision**: SQLite (Python stdlib `sqlite3`), file in a named Docker volume, schema
  created by an idempotent bootstrap at seed time.
- **Rationale**: Scale is ~9k bars and a few hundred signals for a single local user;
  SQLite is zero-dependency, file-copyable for debugging, and deterministic. Idempotent
  DDL + deterministic upserts make reseeding byte-identical (FR-003, FR-005).
- **Alternatives considered**: PostgreSQL in Compose (rejected: an extra container and
  driver for no benefit at this scale); Parquet/CSV files only (rejected: filtered,
  sorted, counted signal queries — FR-011 — are clumsy and slow without an index).

## R4 — Deterministic synthetic data generation

- **Decision**: NumPy `Generator(PCG64(seed))` with per-instrument derived seeds; regime
  switching between trending, mean-reverting (OU-like), and high-volatility GBM segments;
  fixed trading-day calendar (weekdays, no holidays) over a fixed date range ending at a
  pinned "as-of" date.
- **Rationale**: SC-002/FR-005 require byte-identical output across runs and machines —
  PCG64 is stable across NumPy versions, seeds are derived deterministically from the
  instrument symbol hash, and a pinned end date removes all wall-clock dependence (VI).
  Deliberately seeded regimes guarantee every starter rule fires (FR-004/SC-003): trending
  segments force SMA crossovers and breakouts, mean-reverting segments force RSI
  threshold crossings.
- **Alternatives considered**: Pure GBM (rejected: cannot guarantee all rules fire);
  recorded real data (rejected: would be real market data, violating the "clearly
  fictitious" requirement FR-006 and pulling licensing back into scope).

## R5 — Starter signal rules and indicator plugins

- **Decision**: Three rules, each a versioned plugin in the registry (Constitution II):
  1. `sma-crossover` v1 — SMA(20) crosses SMA(50); direction = cross direction; scale-free
     inputs, emits on cross day.
  2. `rsi-threshold` v1 — RSI(14) exits overbought (>70→bearish) / oversold (<30→bullish).
  3. `breakout-20d` v1 — close exceeds the max high of the prior 20 sessions (bullish) or
     falls below min low (bearish).
- **Rationale**: Well-known rules with unambiguous reference definitions (testable per
  Constitution IV), disjoint trigger mechanisms (trend, oscillator, range) so the UI shows
  variety, and each maps cleanly onto the regimes from R4.
- **Alternatives considered**: MACD/Bollinger variants (deferred: more rules add demo cost
  without new proof; the registry makes adding them later trivial).

## R6 — Frontend stack

- **Decision**: React 18 + Vite + TypeScript; plain fetch via the generated
  `openapi-typescript` client; lightweight SVG price chart rendered from API bars (no
  charting library); Vitest + Testing Library for component tests.
- **Rationale**: Matches the constitution's TypeScript frontend mandate with minimal
  dependencies (constitution dependency-justification policy). A hand-rolled SVG chart is
  sufficient for marking signals on a price line and avoids a heavy charting dependency.
- **Alternatives considered**: Next.js (rejected: SSR unneeded for a local read-only SPA);
  a charting library such as Recharts (rejected: dependency weight not justified for one
  simple chart; revisit if chart needs grow).

## R7 — Service topology and startup ordering

- **Decision**: Three Compose services: `seed` (one-shot: waits for nothing, writes SQLite,
  exits 0), `backend` (`depends_on: seed completed_successfully`, healthcheck on
  `/api/v1/health`), `frontend` (static build served by nginx, `depends_on: backend
  service_healthy`). Ports: backend 8000 (internal), frontend 8080 on the host.
- **Rationale**: Guarantees FR-003 (seeding completes before the backend accepts traffic)
  through Compose-native ordering rather than sleeps or retry loops.
- **Alternatives considered**: Seeding inside the backend at startup (rejected: couples
  lifecycle, slows restarts, and complicates idempotency); an init container pattern via
  Compose profiles (equivalent, less readable).

## R8 — Determinism verification approach

- **Decision**: A test hashes the SQLite file (ordered dump of all tables) after seeding
  twice from clean state and asserts equality; SC-002 is proven in `quickstart.md` by the
  same hash comparison across two `make down && make up` cycles.
- **Rationale**: Byte-level comparison of an ordered dump is the strongest cheap proof of
  reproducibility (VI) and catches wall-clock or ordering leakage anywhere in the pipeline.
