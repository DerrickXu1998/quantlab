# Implementation Plan: Warehouse-Backed Experiments

**Branch**: `006-warehouse-experiments` | **Date**: 2026-09-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-warehouse-experiments/spec.md`

## Summary

Let the research workbench run against real ingested history (ClickHouse bars over a Postgres
catalog) as well as the synthetic SQLite demo, without the demo losing its zero-setup property. This
feature *is* the merge of `worktree-pg-historical-store` into `main`: the two branches solved
storage differently — feature 005's workbench calls storage directly, the warehouse branch routes
every handler through a `StorageBackend` protocol — and reconciling them is the work.

Technical approach: merge the branch, then extend the storage seam along two axes rather than one.
The existing `StorageBackend` gains the two bar-reading methods the runner needs; experiment
persistence becomes a **separate** `ExperimentStore` seam, because where a run *reads bars from* and
where it *keeps its results* are different questions — on the warehouse they are literally different
database systems. Runs record the dataset they used and, on the warehouse, the ingest runs behind
the bars they read.

## Technical Context

**Language/Version**: Python 3.11 (backend), TypeScript 5.6 / React 18.3 (frontend) — both unchanged.

**Primary Dependencies**: Existing on `main`; the merge brings `psycopg` (Postgres catalog) and
`clickhouse-connect` (bars) into the backend image, already declared as extras on the warehouse
branch (`quantlab[store]`). No dependency is introduced that the warehouse branch did not already
justify.

**Storage**: Both paths, selected at startup. Warehouse: bars in ClickHouse `price_bars` (read
through the `price_bars_current` view, never the raw table), catalog and experiment runs in Postgres.
Demo: everything in SQLite, exactly as today.

**Testing**: pytest, including the existing look-ahead truncation sweep and contract test; Vitest for
the frontend. The warehouse path needs tests that run without a live database — the `ExperimentStore`
and `StorageBackend` seams are what make that possible, with the live path exercised by the
`quickstart.md` pass.

**Target Platform**: Unchanged — Dockerized backend, static SPA behind nginx, ClickHouse and Postgres
already defined in the warehouse branch's compose file.

**Performance Goals**: A run over a realistic selection (tens of instruments, years of daily bars)
completes inside the synchronous request budget feature 005 established. The columnar store is
*faster* here than SQLite for wide scans, so the constraint is unchanged.

**Constraints**: The demo must keep working with no database, no credentials and no network
(FR-002). Experiment output must not enter the warehouse's materialised `signals` table (FR-010) —
the same trap 005 hit on SQLite. Point-in-time correctness must hold over real data, and the
truncation sweep must keep passing. No analytical computation in the front end.

**Scale/Scope**: One merge, one new Postgres migration, two storage seams extended or added, a
handful of contract fields, and modest frontend work to surface dataset provenance.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applicability | Assessment |
|---|---|---|
| I. Library-First | Applies — PASS | Run execution stays in `quantlab.research.runner`; the new storage seams are library interfaces with adapters. Routes remain thin. |
| II. Pluggable Indicator & Derived-Data Architecture | N/A | The registry is untouched. Models are unchanged; only the data beneath them changes. |
| III. Data Integrity & Free-Source Constraint | Applies — PASS | No new sources or adapters; this consumes what ingest already produced. GBX→GBP normalisation stays at the adapter boundary, and the catalog records both `currency` and `quote_currency` so a pence/pound error stays detectable. |
| IV. Test-First (NON-NEGOTIABLE) | Applies | Symbol/instrument identity, dataset provenance, corporate-action reporting, run isolation, and demo fallback are all written as failing tests first. |
| V. Typed, Contract-Driven API Boundary | Applies — PASS | The authored OpenAPI document moves to this feature and gains dataset provenance fields; the contract test and generated TypeScript client follow. No computation moves client-side. |
| VI. Reproducibility & Observability | Applies — **central** | A run records dataset, model version, effective parameters, selection, window — and for warehouse runs the ingest runs behind the bars it read, which is what makes a re-ingest distinguishable (FR-006). Structured logging continues. |
| VII. Point-in-Time Correctness (NON-NEGOTIABLE) | Applies — **risk point** | The warm-up window now spans real history. `experiment_signals` keeps its `data_window_end <= date` guard on both stores, and the truncation sweep must keep passing. Corporate actions are *reported*, not applied — see the adjustment decision in `research.md`. |
| Repository Structure (NON-NEGOTIABLE) | Applies — PASS | Code in `backend/` and `src/`; the authored contract lives under this feature's `contracts/`, mirrored to `backend/contracts/` by `make sync-contract` and guarded by `make check-contract`. |
| Technology Stack & Data Policy | Applies — PASS | Backend stays Python, frontend TypeScript with no client-side analytics. Postgres and ClickHouse arrive with the merge, already justified by the warehouse branch's own storage rationale. |

**Result**: Passes. One entry in Complexity Tracking.

**Post-Phase 1 re-check**: The design adds one Postgres migration, one new protocol
(`ExperimentStore`), two methods on an existing protocol, and provenance fields. The two decisions
carrying real risk — keeping experiment output out of the materialised signal set, and recording
ingest-run provenance rather than assuming data immutability — both *strengthen* compliance with
VI and VII. Gate result unchanged: **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/006-warehouse-experiments/
├── plan.md               # This file
├── research.md           # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   ├── openapi.yaml      # Authored contract (supersedes 005's as the live document)
│   └── ui-contracts.md   # Dataset provenance surfaces in the workbench
├── checklists/requirements.md
└── tasks.md              # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── src/quantlab/
│   ├── storage/
│   │   ├── backends.py       # MODIFIED — StorageBackend gains load_bars_for + earliest_bar_dates;
│   │   │                     #   both adapters implement them
│   │   ├── experiments.py    # NEW — the ExperimentStore seam + SQLite and Postgres adapters
│   │   ├── warehouse.py      # MODIFIED — windowed multi-instrument bar reads, corporate actions
│   │   └── repository.py     # MODIFIED — existing SQLite run persistence moves behind the seam
│   ├── research/
│   │   └── runner.py         # MODIFIED — takes the two seams instead of a sqlite3 connection;
│   │                         #   records dataset + ingest-run provenance, reports corporate actions
│   └── api/
│       ├── routes.py         # MERGE RESOLUTION — workbench routes ported onto the backend seam
│       └── schemas.py        # MODIFIED — dataset provenance fields
└── tests/
    ├── test_experiment_store.py   # NEW — both adapters against the same contract
    ├── test_dataset_provenance.py # NEW — dataset recorded, re-ingest distinguishable
    ├── test_corporate_actions.py  # NEW — actions in window are reported
    ├── test_run_isolation.py      # EXTENDED — also guards the warehouse signals table
    └── lookahead/                 # EXISTING — sweep must keep passing

src/quantlab/store/
└── migrations/003_experiments.sql # NEW — experiment_runs + experiment_signals in Postgres

frontend/
└── src/workbench/                 # MODIFIED — dataset badge, provenance in results and comparison
```

**Structure Decision**: Two seams, not one. `StorageBackend` answers "what dataset am I reading?" and
gains only the two bar-reading methods the runner needs. `ExperimentStore` answers "where do my
experiments live?" and is separate because on the warehouse those are different systems — bars in
ClickHouse, runs in Postgres — and because a dataset adapter should not acquire responsibility for
storing user artefacts. See Complexity Tracking for the single-protocol alternative and why it was
rejected.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| A second storage protocol (`ExperimentStore`) alongside `StorageBackend` | Reading market data and persisting user experiments are different concerns with different lifetimes, and on the warehouse they are different database systems. Keeping them separate is what lets experiment persistence be tested without a bar store, and lets a future dataset be added without also implementing run storage. | Putting all seven methods on `StorageBackend` was considered and rejected: it forces every dataset adapter to implement experiment persistence even when the question is unrelated, and it would make the protocol's name a lie. The cost of the split is one extra interface; the cost of conflating them is that "which dataset" and "where are my experiments" can never vary independently. |
