# Implementation Plan: Reusable Warehouse Connections

**Feature**: `007-connection-pooling` | **Created**: 2026-09-20 | **Spec**: [spec.md](spec.md)

## Summary

The API opens a fresh Postgres connection and a fresh ClickHouse client per request.
Measured in-container, that is **9.86 ms** and **6.76 ms** of avoidable work per
request — 62x and 7x the cost of the queries themselves — and it makes the API's
connection demand grow with instance count against a catalog whose
`max_connections` is **100**.

Replace per-request construction with two bounded, lazily created, process-local
pools behind the existing `Warehouse.catalog()` and `Warehouse.bars()` methods.
Nothing above the storage layer changes: no contract change, no schema change, no
new analytical code.

## Technical Context

| | |
|---|---|
| Language | Python 3.12 (backend image), 3.11 (host venv) |
| Affected package | `backend/src/quantlab` only — the research library is untouched |
| New dependency | `psycopg[pool]` extra (pure Python, same authors as the driver) |
| Drivers in image | psycopg 3.3.6, clickhouse-connect 1.8.0 |
| Concurrency model | Sync handlers on Starlette's thread pool — pools must be thread-safe |
| Contract impact | **None.** `openapi.yaml` unchanged |
| Storage impact | **None.** No migration |

**Verified, not assumed** (see [research.md](research.md)):
- clickhouse-connect already shares a urllib3 `PoolManager` (`maxsize=8`,
  `block=False`), so sockets and TLS are already reused; the remaining cost is
  `Client` construction.
- `clickhouse_connect` `Client` carries **no lock** and exposes mutable `database`
  state, so it cannot be shared across threads. This rules out the one-shared-client
  design and forces a pool of clients.
- `psycopg_pool` is **not currently installed**; it arrives with the `pool` extra.

## Constitution Check

| Principle | Assessment |
|---|---|
| I. Library-First | Pools live in the storage library behind the existing seam; no logic moves into handlers. **Pass** |
| II. Pluggable indicators | Untouched. **N/A** |
| III. Data integrity & sources | No provider, no ingest, no source change. **N/A** |
| IV. Test-First (NON-NEGOTIABLE) | Every task below writes failing tests first, including the concurrency and restart-recovery cases that are the point of the feature. **Pass** |
| V. Typed contract boundary | Contract unchanged; no computation added to the request path (FR-013). **Pass** |
| VI. Reproducibility | Connections are reused; results are not cached (FR-012). Identical inputs still give identical output, asserted by SC-005. **Pass** |
| VII. Point-in-time | Untouched. **N/A** |
| Repository structure | Code in `backend/`, spec in `quantlab_specs/`. **Pass** |
| Tech stack & YAGNI | One dependency added, justified in research.md Decision 1: it replaces transaction-reset and liveness-check code we would otherwise hand-write. The ClickHouse pool **is** hand-written, because no library offers one. **Pass, recorded** |

No violations. Nothing to enter in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```
specs/007-connection-pooling/
├── spec.md              # what and why
├── plan.md              # this file
├── research.md          # measurements and the five decisions
├── data-model.md        # config + runtime entities, invariants
├── quickstart.md        # one runnable check per success criterion
└── checklists/requirements.md
```

No `contracts/` directory: this feature changes no external interface.

### Source code

```
backend/src/quantlab/storage/
├── pool.py          NEW  bounded client pool for ClickHouse + config resolution
└── warehouse.py     MOD  Warehouse gains two lazy pools; catalog()/bars() become
                          context managers over them

backend/tests/unit/
├── test_pooling.py      NEW  ceiling, reuse, return-on-error, liveness, timeout
└── test_demo_fallback.py     UNCHANGED — must still pass, proves FR-010/FR-011

backend/pyproject.toml   MOD  psycopg[binary] -> psycopg[binary,pool]
docs/STORAGE.md          MOD  document the pools and their configuration
```

## Phases

### Phase 1 — Configuration and the ClickHouse pool

New `storage/pool.py`:
- `pool_config()` reads `QUANTLAB_PG_POOL_MAX`, `QUANTLAB_CH_POOL_MAX`,
  `QUANTLAB_POOL_TIMEOUT`; bad values fall back to defaults with a logged warning
  rather than refusing to start (data-model.md).
- `ClientPool`: bounded, thread-safe, `acquire()` as a context manager. Checks
  liveness with `ping()` before handing out, discards and replaces on failure,
  returns the client on every exit path, and raises a clear error after the timeout.

Tests first: ceiling never exceeded under concurrent acquire; a client is reused
rather than reconstructed; a client is returned after the caller raises; a client
failing `ping()` is replaced not served; acquisition past the ceiling times out
within the configured wait.

### Phase 2 — Wire both pools into `Warehouse`

- `catalog()` becomes a context manager over a lazily created
  `psycopg_pool.ConnectionPool(open=False, max_size=…, timeout=…, check=…)`.
- `bars()` becomes a context manager over the `ClientPool`.
- Driver imports stay inside the functions, and neither pool is constructed in
  `create_app` — startup must still touch no network.

Every call site already uses `with wh.catalog() as conn:`, so the shape is
unchanged; this is why the blast radius stays inside `warehouse.py`.

### Phase 3 — Recovery and observability

- Assert a restarted database heals without an API restart (SC-004) and that a stale
  connection is discarded rather than served (FR-007).
- Log exhaustion and replacement through `quantlab.logging`; do not log successful
  acquisition (FR-014, research.md Decision 6).

### Phase 4 — Verification and docs

- Full suite host and container; `make check-warehouse`; the `quickstart.md`
  scenarios including the 100-request concurrency check and the forced-exhaustion
  check.
- `docs/STORAGE.md` gains the pool section and the three variables.
- `docs/ARCHITECTURE.md` §11 gains the three variables.

## Risks

1. **`test_demo_fallback.py` is the tripwire.** It makes both drivers unimportable.
   Any module-scope `import psycopg_pool` breaks the zero-setup guarantee, and this
   suite is what catches it. Keep imports inside functions.
2. **Transaction semantics change with reuse.** `pool.connection()` commits on clean
   exit where the current code's `with psycopg.connect(...)` also commits — same
   behaviour, but it must be asserted rather than assumed (FR-005, US2).
3. **Thread-pool size vs. ceiling.** With a ceiling below Starlette's thread count,
   excess concurrency now *queues* rather than opening connections. That is the
   intent, but it converts a connection error into latency; SC-007 bounds it.
4. **Hand-written pool.** The ClickHouse pool is ours to get right — concurrency
   tests are not optional there.
