# The execution model — what actually happens between a signal and a number

The question this document exists to answer: *by what, exactly, is a trade
executed?* Not "a backtester". A named function, on a named bar, at a named
price field.

Everything below runs. It is verified against the code, not against
[`docs/CONTRACT_V2.md`](CONTRACT_V2.md) — where the two ever disagree, the
contract is the bug report and this document is a description of what the
machine does. §10 covers what is deliberately *not* modelled, which is a longer
list than people expect.

---

## 1. The whole chain, top to bottom

```
  POST /api/v1/runs      (bearer token; the run is stamped with owner_id)
        |
        |  exactly one of: model_name | strategy_id | strategy
        |  plus an optional run-level `execution` override
        |  anything else -> 400
        v
  research/runner.py : run_experiment()
        |
        |  1. resolve the StrategySpec. A legacy model_name is PROMOTED
        |     into a one-component strategy, so there is one path, not two
        |  2. validate every component parameter against its ParamSpec
        |  3. warm-up start = start_date - StrategySpec.lookback_days,
        |     padded from bars into calendar days
        |  4. backend.load_bars_for(symbols, warmup_start, end_date)
        v
  +-----------------------------------------------------------+
  |  BARS: date, open, high, low, close, volume                |
  |  ascending by date, one list per symbol, unadjusted        |
  +-----------------------------------------------------------+
        |
        v
  signals/engine.py : compute_signals()
        |
        |  for each symbol, for each component rule:
        |      skip if len(bars) < rule.lookback_days
        |      rule.compute(bars, **effective_params)
        |          -> [SignalEvent(date, direction, trigger_values,
        |                          data_window_end)]
        |  sort by (symbol, date, rule_name)
        v
  +-----------------------------------------------------------+
  |  SIGNAL EVENTS: "bullish on ZZTRND at 2024-03-05"          |
  |  a direction and a date. NOT an order. No size, no price.  |
  +-----------------------------------------------------------+
        |
        v
  strategy/spec.py : StrategySpec
        |
        |  per (symbol, date):
        |    active_bullish(c) = c fired bullish in
        |                        [T - combine_window + 1, T]
        |    entry  = all | any | majority | weighted  over entry roles
        |    exit   = same combinator over exit roles
        |    filters gate entries only, never exits
        v
  +-----------------------------------------------------------+
  |  DECISIONS: "open long ZZTRND, decided on 2024-03-05"      |
  +-----------------------------------------------------------+
        |
        v
  execution/engine.py : ExecutionSimulator
        |
        |  per bar, in this fixed order -- five steps, not four:
        |    1. mark the book at this bar's close
        |    2. fill orders queued yesterday   (fill_timing: next_open)
        |    3. protective exits vs THIS BAR'S HIGH/LOW:
        |         stop -> trailing -> target -> max_holding
        |    4. signal exits   (if min_holding_days elapsed)
        |    5. signal entries (if cash, slots, cooldown, filters allow)
        v
  +-----------------------------------------------------------+
  |  ORDERS -> FILLS: a qty, at a price, on a date             |
  |  price = bar field +/- slippage; commission charged as cash|
  +-----------------------------------------------------------+
        |
        |  warm-up bars were INPUTS; reported events and the equity
        |  curve both begin at start_date
        v
  research/performance.py : compute_performance()
        |
        v
  GET /api/v1/runs/{id}/performance
        equity curve, benchmark, trades, metrics, assumptions
```

The same `ExecutionSimulator` drives all three consumers — the batch run, the
SSE replay (`replay/engine.py`) and the live Kafka-fed replay. That is the point
of it. Before it existed the same rules were written twice, once for the batch
report and once for the day-by-day stream, and "keeping two implementations
agreeing by hand is a bug waiting for a quiet afternoon".

The important structural fact: **a signal is not an order.** `SignalEvent` has
four fields — `date`, `direction`, `trigger_values`, `data_window_end`
(`signals/registry.py`). It carries no quantity, no price, no instrument even;
the symbol is attached later by `compute_signals`. Everything about *how much*
and *at what price* is decided downstream, by the execution layer, from the
`ExecutionConfig`. That separation is deliberate: the same rule scored against
two different cost assumptions is two different backtests, and you should be
able to see which assumption produced which number.

---

## 2. What the price actually is, at every step

This is the part that is normally left vague. It is not vague here.

| Step | Which bar | Which field | Why |
|---|---|---|---|
| Rule input | every bar up to and including `T` | mostly `close`; `breakout-20d` reads `high`/`low` of the prior window | Rules are causal by construction: `data_window_end <= date` always. See §5. |
| Signal entry, `fill_timing: "signal_close"` | the signal's own bar `T` | `close` | The decision is made from `T`'s close, so `T`'s close is the earliest price at which you could plausibly have acted. Filling at `T`'s open would be look-ahead: you did not know at the open what the close would say. |
| Signal entry, `fill_timing: "next_open"` | bar `T+1` | `open` | The conservative reading: you saw the close, you placed the order overnight, you got the next print. A signal on the final bar has no `T+1`, is dropped, and is counted in `dropped_no_bar`. |
| Stop / trailing stop / take-profit — *trigger* | the bar being tested | `low` (long stop), `high` (long target) — the bar's *range*, not its close | A stop that only checks the close is not a stop; it is a rule about closes. Intraday, price went where the high and low say it went. |
| Stop / trailing stop — *fill price* | same bar | the level, or the `open` when the session gapped clean through it — whichever is **worse** (`min(stop, open)` long) | A resting order fills at its level. A gap fills at the first available print, which is the open. Pretending the stop held through a gap is how a backtest hides its worst days. |
| Take-profit — *fill price* | same bar | **always the target level**, never the open, even when the open gapped past it | Deliberately asymmetric. See below. |
| `max_holding_days` forced exit | the Nth bar after entry | `close` | There is no price trigger, so there is no better price to claim. |
| Daily mark | every bar in the window | `close` | One mark per bar, step 1 of the simulator's loop. |
| End-of-window open position | the last bar in the window | `close` | Flagged `open: true`, given `exit_reason: "end_of_window"`, and excluded from the win rate (`performance.metrics`). It is not a realised trade. |

### Gaps are pessimistic in both directions, which is not symmetric arithmetic

This is the row people read twice, so it gets its own heading.

A **stop** is an order to leave on weakness. When the session opens below your
stop, the stop did not hold — there was no liquidity at your level, and the
first price you could actually have traded is the open. So the fill is
`min(stop, open)`: the open when it gapped, the level otherwise.

A **target** is an order to leave on strength. When the session opens *above*
your target, the same reasoning says you would have filled at the open, which is
**better** than your level. The engine declines it and fills at the target
anyway.

That looks inconsistent, and it is — on purpose. The two cases are not
symmetric because the error they guard against is not symmetric. Taking the bad
gap is modelling something that happens; taking the good gap is awarding
yourself a windfall that no live book reliably collects. Favourable gaps cluster
on exactly the names and days where your fill would in practice have been
contested, and across hundreds of trades "every gap through my target went my
way" compounds into a material edge that exists only in the backtest.

It is the same argument as stop-beats-target in §3, applied to the other side of
the trade: when the data leaves something genuinely unknowable, resolve it the
way that cannot flatter you. From the engine's own docstring:

> Awarding yourself every favourable gap adds up to a material edge that no live
> book ever collects.

Two more consequences that surprise people:

**Slippage shows up before any price movement does.** You buy at
`close * (1 + slippage_bps/1e4)` and you are immediately marked at `close`. The
mark on entry day is a loss equal to the slippage plus the commission, on the
very first bar. See §8, bar 2.

**A 5% stop is not a 5% loss.** The stop level sits 5% below the *fill* price,
and the exit then pays slippage and commission of its own. In §8 a 5% stop with
10bp slippage per side realises −5.095% on price and −5.19% after fees.

---

## 3. The bar is the resolution limit, and that is the whole problem

`execution/engine.py`.

You have a daily bar: `open`, `high`, `low`, `close`. Suppose you are long from
100.10 with a 5% stop (95.095) and a 10% target (110.11), and the next bar is:

```
  open 102.50   high 111.30   low 94.80   close 97.20
```

Both levels are inside the range. The bar says price reached 111.30 and price
reached 94.80. **It does not say in which order.** A daily bar is four numbers;
the path between them is discarded at the source. There is no field you can read
and no provider you can pay that restores it from daily data.

So the engine has to choose. The resolution order, from `ExecutionSimulator`:

```
  1. mark
  2. fill orders queued yesterday          (next_open only)
  3. stop_loss -> trailing_stop -> take_profit -> max_holding_days
  4. signal exits
  5. signal entries
```

Stop first. The engine takes the loss.

Two of those orderings carry a reason worth repeating, both from the engine's
own docstring. **Protective exits precede signal exits** because a stop hit
intraday was hit *before* the close that produced the signal — resolving it the
other way would let a signal rescue a position that had already been stopped
out. **Entries come last** because a position closed today frees the capital and
the slot a new position needs; resolving that the other way "would silently cap
the book at one rotation a bar".

**Why the alternative is not a coin flip.** Suppose you resolved ties toward the
target instead, or picked one at random. Every ambiguous bar is, by definition, a
bar with a wide range — a volatile bar. Wide bars are exactly where the target is
reachable. So "assume the favourable one" does not add noise to your backtest; it
adds a *positive bias concentrated in the bars that move the most*. Worse, the
bias gets stronger the tighter your stop and the wider your target, which is
exactly the parameter direction a sweep will push you toward. You end up
optimising into the ambiguity. The optimiser finds the fiction, not the edge.

The cost of the pessimistic choice is honest and small: on truly ambiguous bars
you record a loss you might not have taken. The cost of the optimistic choice is
a backtest that cannot be traded, and you find out with real money.

§8 scores the same bar both ways: −2.60% vs +4.89% on one trade. A 7.5 percentage
point swing decided by information the data does not contain.

**What "assume the worst" does not fix:** if your stop and your target are both
inside one bar's range *often*, your stop is too tight for the instrument's
volatility regardless of which way the tie resolves. Check `exit_reasons` in the
performance response. A run dominated by `stop_loss` on an instrument whose
average true range is a large fraction of your stop distance is not a strategy
being tested; it is a strategy being sampled by noise.

---

## 4. Turning a decision into a fill

`execution/config.py` and `execution/engine.py`.

**Sizing.** Four modes, and the choice also decides how cash is held:

| Mode | Notional per trade | Cash model |
|---|---|---|
| `equal_weight` | `initial_capital / len(symbols)` | **Sleeved**: one cash bucket per name; a sleeve trades only its own instrument and an untraded sleeve sits in cash |
| `fixed_fraction` | `sizing_value * current_equity` | Pooled |
| `fixed_notional` | `sizing_value`, flat, regardless of equity | Pooled |
| `volatility_target` | scaled so the position's own realised volatility contributes about `sizing_value` annualised | Pooled |

Then capped by `max_position_pct * equity`, by `max_positions` open slots, and by
available cash — `_available()` returning the sleeve's cash or the pool's
depending on the mode.

The sleeved/pooled split is the load-bearing detail. `equal_weight` is sleeved
because that is what the pre-existing `performance.equity_series` computed, and
keeping it means legacy runs still reproduce exactly. Everything else draws on
one pool, which is what makes `max_positions` and the `rejected_no_cash` counter
meaningful — under sleeves, one name's idle cash cannot fund another's entry.

`sizing_value` is rejected outright for `equal_weight` rather than ignored:
"silently ignoring a number the user typed is how a run quietly does something
other than what the form said". All the percentage fields are validated into
`(0, 1]`, so a user who types `5` meaning "five percent" gets a `422` rather
than a stop 500% away that never triggers.

**Fill price.** Slippage moves against you on both sides:

```
  buy  fill = price * (1 + slippage_bps / 10_000)
  sell fill = price * (1 - slippage_bps / 10_000)
```

**Commission** is charged as cash on the notional, per side:
`commission_bps / 10_000 * qty * fill_price`. It is not folded into the price,
because a fee and a worse price are different things and you want to be able to
separate them — `execution_summary` reports `total_commission` and
`total_slippage` as two numbers for exactly that reason.

**Positions are fractional.** `qty = budget / fill_price`, no rounding to whole
shares. This is the existing house convention (`portfolio.py`: `qty = cash /
price`) and it is a simplification: real fills are integer shares, and the
rounding error matters at small book sizes and high prices. It is not modelled.

---

## 5. The warm-up window, and why it is not look-ahead

`research/runner.py`.

A rule declares `lookback_days`. `rsi-threshold` declares 16: RSI(14) is first
defined at index 14, and detecting a *crossing* needs the value at `T-1` as well.
If a run loaded only bars inside `[start_date, end_date]`, the first 16 bars of
the window could emit nothing, and a 30-bar window would silently report half a
strategy.

So the runner loads earlier:

```python
warmup_start = start - timedelta(days=rule.lookback_days * _CALENDAR_DAYS_PER_BAR)
bars_by_symbol = backend.load_bars_for(requested_symbols, warmup_start, end_date)
```

`_CALENDAR_DAYS_PER_BAR = 2`. Bars are weekdays, so N bars span at most about
N × 7/5 calendar days; doubling absorbs that plus holidays. It is padding, not a
calculation — loading a few extra bars costs nothing and being short costs
correctness.

Then:

```python
in_window = [s for s in computed if start_date <= s.date <= end_date]
```

**Why this is not look-ahead.** Look-ahead means a value at date `T` was computed
from information not available at `T` — from a *later* bar. Warm-up bars are
earlier bars. Every signal emitted on `2024-03-05` was computed from bars dated
`<= 2024-03-05`, some of which happen to predate `start_date`. That is just
history. The forbidden direction is the other one, and it is enforced separately
(§6).

The distinction that makes this safe: warm-up bars are **inputs**; they are never
**results**. They can be simulated over — an ATR stop set on the window's first
session needs the sessions behind it — but they never appear in what is
reported.

That separation is enforced in three places, and all three had to change
together once the execution layer grew a lookback of its own:

- `runner.py` reports only signals dated inside `[start_date, end_date]`.
- `replay/engine.py: load_replay_inputs` loads from
  `start_date - StrategySpec.lookback_days`, and `replay_events` suppresses
  every event dated before `start_date`.
- `compute_performance` takes `window_start` / `window_end` and trims the equity
  curve to them. **The benchmark is normalised from the window's first close,
  not the warm-up's** — otherwise buy-and-hold would be credited with a move
  that happened before the period under test, and every strategy would be
  measured against an inflated bar.

The middle one is the subtle failure: a curve that began in the warm-up would
put a flat stretch of untraded capital at the front of every result, quietly
depressing the reported volatility and flattering the Sharpe.

**Coverage reports when warm-up was short.** `RunCoverage.instruments_full_warmup`
counts the symbols whose earliest stored bar is on or before `warmup_start`. A
symbol that IPO'd inside your warm-up is still included in the run but produces
fewer early signals, and that count is how you find out. It does not fail the
run — an incomplete warm-up is a data fact, not an error.

A composed strategy's warm-up is `StrategySpec.lookback_days`:

```
  max(component.lookback_days)
    + combine_window_days - 1        # a component may have fired that long ago
    + execution.extra_lookback_days  # atr_period + 1, when an ATR stop is set
```

The third term is the one that is easy to forget. An ATR stop is set from the
ATR as at the *entry* bar, so a position opened on the window's first bar still
needs `atr_period` bars behind it or its stop is undefined. `ExecutionConfig`
contributes that requirement itself rather than leaving the strategy layer to
guess at it.

---

## 6. Point-in-time enforcement: two mechanisms, different jobs

Every `SignalEvent` carries `data_window_end`: the latest bar date used to
produce it. It must always be `<= date`.

### 6a. The CHECK constraint — catches what was stored

`backend/src/quantlab/storage/db.py`, on both the seeded `signals` table and
`experiment_signals`:

```sql
data_window_end  TEXT NOT NULL CHECK (data_window_end <= date)
```

Database-level, so it holds regardless of which code path did the insert — the
seeder, the runner, a migration, a manual fix-up in a `sqlite3` shell. A rule
that reads a future bar and honestly reports it cannot be persisted. The row is
rejected and the run fails loudly.

What it does **not** catch: a rule that reads a future bar and reports
`data_window_end = date` anyway. `data_window_end` is self-reported by the rule
author. A buggy or lazy rule can lie, and the constraint will believe it.

### 6b. The truncation sweep — catches what was computed

`backend/tests/lookahead/test_truncation_sweep.py`. For every registered rule,
over every synthetic instrument:

1. Compute signals over the full history.
2. Truncate history at bar `k` (sampled every 20th `k`).
3. Recompute.
4. Assert the truncated run reproduces **exactly** the full-history signals dated
   `<= last_date` — same dates, same directions, same `trigger_values`, same
   `data_window_end`.

This is the one that catches the liar. If a rule's output on `2024-03-05` changes
depending on whether bars after `2024-03-05` were present in the input array, it
used them, whatever it wrote in `data_window_end`. The usual culprits are a
backward-looking centred window, a `fillna` that propagates backwards, a
normalisation over the whole array (a z-score against the full-sample mean is the
classic), or an indicator seeded from a global statistic.

A second sweep, `test_truncation_sweep_under_parameter_overrides`, repeats the
property under non-default parameters, because a longer window reaches further
back and the registered defaults are not the configuration a researcher actually
runs.

Together: the constraint enforces the claim, the sweep enforces the claim's
truthfulness. Neither alone is sufficient, which is why there are two.

---

## 7. Determinism, and what breaks it

Constitution VI: given the same raw data, plugin versions and parameters, outputs
are byte-identical. Concretely the guarantees are:

- **No wall-clock inside computation.** `performance.py`, `portfolio.py`,
  `replay/engine.py` and the rules are pure functions. `datetime.now(UTC)`
  appears once, in `runner.py`, to stamp `created_at` on the run record —
  metadata, never an input.
- **No randomness in the scoring path.** The synthetic generator is seeded;
  nothing else samples.
- **Fixed iteration order.** `compute_signals` sorts output by
  `(symbol, date, rule_name)`. `pair_trades` sorts by `(symbol, entry_date)`.
  `_combine` sums sleeves in the run's recorded selection order — float addition
  is not associative, so the summation order is part of the answer and is pinned
  deliberately. `replay_events` sorts same-day signals by symbol.
- **Effective parameters are recorded, not declared defaults.**
  `SignalRule.effective_params` merges overrides into defaults and *that* is what
  is stored on the run and on every signal. Recording the bare defaults while
  executing overrides would make the record unreproducible — `registry.py` says
  so in the docstring.
- Components are evaluated in the order listed in the strategy spec,
  and combined output is sorted by `(symbol, date)`. `ExecutionSimulator` is
  likewise pure — no I/O, no wall clock, no randomness — so the same bars,
  decisions and config give byte-identical fills.

### What actually breaks it

**A re-ingest.** This is the real one. Everything above holds "given the same
bars". Bars are not immutable in practice: a provider revises a print, a split is
backfilled, a gap is repaired, an adapter is fixed. Run the identical request
before and after and you get a different answer, with nothing in the request to
explain it.

That is why `runner.py` records:

```python
ingest_runs = backend.ingest_run_ids(requested_symbols, warmup_start, end_date)
```

> Which ingest produced the bars we just read. Two runs with identical
> configuration either side of a re-ingest differ here and nowhere else.

`ingest_run_ids` is the only field that can explain the discrepancy. If two runs
of the same strategy over the same window disagree, compare `ingest_run_ids`
first. Note it spans `warmup_start`, not `start_date`: a revision inside the
warm-up changes the indicator values and therefore the signals, without touching
a single bar in the reported window.

`instrument_ids` is recorded for the adjacent reason — the canonical `symbol` is
unique but editable, while `instrument_id` is the stable key the bar store joins
on. A ticker change would otherwise silently repoint a saved run at a different
company.

**Corporate actions.** `runner.py` calls `backend.corporate_actions(...)` and
persists the result on the run. From the source:

> Reported, never applied: stored bars are unadjusted, so a split inside the
> window makes the series jump in a way that is an artefact.

See §9.

---

## 8. Worked example, five bars, arithmetic shown

One symbol. Every number below is computed, not illustrative; the cross-checks at
the end have to close.

**Strategy.** One component: `rsi-threshold`, `period: 14`, `oversold: 30`, role
`entry`, `entry_logic: "all"`. No exit component — this strategy exits only on
execution criteria, which CONTRACT_V2 §3 permits and the builder warns about.

**Execution.**

```jsonc
{
  "initial_capital": 100000.0,
  "position_sizing": "fixed_notional",
  "sizing_value": 50000.0,
  "fill_timing": "signal_close",
  "commission_bps": 5.0,      // 0.05% per side
  "slippage_bps": 10.0,       // 0.10% per side
  "stop_loss_pct": 0.05,
  "take_profit_pct": 0.10,
  "allow_shorts": false
}
```

**Window.** `start_date: 2024-03-04`, `end_date: 2024-03-08`.
Warm-up: `rsi-threshold` declares `lookback_days: 16`, so bars load from
`2024-03-04 − 32 days = 2024-02-01`. Those bars produce the RSI values and are
never traded.

**Bars in the reported window:**

| # | date | open | high | low | close | RSI(14) |
|---|---|---|---|---|---|---|
| 1 | 2024-03-04 | 99.50 | 100.80 | 99.10 | 100.00 | 28.4 |
| 2 | 2024-03-05 | 100.10 | 101.40 | 99.60 | 100.00 | 31.6 |
| 3 | 2024-03-06 | 101.20 | 103.00 | 100.90 | 102.80 | 44.1 |
| 4 | 2024-03-07 | 102.50 | 111.30 | 94.80 | 97.20 | 38.0 |
| 5 | 2024-03-08 | 97.00 | 98.20 | 96.50 | 98.00 | 39.5 |

### Bar 1 — nothing

RSI 28.4 is below `oversold`, but `rsi-threshold` fires on the *exit* from the
zone, not on being in it. From `signals/builtins.py`:

> bullish: RSI exited the oversold zone (was < oversold, now >= oversold)

No event. Equity = 100,000.00, all cash.

### Bar 2 — signal, order, fill

RSI goes 28.4 → 31.6: was `< 30`, now `>= 30`. **Bullish event** on 2024-03-05,
`data_window_end = 2024-03-05`, `trigger_values = {"rsi": 31.6}`.

Composition: one entry component, `all` → satisfied. No filters. Decision: open
long.

`fill_timing: "signal_close"` → fill on bar 2 at bar 2's close, 100.00.

```
  slippage   buy fills higher:  100.00 * (1 + 0.0010)      = 100.10
  qty        50,000 / 100.10                               = 499.5005
  notional   499.5005 * 100.10                             =  50,000.00
  commission 50,000.00 * 0.0005                            =      25.00
  cash       100,000.00 - 50,000.00 - 25.00                =  49,975.00
```

The entry price of record is **100.10** — the fill, not the close. Every
protective level is measured from it:

```
  stop    100.10 * 0.95  =  95.095
  target  100.10 * 1.10  = 110.110
```

Mark at bar 2's close: `49,975.00 + 499.5005 * 100.00 = 49,975.00 + 49,950.05`
= **99,925.05**.

Down 74.95 on day one with the price unchanged. That is 49.95 of slippage
(`499.5005 × 0.10`) plus 25.00 of commission. Cross-check:
`49.95 + 25.00 = 74.95`, and `100,000.00 − 74.95 = 99,925.05`. ✓

### Bar 3 — mark only

No signal. Stop 95.095 is below the low (100.90); target 110.110 is above the
high (103.00). Neither triggers.

```
  position   499.5005 * 102.80     =  51,348.65
  equity     49,975.00 + 51,348.65 = 101,323.65
```

### Bar 4 — both levels inside one bar

```
  high 111.30  >=  target 110.110   -> target reachable
  low   94.80  <=  stop    95.095   -> stop reachable
```

Ambiguous. Resolution order says **stop**.

Did it gap through? The open is 102.50, above the stop, so no. The stop fills at
its level, 95.095.

```
  slippage   sell fills lower: 95.095 * (1 - 0.0010)       =  94.999905
  proceeds   499.5005 * 94.999905                          =  47,452.50
  commission 47,452.50 * 0.0005                            =      23.73
  cash       49,975.00 + 47,452.50 - 23.73                 =  97,403.77
```

Trade record:

| field | value |
|---|---|
| `side` | long |
| `entry_date` / `entry_price` | 2024-03-05 / 100.10 |
| `exit_date` / `exit_price` | 2024-03-07 / 94.999905 |
| `qty` | 499.5005 |
| `exit_reason` | `stop_loss` |
| `return_pct` | `94.999905 / 100.10 - 1` = **−0.050950** |
| `pnl` (price only) | `(94.999905 - 100.10) * 499.5005` = **−2,547.50** |
| `fees` | `25.00 + 23.73` = **48.73** |

The 5% stop realised −5.095%, not −5.00%, because `0.95 × 0.999 = 0.94905`. The
extra 9.5bp is the exit slippage. Fees take it to −5.19% of the notional.

Cross-check the book: `−2,547.50 − 48.73 = −2,596.23`, and
`100,000.00 − 2,596.23 = 97,403.77`. ✓

### Bar 5 — flat

No position, no signal (RSI 38.0 → 39.5 crosses nothing). Equity stays
**97,403.77**.

### The run

```
  equity: 100,000.00  99,925.05  101,323.65  97,403.77  97,403.77

  total_return    97,403.77 / 100,000.00 - 1   = -2.596%
  max_drawdown    97,403.77 / 101,323.65 - 1   = -3.869%
  trade_count     1
  win_rate        0/1 = 0.0
  exit_reasons    { "stop_loss": 1 }
  costs           { "commission": 48.73, "slippage": 97.45 }
```

Slippage total: entry `499.5005 × (100.10 − 100.00) = 49.95`, exit
`499.5005 × (95.095 − 94.999905) = 47.50`. Sum **97.45**.

`sharpe_ratio` computes to a number from four daily returns. Ignore it. See §11.

### The counterfactual that makes §3 concrete

Same bar 4, resolved to the target instead:

```
  exit level 110.110, slippage:  110.110 * 0.999   = 109.99989
  proceeds   499.5005 * 109.99989                  =  54,945.00
  commission 54,945.00 * 0.0005                    =      27.47
  cash       49,975.00 + 54,945.00 - 27.47         = 104,892.53

  total_return  +4.893%
```

**−2.60% or +4.89%**, on one trade, from a choice the data cannot settle. That is
the entire argument for taking the stop. Now imagine a run with 200 trades and a
parameter sweep pointed at it.

---

## 9. What this is still not

Say this part out loud, because the numbers above look like a P&L and are not
one.

**No live broker.** Nothing here places an order anywhere. There is no order
router, no venue, no connectivity, no account. The `Execution` view in the
frontend (`frontend/src/quantlab/data/execution.ts`) is a browser-side simulation
with no matching engine behind it, and its own docstring says so. It is a UI
demonstration, not a trading surface.

**No market impact.** `slippage_bps` is a constant. Real slippage scales with
your size relative to the instrument's liquidity, widens in the volatility that
also triggers your stops, and is worst precisely when everyone else's stop is
firing too. A flat basis-point haircut models the average case of a market that
does not have an average case. Treat it as a floor on your costs, not an
estimate of them.

**No borrow costs, no shorting fees, no locate.** `allow_shorts` mirrors the long
path arithmetically and nothing else. A real short pays a borrow rate that on a
hard-to-borrow name can exceed any edge the signal has, can be recalled at the
worst possible moment, and may not be locatable at all. Short results from this
engine are an upper bound with an unmodelled and unbounded cost line.

**No dividends, no corporate-action adjustment.** Stored bars are unadjusted. A
2-for-1 split appears as a −50% day and will trigger every long stop in the book.
`runner.py` calls `backend.corporate_actions(...)` and persists the result on the
run, so reopening a saved run still warns — *reported, never applied*. If your
window contains a split, the run is wrong and the run tells you it is wrong. It
does not fix it. Dividends are simply absent: a total-return series and this
price series diverge by the dividend yield, compounding, which on income names
over multi-year windows is not a rounding error.

**Daily bars only.** No intraday fills, no limit orders resting inside a bar, no
partial fills, no queue position, no auction vs continuous-session distinction.
The intrabar ambiguity in §3 is a direct consequence and cannot be resolved
without intraday data the free stack does not provide.

**No financing, no interest on cash.** Idle cash earns zero. At non-zero policy
rates that understates a low-turnover strategy — and flatters nothing, which is
the acceptable direction to be wrong.

**Survivorship bias, in any real ingested universe.** Constitution III and the
README are blunt about it: every free source lists *currently listed* companies.
Backtest a screen over "the FTSE 350" as it exists today and you have quietly
excluded every name that delisted, was acquired, or went to zero. The synthetic
demo universe is immune because it is synthetic. Anything ingested is not. There
is no free fix — only snapshotting universe membership from today forward, which
is why the constitution mandates it on every refresh.

**Data licensing is a legal exposure, not a technical one.** Stooq and Yahoo are
unofficial sources with no redistribution rights (Constitution III). See
[SECURITY.md](SECURITY.md).

---

## 10. What is built, what is left, and where the code has overtaken the contract

Verified against the working tree as this was written. The library layer landed
recently and moves fast; re-check before trusting any row.

### Built

| Area | Where |
|---|---|
| `ExecutionConfig`: all 17 fields, validated, with `assumptions()` generated from the values that actually ran | `execution/config.py` |
| `ExecutionSimulator`: fixed intrabar ordering, protective exits against high/low, gap-through fills at the open, `next_open` queued orders, shorts, sleeved *and* pooled cash, ATR stops, all four sizing modes, per-trade `exit_reason`/`pnl`/`fees` | `execution/engine.py` |
| `StrategySpec` / `StrategyComponent`: roles, the four combinators, `combine_window_days`, `invert`, weights, validation naming the offending component, `warnings()`, `promote_legacy()` for the single-model path | `strategy/spec.py` |
| Composed lookback including the execution layer's own ATR requirement | `StrategySpec.lookback_days` |
| Ten new signal rules with `category`, `summary`, `roles` | `signals/library.py` |
| The indicators they need — ema, macd, bollinger, rolling_std, rolling_zscore, true_range, atr, stochastic, roc, adx, obv, donchian | `indicators/technical.py` |
| `category` / `summary` / `roles` on `SignalRule`, defaulted so pre-existing rules register unchanged | `signals/registry.py` |

That closes what were the two largest open questions: the indicator dependency
(ported into the backend distribution rather than reaching into `src/quantlab`,
which ARCHITECTURE.md explains is a separate distribution that is never
installed alongside it), and the cash model (both, selected by sizing mode).

### Resolved during the wiring pass

Eight things were open when this document was first drafted. All eight are
closed, and two of them were real bugs rather than missing work.

| # | What it was | How it landed |
|---|---|---|
| 1 | Nothing was wired: `runner.py`, `routes.py`, `performance.py` and `replay/engine.py` did not import `execution/` or `strategy/` at all | All four drive them now. `POST /runs` takes `model_name`, `strategy_id` or an inline `strategy` — exactly one, else 400 |
| 2 | `replay/engine.py` reduced every bar to `float(bar.close)` before the simulator saw it | Rewritten to drive `ExecutionSimulator` directly, so whole bars reach it. A test asserts a `stop_loss` fill appears in the SSE stream — it could not have, before |
| 3 | `load_replay_inputs` loaded the window with no warm-up | Loads from `start_date - StrategySpec.lookback_days`; events and the curve still start at `start_date` |
| 4 | `performance.ASSUMPTIONS` was a module constant | `ExecutionConfig.assumptions()` generates them from the values that ran. The constant survives only as the default config's disclosure |
| 5 | `performance.Trade` (7 fields) and `ExecutedTrade` (12) were two implementations of one idea | `Trade` gained the five missing fields, all defaulted; `compute_performance` re-executes through the simulator instead of re-deriving. `pair_trades` survives only as the reference implementation the parity test checks against |
| 6 | No identity or strategy schema, and `CREATE TABLE IF NOT EXISTS` cannot add a column | `users`, `sessions`, `strategies`; `owner_id`, `strategy`, `execution`, `execution_summary` on runs; `kind` on signals. `db.migrate()` runs inside `bootstrap()` and `ALTER`s what is missing, so an existing database upgrades when it is opened. Postgres gets migration `004` |
| 7 | **Bug.** `runner.py` compared *calendar* days in the window against *bars* of lookback | Converts first: `window_days * 5/7` sessions against a lookback counted in bars. A 60-day window holds about 43 sessions, and used to be accepted against a 50-bar lookback it could never satisfy |
| 8 | Warm-up was padded from a single rule's `lookback_days` | Uses `StrategySpec.lookback_days`: deepest component, plus the agreement window, plus whatever execution needs |

A ninth was found while writing the tests, and is the one worth remembering:

> **A profit target used to collect a favourable gap.** The gap rule was written
> once and applied to both protective exits, so a session that opened *above* a
> long's target filled at the open — a better price than the order asked for.
> That is free money the backtest awards itself on every gap up, and it
> compounds. Stops and targets are now resolved separately: a stop that gaps
> through fills at the open, which is *worse* than the level and is what really
> happens; a target that gaps through fills at the target, declining the
> windfall. The asymmetry is the point. Pessimism has to be applied in the
> direction that hurts, on both sides, or it is not pessimism — it is a
> preference for good news.

### Where the contract had to change

Building it surfaced six places where the implementation was right and
`CONTRACT_V2.md` was wrong. That document says of itself that it is the bug
report when the two disagree, so it was corrected rather than the code:

- **The intrabar order has five steps, not four.** "Fill orders queued
  yesterday" is step 2, which is how `next_open` is implemented, and it has to
  precede the protective checks because a position opened at today's open is
  exposed for the rest of today's session.
- **`rejected_shorts_disabled` and `contradictions`** join `execution_summary`.
  A bearish entry silently dropped because `allow_shorts` is false is exactly
  the kind of invisible non-event that makes a run confusing.
- **`sizing_value` is rejected under `equal_weight`**, not ignored. Silently
  discarding a number somebody typed into a form is how a run quietly does
  something other than what the form said.
- **Percentage fields are bounded to `(0, 1]`.** Not pedantry: a user who types
  `5` meaning "five percent" would otherwise get a stop 500% away that never
  triggers, and the result would read as "the stop never helped".
- **`donchian-breakout` takes `entry_window` and `exit_window`** — the turtle
  asymmetry, entering slowly and leaving quickly.
- **`equal_weight` stays sleeved while the other three modes pool**, so
  `max_positions` and `rejected_no_cash` mean different things between them.
  Stated now, because somebody comparing two sizing modes would otherwise meet a
  behaviour change they did not ask for.

One more thing changed that no contract mentioned: **filters are excluded from
anything that materialises signals** — the demo seed and the warehouse's
`sync_rules`. A filter describes a *state*, so it emits on every bar; seeding
three of them across twelve instruments and three years would have buried 5,212
real signals under roughly 28,000 rows saying "the gate is shut". They remain
fully available to strategies, which evaluate them live and never store them.

---

## 11. How to read the output without fooling yourself

- **A Sharpe from a short window is noise.** `performance._sharpe` needs two
  returns to produce a number and it will produce one from two. A quarter is ~63
  bars; the standard error on an annualised Sharpe estimated from 63 daily
  observations is roughly `1/sqrt(63/252)` = 2.0. A reported 1.8 over three
  months is indistinguishable from zero. The function returns `None` only when
  the ratio is *undefined* — fewer than two points, or zero variance — because,
  as the docstring says, a fabricated 0.0 would read as "measured, and
  mediocre". It does not and cannot return `None` for "measured, and
  meaningless".
- **The benchmark is the run's own universe**, equal-weight buy-and-hold, not an
  index (`performance.benchmark_series`). Deliberate: it isolates the model's
  *timing* from the question of which names it was pointed at. It also means
  beating it is not the same as beating the market.
- **`win_rate` covers closed trades only.** Positions still open at the end of
  the window are marked and flagged, never counted. A strategy that holds its
  losers open to the last bar shows a flattering win rate, and the `open: true`
  trades are where to look.
- **`trade_count` includes open trades; `winning_trades + losing_trades` does
  not.** They will not sum. Trades that close exactly flat count as neither.
- **`assumptions` travels inside the response body**, not in UI copy. On purpose:
  a refactor can drop a caption, and the caveat has to survive being pasted into
  a spreadsheet.

Further reading: [STRATEGY_GUIDE.md](STRATEGY_GUIDE.md) for choosing the
parameters, [ARCHITECTURE.md](ARCHITECTURE.md) for where the code lives,
[CONTRACT_V2.md](CONTRACT_V2.md) for the normative field list.
