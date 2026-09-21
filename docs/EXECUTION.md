# Execution: how QuantLab turns signals into trades

QuantLab has **no live trading**. Nothing here talks to a broker, and no code path can
place an order. What it has is a deterministic simulation of how a run's signals would
have filled over their window, used in two places:

- **Batch** — `POST /runs` computes and stores a run's signals;
  `GET /runs/{id}/performance` turns them into trades, an equity curve and metrics.
  Execution criteria are chosen at run creation, recorded on the run as provenance,
  and applied when the performance report is computed.
- **Replay** — `GET /runs/{id}/replay/stream` (SSE re-read of a stored run) and
  `GET /replay/live/stream` (a Kafka bar stream) drive a day-by-day portfolio
  simulator. Replay uses the historical default execution model (equal-weight sleeves,
  close-of-signal-date fills, no costs) and its terminal summary reconciles with the
  performance report of a run created without execution criteria.

Everything below describes the batch performance path unless noted. The implementation
is `backend/src/quantlab/research/performance.py`; the replay simulator is
`backend/src/quantlab/replay/portfolio.py`, deliberately mirroring it.

## Signal → entry timing

A signal is stamped for date T and computed only from bars up to T (enforced by the
truncation sweep in `backend/tests/lookahead/`). When it fills is the run's
`execution.entry_price`:

- `same_close` (default) — the fill happens at the close of T itself. This assumes you
  could act at the closing print of the session that produced the signal.
- `next_open` — the fill happens at the open of the next session that has a bar for
  that instrument. This removes the same-bar fill assumption; a signal on the last
  session of the window never fills.

## Trade pairing

Long-only, per instrument. A `bullish` signal opens a position; the next `bearish`
signal on the same instrument closes it. A repeat signal in the direction already held
is ignored (no pyramiding), and a `bearish` signal with nothing held is ignored (never
a short). A signal on a date with no bar for that instrument is skipped — there is no
price to transact at. A position still open at the end of the window is marked at the
last close, flagged `open`, and never counts toward the win rate.

## Sizing

`execution.position_sizing`:

- `equal_weight` (default) — `initial_capital` is split into one sleeve per selected
  instrument. An entry invests the sleeve's whole cash; an untraded sleeve sits in
  cash. Sleeves compound independently: a closed winner's sleeve is bigger the next
  time it enters.
- `fixed_fraction` — one shared cash account; each entry invests `fraction` of the
  book's current value. An entry the cash account cannot fund is skipped.

`execution.max_open_positions` caps how many positions may be open at once; entries
beyond the cap are skipped. Within a day, signals act in symbol order, so which entry
gets the last seat is deterministic.

## Costs

`execution.transaction_cost_bps` (basis points of traded value) and
`execution.fixed_cost_per_trade` (currency units) are charged on **every fill**, entry
and exit. Entry sizing is fee-aware: the quantity solved for leaves room for the fees,
so the book never goes negative to pay them. A trade's `return_pct` is net of its entry
and exit costs. The run's `total_return` is measured against `initial_capital`, so
costs paid on day one are not hidden by the curve's first mark.

## Stops and targets

`execution.stop_loss_pct` / `execution.take_profit_pct` are fractions of the entry
price (0.1 = 10%). They are **evaluated against each bar's range** while a position is
open:

- stop-loss triggers when a bar's `low` trades at or below `entry × (1 − stop_loss_pct)`;
  the fill is the stop level, or the bar's `open` when the market gaps through it.
- take-profit triggers when a bar's `high` trades at or above
  `entry × (1 + take_profit_pct)`; the fill is the target level, or the `open` on a gap.

Two documented tie-breaks, both stated in the run's `assumptions[]`:

1. When a stop and a target trigger on the **same bar**, the stop is assumed to fill
   first — the order is unknowable from daily bars, so the pessimistic reading wins.
2. A `same_close` entry fills after its own day's range has formed, so that range
   cannot stop it out; stops apply from the next bar onward. A `next_open` entry can be
   stopped by its own session's range.

A stop or target exit takes precedence over signal pairing: the later `bearish` signal
finds nothing to close and is ignored, and a later `bullish` signal may re-enter.

## Equity, benchmark, metrics

The book is marked to market on every date that has a bar (the union across selected
instruments). An instrument with no bar on a date keeps its last known price — closed
for the day, not worthless. The benchmark is equal-weight buy-and-hold of the run's own
selection, so the comparison isolates the model's timing from the universe choice.
Metrics: `total_return` (end vs starting capital), `sharpe_ratio` (daily returns,
annualised at √252, zero risk-free; null when undefined), `max_drawdown` (negative
fraction, peak to trough), `win_rate` over **closed** trades only.

## What is not simulated

- **Shorting, leverage, margin** — long-only, fully cash-funded.
- **Slippage and market impact** — fills happen at the modeled price; the cost fields
  are the only friction. There is no liquidity model.
- **Partial fills and intraday order types** — one fill per signal or stop event, at
  one price.
- **Corporate actions** — prices are unadjusted; a split inside the window shows up as
  a real move (runs report overlapping actions as a warning, never apply them).
- **Anything live** — this is a measurement over recorded daily bars. It is not a
  tradeable backtest and must never be presented as one; the `assumptions[]` array in
  every performance and replay payload carries the disclosures so they cannot be
  dropped by a UI refactor.
