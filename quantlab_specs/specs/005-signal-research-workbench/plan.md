# Implementation Plan: Signal Research Workbench

**Branch**: `005-signal-research-workbench` | **Date**: 2026-09-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-signal-research-workbench/spec.md`

## Summary

Turn the app from a viewer of pre-computed signals into a research workbench: browse the models
actually registered in the backend, configure their declared parameters, run one on a chosen slice of
instruments and dates, and inspect, compare and save the results. Unlike the two preceding features,
the bulk of this work is **backend**: the registry must publish real parameter metadata, the engine
must accept parameter overrides, and there must be an on-demand run path with its own provenance-
carrying storage. The front end adds panels to the docking workspace already in place.

## Technical Context

**Language/Version**: Python 3.11 (backend, FastAPI + SQLite); TypeScript 5.6 / React 18.3 (frontend)

**Primary Dependencies**: All existing — FastAPI, numpy, SQLite on the backend; React, Vite,
`dockview-react`, `lightweight-charts`, Tailwind on the front end. **No new runtime dependency is
required by this feature**, which is a direct consequence of the scope decisions (registered models
only, existing universe only): there is no upload handling, no sandbox, no model-scoring runtime.

**Storage**: Existing SQLite database. New tables for experiment runs and their produced signals.
Critically, run output is stored **separately** from the seeded `signals` table — see Constitution
Check and `data-model.md`.

**Testing**: pytest (backend, with the existing look-ahead truncation sweep and contract test);
Vitest + Testing Library (frontend). New backend tests cover parameter validation, the lookback
warm-up window, run determinism, and run isolation from seeded signals.

**Target Platform**: Unchanged — Dockerized backend + static SPA behind nginx.

**Project Type**: Web application (`backend/` + `frontend/`). **Both sides change**, unlike `003` and
`004`.

**Performance Goals**: A run over the seeded universe (12 instruments × ~3 years ≈ 9.4k bars)
completes fast enough to be answered synchronously. Selection size is bounded server-side so a run
cannot be issued that would block the API for an unreasonable time.

**Constraints**: No analytical computation in the front end (Principle V). Runs must be reproducible
from recorded provenance (Principle VI). Signals may not use information after their own date
(Principle VII) — the existing truncation sweep must keep passing, and the new warm-up window design
must not weaken it. The existing Signal Viewer must not regress: experiment output must never leak
into the seeded signal list.

**Scale/Scope**: One workbench surface added to the existing workspace; three new panels; roughly
four new endpoints; two new tables. Registry contract extended in a backward-compatible way.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applicability | Assessment |
|---|---|---|
| I. Library-First | Applies — PASS | Run execution is library logic in `quantlab.signals` (engine + registry), not logic living in an HTTP handler. The route is a thin adapter over an independently testable function. |
| II. Pluggable Indicator & Derived-Data Architecture | Applies — **corrects a gap** | The principle requires plugins to declare their parameters and the registry to support runtime discovery "so the frontend can enumerate available indicators and their parameter metadata". Today the registry stores parameter *values* (`dict[str, Any]`) with no types or ranges, and the front end **hardcodes** its rule list. This feature publishes real parameter metadata and makes the catalog dynamic. Adding a model must still require no change to unrelated code. |
| III. Data Integrity & Free-Source Constraint | N/A | No data sources touched; runs read already-ingested bars. No new ingestion. |
| IV. Test-First (NON-NEGOTIABLE) | Applies | Parameter validation, warm-up window behavior, determinism, and run/seed isolation are all written as failing tests first. Analytical changes additionally require reference-value tests. |
| V. Typed, Contract-Driven API Boundary | Applies — PASS | New endpoints are authored in the OpenAPI document first (the single source of truth), the FastAPI app is validated against it by the existing contract test, and the TypeScript client is regenerated. No computation moves client-side — the front end configures and displays only. |
| VI. Reproducibility & Observability | Applies — **central** | Every run records model name, version, effective parameters, instrument selection and date window, and identical inputs must yield identical output. No wall-clock or randomness inside computation. Runs are structured-logged. |
| VII. Point-in-Time Correctness (NON-NEGOTIABLE) | Applies — **risk point** | Loading warm-up history *before* the window start is past data and is legitimate; the danger is a sloppy implementation letting a signal see bars after its own date. The existing truncation sweep must keep passing and must cover parameter-overridden runs too. |
| Repository Structure (NON-NEGOTIABLE) | Applies — PASS | Code lands in `backend/` and `frontend/`; the OpenAPI document is authored under this feature's `contracts/` and mirrored to `backend/contracts/` by `make sync-contract`, guarded by `make check-contract`. |
| Technology Stack & Data Policy | Applies — PASS | Backend stays Python, frontend stays TypeScript with no client-side analytics. **No new third-party dependency**, so the dependency-justification requirement is not engaged. |

**Result**: Passes. One item in Complexity Tracking, recorded rather than waved through.

**Post-Phase 1 re-check**: The design adds two tables, four endpoints, a backward-compatible registry
extension, and three panels. The two decisions that carried real risk — storing run output separately
from seeded signals, and loading warm-up history while only reporting in-window signals — both
*strengthen* constitutional compliance (VI and VII respectively) rather than straining it. Gate
result unchanged: **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/005-signal-research-workbench/
├── plan.md                 # This file
├── research.md             # Phase 0 output
├── data-model.md           # Phase 1 output
├── quickstart.md           # Phase 1 output
├── contracts/              # Phase 1 output
│   ├── openapi.yaml        # Authored API contract (supersedes 002's as the live document)
│   └── ui-contracts.md     # Workbench panel + state contracts
├── checklists/requirements.md
└── tasks.md                # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── src/quantlab/
│   ├── signals/
│   │   ├── registry.py       # MODIFIED — ParamSpec metadata, backward compatible with params={...}
│   │   ├── builtins.py       # MODIFIED — declare param specs (types, ranges) for the three rules
│   │   └── engine.py         # MODIFIED — accept parameter overrides; record effective params
│   ├── research/             # NEW — the run use case as library logic (Principle I)
│   │   ├── runner.py         #   validate params, resolve warm-up window, execute, summarise
│   │   └── errors.py         #   typed validation/execution failures the API maps to responses
│   ├── storage/
│   │   ├── db.py             # MODIFIED — experiment_runs + experiment_signals DDL
│   │   └── repository.py     # MODIFIED — bars for (symbols, window); run persistence + queries
│   └── api/
│       ├── routes.py         # MODIFIED — /models, /runs (create/get/list/delete)
│       └── schemas.py        # MODIFIED — request/response models mirroring the contract
└── tests/
    ├── test_param_specs.py        # NEW — declared metadata, validation, rejection cases
    ├── test_runner.py             # NEW — warm-up window, determinism, coverage, zero-signal
    ├── test_run_isolation.py      # NEW — run output never appears in /signals
    ├── contract/                  # EXISTING — extended for the new endpoints
    └── lookahead/                 # EXISTING — sweep extended to parameter-overridden runs

frontend/
├── src/
│   ├── workspace/
│   │   └── panels.tsx        # MODIFIED — register the three workbench panels
│   ├── workbench/            # NEW
│   │   ├── ModelCatalog.tsx  #   browse registered models (FR-001)
│   │   ├── RunConfig.tsx     #   parameter form built from declared metadata (FR-002/003/004)
│   │   ├── RunResults.tsx    #   signals, summary, coverage, zero-signal state (FR-007/008/009)
│   │   ├── RunCompare.tsx    #   compare two runs (FR-013/014)
│   │   └── useRuns.ts        #   run lifecycle + in-session run history (FR-012)
│   ├── components/
│   │   └── SignalFilters.tsx # MODIFIED — drop the hardcoded RULES list, use the catalog
│   └── api/schema.d.ts       # REGENERATED from the authored contract
└── tests/                    # NEW tests per panel; existing suites unchanged
```

**Structure Decision**: Run execution goes in a new `quantlab.research` library module rather than
in the route, satisfying Principle I and keeping it testable without HTTP. The front end gains a
`workbench/` module whose panels register into the existing docking workspace — the extensibility
that feature `004` was adopted for, now being used for the first time.

## Complexity Tracking

> Recorded per the constitution's requirement to justify complexity beyond the simplest design.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Separate `experiment_signals` storage instead of reusing the `signals` table | The existing `signals` table is the Signal Viewer's data source, and its identity already includes parameters, so experiment output *would* insert cleanly — and would then appear in the Signal Viewer's list, silently mixing exploratory output with the curated seeded set. Keeping run output in its own table, keyed by run id, preserves the viewer's meaning and lets a run be deleted without touching seeded data. | Reusing `signals` with a nullable `run_id` discriminator was considered and rejected: every existing query would need a `run_id IS NULL` filter, and forgetting that filter anywhere silently corrupts the viewer. A separate table makes the wrong thing hard rather than merely discouraged. |
