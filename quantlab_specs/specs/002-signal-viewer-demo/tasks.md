---
description: "Task list for Dockerized Signal Viewer on Synthetic Data"
---

# Tasks: Dockerized Signal Viewer on Synthetic Data

**Input**: Design documents from `/specs/002-signal-viewer-demo/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml, quickstart.md

**Tests**: INCLUDED — Constitution Principle IV mandates TDD for all analytical and data code
(write tests first, watch them fail, then implement).

**Organization**: Tasks are grouped by user story to enable independent implementation and
testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- All file paths are relative to the repository root

## Path Conventions

Web app per plan.md: `backend/src/quantlab/`, `backend/tests/`, `frontend/src/`,
`frontend/tests/`, root-level `Makefile` and `docker-compose.yml`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Create directory structure per plan.md: `backend/src/quantlab/{synthetic,indicators,signals,storage,api}/`, `backend/tests/{unit,contract,lookahead}/`, `frontend/src/{api,components,pages}/`, `frontend/tests/`, `scripts/`
- [x] T002 Create `backend/pyproject.toml` (Python 3.12; deps: fastapi, pydantic v2, uvicorn, numpy; dev: pytest, ruff, pyyaml) and `backend/Dockerfile` (python:3.12-slim, install package, uvicorn entrypoint, SQLite file at `/data/quantlab.db` from env `QUANTLAB_DB_PATH`)
- [x] T003 [P] Create `frontend/package.json` (react 18, vite, typescript 5, openapi-typescript; dev: vitest, @testing-library/react, jsdom), `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/Dockerfile` (node:22 build stage → nginx serve stage), `frontend/nginx.conf` (serve SPA, reverse-proxy `/api/` to `backend:8000`)
- [x] T004 [P] Configure lint/format gates per constitution: ruff config in `backend/pyproject.toml` (lint + format check) and eslint + prettier config in `frontend/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 Implement `backend/src/quantlab/config.py`: fixed universe of ≥10 recognizably fake symbols (e.g. `ZZTRND`, `ZZMEAN`, `ZZVOLT` — MUST match `[A-Z]{2,8}`, currency fixed `USD`, regime_profile in `trending|mean_reverting|volatile|mixed`); pinned as-of end date; weekday-only calendar covering ≥3 years; base seed constant; per-instrument seed derived deterministically from the symbol hash (no wall-clock anywhere)
- [x] T006 Implement `backend/src/quantlab/storage/db.py`: connect + idempotent bootstrap DDL for `instruments`, `price_bars`, `signal_rules`, `signals` per data-model.md — `price_bars` PRIMARY KEY `(symbol, date)` with CHECK constraints `high >= max(open, close)`, `low <= min(open, close)`, `low > 0`, `close > 0`, `volume >= 0`; `signals` UNIQUE `(symbol, date, rule_name, rule_version, parameters)` with CHECK `data_window_end <= date`; `signal_rules` PRIMARY KEY `(rule_name, rule_version, parameters)`; deterministic upserts keyed on natural keys; ordered full-dump hash helper for determinism verification
- [x] T007 Implement plugin registries `backend/src/quantlab/indicators/registry.py` and `backend/src/quantlab/signals/registry.py` per Constitution II: decorator-based registration declaring name, version, input schema, output schema, parameters, and scale class (`scale_free` | `price_scaled`); runtime discovery; adding a plugin MUST NOT require changes to registry or engine code
- [x] T008 [P] Implement structured JSON logging in `backend/src/quantlab/logging.py` for seed and API paths (records symbols processed, failures, timings per Constitution VI)
- [x] T009 Implement FastAPI app skeleton `backend/src/quantlab/api/app.py` with `GET /api/v1/health` returning `{status: "ok", seeded: bool, signal_count: int}` per `contracts/openapi.yaml`; DB path from `QUANTLAB_DB_PATH` env var
- [x] T010 Scaffold frontend app `frontend/src/main.tsx` + `frontend/index.html` (placeholder page) and add `npm run codegen` script running openapi-typescript against `specs/002-signal-viewer-demo/contracts/openapi.yaml` into `frontend/src/api/schema.d.ts`

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - One-Command Dockerized Environment (Priority: P1) 🎯 MVP

**Goal**: A single `make up` builds and starts seed → backend → frontend in Docker; only
Docker and make required on the host; `make down` tears down cleanly.

**Independent Test**: On a clean checkout, `make up` brings all services up healthy and the
UI loads at `http://localhost:8080`; `make down` removes everything and a second `make up`
reproduces a clean environment (spec US1 acceptance scenarios 1–2; full seed determinism is
verified in US2/Polish).

### Tests for User Story 1

> Write FIRST, ensure they FAIL before implementation (stack does not exist yet).

- [x] T011 [US1] Write `scripts/smoke.sh`: fails fast if Docker is unavailable; waits for backend healthcheck; asserts `GET /api/v1/health` returns `status: "ok"`; asserts `http://localhost:8080` returns HTTP 200. Run it now and confirm it FAILS (no stack running)

### Implementation for User Story 1

- [x] T012 [US1] Create root `Makefile` with targets: `up` (preflight: verify `docker` daemon reachable and host ports 8000/8080 free, exit non-zero with an actionable message naming the problem if not; then `docker compose up --build -d`), `down` (compose down + volume removal for clean reseed), `build`, `seed`, `logs`, `test`, `smoke`, `dump-hash` (stub printing TODO until T036)
- [x] T013 [US1] Create `docker-compose.yml`: service `seed` (one-shot, runs `python -m quantlab.seed`, exits 0); service `backend` (`depends_on: seed: condition: service_completed_successfully`, healthcheck on `/api/v1/health`, internal port 8000); service `frontend` (nginx, `depends_on: backend: condition: service_healthy`, host port 8080); named volume `quantlab-data` mounted at `/data` in `seed` and `backend`
- [x] T014 [US1] Implement minimal `backend/src/quantlab/seed.py` entrypoint: delete any existing DB file (interrupted seeds never leave partial state — spec edge case), run storage bootstrap DDL, log completion, exit 0. Data generation and signal computation are added in US2 (T026)
- [x] T015 [US1] Verify end-to-end per spec US1 scenarios: `make up` from clean checkout → all services healthy, UI loads; `make down` → containers stopped/removed; second `make up` → clean re-seeded environment; `make smoke` passes

**Checkpoint**: User Story 1 fully functional — anyone with Docker + make can run the stack

---

## Phase 4: User Story 2 - Synthetic Market Data with Computed Signals (Priority: P2)

**Goal**: Deterministic synthetic OHLCV dataset (≥10 fictitious instruments × ≥3 years
daily, varied regimes) seeded automatically; ≥3 versioned signal-rule plugins computed at
seed time and stored with full provenance; signals and prices queryable via the typed API.

**Independent Test**: Without the UI — `make seed` twice from clean state produces a
byte-identical ordered DB dump; `curl` the signals API and confirm every stored signal
carries instrument, date, type, direction, trigger values and re-derives from the price
history (spec US2 acceptance scenarios 1–3; SC-002, SC-003, SC-005).

### Tests for User Story 2

> Write FIRST, ensure they FAIL before implementation.

- [x] T016 [P] [US2] `backend/tests/unit/test_synthetic_determinism.py`: generate the full dataset twice from clean state → byte-identical bars; double-seed the DB → identical ordered dump hash (uses helper from T006); assert no wall-clock dependence (pinned as-of date from config)
- [x] T017 [P] [US2] `backend/tests/unit/test_indicators.py`: SMA(20), SMA(50), RSI(14) (Wilder smoothing), rolling-20 max high / min low against independently computed reference values; boundary cases: insufficient history → no value/NaN with warning, flat series, gaps/nulls
- [x] T018 [P] [US2] `backend/tests/unit/test_signal_rules.py`: each rule fires on crafted series with known expected signal dates, directions, and trigger values — `sma-crossover` (SMA(20) crosses SMA(50), direction = cross direction), `rsi-threshold` (RSI(14) exits >70 → bearish, <30 → bullish), `breakout-20d` (close > max high of prior 20 sessions → bullish; close < min low → bearish); series shorter than lookback emits zero signals (expected behavior, not error)
- [x] T019 [P] [US2] `backend/tests/lookahead/test_lookahead_sweep.py`: recompute every rule on truncated history at each date T; assert emitted signals exactly match the full-history run restricted to `date <= T` and every signal has `data_window_end <= T` (Constitution VII)
- [x] T020 [P] [US2] `backend/tests/unit/test_signal_rederivation.py`: recompute all rules from stored `price_bars` and assert the result equals the stored `signals` set exactly — instrument, date, rule, direction, trigger values (SC-005)
- [x] T021 [P] [US2] `backend/tests/contract/test_api_contract.py`: validate responses of `GET /api/v1/health`, `GET /api/v1/instruments`, `GET /api/v1/instruments/{symbol}/prices`, `GET /api/v1/signals` against `contracts/openapi.yaml` (load via pyyaml); assert signal filters (instrument, signal_type, direction, start_date/end_date), sort (`date_asc|date_desc`), `total` reflects pre-pagination filtered count; 404 unknown symbol; 400 when start_date > end_date

### Implementation for User Story 2

- [x] T022 [US2] Implement `backend/src/quantlab/synthetic/generator.py`: NumPy `Generator(PCG64(seed))` with per-instrument seeds from config; regime switching between trending, mean-reverting (OU-like), and high-volatility GBM segments so every starter rule fires somewhere; OHLCV + volume construction satisfying the `price_bars` CHECK invariants; fake-symbol denylist guard (FR-006)
- [x] T023 [US2] Implement indicator plugins `backend/src/quantlab/indicators/sma.py`, `rsi.py`, `rolling.py`: SMA(n), RSI(14) Wilder, rolling max high / min low(20); each registered via the T007 registry with name, version, parameters, and scale class
- [x] T024 [US2] Implement signal rule plugins `backend/src/quantlab/signals/rules.py`: `sma-crossover` v1, `rsi-threshold` v1, `breakout-20d` v1 with the exact semantics from T018; each declares lookback_days and direction semantics; each uses only bars with `date <= T`
- [x] T025 [US2] Implement signal engine `backend/src/quantlab/signals/engine.py`: iterate instruments × registered rules in deterministic order (symbol, date, rule), skip emission until `lookback_days` of history, emit signals with `trigger_values` (canonical JSON) and `data_window_end`
- [x] T026 [US2] Extend `backend/src/quantlab/seed.py`: generate universe → persist `instruments` and `price_bars` FIRST (raw before transformation, Constitution III) → snapshot registered rules into `signal_rules` → run engine → persist `signals`; structured logs of symbols processed and signal counts
- [x] T027 [US2] Implement API routes `backend/src/quantlab/api/routes.py` + Pydantic response models mirroring `contracts/openapi.yaml`: `GET /api/v1/instruments`, `GET /api/v1/instruments/{symbol}/prices` (optional start_date/end_date, ascending), `GET /api/v1/signals` (filters instrument/signal_type/direction/start_date/end_date, sort date_asc|date_desc, limit ≤1000 default 200, offset, `total` = pre-pagination filtered count); thin handlers only — all queries via storage library; error responses per contract `Error` schema

**Checkpoint**: US2 independently verifiable — deterministic dataset + signals queryable via
API, no UI needed

---

## Phase 5: User Story 3 - Signal Viewer UI (Priority: P3)

**Goal**: Read-only web UI listing ALL signals with instrument, date, type, direction,
trigger values and total count; filter by instrument/type/direction/date range; sort by
date; select a signal to see it marked on the instrument's price history.

**Independent Test**: Against the seeded backend — UI count matches `GET /signals` total
exactly, every filter combination's count matches the equivalent API query, selecting a
signal shows the price chart with the signal marked (spec US3 acceptance scenarios; SC-004).

### Tests for User Story 3

> Write FIRST, ensure they FAIL before implementation. Mocked API client only — the
> frontend computes nothing (Constitution V).

- [x] T028 [P] [US3] `frontend/tests/SignalTable.test.tsx`: renders one row per signal showing symbol, date, rule name, direction, trigger values; displays the total count from the API response
- [x] T029 [P] [US3] `frontend/tests/SignalFilters.test.tsx`: instrument/type/direction/date-range filters and date sort issue the corresponding API query; displayed count reflects the filtered total; filters matching nothing render the explicit empty state
- [x] T030 [P] [US3] `frontend/tests/StatusStates.test.tsx`: loading, empty-results, and backend-unavailable states are visually distinct (backend error MUST NOT look like an empty list)

### Implementation for User Story 3

- [x] T031 [US3] Implement `frontend/src/api/client.ts`: typed fetch wrapper built on the generated `schema.d.ts` types, base URL `/api/v1`; surfaces network/HTTP errors distinctly from empty results
- [x] T032 [US3] Implement `frontend/src/components/SignalTable.tsx` and `frontend/src/components/SignalFilters.tsx` per FR-010/FR-011 (list with all fields + total count; filters for instrument, signal type, direction, date range; sort by date)
- [x] T033 [US3] Implement `frontend/src/components/PriceChart.tsx`: lightweight SVG close-price line for one instrument with the selected signal marked at its date (no charting library, per research R6)
- [x] T034 [US3] Implement `frontend/src/pages/SignalsPage.tsx`: composes filters + table + chart; selecting a row fetches that instrument's prices and shows the chart with the signal marker; wires the three status states from T030 (FR-012, FR-013)

**Checkpoint**: All three user stories independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Full-stack validation and documentation

- [x] T035 Extend `scripts/smoke.sh` and the `Makefile` `smoke` target: additionally assert health returns `seeded: true` and `signal_count > 0` (full SC-001 demo check)
- [x] T036 [P] Implement `Makefile` `dump-hash` target: dumps all tables in fixed order from the `quantlab-data` volume and prints a SHA-256 hash (used by quickstart Scenario 2)
- [x] T037 [P] Write root `README.md`: prerequisites (Docker + make only), `make up` / `make down` / `make smoke` / `make test`, UI URL, and a note that all data is synthetic/fictitious
- [x] T038 Run every `quickstart.md` scenario end-to-end (Scenarios 1–6) and fix any discrepancies; confirm `make test` runs backend unit + contract + look-ahead suites and frontend Vitest suite inside containers and all pass

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup (T001–T004) - BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational (needs app skeleton T009, scaffold T010)
- **US2 (Phase 4)**: Depends on Foundational (storage T006, registries T007, config T005) and on US1's seed entrypoint T014 and compose wiring T013; does NOT depend on US3
- **US3 (Phase 5)**: Depends on Foundational (client codegen T010) and US2's API routes T027 (contract + live backend for verification)
- **Polish (Phase 6)**: Depends on all three stories

### Within Each User Story

- Tests MUST be written and FAIL before implementation (Constitution IV)
- Libraries (generator, indicators, rules, engine) before the seed entrypoint and API routes
- Components before the page that composes them
- Story checkpoint passed before moving to the next priority

### Parallel Opportunities

- Setup: T003, T004 in parallel (after T002 for T003's repo layout? — no: T003/T004 touch only `frontend/` and config files, parallel with T002)
- Foundational: T008 parallel with T005–T007; T010 parallel with T005–T009 once T001–T003 land
- US2 tests: T016–T021 all [P] — six test files, zero shared files
- US2 implementation: T022 (synthetic), T023 (indicators) in parallel; T024 after T023; T025 after T024; T026 after T022+T025; T027 parallel with T022–T026 (depends only on T006/T009)
- US3 tests: T028–T030 all [P]; components T032–T033 [P] after T031

---

## Parallel Example: User Story 2

```bash
# Launch all US2 test tasks together (all different files):
Task: "test_synthetic_determinism.py"
Task: "test_indicators.py"
Task: "test_signal_rules.py"
Task: "test_lookahead_sweep.py"
Task: "test_signal_rederivation.py"
Task: "test_api_contract.py"

# Then launch independent libraries together:
Task: "synthetic/generator.py"
Task: "indicators (sma/rsi/rolling)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1 → `make up` works end-to-end
4. **STOP and VALIDATE**: clean-checkout `make up` → healthy stack, UI loads
5. Demo the skeleton if ready

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. US1 → reproducible Docker stack (MVP!)
3. US2 → deterministic data + signals queryable via API (demo-able headless)
4. US3 → full signal viewer UI
5. Polish → quickstart scenarios all green

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [US#] label maps each task to its user story for traceability
- TDD is mandatory for analytical/data code (Constitution IV): tests first, watch them fail
- Constitution review gates: plugin contract conformance (scale class on every indicator),
  raw-before-derived persistence, no look-ahead (`data_window_end <= date`), no analytics in
  the frontend
- Commit after each task or logical group
