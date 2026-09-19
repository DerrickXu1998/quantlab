---

description: "Task list for Signal Research Workbench"
---

# Tasks: Signal Research Workbench

**Input**: Design documents from `/specs/005-signal-research-workbench/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml,
contracts/ui-contracts.md, quickstart.md

**Tests**: Included and REQUIRED — Constitution Principle IV (Test-First, NON-NEGOTIABLE). Analytical
changes additionally require reference-value tests, and Principle VII requires the look-ahead sweep to
cover the new execution path.

**Organization**: Grouped by user story (spec.md P1/P2/P3). Paths are relative to the repository root.

**Two things that differ from features 003 and 004, and shape this list:**

1. **This is backend-dominated.** Roughly two-thirds of the work is in `backend/`, because the
   registry cannot describe its parameters, the engine cannot accept parameter overrides, and there
   is no on-demand run path. None of the UI is buildable until those exist.
2. **The user stories are NOT independent here.** US2 (compare) and US3 (save) both operate on runs
   that US1 creates, so they genuinely depend on US1 — unlike the previous two features where stories
   could be parallelized. Stated plainly rather than papered over in the dependency section.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1/US2/US3; Setup, Foundational, and Polish tasks carry no story label

---

## Phase 1: Setup (Contract Relocation)

**Purpose**: Move the authored API contract forward to this feature and re-point every consumer, so
all later work generates from one authored home (Constitution V and Repository Structure).

- [X] T001 [P] Update the `gen:api` and `codegen` scripts in `frontend/package.json` to read
      `../quantlab_specs/specs/005-signal-research-workbench/contracts/openapi.yaml` instead of the
      `002-signal-viewer-demo` path.
- [X] T002 [P] Update the `sync-contract` and `check-contract` targets in `Makefile` to treat
      `quantlab_specs/specs/005-signal-research-workbench/contracts/openapi.yaml` as the authored
      source mirrored into `backend/contracts/openapi.yaml`.
- [X] T003 Run `make sync-contract` to refresh `backend/contracts/openapi.yaml`, then `make
      check-contract` to confirm the guard passes against the new source (depends on: T002).
- [X] T004 Regenerate `frontend/src/api/schema.d.ts` via `npm run gen:api` in `frontend/` and confirm
      it now contains the `Model`, `Run`, `RunDetail`, and `ParamSpec` types (depends on: T001).

---

## Phase 2: Foundational (Backend Core)

**Purpose**: Make the backend able to *describe* its models, *run* them with chosen parameters, and
*store* the results. Every user story is blocked on this; none of it is reachable over HTTP yet, and
all of it is testable without HTTP.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Tests (write first, watch fail)

- [X] T005 [P] Write `backend/tests/test_param_specs.py`: a parameter declares `name`, `type` (one of
      `int`, `float`, `bool`, `enum`), and `default`; **"`minimum`/`maximum` only on numeric types;
      `choices` only on `enum`"**; **"`default` must satisfy its own constraints"** (a violating
      default fails at registration, not at run time); **"Every declared `name` must be an accepted
      keyword of the compute function"**; `maximum` **"must be `>= minimum` when both are present"**;
      and `choices` **"must be non-empty"** when `type` is `enum`.
- [X] T006 [P] Write `backend/tests/test_param_specs_compat.py`: the existing shorthand
      `params={"fast": 20}` still registers, and is interpreted as **"`{name: "fast", type: inferred
      from the value, default: 20}` with no bounds"** — existing rules must keep working untouched.
- [X] T007 [P] Write `backend/tests/test_engine_overrides.py`: `compute_signals` accepts per-run
      parameter overrides; the signals it emits record the **effective** parameters (registered
      defaults merged with overrides) and never the bare registered defaults; omitted parameters fall
      back to declared defaults.
- [X] T008 [P] Write `backend/tests/test_runner.py` covering the runner's four risky behaviours:
      (a) **warm-up** — bars are loaded from `start − lookback_days` through `end`, and every reported
      signal's `date` falls **within `[start_date, end_date]`**; (b) a window shorter than the model's
      `lookback_days` is **rejected before executing** with an explanation, not returned as an empty
      result; (c) **determinism** — two runs of one configuration produce identical signal sequences;
      (d) a run that fires nothing completes with `signal_count: 0` and populated coverage, since
      **"Zero is a valid, meaningful result, not an error."**
- [X] T009 [P] Write `backend/tests/test_run_isolation.py`: executing a run does not change the row
      count of the seeded `signals` table and its output is not returned by the existing signals
      query — the regression guard for the Signal Viewer.

### Implementation

- [X] T010 Add a `ParamSpec` structure and registration-time validation to
      `backend/src/quantlab/signals/registry.py` per `data-model.md`'s ParamSpec table, replacing the
      value-only `params: dict[str, Any]` while normalizing the bare-value shorthand for backward
      compatibility (depends on: T005, T006 failing first).
- [X] T011 Declare full parameter specs (types, inclusive bounds, descriptions) for `sma-crossover`,
      `rsi-threshold`, and `breakout-20d` in `backend/src/quantlab/signals/builtins.py`, leaving each
      rule's compute logic untouched (depends on: T010).
- [X] T012 Add parameter-override support to `compute_signals` in
      `backend/src/quantlab/signals/engine.py`, merging overrides over declared defaults and recording
      the merged result as each signal's `parameters` (depends on: T007 failing first, T010).
- [X] T013 [P] Add the `experiment_runs` DDL to `backend/src/quantlab/storage/db.py` with the columns
      and constraints in `data-model.md`, including `status` in (`completed`, `failed`),
      `signal_count >= 0`, `instruments_requested >= 1`, and the three coverage counts.
- [X] T014 [P] Add the `experiment_signals` DDL to `backend/src/quantlab/storage/db.py`, keyed by
      `run_id` with cascade delete, `direction` in (`bullish`, `bearish`), and the point-in-time CHECK
      **"`data_window_end` ... Must be `<= date`"** — the same proof the existing `signals` table
      enforces (Constitution VII).
- [X] T015 Add a repository function to `backend/src/quantlab/storage/repository.py` that loads bars
      for a set of symbols across a date window (the existing `load_all_bars` loads everything and
      `get_prices` handles only one symbol, so neither fits) (depends on: T013, T014).
- [X] T016 Add run persistence and queries to `backend/src/quantlab/storage/repository.py`: insert a
      run with its provenance and signals, fetch one with signals, list runs newest-first with an
      optional saved-only filter, set a run's name, and delete a run **together with its signals**
      (depends on: T013, T014).
- [X] T017 [P] Create `backend/src/quantlab/research/errors.py` with typed errors the API layer maps
      to responses: unknown model, unknown symbol, parameter validation failure (carrying the
      offending parameter name), window-too-short, and selection-too-large.
- [X] T018 Create `backend/src/quantlab/research/runner.py` as library logic (Principle I — not in a
      route): validate overrides against declared specs, reject a window shorter than `lookback_days`,
      bound the selection size, resolve and load the warm-up window, execute via the engine, filter
      reported signals to `[start_date, end_date]`, and compute the three coverage counts
      (`instruments_requested`, `instruments_with_data`, `instruments_full_warmup`) (depends on: T008
      failing first, T012, T015, T016, T017).
- [X] T019 Extend the look-ahead truncation sweep in `backend/tests/lookahead/` to cover
      **parameter-overridden** runs — overrides change lookback behaviour and are an execution path
      the sweep has never exercised (Constitution VII) (depends on: T012).
- [X] T020 Run `pytest` in `backend/` and confirm the new suites and the existing sweep all pass
      (depends on: T010–T019).

**Checkpoint**: The backend can describe its models, run one with chosen parameters over a chosen
slice, and store the result with provenance — all without HTTP. Nothing is user-visible yet.

---

## Phase 3: User Story 1 - Run a Model Against a Dataset and See What It Finds (Priority: P1) 🎯 MVP

**Goal**: The core discovery loop — browse registered models, configure declared parameters, pick
instruments and dates, run, and inspect the signals with their summary and coverage.

**Independent Test**: Choose a model, adjust a parameter, select instruments and a date range, run,
and confirm the signals appear with a summary — per `quickstart.md` §2–§4 and §7.

### Tests for User Story 1 ⚠️

- [X] T021 [P] [US1] Add a contract test in `backend/tests/contract/` for `GET /models`: the response
      matches the `ModelList` schema and every registered rule is present with its `ParamSpec[]`.
- [X] T022 [P] [US1] Add a contract test in `backend/tests/contract/` for `POST /runs` and
      `GET /runs/{run_id}`: `201` with a `Run` on success; `404` for an unknown model or symbol; `422`
      naming the offending parameter for an out-of-range value, a window shorter than the model's
      lookback, `start_date` after `end_date`, and an over-large selection.
- [X] T023 [P] [US1] Write `frontend/tests/ModelCatalog.test.tsx`: the catalog renders models from
      `GET /models` and renders a model the test invents, proving nothing about model identity is
      hardcoded.
- [X] T024 [P] [US1] Write `frontend/tests/RunConfig.test.tsx`: the parameter form is generated from
      the selected model's `ParamSpec[]` (one control per parameter, typed, bounded, default-seeded);
      an out-of-range value reports **against that specific parameter**; only overrides are submitted.
- [X] T025 [P] [US1] Write `frontend/tests/RunResults.test.tsx`: a completed run with
      `signal_count: 0` renders as a **success** state distinct from a failed run; coverage is
      rendered **whenever** a signal count is rendered, never separately.

### Implementation for User Story 1

- [X] T026 [US1] Add the request/response models to `backend/src/quantlab/api/schemas.py` mirroring
      `contracts/openapi.yaml`: `ParamSpec`, `Model`, `ModelList`, `RunRequest`, `RunCoverage`, `Run`,
      `ExperimentSignal`, `RunDetail` (depends on: T021, T022 failing first).
- [X] T027 [US1] Implement `GET /models` in `backend/src/quantlab/api/routes.py`, assembling the
      catalog from the registry at request time so registering a model changes the response with no
      code change (FR-001, SC-002) (depends on: T026).
- [X] T028 [US1] Implement `POST /runs` and `GET /runs/{run_id}` in
      `backend/src/quantlab/api/routes.py` as thin adapters over `research/runner.py`, mapping the
      typed errors from `research/errors.py` to `404`/`422` with the offending field named (depends
      on: T018, T026).
- [X] T029 [P] [US1] Create `frontend/src/workbench/ModelCatalog.tsx` — lists models from the catalog
      and publishes the selection (depends on: T023 failing first).
- [X] T030 [P] [US1] Create `frontend/src/workbench/RunConfig.tsx` — builds the parameter form from
      the selected model's declared metadata, mirrors the declared constraints for immediate feedback
      while treating the server's rejection as authoritative, and collects instruments plus a date
      range (depends on: T024 failing first).
- [X] T031 [US1] Create `frontend/src/workbench/useRuns.ts` — starts a run, exposes `inFlight` and a
      `cancel()` that aborts the in-flight request, and appends completed and failed runs to an
      in-session history (depends on: T004).
- [X] T032 [P] [US1] Create `frontend/src/workbench/RunResults.tsx` — signals as a list and marked on
      the existing `CandlestickChart`, with summary and coverage always shown together, and a
      zero-signal success state distinct from failure (depends on: T025 failing first).
- [X] T033 [US1] Register `catalog`, `runConfig`, and `runResults` panels in
      `frontend/src/workspace/panels.tsx` and add them to the default layout in
      `frontend/src/workspace/defaultLayout.ts` (depends on: T029, T030, T032).
- [X] T034 [US1] Delete the hardcoded `RULES = ['sma-crossover', 'rsi-threshold', 'breakout-20d']`
      from `frontend/src/components/SignalFilters.tsx` and source that list from the model catalog —
      leaving it would keep the constitutional gap open and make SC-002 unverifiable (depends on:
      T027).
- [ ] T035 [US1] Run `pytest` and `npm test`, then walk `quickstart.md` §2, §3, §4 and §7 — including
      **registering a fourth model and confirming it appears and is runnable with no frontend change**
      (depends on: T026–T034).

**Checkpoint**: A researcher can run any registered model over a chosen slice and read the result —
a complete, demonstrable MVP.

---

## Phase 4: User Story 2 - Tune, Re-run, and Compare (Priority: P2)

**Goal**: Keep multiple runs and make the difference between two of them explicit, in both
configuration and outcome.

**Independent Test**: Run, change one parameter, run again, and confirm both runs remain and their
differences are stated — per `quickstart.md` §5 and browser step 7.

### Tests for User Story 2 ⚠️

- [X] T036 [P] [US2] Add a contract test in `backend/tests/contract/` for `GET /runs`: returns a
      `RunList` newest-first, and `saved_only=true` returns only named runs.
- [X] T037 [P] [US2] Write `frontend/tests/RunCompare.test.tsx`: the comparison states which
      configuration values differ and how outcomes differ; and when the two runs' `model_version`
      values differ, that difference is surfaced **prominently** rather than as one field among many
      (FR-014).

### Implementation for User Story 2

- [X] T038 [US2] Implement `GET /runs` with the `saved_only` query parameter in
      `backend/src/quantlab/api/routes.py` (depends on: T016, T036 failing first).
- [X] T039 [US2] Create `frontend/src/workbench/RunCompare.tsx` — side-by-side configuration and
      outcome diff, with a model-version mismatch called out distinctly (depends on: T037 failing
      first).
- [X] T040 [US2] Extend `frontend/src/workbench/useRuns.ts` and `RunResults.tsx` so a new run never
      replaces an earlier one and any two runs in history can be selected for comparison (FR-012)
      (depends on: T031, T039).
- [ ] T041 [US2] Run `pytest` and `npm test`, then walk `quickstart.md` §5 (determinism) and browser
      steps 7–8 (depends on: T038, T039, T040).

**Checkpoint**: The workbench is a comparison instrument, not just a runner.

---

## Phase 5: User Story 3 - Keep and Reopen Named Experiments (Priority: P3)

**Goal**: Name, save, reopen, and delete experiments so work survives a session.

**Independent Test**: Save a run, reload, reopen it with configuration and results intact, then delete
it — per `quickstart.md` browser steps 9–10.

### Tests for User Story 3 ⚠️

- [X] T042 [P] [US3] Add contract tests in `backend/tests/contract/` for `PATCH /runs/{run_id}`
      (names a run; `404` unknown) and `DELETE /runs/{run_id}` (`204`; `404` unknown), and assert that
      deleting a run also removes its `experiment_signals` rows.
- [X] T043 [P] [US3] Write `frontend/tests/SavedExperiments.test.tsx`: deletion asks for confirmation
      first; a run whose `model_available` is false renders read-only and is marked not re-runnable
      (FR-017); "use as starting point" seeds a new configuration **without mutating the saved
      original** (FR-016).

### Implementation for User Story 3

- [X] T044 [US3] Implement `PATCH /runs/{run_id}` (set `name`, 1–200 characters) and
      `DELETE /runs/{run_id}` in `backend/src/quantlab/api/routes.py`, deleting a run and its signals
      together (depends on: T016, T042 failing first).
- [X] T045 [US3] Populate `model_available` on run responses in
      `backend/src/quantlab/api/routes.py` by checking the recorded `(model_name, model_version)`
      against the live registry, so a run referencing a removed model stays readable (depends on:
      T027, T044).
- [X] T046 [US3] Create `frontend/src/workbench/SavedExperiments.tsx` — list saved experiments,
      reopen one with configuration and results intact, confirm before deleting, and offer "use as
      starting point" (depends on: T043 failing first, T044).
- [X] T047 [US3] Register the saved-experiments panel in `frontend/src/workspace/panels.tsx` (depends
      on: T046).
- [ ] T048 [US3] Run `pytest` and `npm test`, then walk `quickstart.md` browser steps 9–10 (depends
      on: T044–T047).

**Checkpoint**: All three stories complete; experiments persist across sessions.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T049 [P] Add structured logging for runs in `backend/src/quantlab/research/runner.py` —
      model, version, effective parameters, selection size, duration, outcome (Constitution VI
      requires structured logging across computation paths).
- [X] T050 [P] Update `docs/SIGNAL_VIEWER_DEMO.md` and the root `README.md` to describe the workbench
      (model catalog, configured runs, saved experiments) alongside the viewer.
- [X] T051 [P] Update `docs/ARCHITECTURE.md` (and `docs/INDICATORS.md` if it documents the registry
      contract) to reflect that plugins now declare typed, bounded parameter specs.
- [X] T052 Run the full gate: `pytest` in `backend/`, then `npm run lint`, `npx prettier --check .`,
      `npm run build` and `npm test` in `frontend/`, and `make check-contract` (depends on: all
      story phases).
- [X] T053 Run `docker build --target build ./frontend` and `docker build ./backend` to confirm both
      images still build (depends on: T052).
- [ ] T054 Full `quickstart.md` pass (§1–§10), including §6's isolation check and §10's confirmation
      that the hardcoded rule list is gone (depends on: T052, T053).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup only for the regenerated client (frontend work);
  backend tasks can start immediately. **BLOCKS all user stories.**
- **US1 (Phase 3)**: Depends on Foundational.
- **US2 (Phase 4)**: Depends on Foundational **and on US1** — comparison operates on runs that US1's
  create-run path produces.
- **US3 (Phase 5)**: Depends on Foundational **and on US1** — saving operates on runs US1 creates.
- **Polish (Phase 6)**: Depends on the story phases.

### User Story Dependencies — read this before planning staffing

Unlike features `003` and `004`, **the stories here are sequential, not independent**. US2 and US3 both
act on runs, and runs only exist once US1's create path works. Attempting to build US2 or US3 in
parallel with US1 means building against an endpoint that does not yet exist. The honest parallelism
in this feature is *within* phases, not across stories.

### Within Each User Story

- Tests written and confirmed failing before implementation (Constitution IV).
- API schemas before routes; routes before the panels that call them.
- Library logic (`research/runner.py`) before the route that adapts it (Principle I).

### Parallel Opportunities

- T001 and T002 in parallel; T005–T009 (all Foundational tests) in parallel; T013/T014 and T017 in
  parallel with each other.
- Within US1: T021–T025 (all tests) in parallel; T029, T030 and T032 in parallel once their tests
  exist.
- Backend and frontend tracks within a single story can proceed in parallel once the contract and the
  regenerated client are in place (Phase 1) — e.g. T027/T028 alongside T029–T032, since the contract
  defines the boundary between them.
- Polish: T049, T050, T051 in parallel.

---

## Parallel Example: Foundational Phase

```bash
# All five foundational test files are independent:
Task: "backend/tests/test_param_specs.py"
Task: "backend/tests/test_param_specs_compat.py"
Task: "backend/tests/test_engine_overrides.py"
Task: "backend/tests/test_runner.py"
Task: "backend/tests/test_run_isolation.py"

# Then, independent implementation files:
Task: "experiment_runs DDL in storage/db.py"
Task: "experiment_signals DDL in storage/db.py"
Task: "research/errors.py"
```

---

## Implementation Strategy

### MVP First (Setup + Foundational + US1)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1.
4. **STOP and VALIDATE**: `quickstart.md` §2–§4 and §7. The decisive check is §2's "register a fourth
   model and confirm it appears with no frontend change" — that is what proves the catalog is real
   rather than a relabelled hardcoded list.
5. Demo. Running any registered model over a chosen slice and reading the result is the feature's
   core value; comparison and saving are additive.

### Incremental Delivery

1. Setup + Foundational → backend can describe, run, and store; nothing visible yet.
2. + US1 → the discovery loop works end to end (MVP).
3. + US2 → runs accumulate and can be compared.
4. + US3 → experiments survive the session.
5. Polish → logging, docs, full gate.

---

## Notes

- Tests are mandatory: write, watch fail, then implement.
- **The highest-risk tasks are T018 (warm-up window) and T019 (extending the look-ahead sweep).** A
  wrong warm-up window produces results that look plausible and are quietly misleading, which is worse
  than a crash; and parameter overrides are an execution path the existing sweep has never covered.
- **T009's isolation test is the guard on an existing screen**: run output inserted into the seeded
  `signals` table would appear in the Signal Viewer, and the existing schema would accept it happily.
- No new third-party dependency is introduced anywhere in this list — a consequence of scoping to
  registered models and the existing universe.
- All code lands in `backend/` and `frontend/`; nothing under `quantlab_specs/` (Constitution).

---

## Implementation Status Note (added by /speckit-implement)

**Backend: 107 tests pass (from 52), ruff clean. Frontend: 73 tests pass (from 66), lint/format/
tsc/build clean. Both Docker images build. `make check-contract` passes against the relocated
authored contract.**

**SC-002 was verified for real, not assumed.** A model (`zeta-reversion`) was registered at
runtime with an invented parameter name, and without any frontend change it appeared in the
catalog, was fully described with its own bounds, ran successfully, and rejected an out-of-range
value naming that invented parameter. That is the check separating a real catalog from a
relabelled hardcoded list.

### Remaining: manual browser passes only

The backend half of this feature is verifiable headlessly and has been. What is NOT machine-verified
is how the workbench *looks and feels* in a browser — the panels render under a mocked docking
library in tests, as in feature 004.

- **T035 / T041 / T048** — the browser halves: parameter form usability, run progress and cancel,
  comparing two runs side by side, saving and reopening an experiment.
- **T054** — full `quickstart.md` §1–§10 pass against `make up`.

### Deviations worth knowing

1. **US2/US3 backend shipped early.** `GET /runs`, `PATCH /runs/{id}` and `DELETE /runs/{id}` were
   written in the same block as US1's routes rather than in their own phases. They are contract-
   tested. The remaining US2/US3 work is frontend (compare view, saved-experiments panel).
2. **TDD order was broken for the route layer.** Routes and schemas were implemented before
   `test_workbench_contract.py` was written, contrary to the plan. Every other component followed
   write-test-watch-it-fail-then-implement.
3. **`SignalFilters` gained a `ruleNames` prop** instead of reading workbench context. Reaching into
   context from a controlled presentational component was the wrong coupling; the panel supplies the
   list from the catalog.
