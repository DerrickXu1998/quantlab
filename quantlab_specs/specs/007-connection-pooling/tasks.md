---
description: "Task list for 007-connection-pooling"
---

# Tasks: Reusable Warehouse Connections

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Research**: [research.md](research.md)

Tests are written first and shown to fail before implementation (Constitution IV,
NON-NEGOTIABLE). `[P]` marks tasks touching different files with no dependency on
incomplete work.

**MVP scope**: Phase 3 (US1 + US2). Those two stories are both P1 and must ship
together — shipping availability without the correctness guarantees would trade a
visible failure for a silent one.

---

## Phase 1: Setup

- [X] T001 Add the `pool` extra in `backend/pyproject.toml`, changing `psycopg[binary]>=3.1` to `psycopg[binary,pool]>=3.1`
- [X] T002 Rebuild the backend image and confirm `psycopg_pool` imports inside it, via `docker compose build backend && docker compose run --rm --no-deps backend python -c "import psycopg_pool"`
- [X] T003 Record the pre-change baseline for SC-005 in `specs/007-connection-pooling/quickstart.md`: run one `sma-crossover` experiment and save its `signal_count` and `coverage`

---

## Phase 2: Foundational (blocking — every user story depends on these)

- [X] T004 Write failing tests for configuration resolution in `backend/tests/unit/test_pooling.py`: defaults of 5/5/10.0, env overrides honoured, and an unparseable or out-of-range value falling back to the default with a logged warning rather than raising
- [X] T005 Implement `pool_config()` in `backend/src/quantlab/storage/pool.py` reading `QUANTLAB_PG_POOL_MAX` (default 5), `QUANTLAB_CH_POOL_MAX` (default 5), `QUANTLAB_POOL_TIMEOUT` (default 10.0), to satisfy T004
- [X] T006 Verify no module-scope driver import was introduced, by running `backend/tests/unit/test_demo_fallback.py` unchanged — it makes `psycopg` and `clickhouse_connect` unimportable and is the tripwire for FR-010/FR-011

---

## Phase 3: User Story 1 + 2 — bounded reuse that does not leak state (P1) 🎯 MVP

**Goal**: Connections are reused and bounded, and a reused connection never carries
state from the request before it.

**Independent test**: Drive 100 concurrent requests at a catalog permitting fewer
connections than per-request demand would need; all succeed, peak connections stay
under the ceiling, and the existing experiment suites produce identical output.

### Tests first

- [X] T007 [P] [US1] Write failing concurrency tests for `ClientPool` in `backend/tests/unit/test_pooling.py`: N threads acquiring simultaneously never exceed the ceiling, and a client is held by at most one thread at a time
- [X] T008 [P] [US1] Write a failing test that a second acquire reuses the first client rather than constructing a new one, asserted by identity
- [X] T009 [P] [US1] Write a failing test that acquisition past the ceiling raises a clear error within `QUANTLAB_POOL_TIMEOUT` and does not hang (FR-009, SC-007)
- [X] T010 [P] [US2] Write a failing test that a client is returned to the pool when the caller raises, and when the caller abandons the block (FR-006)
- [X] T011 [P] [US2] Write a failing test that a catalog connection handed to a request carries no open transaction and no altered session setting from a previous request (FR-005)

### Implementation

- [X] T012 [US1] Implement `ClientPool` in `backend/src/quantlab/storage/pool.py`: bounded, thread-safe, `acquire()` as a context manager, returning the client on every exit path, to satisfy T007–T010
- [X] T013 [US1] Convert `Warehouse.bars()` in `backend/src/quantlab/storage/warehouse.py` into a context manager over a lazily created `ClientPool`, keeping `import clickhouse_connect` inside the function
- [X] T014 [US2] Convert `Warehouse.catalog()` in `backend/src/quantlab/storage/warehouse.py` into a context manager over a lazily created `psycopg_pool.ConnectionPool(open=False, max_size=…, timeout=…)`, keeping `import psycopg_pool` inside the function
- [X] T015 [US2] Confirm every existing call site of `catalog()` and `bars()` in `backend/src/quantlab/storage/warehouse.py` still uses the `with` form unchanged, and adjust any that do not
- [X] T016 [US2] Run `backend/tests/unit/test_experiment_store.py` and `backend/tests/contract/` unchanged and confirm identical results (SC-005, FR-012)

**Checkpoint**: MVP complete — reuse is bounded and state-safe.

---

## Phase 4: User Story 3 — recovery without an API restart (P2)

**Goal**: A restarted or idle-timed-out database heals on the next request.

**Independent test**: Serve traffic, restart the catalog, keep serving — without
restarting the API.

- [X] T017 [P] [US3] Write a failing test that a pooled ClickHouse client failing `ping()` is discarded and replaced rather than handed to a request (FR-007)
- [X] T018 [P] [US3] Write a failing test that a closed or broken catalog connection is not served, and that the pool recovers once the database is reachable again (FR-008)
- [X] T019 [US3] Add liveness checking to `ClientPool.acquire()` in `backend/src/quantlab/storage/pool.py` — `ping()` before handing out, discard and replace on failure
- [X] T020 [US3] Pass `check=ConnectionPool.check_connection` to the catalog pool in `backend/src/quantlab/storage/warehouse.py` so a dead connection is discarded before use
- [X] T021 [US3] Verify SC-004 by hand: `docker compose restart postgres` while the API is serving, then confirm a successful request within 30 seconds with no backend restart

**Checkpoint**: The API self-heals.

---

## Phase 5: User Story 4 — the demo path is untouched (P2)

**Goal**: Clone, start, run — no databases, no credentials, no network.

- [X] T022 [US4] Run `backend/tests/unit/test_demo_fallback.py` unchanged in the container with `QUANTLAB_DB_URL=` and `QUANTLAB_CH_URL=` empty and confirm it passes (SC-006)
- [X] T023 [US4] Confirm `SqliteBackend` in `backend/src/quantlab/storage/backends.py` is unmodified and constructs no pool
- [X] T024 [US4] Confirm the application starts with no database reachable, asserting FR-011 is preserved by the lazy construction in T013/T014

**Checkpoint**: Zero-setup guarantee intact.

---

## Phase 6: Observability and documentation

- [X] T025 [P] Write a failing test that pool exhaustion and connection replacement each emit a structured log record, and that a successful acquisition does not (FR-014)
- [X] T026 Emit those records via `quantlab.logging` in `backend/src/quantlab/storage/pool.py` and `backend/src/quantlab/storage/warehouse.py`
- [X] T027 [P] Document the pools, the three variables and their defaults in `docs/STORAGE.md`
- [X] T028 [P] Add the three variables to the configuration table in `docs/ARCHITECTURE.md` §11
- [X] T029 [P] Record the measured connection costs and the `Client` thread-safety finding in `docs/STORAGE.md`, so the next reader does not re-derive them

---

## Phase 7: Verification

- [X] T030 Run the full backend suite on the host (`cd backend && ./.venv/bin/python -m pytest -q`) and in the container with warehouse vars unset; both green
- [X] T031 Run `./.venv/bin/python -m ruff check src tests` clean
- [X] T032 Run `make check-warehouse` against the local stack
- [X] T033 Execute the SC-003 scenario in `quickstart.md`: 50 identical requests open no new connections beyond the ceiling
- [X] T034 Execute the SC-001/SC-002 scenario: 100 requests at concurrency 20 all return 200, peak connections stay within `QUANTLAB_PG_POOL_MAX`
- [X] T035 Execute the SC-007 scenario with `QUANTLAB_PG_POOL_MAX=1 QUANTLAB_POOL_TIMEOUT=2` and confirm no request materially exceeds the timeout
- [X] T036 Re-run the T003 baseline experiment and confirm `signal_count` and `coverage` are identical (SC-005)

---

## Dependencies

```
Phase 1 (T001-T003)
   └─▶ Phase 2 (T004-T006)          blocking for everything
          ├─▶ Phase 3 (T007-T016)   US1+US2 — the MVP
          │      ├─▶ Phase 4 (T017-T021)  US3, needs the pools to exist
          │      └─▶ Phase 5 (T022-T024)  US4, verification only
          └─────────▶ Phase 6 (T025-T029)  needs the pools to exist
                          └─▶ Phase 7 (T030-T036)
```

Within Phase 3, T007–T011 are all `[P]` (same new test file, independent cases) and
must be failing before T012. T013 and T014 both edit `warehouse.py` and are
therefore sequential.

## Parallel opportunities

- **Phase 3 tests**: T007, T008, T009, T010, T011 together
- **Phase 4 tests**: T017, T018 together
- **Phase 6 docs**: T027, T028, T029 together, alongside T025

## Independent test criteria

| Story | Proven by |
|---|---|
| US1 — works under load | T034: 100 requests at concurrency 20, all 200, peak under ceiling |
| US2 — results unchanged | T016 + T036: existing suites unchanged, experiment output identical |
| US3 — self-healing | T021: restart the catalog, next request succeeds, no API restart |
| US4 — demo untouched | T022: `test_demo_fallback.py` passes with drivers unimportable |

---

## Implementation notes (2026-09-20)

All 36 tasks complete. Three deviations from the plan, recorded rather than
silently absorbed:

1. **T015 was larger than planned.** The plan asserted every call site already used
   the `with` form. True for `catalog()`, false for `bars()` — all 7 used
   `client = wh.bars()` with `try/finally: client.close()`. Converted to `with`;
   body indentation was already correct, so the change was mechanical, and
   `health()` needed its own handling because it guarded acquisition separately.

2. **A pre-existing test-isolation defect blocked verification.** Running the suite
   against a live Postgres failed with `UniqueViolation` on `experiment_runs_pkey`:
   the `postgres_store` fixture never cleaned up, so the suite passed only once per
   database, and two tests asserted exclusive ownership of the table. Unrelated to
   pooling — it surfaced only because these tests had never actually run against a
   reachable catalog. The fixture now diffs run ids and removes what it created, and
   the two tests assert "contains, in order" instead of "equals". Suite time went
   from 295 s to 4 s; the 295 s was collision retries, not pooling.

3. **A test of mine was wrong.** `test_deployment.py` reads the Dockerfile, which
   the image does not copy, so it failed inside the container. Now skipped when the
   file is absent.

One assertion was deliberately changed: `test_client_is_closed_even_though_rows_were_returned`
asserted the client is *closed* after a read. Under pooling it is *returned* —
closing it is precisely the behaviour removed. Renamed and rewritten to assert the
invariant that still matters (the client is released on every exit path, including
failure), plus a new test for the failing-read path.

### Measured results

| Criterion | Result |
|---|---|
| SC-001 | 100 requests at concurrency 20 → all HTTP 200 |
| SC-002 | Peak catalog connections 5, exactly the ceiling |
| SC-003 | 50 identical requests → connections unchanged at 2 |
| SC-004 | Catalog restarted; recovered in 2 s, API never restarted |
| SC-005 | Baseline experiment identical: 14 signals, coverage 3/3/3 |
| SC-006 | Demo path green with both drivers unimportable |
| SC-007 | Ceiling 1 / 20 concurrent → all 200, slowest 3.3 s, none hung |

### Known residue (not this feature)

Contract tests fail when run with the warehouse env vars set: they seed a temporary
SQLite database, but `create_app` selects the warehouse whenever both URLs are
present and ignores the supplied path. `make test` hides this by running `--no-deps`.
Documented in `docs/ARCHITECTURE.md` §9.
