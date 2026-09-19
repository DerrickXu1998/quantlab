# quantlab

Pluggable quantitative equity analytics for the **NYSE and LSE** universes, built entirely
on free data sources.

70 technical indicators, 22 derived/alternative-data features, 8 data providers, a plugin
system with three levels of formality, and point-in-time discipline enforced by the engine
rather than by your memory.

```bash
pip install -e .              # core
pip install -e '.[all]'       # + yahoo, duckdb, polars, excel, plots
```

```python
import quantlab as ql

panel, ctx = ql.load(
    ["JPM.US", "XOM.US", "HSBA.LON", "SHEL.LON"],
    start="2020-01-01",
    providers=["stooq", "yahoo"],       # fallback chain
    return_context=True,
)

result = ql.compute(panel, [
    "rsi", "yang_zhang_vol", "amihud_illiquidity", "hurst",
    "momentum_12_1", "market_beta", "breadth",
    {"cs_zscore": {"column": "momentum_12_1", "as": "mom_z"}},
], context=ctx)
```

```bash
quantlab list indicators --tag volatility
quantlab sources                       # every source, its limits and its licence
quantlab doctor                        # plugins, credentials, paths
quantlab run examples/config.example.yaml --out features.parquet
```

## Documentation

| | |
|---|---|
| **[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)** | Every free source, verified Sept 2026: limits, coverage, licensing, and what to skip. |
| **[docs/INDICATORS.md](docs/INDICATORS.md)** | All 92 features, with an opinion on which ones actually earn their place. |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Panel shape, plugin contracts, point-in-time enforcement, performance. |
| **[examples/](examples/)** | Quickstart script, full pipeline config, and a complete third-party plugin. |
| **[docs/SIGNAL_VIEWER_DEMO.md](docs/SIGNAL_VIEWER_DEMO.md)** | The dockerized signal viewer demo: `make up`, `make docker-shell`, and the rest of the target list. |

## Repository layout

```
quantlab_specs/     specifications only — no code (Spec Kit root: .specify/ + specs/)
src/quantlab/       the library
tests/
backend/            signal viewer demo — FastAPI, synthetic data, signal plugins
frontend/           signal viewer demo — TypeScript SPA
scripts/            up.sh, docker-shell.sh, smoke.sh
docker-compose.yml  seed -> backend -> frontend
Makefile            make up / make docker-shell / make test / make smoke
```

`quantlab_specs/` holds specifications and nothing else; this is enforced by the
constitution's Repository Structure principle. Run `make up` from the repository root.

## Four things to know before you build on this

**1. The LSE data problem is real.** There is no free, licensed, API-based source of LSE
daily OHLCV at 5,000-name scale. Stooq (`.uk`) and Yahoo (`.L`) both work and both are
unofficial. Decide now whether you can live with that or whether ~$30–80/month is the honest
answer for the UK half. Everything else here is genuinely free and mostly official.

**2. The pence trap.** Most LSE lines quote in GBX, some in GBP. Mixing them makes every
cross-sectional number wrong by 100×. `fx.normalise_panel` handles it; prefer scale-free
indicators (`natr`, not `atr`) and you mostly sidestep it.

**3. Survivorship bias has no free fix.** Every free source gives you *currently listed*
companies. Start snapshotting your universe today — `quantlab universe lse --out snap.csv`
on a schedule costs nothing, and in three years you will have something no free source
sells.

**4. Point-in-time or nothing.** Fundamentals are stamped at the filing date, never the
fiscal period end, and every externally-sourced feature declares a publication lag the
engine enforces. A test asserts no `external` feature ships with `lag=0`, and another sweeps
all 70 indicators for accidental look-ahead.

## Adding your own

Three ways, increasing in formality. All land in the same registry, so your feature is
indistinguishable from a builtin.

```python
# 1. In-process — notebooks and one-offs
@ql.indicator("my_signal", params={"period": 20}, inputs=("close",), tags=("custom",))
def my_signal(df, period=20):
    return df["close"].pct_change(period)
```

```python
# 2. A .py file in ~/.quantlab/plugins/ — no packaging at all
```

```toml
# 3. Entry points — pip install is the whole install step
[project.entry-points."quantlab.indicators"]
myfactors = "quantlab_myfactors:register_all"
```

Groups: `quantlab.providers`, `quantlab.universes`, `quantlab.indicators`,
`quantlab.derived`. A complete working plugin — two indicators, a cross-sectional derived
feature and a provider — is in [`examples/example_plugin/`](examples/example_plugin/).

A new data provider is one method:

```python
@ql.provider("mybroker")
class MyBroker(DataProvider):
    name = "mybroker"
    def fetch_one(self, symbol, start, end, frequency="1d"):
        return a_dataframe_with_ohlcv_and_a_date_index
```

Caching, rate limiting, retries, schema validation and currency normalisation are the
framework's job.

## Credentials

All optional, all free. `quantlab doctor` shows what is set.

| Variable | For | Needed? |
|---|---|---|
| `SEC_USER_AGENT` | SEC EDGAR — **must contain a contact email** | US fundamentals & insider data |
| `FRED_API_KEY` | US macro series | `macro_us` |
| `COMPANIES_HOUSE_API_KEY` | UK fundamentals | `valuation`/`quality` for LSE names |
| `OPENFIGI_API_KEY` | 10× identifier-mapping throughput | optional, recommended |

Stooq, Yahoo, FINRA, FCA and the Bank of England need nothing.

## Tests

```bash
pytest -q        # 84 tests, fully offline, no vendor data
```

Notable ones: RSI and ATR are checked against independently written reference
implementations; Hurst is checked against simulated trending and mean-reverting processes;
the half-life estimator is checked against a simulated Ornstein–Uhlenbeck process with a
known half-life; beta is checked against a construction with known betas; every indicator is
swept for look-ahead by recomputation on truncated history; and every externally-sourced
feature is checked to fail *softly* offline rather than inventing data.

## Performance

250 symbols × 900 bars × 28 features in ~35s on 8 threads. A 5,000-name daily refresh is
roughly 10–15 minutes of compute, plus fetch time dominated by provider rate limits.

## Licence

MIT for this code. The data is a separate matter entirely — see
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md), which records each source's terms. Several
free sources permit personal research only.
