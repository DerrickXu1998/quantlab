---

description: "Task list for Warehouse-Backed Experiments"
---

# Tasks: Warehouse-Backed Experiments

**Input**: Design documents from `/specs/006-warehouse-experiments/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml,
contracts/ui-contracts.md, quickstart.md

**Tests**: Included and REQUIRED — Constitution Principle IV (Test-First, NON-NEGOTIABLE), and
Principle VII requires the look-ahead sweep to keep passing over the new data path.

**Organization**: Grouped by user story (spec.md P1/P2/P3). Paths are relative to the repository root.

**Three things that shape this list:**

1. **This feature carries a merge.** `worktree-pg-historical-store` comes into `main`, and the one
   real conflict — `backend/src/quantlab/api/routes.py` — is resolved by *keeping both* sets of
   handlers so the tree never stops working, then porting the workbench handlers onto the storage
   seam in Phase 2. No commit in this sequence leaves a broken system.
2. **The riskiest phase is Foundational, not a user story.** Moving run persistence behind a seam
   touches the working SQLite path. US2's regression guards are therefore worth running from the end
   of Phase 2 onward, not only when US2's own phase arrives.
3. **`research.md` corrected FR-007.** Do **not** build as-of vendor-symbol resolution: canonical
   symbols are already unique and stable, and the ticker-reuse constraint is enforced at ingest.
   Recording `instrument_id` is what the requirement actually needs.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1/US2/US3; Setup, Foundational and Polish tasks carry no story label

---

## Phase 1: Setup (Merge and Contract Relocation)

**Purpose**: Land the warehouse architecture on `main` and move the authored contract forward,
without breaking anything that works today.

- [X] T001 Merge `worktree-pg-historical-store` into `main`, resolving the sole conflict in
      `backend/src/quantlab/api/routes.py` by **keeping both** sets of handlers: the warehouse
      branch's seam-based instrument/price/signal routes, and feature 005's workbench routes
      unchanged. The workbench is temporarily demo-only; Phase 2 ports it onto the seam. Resolving
      the conflict this way is what keeps every commit in this sequence working.
- [X] T002 Run `pytest` in `backend/` and `npm test` in `frontend/` and confirm the post-merge tree
      is green before any further change (depends on: T001).
- [X] T003 [P] Copy the authored contract forward to
      `quantlab_specs/specs/006-warehouse-experiments/contracts/openapi.yaml` as the live document and
      re-point every consumer: `CONTRACT_SRC` and `gen-api` in `Makefile`, the `gen:api`/`codegen`
      scripts in `frontend/package.json`, and the contract-path resolver in
      `backend/tests/contract/test_api_contract.py` **and** `test_workbench_contract.py` — both
      hardcode a feature directory, and a stale one silently validates the wrong document.
- [X] T004 Run `make sync-contract` then `make check-contract` and confirm the guard passes against
      the new source (depends on: T003).
- [X] T005 Regenerate `frontend/src/api/schema.d.ts` via `npm run gen:api` and confirm it contains
      `Dataset` and `CorporateActionNotice` (depends on: T003).
- [X] T006 [P] Ensure the backend image installs the store extras (`psycopg`, `clickhouse-connect`)
      in `backend/pyproject.toml` / `backend/Dockerfile`, so the warehouse path is runnable in the
      container while remaining optional at import time.

---

## Phase 2: Foundational (The Two Storage Seams)

**Purpose**: Put both seams in place and move the workbench behind them, so the runner no longer
knows which store it is talking to. Every user story is blocked on this.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. This phase also carries
the highest regression risk in the feature, because it rewires a working SQLite path.

### Tests (write first, watch fail)

- [X] T007 [P] Write `backend/tests/test_experiment_store.py`: one suite exercising the
      `ExperimentStore` contract — `save_run`, `get_run`, `list_runs(saved_only)`, `set_run_name`,
      `delete_run` — parameterised so it runs against **both** adapters. Deleting a run must remove
      **"a run and its signals together"**. A run must remain readable regardless of which dataset is
      active.
- [X] T008 [P] Write `backend/tests/test_backend_bar_reads.py`: the three new `StorageBackend`
      methods against the SQLite adapter — `load_bars_for(symbols, start, end)` returns bars for
      several instruments across one window, `earliest_bar_dates(symbols)` returns the first
      available bar per instrument, and `corporate_actions(symbols, start, end)` **returns empty on
      the demo, which has none**.
- [X] T009 [P] Write `backend/tests/test_runner_seams.py`: `run_experiment` takes the two seams
      rather than a database connection, and every existing guarantee from feature 005 still holds —
      warm-up window, in-window-only reporting, short-window rejection, determinism, coverage counts,
      and zero signals completing successfully.

### Implementation

- [X] T010 [P] Create `src/quantlab/store/migrations/003_experiments.sql` adding `experiment_runs`
      and `experiment_signals` to the Postgres catalog per `data-model.md`, keyed by `instrument_id`
      referencing `instruments`, with `ON DELETE CASCADE` from run to signals and the point-in-time
      constraint **"`data_window_end` ... Must be `<= date`"** — the same guard the catalog's own
      `signals` table carries (Constitution VII).
- [X] T011 Create `backend/src/quantlab/storage/experiments.py` defining the `ExperimentStore`
      protocol and `SqliteExperimentStore`, moving the run-persistence functions added in feature 005
      out of `backend/src/quantlab/storage/repository.py` and behind the seam without changing their
      behaviour (depends on: T007 failing first).
- [X] T012 Add `PostgresExperimentStore` to `backend/src/quantlab/storage/experiments.py`, satisfying
      the same contract against the new tables. Keep the driver import inside the adapter, never at
      module scope — the demo path must not acquire a database dependency (depends on: T010, T011).
- [X] T013 Extend the `StorageBackend` protocol in `backend/src/quantlab/storage/backends.py` with
      `load_bars_for`, `earliest_bar_dates` and `corporate_actions`, and implement all three on
      `SqliteBackend` using the existing repository functions (depends on: T008 failing first).
- [X] T014 Change `run_experiment` in `backend/src/quantlab/research/runner.py` to take a
      `StorageBackend` and an `ExperimentStore` instead of a `sqlite3` connection, preserving the
      warm-up window, in-window filtering and coverage logic exactly (depends on: T009 failing first,
      T011, T013).
- [X] T015 Port the workbench handlers in `backend/src/quantlab/api/routes.py` onto the seams,
      removing every direct `db.connect(...)` and `repository.*` call left by T001's union merge, so
      no handler knows which store is behind it (depends on: T014).
- [X] T016 Select and bind the `ExperimentStore` alongside the `StorageBackend` at startup in
      `backend/src/quantlab/api/app.py`, mirroring `select_backend()`'s "warehouse when configured,
      else the demo" rule (depends on: T012, T015).
- [X] T017 Run the full backend and frontend suites and confirm the demo path still behaves exactly
      as before this feature — this is the regression checkpoint for the riskiest phase (depends on:
      T010–T016).

**Checkpoint**: Both seams exist, the workbench runs through them, and the demo path is unchanged in
behaviour. Nothing yet reads real history.

---

## Phase 3: User Story 1 - Run a Model Over Real Ingested History (Priority: P1) 🎯 MVP

**Goal**: The workbench answers questions about real markets — a registered model over real
instruments and dates, with results trustworthy enough to act on.

**Independent Test**: With history ingested, select real instruments and a window, run a model, and
confirm the signals derive from real bars — spot-checked against that instrument's price history —
per `quickstart.md` §3.

### Tests for User Story 1 ⚠️

- [ ] T018 [P] [US1] Write `backend/tests/test_warehouse_bar_reads.py` against a fake ClickHouse
      client: `load_bars_for` reads through the **`price_bars_current` view, never the raw
      `price_bars` table** (reading the raw table returns doubled rows after a re-ingest), filters by
      instrument and window, and `earliest_bar_dates` returns the first bar per instrument.
- [ ] T019 [P] [US1] Write `backend/tests/test_corporate_actions.py`: actions overlapping the run
      window are returned for the selected instruments, with `action_type` in `split | dividend`
      matching the catalog's CHECK constraint; a window containing no action returns empty.
- [ ] T020 [P] [US1] Add a contract test in `backend/tests/contract/` asserting a run against the
      warehouse returns `dataset: "warehouse"` with non-null `instrument_ids`, and that every
      returned signal's date falls inside the window with `data_window_end <= date`.

### Implementation for User Story 1

- [ ] T021 [US1] Implement windowed multi-instrument bar reading in
      `backend/src/quantlab/storage/warehouse.py`, reading through `price_bars_current` and resolving
      canonical symbols to `instrument_id` via `instruments.symbol` (depends on: T018 failing first).
- [ ] T022 [US1] Implement `earliest_bar_dates` and `corporate_actions` in
      `backend/src/quantlab/storage/warehouse.py`, the latter querying `corporate_actions` by
      `instrument_id` and `ex_date` within the window (depends on: T019 failing first, T021).
- [ ] T023 [US1] Implement the three new `StorageBackend` methods on `WarehouseBackend` in
      `backend/src/quantlab/storage/backends.py`, delegating to T021/T022 (depends on: T021, T022).
- [ ] T024 [US1] Record `instrument_ids` on warehouse runs in
      `backend/src/quantlab/research/runner.py` — **"Recorded because the canonical symbol is unique
      but editable, while `instrument_id` is the stable key the bar store joins on."** Do not build
      as-of vendor-symbol resolution (see `research.md`) (depends on: T023).
- [ ] T025 [US1] Surface `corporate_actions` on the run result in
      `backend/src/quantlab/api/schemas.py` and the runner, reported and **never applied to prices**
      (depends on: T022, T024).
- [ ] T026 [US1] Run the backend suite, then walk `quickstart.md` §2–§3 against a live warehouse:
      ingest, run a model over real instruments, and spot-check a reported signal against the
      underlying price history (depends on: T021–T025).

**Checkpoint**: The workbench runs against real history — the feature's core value, demoable.

---

## Phase 4: User Story 2 - The Demo Still Works With No Warehouse (Priority: P2)

**Goal**: Cloning the project with no databases, credentials or network still produces a working
workbench, and the active dataset is never ambiguous.

**Independent Test**: With the warehouse unconfigured, complete the entire workbench loop, and
confirm the application starts and serves without any database being reachable — per
`quickstart.md` §1.

### Tests for User Story 2 ⚠️

- [ ] T027 [P] [US2] Write `backend/tests/test_demo_fallback.py`: the application starts and serves
      the synthetic dataset **with `psycopg` and `clickhouse_connect` unimportable**, proving no
      driver is imported at module scope. This is the cheapest guard on the zero-setup promise.
- [ ] T028 [P] [US2] Extend the contract tests so the health response reports the active dataset,
      with `dataset` in the required set and valued `sqlite` when the warehouse is not configured.
- [ ] T029 [P] [US2] Write `frontend/tests/DatasetBadge.test.tsx`: the active dataset is rendered
      from the health response and never inferred from the shape of the data.

### Implementation for User Story 2

- [X] T030 [US2] Add the active dataset to the health response in
      `backend/src/quantlab/api/routes.py` and `schemas.py`, sourced from the bound backend's `name`
      (depends on: T028 failing first).
- [ ] T031 [US2] Report a configured-but-unreachable warehouse distinctly at startup and in health in
      `backend/src/quantlab/api/app.py` — **"cannot reach the data" must not look like "no data"**
      (depends on: T030).
- [ ] T032 [US2] Show the active dataset in the workbench in `frontend/src/App.tsx` and
      `frontend/src/workbench/`, per `contracts/ui-contracts.md` §1 — visible without opening a menu
      (depends on: T029 failing first, T030).
- [ ] T033 [US2] Run the full suite with the warehouse unconfigured, then walk `quickstart.md` §1
      including the driver-unavailability check (depends on: T030–T032).

**Checkpoint**: Both paths work, and which one is live is never in doubt.

---

## Phase 5: User Story 3 - Experiments Stay Trustworthy Across Datasets (Priority: P3)

**Goal**: Every run says what it was computed from, and a result that cannot be reproduced says so
rather than quietly differing.

**Independent Test**: Save a run against one dataset, switch datasets, reopen it — configuration and
results intact, clearly marked not re-runnable — per `quickstart.md` §5.

### Tests for User Story 3 ⚠️

- [ ] T034 [P] [US3] Write `backend/tests/test_dataset_provenance.py`: every run records `dataset`;
      warehouse runs that read bars record `ingest_run_ids`; and **two runs with identical
      configuration either side of a re-ingest record different `ingest_run_ids`** — the case where
      every input the researcher chose is the same but the data changed.
- [ ] T035 [P] [US3] Extend the contract tests: `re_runnable` is false when a run's recorded dataset
      is not the active one, and the run remains fully readable.
- [ ] T036 [P] [US3] Write `frontend/tests/RunProvenance.test.tsx`: dataset appears with the run's
      results; a non-empty `corporate_actions` list is surfaced as a correctness warning, not hidden;
      a run with `re_runnable: false` renders read-only and marked.

### Implementation for User Story 3

- [ ] T037 [US3] Record `dataset` on every run and `ingest_run_ids` on warehouse runs in
      `backend/src/quantlab/research/runner.py`, taking the ingest provenance from the `run_id` column
      carried on every bar read — **"a re-ingest writes rows with a higher `run_id` that supersede
      the earlier copies"**, so this is what distinguishes them (depends on: T034 failing first,
      T024).
- [ ] T038 [US3] Compute `re_runnable` on run responses in `backend/src/quantlab/api/routes.py` by
      comparing the run's recorded dataset against the active one (depends on: T035 failing first,
      T030).
- [ ] T039 [US3] Show provenance and the corporate-action warning with run results in
      `frontend/src/workbench/RunResults.tsx`, per `contracts/ui-contracts.md` §2 (depends on: T036
      failing first).
- [ ] T040 [US3] Surface a dataset mismatch in `frontend/src/workbench/RunCompare.tsx` **as
      prominently as a model-version difference**, and flag differing `ingest_run_ids` as "the data
      changed underneath" (depends on: T039).
- [ ] T041 [US3] Run the suite, then walk `quickstart.md` §4 (re-ingest distinguishable, corporate
      actions reported) and §5 (provenance across datasets) (depends on: T037–T040).

**Checkpoint**: All three stories complete; no run's data source is ambiguous.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T042 Extend `backend/tests/unit/test_run_isolation.py` to guard the **catalog's** materialised
      `signals` table as well as the demo's — the same trap on a different store: experiment output
      would insert cleanly and then surface in the Signal Viewer.
- [ ] T043 Confirm the look-ahead truncation sweep in `backend/tests/lookahead/` still passes over
      the warehouse path, including parameter-overridden runs (Constitution VII).
- [ ] T044 [P] Update `docs/STORAGE.md` and `docs/ARCHITECTURE.md` to describe experiment storage
      alongside the bars/catalog split, and `docs/SIGNAL_VIEWER_DEMO.md` to explain the two datasets.
- [ ] T045 [P] Add structured logging for the dataset and ingest provenance of each run in
      `backend/src/quantlab/research/runner.py` (Constitution VI).
- [ ] T046 Run the full gate: `pytest`, `npm run lint`, `npx prettier --check .`, `npm run build`,
      `npm test`, and `make check-contract` (depends on: all story phases).
- [ ] T047 Build both Docker images and bring the full stack up to confirm it runs (depends on:
      T046).
- [ ] T048 Full `quickstart.md` pass (§1–§7), including §7's check that no handler reaches past the
      storage seams — the property the original merge conflict was about (depends on: T046, T047).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. Lands the merge.
- **Foundational (Phase 2)**: Depends on Setup. **BLOCKS all user stories.** Highest regression risk
  in the feature.
- **US1 (Phase 3)**: Depends on Foundational.
- **US2 (Phase 4)**: Depends on Foundational. Independent of US1 — it exercises the path US1 does not.
- **US3 (Phase 5)**: Depends on Foundational, and on US1 for `instrument_ids` (T037 extends T024).
- **Polish (Phase 6)**: Depends on the story phases.

### User Story Dependencies

- **US1 (P1)** and **US2 (P2)** are genuinely independent — one is the warehouse path, the other the
  demo path, and they touch different adapters.
- **US3 (P3)** depends on US1: ingest provenance is recorded by the same runner code that records
  instrument identity.

**Worth stating plainly**: US2 is *preservation*, not new capability. Its guards (T027 especially)
are most valuable run at the end of Phase 2, when the SQLite path has just been rewired — not held
back until Phase 4. Treat T017 and T027 as the same checkpoint if working sequentially.

### Within Each User Story

- Tests written and confirmed failing before implementation (Constitution IV).
- Storage adapter before the backend method that delegates to it; backend method before the runner
  that calls it; runner before the route that adapts it (Principle I).

### Parallel Opportunities

- T003 and T006 in parallel (after T002).
- All Foundational tests (T007–T009) in parallel; T010 in parallel with T011.
- Once Foundational completes, **US1 and US2 can proceed in parallel** — different adapters, different
  files.
- Within each story, the test tasks are all `[P]`.
- Polish: T044 and T045 in parallel.

---

## Parallel Example: after Foundational

```bash
# Two independent tracks:
Developer A (US1): warehouse.py bar reads + corporate actions + WarehouseBackend
Developer B (US2): health dataset reporting + driver isolation + dataset badge

# US3 waits for US1's T024 before T037.
```

---

## Implementation Strategy

### MVP First (Setup + Foundational + US1)

1. Phase 1 Setup — land the merge, tree stays green.
2. Phase 2 Foundational — both seams, workbench ported, demo unchanged.
3. Phase 3 US1 — run against real history.
4. **STOP and VALIDATE**: `quickstart.md` §3, spot-checking a signal against real price history.
5. Demo. Answering a question about real markets is the whole point; provenance polish can follow.

### Incremental Delivery

1. Setup + Foundational → nothing user-visible changed, architecture reconciled.
2. + US1 → real history (MVP).
3. + US2 → the zero-setup demo is provably still intact, and the live dataset is visible.
4. + US3 → provenance, re-runnability, and honest comparison.
5. Polish → isolation guards, docs, logging, full gate.

---

## Notes

- Tests are mandatory: write, watch fail, then implement.
- **The two highest-risk tasks are T015 (porting handlers onto the seam) and T037 (ingest
  provenance).** A mistake in T015 silently reintroduces a direct store dependency and the two
  datasets stop being interchangeable; a mistake in T037 makes a run look reproducible when its data
  has changed underneath.
- **T027 is the guard on the project's approachability.** A module-scope driver import would break
  `make up` for anyone without databases, and nothing else in the suite would notice.
- Do not implement as-of vendor-symbol resolution — `research.md` records why FR-007 is satisfied by
  recording `instrument_id`.
- No blending of datasets anywhere: one run draws entirely from one dataset.
