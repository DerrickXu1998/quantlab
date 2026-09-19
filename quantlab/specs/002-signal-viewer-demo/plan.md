# Implementation Plan: Dockerized Signal Viewer on Synthetic Data

**Branch**: `002-signal-viewer-demo` | **Date**: 2026-09-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-signal-viewer-demo/spec.md`

## Summary

Deliver an end-to-end runnable demo of the QuantLab vertical slice: a Makefile-driven
Docker Compose stack that (1) starts a Python FastAPI backend and a TypeScript React
frontend, (2) seeds a deterministic synthetic OHLCV dataset for a fixed fictitious
universe, (3) computes a starter set of versioned signal-rule plugins over that data with
full provenance, and (4) displays all signals in a filterable web UI backed by an
OpenAPI-defined typed contract. Storage is SQLite in a Docker volume; all analytics live
in backend libraries per the constitution; no external network access is required at
runtime.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5.x / Node 22 (frontend build)

**Primary Dependencies**: FastAPI + Pydantic v2 + Uvicorn (API), NumPy (synthetic data +
indicator math), SQLite via stdlib `sqlite3` (storage), React 18 + Vite (frontend),
openapi-typescript (contract client generation), Docker Compose v2 + GNU Make (runtime)

**Storage**: SQLite file in a named Docker volume (`quantlab-data`), schema-managed by an
idempotent bootstrap migration run at seed time; raw price bars persisted before signal
computation (Constitution III)

**Testing**: pytest (backend: reference-value signal tests, determinism tests, look-ahead
sweep, API contract tests against the OpenAPI schema); Vitest + Testing Library
(frontend component tests); a smoke script validating the running Compose stack

**Target Platform**: Local Docker (Linux containers) on macOS/Linux developer machines;
frontend served to any modern browser

**Project Type**: Web application (backend service + frontend SPA) with backend analytics
libraries

**Performance Goals**: Full seed (≥10 instruments × ≥3 years daily + all signals) < 30 s;
signal list API p95 < 500 ms; `git clone` → UI in < 10 min per SC-001

**Constraints**: No runtime network access (offline after image build); deterministic
output — identical dataset and signal set across runs (SC-002); no analytics in the
frontend (Constitution V); no look-ahead in signal computation (Constitution VII)

**Scale/Scope**: ~12 instruments × ~756 trading days ≈ 9k price bars; hundreds of
signals; single local user; 3 starter signal rules; read-only UI

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| I. Library-First | Synthetic-data generation, indicators, and signal rules are standalone libraries under `backend/src/quantlab/` with public interfaces; FastAPI handlers and React components contain no feature logic | PASS |
| II. Pluggable Indicators | Signal rules are plugins registered in a runtime registry with name, version, input/output schema, parameters, and scale class; adding a rule never touches core engine code | PASS |
| III. Data Integrity & Free-Source | Synthetic data only — licensing constraints N/A (noted in spec assumptions); raw bars persisted immutably before transformation; signals stored with provenance (rule name/version, params, data window) | PASS |
| IV. Test-First | TDD mandated for all analytical code; each signal rule has correctness tests against independently computed reference values plus boundary cases (insufficient history, flat series); determinism tested by double-seed comparison | PASS |
| V. Typed API Boundary | OpenAPI 3.1 spec in `contracts/` is the single source of truth; TS client generated from it; frontend performs zero computation | PASS |
| VI. Reproducibility & Observability | All randomness via explicitly seeded NumPy Generator; no wall-clock dependence in generation or signal logic; structured JSON logging in seed and API paths | PASS |
| VII. Point-in-Time Correctness | Signal for day T computed only from bars with date ≤ T; automated look-ahead sweep recomputes every rule on truncated history in the standard test suite | PASS |

No violations; Complexity Tracking table not required.

## Project Structure

### Documentation (this feature)

```text
specs/002-signal-viewer-demo/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── openapi.yaml     # Phase 1 output — typed API contract (single source of truth)
└── tasks.md             # Phase 2 output (/skill:speckit-tasks)
```

### Source Code (repository root)

```text
Makefile                  # up / down / build / seed / logs / test / smoke targets
docker-compose.yml        # backend, frontend, seed (one-shot) services
backend/
├── Dockerfile
├── pyproject.toml
├── src/quantlab/
│   ├── config.py             # seed config: universe, date range, RNG seeds
│   ├── synthetic/            # LIBRARY: deterministic OHLCV generator (regime-based)
│   ├── indicators/           # LIBRARY: indicator plugins (SMA, RSI, rolling max) + registry
│   ├── signals/              # LIBRARY: signal rule plugins + registry + engine
│   ├── storage/              # LIBRARY: SQLite schema bootstrap + repository functions
│   ├── api/                  # FastAPI app: routes, pydantic schemas (thin, no logic)
│   └── seed.py               # seed entrypoint: generate → persist raw → compute signals
└── tests/
    ├── unit/                 # synthetic determinism, indicator reference values
    ├── contract/             # API responses validated against contracts/openapi.yaml
    └── lookahead/            # truncated-history sweep for every signal rule
frontend/
├── Dockerfile
├── package.json
├── vite.config.ts
├── src/
│   ├── api/                  # generated typed client (from contracts/openapi.yaml)
│   ├── components/           # SignalTable, SignalFilters, PriceChart, StatusStates
│   ├── pages/                # SignalsPage (list + detail context view)
│   └── main.tsx
└── tests/                    # Vitest component tests (mocked API client)
```

**Structure Decision**: Web-application layout (Option 2) — `backend/` + `frontend/` with
root-level `Makefile` and `docker-compose.yml`. Backend feature logic lives in importable
libraries under `src/quantlab/` (synthetic, indicators, signals, storage); `api/` is a
thin shell. This satisfies Library-First while keeping the demo small.

## Phase 0: Research

All technical-context choices are resolved in [research.md](research.md). No NEEDS
CLARIFICATION items remain. Key decisions: FastAPI+Pydantic for the typed Python API,
OpenAPI 3.1 + openapi-typescript as the contract mechanism, SQLite for zero-dependency
local storage, NumPy seeded PCG64 for deterministic synthetic data, regime-switching GBM
to guarantee every signal rule fires, Docker Compose v2 behind Makefile targets.

## Phase 1: Design

- Data model: [data-model.md](data-model.md) — instruments, price_bars, signal_rules,
  signals; validation rules and invariants.
- API contract: [contracts/openapi.yaml](contracts/openapi.yaml) — health, instruments,
  prices, signals (filter/sort/paginate with total count).
- Validation guide: [quickstart.md](quickstart.md) — runnable scenarios proving SC-001
  through SC-005.

## Constitution Check (Post-Design Re-Evaluation)

Re-checked after Phase 1: the data model persists raw bars before signals (III), signals
carry rule provenance and a `data_window_end` proving point-in-time inputs (VII), the
contract carries no computational payloads for the frontend (V), and every entity maps to
a library module, not a handler (I). All gates remain PASS.
