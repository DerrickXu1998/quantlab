# Research: Reusable Warehouse Connections

All figures below were measured in the backend container against the local stack on
2026-09-20. Against a remote managed database every connection cost is larger; these
are the floor, not the expected case.

## The measurement that justifies the work

| Store | Connect + query | Query on a reused connection | Avoidable per request |
|---|---:|---:|---:|
| Postgres | 10.02 ms | 0.16 ms | **9.86 ms (62x the query)** |
| ClickHouse | 7.74 ms | 0.98 ms | **6.76 ms (7x the query)** |

A request touching both stores pays ~16.6 ms of pure connection setup. The work the
request actually exists to do costs ~1.1 ms.

`SHOW max_connections` on the catalog returns **100**. FastAPI runs this project's
synchronous handlers in Starlette's thread pool, so one instance can hold as many
simultaneous connections as it has busy threads. Three or four instances under load
exceed the budget, and the symptom is a refusal on a request that was otherwise
valid — which is SC-001.

## Decision 1 — Postgres: `psycopg_pool.ConnectionPool`

**Decision**: Add the `pool` extra (`psycopg[binary,pool]`) and hold one
`ConnectionPool` per process, created lazily.

**Rationale**: It is the pool written by the driver's own authors, it is thread-safe,
and it already implements every requirement this feature has. `max_size` is FR-003;
`timeout` is FR-009; `check=ConnectionPool.check_connection` discards a dead
connection before handing it out, which is FR-007 and FR-008. Critically, the
`pool.connection()` context manager commits on clean exit, rolls back on exception,
and resets session state before returning the connection — that is FR-005, the
requirement most likely to be got wrong by hand.

**Alternatives considered**:
- *Hand-rolled queue of connections*: every one of the above would have to be
  reimplemented, including transaction reset. Rejected — this is the precise case
  the YAGNI clause says not to build.
- *PgBouncer sidecar*: solves it at the infrastructure layer and is the right answer
  at much higher scale, but it is another deployable component for a project whose
  whole deployment story is being simplified. It also does not help ClickHouse.
- *Cap `max-instances` and accept per-request connections*: makes the ceiling a
  platform setting nobody reads, and leaves the 9.86 ms untouched.

## Decision 2 — ClickHouse: a bounded pool of clients, not a shared client

**Decision**: A small bounded pool of `Client` objects guarded by a queue, with
`client.ping()` as the liveness check.

**Rationale**: `clickhouse-connect` ships no pool. Two things were verified in the
container rather than assumed:

1. **HTTP connections are already pooled.** Clients share a module-level urllib3
   `PoolManager` (`maxsize=8`, `block=False`). So TCP and TLS are *already* reused
   across `get_client()` calls in one process.
2. **The remaining 6.76 ms is `Client` construction**, not the socket — and
   `Client` is **not safe to share across threads**: it carries no lock and exposes
   mutable per-instance state such as `database`.

Those two facts together rule out both obvious designs. Sharing one client is a data
race. Constructing per request is what we are removing. A bounded pool of clients is
what is left, and it is small: acquire, use, return, replace on failure.

`block=False` on the urllib3 manager also means the HTTP layer will quietly exceed
`maxsize` rather than bound itself, so the ceiling has to be enforced by our pool,
not inherited from urllib3.

**Alternatives considered**:
- *One shared `Client`*: rejected on the thread-safety evidence above.
- *Rely on urllib3 pooling alone*: leaves construction cost and enforces no ceiling.
- *`clickhouse-driver` (native protocol) which has a pool*: a second driver for the
  same database, and a rewrite of every read path. Rejected.

## Decision 3 — Lazy creation, so startup still needs no database

**Decision**: Pools are created on first use, not at application start.

**Rationale**: FR-011 and the existing `test_demo_fallback.py` guarantee the app
starts with no database reachable and no drivers installed. A pool constructed in
`create_app` with `open=True` would connect eagerly and break that. `ConnectionPool`
defaults to opening in the background; it will be constructed with `open=False` and
opened on demand, and the driver imports stay inside the functions that use them, as
they already are.

## Decision 4 — Where the pools live

**Decision**: On the `Warehouse` object in `backend/src/quantlab/storage/warehouse.py`,
behind the existing `catalog()` and `bars()` methods, which become context managers.

**Rationale**: Every read path already goes through those two methods, so the change
is contained and `StorageBackend`'s protocol is untouched. The demo path never
constructs a `Warehouse`, so FR-010 holds by construction rather than by a branch.

**Consequence**: `catalog()` and `bars()` currently return a raw connection that
callers use in a `with` block. Returning a pooled connection from a context manager
keeps every call site's shape identical, which is what keeps this a storage-layer
change rather than a refactor of the whole read path.

## Decision 5 — Configuration

| Variable | Default | Meaning |
|---|---|---|
| `QUANTLAB_PG_POOL_MAX` | 5 | Ceiling on catalog connections per instance |
| `QUANTLAB_CH_POOL_MAX` | 5 | Ceiling on bar-store clients per instance |
| `QUANTLAB_POOL_TIMEOUT` | 10.0 | Seconds a request waits before failing (FR-009) |

**Rationale for a default of 5**: with a 100-connection budget and headroom for
migrations and ad-hoc sessions, 5 per instance supports a dozen instances. It is
deliberately well below Starlette's thread-pool size so the ceiling — not the thread
count — is what bounds connections. Deployments raise it knowingly.

## Decision 6 — Observability

**Decision**: Log pool exhaustion and connection replacement through the existing
`quantlab.logging` structured logger.

**Rationale**: FR-014. A deployment approaching its ceiling should be visible before
it starts refusing requests; waiting for SC-007 failures to appear in user-facing
errors is too late. Acquisition on the happy path is not logged — per-request logging
of a successful acquire is noise at this volume.

## Open risk carried into the plan

`psycopg[pool]` adds a dependency to an image that is deliberately lean. It is pure
Python, maintained by the psycopg authors, and replaces code we would otherwise write
and test ourselves — the Constitution's dependency clause is satisfied, but the plan
records it explicitly rather than letting it pass unremarked.
