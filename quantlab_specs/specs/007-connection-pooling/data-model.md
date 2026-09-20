# Data Model: Reusable Warehouse Connections

No persisted data changes. No table, column, index or migration is added, and the
API contract is unchanged. The entities here are process-local runtime objects and
configuration.

## Configuration

Read once per process from the environment, at pool construction.

| Setting | Env var | Type | Default | Constraint |
|---|---|---|---|---|
| Catalog ceiling | `QUANTLAB_PG_POOL_MAX` | int | `5` | >= 1 |
| Bar-store ceiling | `QUANTLAB_CH_POOL_MAX` | int | `5` | >= 1 |
| Acquisition wait | `QUANTLAB_POOL_TIMEOUT` | float (seconds) | `10.0` | > 0 |

An unparseable or out-of-range value falls back to the default and logs a warning.
Refusing to start would turn a typo in an optional tuning knob into an outage, and
these are tuning knobs, not correctness settings.

## Runtime entities

### `Warehouse` (existing, extended)

Already holds the resolved `dsn` and ClickHouse settings. Gains two lazily created,
process-local pools. One `Warehouse` per application instance.

| Field | Meaning |
|---|---|
| `dsn` | Postgres connection string (existing) |
| `ch` | ClickHouse client kwargs (existing) |
| catalog pool | Created on first `catalog()`; `None` until then |
| bar-store pool | Created on first `bars()`; `None` until then |

**Lifecycle**: constructed at application start without touching the network; each
pool opens on first use; both are released when the process exits.

### Catalog pool

A `psycopg_pool.ConnectionPool`. State per connection is owned by the driver: idle,
checked out, or discarded after a failed liveness check.

**Invariants**
- Never more than `QUANTLAB_PG_POOL_MAX` connections exist at once.
- A connection is returned on every exit path, including exceptions and client
  disconnects.
- A connection handed to a request carries no transaction and no session state from
  a previous one.
- A connection failing its liveness check is discarded and replaced, never handed out.

### Bar-store pool

A bounded pool of `clickhouse_connect` `Client` objects. Written here because the
driver ships none, and a `Client` cannot be shared between threads.

| State | Meaning |
|---|---|
| idle | In the pool, available |
| checked out | Held by exactly one request |
| discarded | Failed `ping()` or raised a connection error; replaced on next acquire |

**Invariants**
- At most `QUANTLAB_CH_POOL_MAX` clients exist at once.
- A client is held by at most one request at a time — this is the thread-safety
  requirement, not an optimisation.
- A client is returned on every exit path.
- A client that has failed is not returned to the pool.

## State transitions

```
        ┌────────── acquire (waits up to QUANTLAB_POOL_TIMEOUT) ──────────┐
        ▼                                                                │
     idle ──── liveness check ──── fails ────▶ discarded ──▶ replaced ───┘
        │
        └─ passes ─▶ checked out ─┬─ request succeeds ─▶ reset ─▶ idle
                                  ├─ request raises ───▶ rollback ─▶ idle
                                  ├─ connection error ─▶ discarded
                                  └─ caller disconnects ▶ reset ─▶ idle
```

Exhaustion: when no connection is idle and the ceiling is reached, the request waits
up to the timeout, then fails with a clear error (FR-009, SC-007). It never opens an
extra connection beyond the ceiling and never waits indefinitely.

## What is deliberately absent

- **No cross-instance coordination.** The ceiling is per instance, as the spec's
  assumptions state. A global budget is the deployment's arithmetic: ceiling x
  expected instances must fit the database's limit.
- **No pooling on the demo path.** `SqliteBackend` is unchanged; it opens a local
  file and has no connection budget to exhaust.
- **No caching of query results.** Connections are reused; answers are not. Caching
  would change observable results and is excluded by FR-012.
