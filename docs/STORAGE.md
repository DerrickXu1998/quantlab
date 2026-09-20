# Storage

Historical market data lives in two stores, split by the shape of the data
rather than by convenience.

| | ClickHouse | Postgres |
|---|---|---|
| Holds | `price_bars` | instruments, symbol maps, universe snapshots, ingest runs, rejects, corporate actions, fundamentals, signals |
| Shape | append-only, enormous, scan-heavy | small, mutable, relational |
| Why there | columnar scans, 10–30× compression, built for time series | foreign keys, unique/exclusion constraints, transactions |

The rule of thumb: **anything with bar-level cardinality goes to ClickHouse;
anything that needs a constraint stays in Postgres.**

## Why not one system

*Postgres only* works fine at daily-bar scale (NYSE+LSE is ~30–150M rows), but
a full-panel scan costs 30–60s versus 1–2s columnar, and that is the loop you
sit in while modelling. It also does not extend to intraday.

*ClickHouse only* costs the integrity guarantees. ClickHouse has no foreign
keys, no unique constraints, no exclusion constraints, and no multi-statement
transactions. The catalog is where correctness is cheap to enforce, so it stays
in Postgres.

## Design decisions worth knowing

**Surrogate instrument ids.** Over a 30-year horizon tickers get reused —
FB→META, and dead tickers reassigned to unrelated companies. Nothing keys on
ticker text. `symbol_map` binds a vendor ticker to an instrument over a date
range, and a GiST exclusion constraint makes it impossible for one vendor
symbol to point at two instruments on the same day.

**`ts` is a timestamp, not a date.** Daily bars are stored at 00:00:00 UTC of
the session date. Moving to minute or tick data is then a change of what goes
in the column, not a migration of 10⁹ rows.

**Adjustment is derived, never stored.** `adj_close` is kept only as the
vendor's opinion on the day it was fetched, and it is not authoritative:
adj_close today differs from adj_close as of 2019. Splits and dividends live in
`corporate_actions` so an adjustment factor can be rebuilt for any as-of date.
Storing only the adjusted series silently poisons backtests, invisibly.

**Currency is recorded twice.** `instruments.currency` is what the stored
numbers are in (GBP); `quote_currency` is what the vendor quoted (GBX for
London pence). Normalisation happens at the adapter boundary. Keeping both is
what makes a 100× pence/pound error detectable after the fact.

**Universe membership is append-only,** enforced by a trigger. A snapshot you
can edit after the fact is not a snapshot, and reconstructing the historical
universe is the only free defence against survivorship bias.
`make universe-snapshot` archives the currently ingested universe (real
instruments with bars; synthetic and macro pseudo-instruments excluded).

**Fundamentals are point-in-time by `filed_at`.** The `fundamentals` table
(migration 004) holds raw XBRL facts from SEC EDGAR and Companies House: one
row per (instrument, taxonomy, tag, unit, fiscal period, filing). Identity
includes the filing's accession/document id, so restatements land as new rows
with a later `filed_at` — never edits — and re-ingesting one filing is a no-op
via `ON CONFLICT DO NOTHING`. A backtest at as-of date D reads
`filed_at <= D` and takes the latest filing per concept; the `CONCEPT_TAGS` /
`UK_TAGS` fallback chains are resolved at read time, not stored. CIK and
company number live on `instruments` (and can bind through `symbol_map`), so
no separate identifier bridge table exists.

The same table also carries two daily metric series, modelled as publications
rather than filings: FINRA short *volume* (`provider='finra'`, tags
`short_volume`/`short_exempt_volume`/`total_volume` in shares, `period_end =
filed_at =` trade date, `accession` the file name) and FCA net short *interest*
(`provider='fca'`, tag `net_short_position_pct`, one row per holder disclosure
with the holder as accession, `filed_at =` position date + 2 business days for
the T+2 basis). Both are idempotent on the same row identity and never touch
ClickHouse.

**Provenance is per batch.** Every bar carries `run_id`, a foreign key in
spirit to `ingest_runs`. That is ~8 bytes a row instead of duplicating source
strings across 100M rows, and it gives full lineage for any value.

**OpenFIGI identifiers land in three places, no new table.** `make
map-identifiers` resolves every real instrument against keyless OpenFIGI
(25 req/min × 10 jobs, resumable via `--only-missing`). The exchange-level
FIGI goes into `instruments.figi` and a `symbol_map` row under
`source='openfigi'` — the same vendor-identifier binding every other source
uses — while the rest of the mapping payload (composite FIGI, name, exchange
code, market sector, security type, mapped-at date) folds into
`meta.openfigi`. Synthetic and macro pseudo-instruments are never submitted.

## Idempotency

`price_bars` is a `ReplacingMergeTree(run_id)`: re-ingesting a range writes
rows with a higher `run_id` that supersede the earlier copies.

**Collapsing happens at merge time, not at insert.** Immediately after a
re-ingest the raw table genuinely holds both copies. Therefore:

> Always read through the `price_bars_current` view, never the `price_bars`
> table. The view applies `FINAL`, which forces the dedup.

After a large backfill, `quantlab ingest --optimize` (or `OPTIMIZE TABLE
price_bars FINAL`) pays the merge cost once rather than on every read.

## Consistency across the two stores

There is no transaction spanning Postgres and ClickHouse. The write order is
the consistency mechanism:

1. Catalog: upsert instruments, snapshot the universe, open the run. **Commit.**
2. ClickHouse: insert bars tagged with that `run_id`.
3. Catalog: record rejects, close the run with real counts. **Commit.**

A crash between 2 and 3 leaves the run `running` — the honest state: bars may
be present but nothing has vouched for them. `quantlab coverage` surfaces
those. Re-running the same range is always safe. What cannot happen is bars
that no run vouches for.

## Validation

ClickHouse will accept anything, so bars are validated in the library before
insert: positive prices, OHLC ordering, non-negative volume. Failures are
written to `ingest_rejects` with a reason and the original payload — never
dropped silently, and never allowed to abort a 5,000-symbol refresh over one
bad tick. Free sources do ship bad ticks; Yahoo's HSBA.LON history contains a
bar whose low sits above its open.

## Synthetic data

The warehouse can be seeded with deterministic synthetic bars so the whole
stack — `make signals`, the API's warehouse mode, modelling notebooks — works
with no network and no vendor keys:

```bash
make seed-warehouse          # inside the ingest container: quantlab seed-synthetic
make signals
```

`quantlab.synthetic.generate_bars(symbol, start, end, seed=...)` produces
daily OHLCV bars on a weekday calendar using a regime-switching model
(trend / mean-reversion / high-volatility segments, mixed per instrument
profile). All randomness derives from `sha256(seed + symbol)` fed to a PCG64
generator — there is no wall-clock input, so the same arguments produce
byte-identical bars on any machine. The default universe is 25 fictitious
tickers (`ZX1.US` … `ZX25.US`) across four regime profiles, chosen so every
starter signal rule (SMA crossover, RSI threshold, 20d breakout) fires
somewhere in the data.

Seeding goes through the same write path as a real ingest: instruments are
upserted into the Postgres catalog (with `meta.synthetic = true`), an
`ingest_runs` row with `source = 'synthetic'` records the run, and bars land
in ClickHouse tagged with that `run_id`. Re-running `make seed-warehouse` is
safe — ReplacingMergeTree supersedes the earlier copy of every bar, and the
values written are identical anyway. Synthetic and real symbols coexist; the
`synthetic` flag and the run's provenance keep them distinguishable.

## Commands

```bash
make migrate     # apply pending migrations to both stores
make ingest      # SYMBOLS="AAPL.US HSBA.LON" START=2015-01-01
make seed-warehouse  # deterministic synthetic bars, no network
make map-identifiers  # OpenFIGI FIGIs for every real instrument (keyless, resumable)
make universe-snapshot  # archive the current ingested universe (append-only)
make coverage    # what is held, where it came from, compression ratios
make signals     # recompute signals from bars into the catalog
make store-test  # store test suite against the live stack
make db-shell    # psql into the catalog
make ch-shell    # clickhouse-client into the bars
```

The API picks its dataset automatically: with `QUANTLAB_DB_URL` and
`QUANTLAB_CH_URL` set it serves the real warehouse, otherwise it falls back to
the synthetic SQLite demo (`--profile demo`), which needs no network and no
databases.

## Modelling

`store.load_panel(conn, client, ...)` returns the same `(date, symbol)` long
panel `quantlab.data.load` does, so modelling code does not care whether bars
came off the wire or out of the warehouse. Passing `universe_snapshot=` limits
the panel to who was actually in the universe on that date.

For reproducibility, `store.panel_for_modelling(...)` materialises a panel to
Parquet. ClickHouse is fast enough to model against directly, but a pinned file
is an artefact a backtest result can be traced back to; a live query is not.

## Connection reuse

Both halves of the warehouse are reached through bounded, per-process pools
(feature 007). They replaced per-request connections, which were the right trade
for one long-lived container beside its databases and the wrong one on a platform
that runs several instances: connection cost was paid per request, and total demand
grew with instance count against a fixed database budget.

Measured in the backend container against the local stack:

| Store | Connect + query | Query on a reused connection | Avoidable per request |
|---|---:|---:|---:|
| Postgres | 10.02 ms | 0.16 ms | 9.86 ms — 62x the query |
| ClickHouse | 7.74 ms | 0.98 ms | 6.76 ms — 7x the query |

The catalog's `max_connections` is 100. FastAPI runs this project's synchronous
handlers on a thread pool, so one instance could hold as many connections as it had
busy threads; three or four instances exhausted the budget, and the symptom was a
refusal on a request that was otherwise valid.

| Setting | Default | Meaning |
|---|---|---|
| `QUANTLAB_PG_POOL_MAX` | 5 | Catalog connections per instance |
| `QUANTLAB_CH_POOL_MAX` | 5 | Bar-store clients per instance |
| `QUANTLAB_POOL_TIMEOUT` | 10.0 | Seconds a request waits before failing |

The default of 5 is well below the thread-pool size on purpose: the ceiling, not the
thread count, should be what bounds connections. With a 100-connection budget it
supports a dozen instances with headroom for migrations and ad-hoc sessions. A bad
value falls back to the default with a logged warning rather than refusing to start
— these are tuning knobs, not correctness settings.

**Postgres uses `psycopg_pool`, ClickHouse uses a pool written here.** That asymmetry
is deliberate and worth knowing before changing either:

- `psycopg_pool.ConnectionPool` already commits on clean exit, rolls back on error,
  and resets session state when a connection is returned. Reimplementing that is how
  a half-finished transaction leaks into somebody else's request. It also does the
  liveness check (`check=ConnectionPool.check_connection`) that makes a database
  restart heal without an API restart.
- `clickhouse-connect` ships no pool. Its clients already share a urllib3
  `PoolManager`, so sockets and TLS *are* reused — but that manager is `block=False`
  and bounds nothing, and the remaining cost is `Client` construction. Critically, a
  `Client` carries no lock and exposes mutable per-instance state (`database`), so it
  **cannot be shared between threads**. One shared client would be a data race; a
  bounded pool of clients is what is left.

Both pools are created lazily on first use, never at construction, so the
application still starts with every database unreachable and the synthetic demo path
needs no driver at all.

