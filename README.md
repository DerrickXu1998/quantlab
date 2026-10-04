# quantlab

A quant research workbench: build a strategy from signal rules, backtest it in the
background, and read the results against buy-and-hold. FastAPI backend, TypeScript
frontend, Postgres + ClickHouse warehouse, deployed to one Compute Engine VM.

| Where | What |
|---|---|
| `backend/` | The application: API, backtest engine, background run worker (`quantlab` package, backend image). |
| `frontend/` | The SPA (Vercel). |
| `src/quantlab/store/` | **The warehouse schema**: every Postgres and ClickHouse migration, applied by `quantlab migrate` on each deploy (migrate image). |
| [quantlab-data-pipeline](https://github.com/DerrickXu1998/quantlab-data-pipeline) | **Everything that loads data**: minute and daily bars, fundamentals, macro (FRED, BoE), short interest, universes, identifier mapping, and the research/feature library (`quantlab_data`). It keeps pinned copies of the schema and never changes it. |

To change the warehouse schema, add the next numbered file under
`src/quantlab/store/migrations/` (Postgres) or `ch_migrations/` (ClickHouse) here;
never edit an applied one. Then `make sync-schema QUANTLAB=../quantlab` in the pipeline.

To load data -- locally or into production -- use the pipeline:
`make quantlab-data ARGS="..."`, or `make ingest-fred TARGET=prod` for the macro
series the S6 regime gate reads.

## Documentation

| | |
|---|---|
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Panel shape, plugin contracts, point-in-time enforcement, performance. |
| **[docs/EXECUTION_MODEL.md](docs/EXECUTION_MODEL.md)** | What actually executes a trade: which bar, which price field, and why a stop beats a target inside one bar. Includes what the backtester still is not. |
| **[docs/STRATEGY_GUIDE.md](docs/STRATEGY_GUIDE.md)** | Signals vs strategies, the three roles, the four combination modes, every execution criterion and its failure mode, four worked starter strategies. |
| **[docs/SECURITY.md](docs/SECURITY.md)** | Threat model, the auth design and why those choices, an honest list of what is still missing, and the pre-exposure checklist. |
| **[docs/SIGNAL_VIEWER_DEMO.md](docs/SIGNAL_VIEWER_DEMO.md)** | The dockerized signal viewer demo: `make up`, `make docker-shell`, and the rest of the target list. |
| **[docs/DEPLOY.md](docs/DEPLOY.md)** | Running it for real: one Compute Engine VM, images from Artifact Registry, deploys from GitHub Actions. What it costs and how to roll back. |

## Repository layout

```
quantlab_specs/     specifications only — no code (Spec Kit root: .specify/ + specs/)
src/quantlab/       the warehouse schema (migrations) and `quantlab migrate`
tests/
backend/            signal viewer demo — FastAPI, synthetic data, signal plugins
frontend/           signal viewer demo — TypeScript SPA
scripts/            up.sh, docker-shell.sh, smoke.sh
docker-compose.yml  seed -> backend -> frontend
Makefile            make up / make docker-shell / make test / make smoke
```

`quantlab_specs/` holds specifications and nothing else; this is enforced by the
constitution's Repository Structure principle. Run `make up` from the repository root.

## Strategies, execution criteria and accounts

The demo app has a second contract on top of the indicator library:
[`docs/CONTRACT_V2.md`](docs/CONTRACT_V2.md), covering strategies, execution and
identity. It is in progress: the strategy, execution and signal-catalogue
libraries exist under `backend/src/quantlab/`, the API routes do not call them
yet, and identity is not started.
[`docs/EXECUTION_MODEL.md`](docs/EXECUTION_MODEL.md) §10 tracks exactly what is
built and what is left.

**A signal is not a strategy.** A signal rule maps bars to directional events —
a date and a direction, nothing else. A *strategy* assigns several rules a role
(`entry`, `exit`, `filter`), combines them (`all` / `any` / `majority` /
`weighted`), and attaches the execution criteria that turn a decision into
orders. Filters gate entries and never exits: a filter turning off must not trap
a position in the book.

**Execution criteria are fields, not assumptions.** Fill timing
(`signal_close`, `next_open`, `next_close`, or `next_typical` -- the next
session's (high + low + close) / 3, a VWAP stand-in), commission and slippage in basis points per
side, stops (fixed, trailing, or ATR-scaled), take-profits, holding-period
bounds, cooldowns, sizing mode and position caps. Every one of them is reported
back on the run, so a result carries the assumptions that produced it rather
than a fixed caveat string.

**One thing worth knowing before you read a number.** When a stop and a target
both sit inside a single bar's high–low range, the engine takes the stop. A
daily bar does not record which came first, and assuming the favourable one adds
a positive bias concentrated in the widest bars — which is exactly where a
parameter sweep will push you. The pessimistic reading is the only one that
survives contact with real money.
[`docs/EXECUTION_MODEL.md`](docs/EXECUTION_MODEL.md) works the arithmetic
through five bars, both ways: −2.60% or +4.89% on one trade.

**Authentication.** Opaque bearer tokens, not JWTs — a session is a database row,
so logout genuinely revokes it. Only the token's SHA-256 is stored, so a database
read does not yield a usable credential. Passwords use PBKDF2-HMAC-SHA256 from
the standard library rather than adding an argon2 dependency; argon2id would be
better and the trade-off is written down in
[`docs/SECURITY.md`](docs/SECURITY.md) rather than assumed. Login answers `401`
identically for an unknown email and a wrong password, and reading another user's
row is `404` rather than `403`, because a `403` confirms the row exists.

`QUANTLAB_AUTH_REQUIRED=false` restores the open local demo by binding every
request to a built-in `local` user. It is not a deployment mode — on a public
host every visitor shares that one account.

## Tests

```bash
make test        # backend pytest + frontend vitest, in containers
make store-test  # the schema against the live stack: migrations apply and are idempotent
```

The data library's tests (indicators, providers, look-ahead sweeps) moved with it to
quantlab-data-pipeline.

## Backtest size limits

A backtest runs inside the API request, in a backend worker. On the production
VM the backend container may use **2 GiB of memory, shared by 2 workers**
(`deploy/docker-compose.prod.yml`); an idle worker uses ~56 MB. Bars are held
as compact columns (~120–150 B a bar at a run's peak), daily and intraday
alike. A run past a limit is refused with a `422` that says how big it was,
before any data is read.

| Bars | Limit (`research/runner.py`) | What fits, e.g. |
|---|---|---|
| Daily (`bar_frequency` `1d`, default) | 8,400,000 instrument-days (symbols × calendar days, ≈ 6M bars) | all 503 S&P 500 names × all ~10 years of data, with room to spare |
| Intraday (`1h`, `15m`, `5m`) | 6,000,000 bars, estimated as symbols × weekdays × bars per session (warm-up included) | see below |

Choose the bars in the Strategy tab under **Universe & window → Bars** (or
`execution.bar_frequency` in the API); the form shows the estimated size and
time and disables **Run backtest** when a run would be refused.

Bars per session: `1h` 7, `15m` 26, `5m` 78 (regular hours, 09:30–16:00 New
York). So 6M intraday bars is about:

| Frequency | Bars per symbol-year | 6M bars allows, e.g. |
|---|---|---|
| `5m` | ~19,600 | 60 symbols × 5 years, 30 × 10, 300 × 1 |
| `15m` | ~6,550 | 90 symbols × 10 years, all 503 × 1.8 |
| `1h` | ~1,760 | all 503 symbols × ~7 years |

**Measured** on production data (wall time from a laptop through the IAP
tunnel, so the read is slower than on the VM itself):

| Run | Peak memory | Time |
|---|---|---|
| Daily, all 503 symbols × 10 years (1.3M bars) | +189 MB (was +765 MB before columns) | 149 s |
| 5m, 20 symbols × 5 years (2.0M bars) | +277 MB | 40 s |
| 5m, 40 symbols × 5 years (4.1M bars) | +462 MB | 79 s |

**One large run at a time, server-wide.** A run estimated above 300,000 bars
takes a Postgres advisory lock shared by every worker. A second large run
waits up to 30 s, then gets `429` with `Retry-After: 60`. Smaller runs never
wait. The lock is released when the run ends, or by Postgres if the worker
dies. So at most one large run is in memory at once: ~650 MB at the 6M-bar
limit, a third of the container.

**Time.** Runs are synchronous, and the time is mostly the strategy, not the
data: each component computes its signals over every bar. Measured on the
production VM (5m bars, 29 symbols × 2024 = 569k bars):

| Strategy | Read | Signals | Backtest | Total |
|---|---|---|---|---|
| RSI mean reversion (2 components) | 2.5 s | 16 s | 3 s | 21 s |
| S2 regime reversion (4 components) | 3 s | 46 s | 3.5 s | 53 s |

Roughly 5 s (read) + 6 s (backtest) + 18 s per component, per million bars.
The Strategy tab shows this estimate before a run. At the 6M-bar limit that is
~5 minutes for 2 components and ~8 for 4 -- long for one request; memory
allows it, time is what argues for smaller runs or background jobs.

**Minute data.** Intraday bars are built from the IEX minute feed, which starts
on 2016-12-12. Market holidays are excluded (the feed carries flat placeholder
bars on them).

## Licence

MIT for this code. The data is a separate matter entirely — see
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md), which records each source's terms. Several
free sources permit personal research only.
