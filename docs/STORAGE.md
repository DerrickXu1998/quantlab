# Storage

Historical market data lives in two stores, split by the shape of the data
rather than by convenience.

| | ClickHouse | Postgres |
|---|---|---|
| Holds | `price_bars` | instruments, symbol maps, universe snapshots, ingest runs, rejects, corporate actions, signals |
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

**Provenance is per batch.** Every bar carries `run_id`, a foreign key in
spirit to `ingest_runs`. That is ~8 bytes a row instead of duplicating source
strings across 100M rows, and it gives full lineage for any value.

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

## Commands

```bash
make migrate     # apply pending migrations to both stores
make ingest      # SYMBOLS="AAPL.US HSBA.LON" START=2015-01-01
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
