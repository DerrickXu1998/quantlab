# Architecture

```
                    ┌──────────────┐
  universe source → │   Security   │ ← identifier bridge (OpenFIGI)
  (nasdaqtrader,    │  symbol,isin │
   lse, static)     │  sedol,cik,  │
                    │  company_no  │
                    └──────┬───────┘
                           │
      ┌────────────────────▼─────────────────────┐
      │  data.load()  — provider fallback chain   │
      │  stooq → yahoo → csv → …                  │
      │  (rate limited, cached, retried)          │
      └────────────────────┬─────────────────────┘
                           │
                    ┌──────▼───────┐
                    │  fx.normalise │   GBX → GBP, unit recorded
                    └──────┬───────┘
                           │
               long panel: (date, symbol) × OHLCV
                           │
      ┌────────────────────▼─────────────────────┐
      │  FeatureEngine                            │
      │   1. per-symbol indicators  (parallel)    │
      │   2. cross-sectional derived (whole panel)│
      │   3. lag enforcement (point-in-time)      │
      └────────────────────┬─────────────────────┘
                           │
                 panel + feature columns → Parquet
```

## The canonical panel

One shape, everywhere: a pandas DataFrame with a `MultiIndex` of `(date, symbol)` and at
minimum `open, high, low, close, adj_close, volume`. `validate_bars` coerces any provider's
output into it and repairs the untidy parts (column case, index name, sort order,
duplicates) while raising on anything structurally wrong.

Symbols are canonical, not vendor-specific: `AAPL.US`, `HSBA.LON`. Each provider maps to its
own convention in `to_native` (`aapl.us` for Stooq, `HSBA.L` for Yahoo). This is what lets
you swap providers without rewriting your symbol lists.

## Plugins

Three ways to extend, all landing in the same registries, so a builtin and a third-party
feature are indistinguishable to the engine.

**1. Decorator, in-process** — notebooks and one-offs:

```python
import quantlab as ql

@ql.indicator("my_signal", params={"period": 20}, inputs=("close", "volume"), tags=("custom",))
def my_signal(df, period=20):
    """One symbol's bars in, a Series out."""
    return df["close"].pct_change(period) * df["volume"].rolling(period).mean()
```

**2. A `.py` file in a plugin directory** — no packaging at all. Drop it in
`~/.quantlab/plugins/` or anywhere on `QUANTLAB_PLUGIN_PATH`.

**3. Entry points** — a real distribution. `pip install` is the whole install step:

```toml
[project.entry-points."quantlab.indicators"]
myfactors = "quantlab_myfactors:register_all"
```

Groups: `quantlab.providers`, `quantlab.universes`, `quantlab.indicators`,
`quantlab.derived`. See `examples/example_plugin/` for a complete working one.

Builtins load first, so a third party can deliberately override one with `override=True`.
A plugin that fails to import is logged and skipped — it never takes the registry down.

## Feature contracts

Every feature carries a `FeatureSpec` the engine uses to schedule it:

| Field | Meaning |
|---|---|
| `inputs` | Required panel columns. Validated before the function runs. |
| `outputs` | Column names produced. Defaults to `(name,)`. |
| `params` | Defaults, overridable per call. |
| `cross_sectional` | `False` → `fn(df, **params)` per symbol. `True` → `fn(panel, ctx, **params)` over everything. |
| `lag` | Bars of publication delay. **Enforced by the engine**, per symbol. |
| `tags` | For filtering: `quantlab list indicators --tag volatility`. |

Per-symbol features run first and in parallel across symbols; cross-sectional ones run
afterwards over the whole panel, so a cross-sectional feature can consume a column a
per-symbol feature produced in the same call.

A feature that raises is caught, recorded in the `ComputeReport`, and skipped — the rest of
the run completes. `on_error="raise"` turns that off when you are debugging.

## Point-in-time correctness

Two mechanisms, because this is the bug class that makes paper money and loses real money.

1. **Declared lag.** Any feature sourced from a filing or a published file declares a `lag`,
   and the engine shifts it forward per symbol before it reaches you. A test enforces that
   no `external` feature ships with `lag=0`.
2. **Filing dates, not period ends.** Fundamentals providers index on the date the number
   became public, never the fiscal period it describes.

The indicator suite is also swept by `test_no_indicator_looks_ahead`, which recomputes every
indicator on truncated history and asserts nothing earlier changed. `ichimoku` is the single
documented exception (its `chikou` line is a deliberate backward shift for charting).

## Currency and units

Most LSE lines quote in GBX (pence), some in GBP, a few in USD or EUR. Mixing them produces
ratios off by 100×.

The rule: **keep prices in their native quote unit, record the unit explicitly, and convert
only where cross-currency comparison is actually needed.** `fx.normalise_panel` infers the
unit from declared metadata first and a price-level heuristic second, converts GBX → GBP,
and returns the units it used. `Context.currencies` keeps them.

Prefer scale-free indicators (`natr`, not `atr`) and you mostly sidestep the problem —
see `INDICATORS.md`.

## Rate limiting

A token bucket per source, seeded from published limits (`ratelimit.DEFAULT_LIMITS`, each
with a `note` citing its basis). Daily caps persist to disk, so a restart does not reset
your Alpha Vantage quota. `retry()` does exponential backoff with full jitter and never
retries a quota exhaustion.

`HttpClient` ties it together: rate limited, disk cached (historical files get `ttl=-1` —
they never change), retried, and offline-aware. `QUANTLAB_OFFLINE=1` makes any cache miss
raise instead of hitting the network, which is what the test suite runs under.

## Performance

Measured: 250 symbols × 900 bars × 28 features (including 6 cross-sectional) in ~35s on 8
threads. Extrapolating, a 5,000-name daily refresh with a rich feature set is **roughly
10–15 minutes of compute**, plus fetch time dominated by provider rate limits.

The engine parallelises per-symbol features across symbols. Cross-sectional features are
already vectorised over the whole panel — they use `groupby.transform("mean")` rather than
`transform(python_function)`, which at 5,000 names is a ~100× difference and would otherwise
dominate a run. Same reasoning applies to `hurst`, `half_life`, `trend_slope` and
`autocorr`, all rewritten in closed form.

`supertrend`, `psar` and `kama` keep Python loops because their recursions are genuinely
sequential.

## Storage

Two stores, split by the shape of the data — see `STORAGE.md` for the full reasoning.

**ClickHouse holds `price_bars`**: append-only, columnar, 10–30x compression, and a `ts`
column that is a timestamp from day one so intraday needs no migration. Re-ingest is
idempotent via `ReplacingMergeTree(run_id)`, but reads must go through the
`price_bars_current` view — the dedup happens at merge time, not at insert.

**Postgres holds the catalog**: instruments, vendor symbol maps, universe snapshots, ingest
provenance, corporate actions and signals. Small, mutable, relational data that wants
foreign keys, unique and exclusion constraints, and transactions — none of which ClickHouse
has. The rule of thumb: bar-level cardinality goes to ClickHouse, anything needing a
constraint stays in Postgres.

Parquet remains the *derived* tier, not the system of record. `save_panel(...,
partition_by_symbol=True)` writes a Hive-partitioned layout, and
`store.panel_for_modelling(...)` materialises one straight out of the warehouse — a pinned
file a backtest result can be traced back to, which a live query is not.

## What is deliberately not here

- **No backtester.** Feature generation and strategy simulation are separate concerns and
  conflating them is how look-ahead creeps in. Feed the panel to `vectorbt`, `zipline-reloaded`
  or your own.
- **No retroactive survivorship-bias fix.** There isn't a free one: nobody will sell you the
  1998 index membership for nothing. What the store does do is snapshot universe membership
  on every refresh, append-only, so history accumulates from today forward and
  `load_panel(universe_snapshot=...)` can reconstruct it later. Start ingesting now.
- **No intraday data yet.** The free sources cap intraday history at weeks, which is not
  enough to model on. The bar schema is intraday-ready regardless (`ts` is a `DateTime64`),
  so adding a licensed minute feed is an ingest adapter, not a migration.
