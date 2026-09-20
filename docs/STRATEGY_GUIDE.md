# Strategy guide — from "I want to trade RSI" to a saved strategy

For someone who knows what RSI is and wants to test a rule with it. If you want
to know what happens to the order after the strategy fires, read
[EXECUTION_MODEL.md](EXECUTION_MODEL.md) instead — this document is about
choosing what fires and when.

**What runs today.** All thirteen signal rules are registered
(`signals/builtins.py` and `signals/library.py`), and the strategy and execution
layers are implemented in `backend/src/quantlab/strategy/` and
`backend/src/quantlab/execution/`. What does **not** exist yet is the wiring:
`research/runner.py` and `api/routes.py` do not call any of it, so none of it is
reachable from an HTTP request. Everything below is checkable against the code
and none of it is yet callable over the API. See
[EXECUTION_MODEL.md](EXECUTION_MODEL.md) §10 for the exact state.

Every parameter name and default here is taken from the registered
`ParamSpec`s. If a value below is rejected with a `422`, the rule is right and
this document is stale — check the rule's own spec via `GET /api/v1/models`.

---

## 1. A signal is not a strategy

This distinction is the thing most people get wrong, and it is the reason the
builder is shaped the way it is.

**A signal rule** takes one instrument's bars and emits directional events:

```
  bars in  ->  [ {date: "2024-03-05", direction: "bullish", rsi: 31.6}, ... ]
```

That is all it does. It has no opinion about position size, about whether you
are already long, about what to do if it fires three days running, or about what
price you would get. It is a *detector*. `rsi-threshold` detects "RSI came back
up through 30". Whether that is worth acting on is not its business.

**A strategy** is the object you actually trade:

- several rules, each assigned a **role** (entry, exit, or filter),
- a rule for **combining** them into one decision per symbol per day,
- and an **execution configuration** that turns a decision into orders, fills,
  costs and stops.

### Why the difference matters

Because the interesting questions live in the second object, not the first.

"Does RSI work?" is not answerable. "Does buying when RSI(14) crosses back above
30, only when ADX(14) is above 25, exiting on a 5% stop or when RSI crosses back
below 70, with 5bp commission and 10bp slippage, over these 40 names from 2020
to 2024" is answerable. Same detector, and the two sentences are not the same
claim.

It also means you can change the costing, the stop, or the filter without
touching the detector — and the run record carries the resolved strategy *and*
the resolved execution config, so a result always says which combination
produced it.

One more consequence: the same rule can be a detector in one strategy and
nothing at all in another. `rsi-threshold` advertises roles
`["entry", "exit"]`; `adx-trend-filter` advertises `["filter"]` only, because it
reports a regime rather than a tradeable event. The builder refuses to wire a
filter-only rule as an entry. That is not a UI nicety — see §3.

---

## 2. The three roles

| Role | What it does | Can it open a position? | Can it close one? |
|---|---|---|---|
| `entry` | Fires the decision to open | Yes | No |
| `exit` | Fires the decision to close | No | Yes |
| `filter` | Gates whether an entry is allowed | **Never** | **Never** |

### Entry — a worked example

```jsonc
{
  "rule_name": "rsi-threshold",
  "parameters": { "period": 14, "oversold": 30, "overbought": 70 },
  "role": "entry"
}
```

`rsi-threshold` emits bullish when RSI exits the oversold zone — was below 30,
now at or above it. With `entry_logic: "all"` and this as the only entry
component, that bullish event is the decision to open a long.

Note what it is *not*: it is not "RSI is below 30". Being oversold is a state
and can persist for twenty bars; the rule fires on the *transition out*. Read
`direction_semantics` on any rule before you assume what triggers it. From
`signals/builtins.py`:

> bearish: RSI exited the overbought zone (was > overbought, now <= overbought);
> bullish: RSI exited the oversold zone (was < oversold, now >= oversold)

### Exit — a worked example

```jsonc
{
  "rule_name": "rsi-threshold",
  "parameters": { "period": 14, "oversold": 30, "overbought": 70 },
  "role": "exit",
  "invert": false
}
```

The same rule, in the exit slot. Its bearish event — RSI falling back through
70 — is now the decision to close. A mean-reversion strategy that enters
oversold and exits overbought is exactly this rule twice, in two roles.

`invert: true` swaps a component's two directions before anything else happens.
It is for the case where a rule's natural direction is backwards for your thesis
— a breakout rule used as a fade, say. It is easy to confuse yourself with;
prefer changing the parameters if you can express the same idea that way.

### Filter — a worked example

```jsonc
{
  "rule_name": "adx-trend-filter",
  "parameters": { "period": 14, "threshold": 25 },
  "role": "filter"
}
```

ADX above 25 means "there is a trend here". This component never opens anything.
It only *permits*: an entry is suppressed unless every filter-role component is
active bullish on that date.

### The trap: a filter cannot open a position

If you build a strategy whose only components are filters, it will never trade.
Not "trade rarely" — never, zero orders, an empty run. This looks like a bug and
is not one.

The failure mode people hit is subtler: they wire a filter-shaped rule into the
*entry* slot. "ADX > 25" is true on hundreds of consecutive bars. As an entry
condition that means "enter every single bar", which after the first entry
becomes "enter, then re-enter every bar you are not already in". The backtest
fills up with trades that have nothing to do with any thesis, the turnover
explodes, and the costs eat everything — and nothing in the output says *why*,
because every one of those entries was a correctly evaluated condition. This is
exactly why rules advertise `roles` and the builder enforces them.

### And filters deliberately do not gate exits

From CONTRACT_V2 §3:

> Filters do **not** gate exits — a filter turning off must never trap a
> position in the book.

Consider what the alternative does. You are long, gated in by ADX > 25. The
trend dies, ADX falls to 18, the filter goes false. Your exit rule fires. If
filters gated exits, the exit would be suppressed — because the filter is
off — and you would be **locked into a position you can no longer exit by
signal**, in precisely the regime your own filter just told you had ended.

You would then be relying entirely on the stop-loss to get out, which converts
every filtered strategy into "hold until stopped" the moment conditions change.
That is strictly worse than the alternative it was meant to prevent.

The principle generalises: **conditions that restrict getting in should never
restrict getting out.** Anything that can trap a position is a bug even when
every individual rule evaluated correctly.

---

## 3. The four combination modes

Each component is evaluated independently and produces bullish/bearish events
per date. A component is **active bullish** on date `T` if it emitted a bullish
event in `[T - combine_window_days + 1, T]`. With the default
`combine_window_days: 1`, that means "fired today".

Raise `combine_window_days` when you want components to *agree* without
demanding they agree on the same bar — MACD crossing on Tuesday and a breakout
confirming on Thursday is still a confluence. Raise it too far and "agreement"
degrades into "both happened this month", which is not a signal.

### `all` — every entry component must be active bullish

```jsonc
{ "entry_logic": "all", "combine_window_days": 1,
  "components": [
    { "rule_name": "rsi-threshold",  "role": "entry", "parameters": {"period": 14, "oversold": 30} },
    { "rule_name": "macd-crossover", "role": "entry", "parameters": {"fast": 12, "slow": 26, "signal": 9} }
  ]}
```

Both must fire. Conjunction is the strictest mode and produces the fewest
trades. Two conditions that each fire 20 times a year rarely coincide on the
same bar; with `combine_window_days: 1` this may produce a handful of trades
across a multi-year window, which is not enough to conclude anything. If `all`
gives you three trades, widen the window or move to `any` — do not conclude the
strategy is selective.

### `any` — at least one

```jsonc
{ "entry_logic": "any",
  "components": [
    { "rule_name": "breakout-20d",      "role": "entry",
      "parameters": {"window": 20} },
    { "rule_name": "donchian-breakout", "role": "entry",
      "parameters": {"entry_window": 55, "exit_window": 20} }
  ]}
```

Disjunction: "a short breakout *or* a long one". Most useful when the components
express the same idea at different speeds and you do not want to pick.

Watch the turnover. `any` fires at least as often as its most trigger-happy
component, and adding a component can only increase the trade count.

### `majority` — strictly more than half

```jsonc
{ "entry_logic": "majority",
  "components": [
    { "rule_name": "macd-crossover", "role": "entry", "parameters": {"fast": 12, "slow": 26, "signal": 9} },
    { "rule_name": "ema-crossover",  "role": "entry", "parameters": {"fast": 20, "slow": 50} },
    { "rule_name": "roc-momentum",   "role": "entry", "parameters": {"period": 12, "upper": 5.0, "lower": -5.0} }
  ]}
```

Two of these three. A voting scheme for components that measure the same thing
different ways — here, three views of momentum. It tolerates one detector being
out of phase, which is the usual failure of any single trend rule.

**Strictly** more than half: with 2 components, majority needs 2, which makes it
identical to `all`. With 4 it needs 3. Use odd counts or the mode surprises you.

### `weighted` — summed weight of active components meets a threshold

```jsonc
{ "entry_logic": "weighted", "entry_threshold": 1.5,
  "components": [
    { "rule_name": "macd-crossover",     "role": "entry", "weight": 1.0, "parameters": {"fast": 12, "slow": 26, "signal": 9} },
    { "rule_name": "rsi-threshold",      "role": "entry", "weight": 0.5, "parameters": {"period": 14, "oversold": 30} },
    { "rule_name": "zscore-reversion",   "role": "entry", "weight": 0.5, "parameters": {"window": 20, "threshold": 2.0} }
  ]}
```

MACD alone (1.0) is not enough. MACD plus either confirmer (1.5) is. Either
confirmer alone (0.5) is not. The other three modes are all special cases of
this one, and the price of the generality is that the threshold is one more
number with no principled value — which makes it one more knob for a sweep to
overfit. Reach for `weighted` when you genuinely have a primary signal and
secondary confirmers, not as a default.

`exit_logic` and `exit_threshold` work identically over exit-role components.
`exit_logic: "any"` is the sane default: you generally want *one* reason to be
enough to get out.

**A strategy with no exit components is legal.** It then exits only on execution
criteria — stop, target, trailing stop, `max_holding_days`, or the end of the
window. The builder warns rather than blocks. If you do this, make sure at least
one of those criteria is set, or every position runs to the end of the window
and your win rate is computed over nothing (open trades never count — see
EXECUTION_MODEL.md §11).

---

## 4. Every execution criterion, in plain English

Contract §4. For each: what it does, when you want it, and how it hurts you.

### Sizing

| Field | What it does |
|---|---|
| `initial_capital` | The notional book. Scale-invariant for every ratio metric; it only sets the axis labels. |
| `position_sizing` | `equal_weight` \| `fixed_fraction` \| `fixed_notional` \| `volatility_target` |
| `sizing_value` | Fraction of equity, notional per trade, or target annual vol, depending on the mode |
| `max_positions` | Cap on concurrent open positions |
| `max_position_pct` | Cap per name as a fraction of equity |

**`equal_weight`** splits capital into one sleeve per name in the run's
selection; an untraded sleeve sits in cash. It is the only **sleeved** mode —
each name has its own cash bucket and trades only its own instrument. The other
three draw on a shared pool. *Want it when* comparing a rule across a universe
without letting one name dominate. *Failure mode:* your result depends heavily
on which names were in the selection; with a large universe each sleeve is small
enough that fixed costs matter more; and because cash is sleeved, one name's
idle capital cannot fund another's entry, so `max_positions` behaves differently
here than under the pooled modes. Note also that `sizing_value` is *rejected*
under `equal_weight` rather than ignored — a number you typed must never be
silently dropped.

**`fixed_fraction`** risks a constant fraction of *current* equity, so it
compounds. *Want it when* modelling something you would actually scale.
*Failure mode:* compounding amplifies the early part of the window. A strategy
that happened to work in year one shows a total return dominated by that year,
and reordering the same returns would give a different answer.

**`fixed_notional`** is flat regardless of equity. *Want it when* you want each
trade to count equally so the trade statistics mean something. *Failure mode:*
it is not how anyone trades, and it can size above available equity after a
drawdown.

**`volatility_target`** sizes so each position's estimated volatility hits a
target, so quiet names get more capital. *Want it when* your universe mixes
utilities and small-cap biotech and you do not want the biotech to be the whole
result. *Failure mode:* volatility is estimated from a trailing window, so it is
always late — it sizes *up* into the calm that precedes a shock, which is the
one time you wanted less.

**`max_positions`** caps concurrent names. *Want it when* you have a
concentration limit. *Failure mode:* it makes the result path-dependent in a way
that is easy to miss — which signals get filled depends on which fired first,
so the run silently measures "the first N signals" rather than the rule.

**`max_position_pct`** caps one name's share of equity. *Want it* always, as a
sanity bound.

### Timing

**`fill_timing: "signal_close"`** fills at the close of the signal's own bar.
*Want it when* you want the least pessimistic assumption that is still not
look-ahead. *Failure mode:* it assumes you could transact at the close you used
to make the decision — true for a liquid name at the auction, optimistic for
anything thin.

**`fill_timing: "next_open"`** fills at the next bar's open. *Want it when* you
want a defensible assumption: you saw the close, you queued the order, you got
the next print. *Failure mode:* overnight gaps are exactly where the news is. On
a rule that reacts to large moves, the next open is systematically worse and the
strategy may lose most of its edge — which is information, not a problem with
the setting. Also, a signal on the window's final bar has no bar to fill on and
is dropped (counted in `dropped_no_bar`).

### Costs

**`commission_bps`** — charged per side, on notional, deducted as cash.
**`slippage_bps`** — per side, moving the price against you.

*Want them:* always, on every run you intend to believe. Zero costs is a
diagnostic setting for checking that the signal logic does what you think, not a
result.

*Failure mode:* both are constants. Real slippage scales with your size relative
to liquidity and is worst in the volatility that also triggers your stops. A
flat haircut is a floor on your costs, not an estimate. See §7 for why the size
of the number matters more than you expect.

### Protective exits

**`stop_loss_pct`** — exit at a fixed percentage against the entry *fill* price
(not the signal close). *Want it when* you need a bounded loss per trade.

*Failure mode, and this is the big one:* **a tight stop on a volatile name
converts a winning strategy into death by a thousand cuts.** If the instrument's
daily range routinely exceeds your stop distance, the stop is not managing risk —
it is sampling noise. You get stopped out at the bottom of ordinary
oscillations, re-enter on the next signal, and pay two sides of costs each time,
while the trades that would have carried the strategy never get room to develop.
The diagnostic is in the response: `exit_reasons` dominated by `stop_loss` with
a win rate far below what the rule shows unstopped. The fix is usually
`atr_stop_multiple` rather than a bigger percentage, because it scales the stop
to the instrument instead of to your intuition.

**`take_profit_pct`** — exit at a fixed percentage in your favour. *Want it when*
the thesis is explicitly a bounded move, like a mean-reversion snap back to an
average.

*Failure mode:* it truncates the right tail. Most trend-following returns come
from a small number of very large winners; capping every winner at +10% while
leaving losers to run to the stop inverts the payoff the rule depends on. It
also flatters the win rate, which is the metric most likely to make you feel
good about a strategy that loses money.

**`trailing_stop_pct`** — a stop measured from the best *close* seen while held,
ratcheting up and never down. *Want it when* you want to let a winner run but
keep the gains.

*Failure mode:* it exits on the first meaningful retracement, and normal trends
retrace. Set from closes, it is also blind to an intrabar spike that would have
taken out a fixed stop. A trail tight enough to protect much of the profit is
tight enough to end most trends early.

**`atr_stop_multiple`** with **`atr_period`** — the stop sits `k × ATR(period)`
from entry, so a volatile name gets a wide stop and a quiet one a narrow stop.
*Want it* as the default for any multi-name run, because one percentage cannot
be right for a $400 name and a 90p line at once (Constitution II's scale-class
problem, in another guise).

*Failure mode:* ATR is trailing, so after a volatility regime change the stop is
sized for the old regime — too tight just after volatility rises, which is when
you most need it wide. Typical `k` is 2 to 3; below 1.5 you are back to
sampling noise.

### Holding constraints

**`max_holding_days`** — force an exit after N bars. *Want it when* the thesis
has a horizon ("mean reversion should resolve within ten days") and a position
that has not worked in that time is a failed thesis, not a slow one.

*Failure mode:* it exits at an arbitrary price on an arbitrary date, at the
close, with no trigger. On a trend rule it is close to random and cuts winners
indiscriminately.

**`min_holding_days`** — suppress signal exits before N bars. *Want it when* your
entry and exit rules are the same detector and it whipsaws, entering and exiting
within a bar or two.

*Failure mode:* it deliberately blocks your exit logic. Protective exits still
fire, so a losing trade can still stop out — but a signal exit saying "this was
wrong" is ignored until the clock runs out. Keep it small, and treat a large
value as evidence the entry rule is the thing that needs fixing.

**`cooldown_days`** — bars to wait after an exit before re-entering the same
name. *Want it when* a rule re-fires immediately after being stopped out and you
are paying costs to repeatedly buy the same falling knife.

*Failure mode:* it will make you miss the real entry. A genuine reversal often
happens right after the failed one.

### `allow_shorts`

Mirrors the long path: a bearish entry opens a short, a bullish signal covers,
stop and target percentages measure in the direction that hurts a short.

Left at `false` — the default — a bearish *entry* decision is dropped and
counted in `rejected_shorts_disabled`. Check that counter if a strategy you
expected to trade both ways looks unexpectedly quiet; a silently discarded
entry is otherwise invisible.

*Failure mode, and it is not a parameter choice:* the model charges **no borrow
cost, no shorting fee and no locate**. A hard-to-borrow name's borrow rate can
exceed any edge the signal has. Short results here are an upper bound with an
unmodelled and unbounded cost line, and the gap is largest on exactly the names
a short signal likes.

---

## 5. Warm-up, and why a short window lies to you

A strategy's warm-up (`StrategySpec.lookback_days`) is:

```
  max(component.lookback_days)
    + combine_window_days - 1
    + execution.extra_lookback_days     # atr_period + 1, if an ATR stop is set
```

bars, and the runner loads that much history *before* `start_date`. Those bars
are inputs to the indicators and are never traded.

Three things follow:

1. **Adding a slow component lengthens the warm-up for the whole strategy.**
   Adding a 200-day moving average to a strategy of 14-day rules means 200 bars
   of history must exist before the window, for every symbol. Symbols that
   cannot supply it appear in `coverage.instruments_full_warmup` as a shortfall
   — check that number rather than assuming the run covered what you asked for.
2. **Turning on an ATR stop lengthens the warm-up too.** The stop is set from
   the ATR as at the entry bar, so a position opened on the window's first bar
   needs `atr_period` bars behind it or the stop would be undefined. Switching
   `atr_stop_multiple` on can therefore change how much history a run needs
   even though you touched nothing in the strategy.
3. **A window shorter than the warm-up is refused**, not silently returned
   empty. A 30-bar window on a rule needing 51 bars is an error, because an
   empty result would look like "the rule found nothing".

Full mechanics in [EXECUTION_MODEL.md](EXECUTION_MODEL.md) §5.

---

## 6. Four starter strategies

These are the four templates the builder ships (`frontend/src/strategies/templates.ts`),
with the reasoning behind the numbers. Load one, change one thing, run it —
that is how most people learn what the controls do, and a filled builder is a
better first screen than a blank one.

Every rule used below is registered today and every parameter name comes from
its `ParamSpec`. Parameters not listed take the rule's registered defaults; the
template loader applies a suggested value only where the registry actually
declares a parameter of that name, and reports any rule the backend does not
have rather than faking it.

### 6.1 RSI mean reversion

*Buys names that have fallen far enough to look stretched, and lets them go once
they have recovered. Wants a stop, because "stretched" can always stretch
further.*

```jsonc
{
  "name": "RSI mean reversion",
  "components": [
    { "rule_name": "rsi-threshold", "role": "entry",
      "parameters": { "period": 14, "oversold": 30 } },
    { "rule_name": "rsi-threshold", "role": "exit",
      "parameters": { "period": 14, "overbought": 60 } }
  ],
  "entry_logic": "all",
  "exit_logic": "any",
  "combine_window_days": 1,
  "execution": {
    "initial_capital": 100000.0,
    "position_sizing": "fixed_fraction",
    "sizing_value": 0.20,
    "max_positions": 5,
    "stop_loss_pct": 0.05,
    "take_profit_pct": 0.10,
    "commission_bps": 5.0,
    "slippage_bps": 2.0,
    "min_holding_days": 1,
    "cooldown_days": 2,
    "allow_shorts": false
  }
}
```

The same rule twice, in two roles, with *different* parameters — that is the
detail worth copying. Entry uses `oversold: 30`; exit uses `overbought: 60`
rather than the registered 70. Waiting for a full 70 on a name that only fell to
30 means often waiting for a recovery that does not arrive; 60 takes the
reversion when it happens. The two components are independent evaluations of
`rsi-threshold` and nothing requires their parameters to match.

`take_profit_pct: 0.10` against `stop_loss_pct: 0.05` is a 2:1 target-to-stop —
reasonable for mean reversion, where the thesis is a bounded snap back rather
than an open-ended move. `min_holding_days: 1` stops the same detector entering
and exiting on consecutive bars; `cooldown_days: 2` stops it re-buying a falling
name immediately after a stop.

**The known weakness:** mean reversion loses badly in a sustained downtrend,
where "oversold" is just "going down". The obvious fix is a regime filter, and
the obvious trap is adding one, seeing the number improve, and treating that as
confirmation — see §7.

### 6.2 MACD trend following

*Rides momentum: in on the crossover, out on the crossover back, with a trailing
stop so a reversal does not give the whole move back.*

```jsonc
{
  "name": "MACD trend following",
  "components": [
    { "rule_name": "macd-crossover", "role": "entry" },
    { "rule_name": "macd-crossover", "role": "exit" }
  ],
  "entry_logic": "all",
  "exit_logic": "any",
  "combine_window_days": 1,
  "execution": {
    "initial_capital": 100000.0,
    "position_sizing": "equal_weight",
    "max_positions": 4,
    "trailing_stop_pct": 0.08,
    "commission_bps": 5.0,
    "slippage_bps": 2.0,
    "allow_shorts": false
  }
}
```

No parameters at all: `macd-crossover` registers 12/26/9, the conventional
values, and a template that overrode them would be asserting something it cannot
justify. Starting from registered defaults is the honest default.

Note **no `sizing_value`** — `equal_weight` rejects one rather than ignoring it,
and this is the only one of the four templates using sleeved cash.

No take-profit, on purpose. Trend following earns its return from a small number
of very large winners, and a fixed target caps exactly the part that pays. The
8% trailing stop is the compromise: it lets a winner run while limiting
give-back. It will also exit some trends early on an ordinary retracement, which
is the price.

**The known weakness:** MACD whipsaws in a range, crossing back and forth and
paying costs each time. That is what 6.3 addresses.

### 6.3 Donchian breakout with an ADX filter

*Only takes breakouts while the market is actually trending — the ADX filter is
what keeps it out of the chop where breakouts fail.*

```jsonc
{
  "name": "Donchian breakout with ADX filter",
  "components": [
    { "rule_name": "donchian-breakout", "role": "entry" },
    { "rule_name": "adx-trend-filter",  "role": "filter",
      "parameters": { "period": 14, "threshold": 25 } }
  ],
  "entry_logic": "all",
  "exit_logic": "any",
  "combine_window_days": 1,
  "execution": {
    "initial_capital": 100000.0,
    "position_sizing": "fixed_fraction",
    "sizing_value": 0.25,
    "max_positions": 4,
    "stop_loss_pct": 0.06,
    "max_holding_days": 40,
    "commission_bps": 5.0,
    "slippage_bps": 3.0,
    "allow_shorts": false
  }
}
```

**This strategy has no exit component**, and that is the instructive part. It
exits only on execution criteria — the 6% stop, the 40-session cap, or the end
of the window. That is legal, the builder warns rather than blocks, and it is
only safe *because* both criteria are set. Delete either one and positions run
to the end of the window, at which point they are marked open, excluded from the
win rate, and the trade statistics describe almost nothing.

`donchian-breakout` uses its registered `entry_window: 20` / `exit_window: 10`.
The two windows are separate on purpose — the turtle asymmetry, entering slowly
and leaving quickly — so even used for entries only, the rule is already
asymmetric internally.

ADX > 25 gates entries only. A breakout in a range is a false breakout, and this
is the filter doing the job filters exist for. When ADX falls away mid-trade the
position is *not* trapped, because filters do not gate exits (§2) — here that
matters doubly, since the only way out is the stop or the clock.

Slippage is 3bp rather than 2: you are buying strength, into a move, at a price
that has just gone through a level everyone else is watching.

### 6.4 Bollinger fade on volume

*Fades a push outside the bands, but only when volume confirms that the push was
a real event rather than a thin-tape wobble.*

```jsonc
{
  "name": "Bollinger fade on volume",
  "components": [
    { "rule_name": "bollinger-reversion", "role": "entry" },
    { "rule_name": "volume-spike",        "role": "filter" },
    { "rule_name": "zscore-reversion",    "role": "exit" }
  ],
  "entry_logic": "all",
  "exit_logic": "any",
  "combine_window_days": 2,
  "execution": {
    "initial_capital": 100000.0,
    "position_sizing": "fixed_fraction",
    "sizing_value": 0.15,
    "max_positions": 6,
    "stop_loss_pct": 0.04,
    "take_profit_pct": 0.06,
    "max_holding_days": 15,
    "commission_bps": 5.0,
    "slippage_bps": 3.0,
    "allow_shorts": false
  }
}
```

The most interesting of the four, because all three roles are filled by three
*different* rules: Bollinger detects the stretch, volume confirms it was real,
and a z-score decides when it is over. Nothing requires the entry and exit
detectors to be the same rule, and here they deliberately are not — the
condition that gets you in is not the condition that tells you the trade is
done.

`combine_window_days: 2` is doing real work. A band breach and a volume spike
often land a bar apart — the volume arrives with the move that causes the
breach. At 1 this strategy would trade rarely and you would wrongly conclude the
volume filter kills it.

The tightest risk settings of the four: a 4% stop with a 6% target and a
15-session cap. That suits a strategy whose thesis is a short, sharp snap back —
and it is also the one most exposed to the failure in §4, because a 4% stop on a
volatile name is inside a single bad day's range. If `exit_reasons` comes back
dominated by `stop_loss`, this is the strategy where that diagnosis matters
most.
---

## 7. How to not fool yourself

The uncomfortable section. Every item is a way to produce a good-looking number
that means nothing, and all of them are easy to do by accident.

### Overfitting

The engine will happily score ten thousand parameter combinations and report the
best. The best of ten thousand is not the best strategy; it is the combination
that best matches this particular sample's noise.

The tell is **fragility**. If `period: 14` shows a Sharpe of 1.4 and `period:
13` and `period: 15` show 0.3, you have not found a parameter — you have found a
coincidence. A real effect is a *plateau*: neighbouring parameters give
similar answers, because the underlying phenomenon does not care about your
exact integer. Always look at the neighbourhood, never at the maximum alone.

Corollary: **prefer fewer components and rounder numbers.** Each component adds
parameters, each parameter multiplies the search space, and a strategy with
eleven tuned numbers has almost certainly memorised its sample. `oversold: 30`
is a convention. `oversold: 27.5` is a fitted constant, and you should be able
to say why it is not 27 or 28.

### The multiple-comparisons problem

This is overfitting stated precisely, and the arithmetic is worth doing once.

Sweep three parameters over ten values each: 1,000 combinations. Suppose every
one is pure noise with zero expected return. The expected *maximum* t-statistic
across 1,000 independent draws from a standard normal is about **3.1**, and it
grows like `sqrt(2 ln N)`.

So: sweep a thousand useless strategies and the winner will show a t-stat above
3 — the threshold most people treat as strong evidence — **with certainty, by
construction, from nothing.** The number is not evidence of an edge; it is
evidence that you ran a thousand tests.

What to do:

- **Count your tests and say the number out loud**, including the ones you ran
  last week and abandoned. The count includes every variant you tried, not just
  the ones in the final sweep.
- **Raise the bar with the count.** Roughly, require your t-stat to exceed
  `sqrt(2 ln N)` before you are interested at all.
- **Decide the evaluation rule before you look.** "I will accept it if the
  out-of-sample Sharpe exceeds 0.8" is a test. "That one looks good" is not.

### In-sample vs out-of-sample

Split the window *before* you start. Develop on the first portion, and do not
run on the held-out portion until you have committed to a single strategy.

The part that actually matters and gets violated constantly: **once you look at
out-of-sample results and change anything, that data is in-sample.** There is no
way to un-see it. If you tune against the holdout three times, you have a
three-observation in-sample set and no holdout at all.

A 2020–2024 window contains a crash, a melt-up and a rate cycle. A strategy that
works in all of them is interesting. A strategy fitted across all of them is
overfitted to the whole period, and a rolling walk-forward — fit on a window,
test on the next, roll, repeat — is the only version of this that does not
quietly cheat.

And keep a strategy's *identity* stable when you compare periods. Refitting the
parameters per period and reporting the combined result measures your fitting
procedure, not the strategy.

### A Sharpe from three months means nothing

The standard error on an annualised Sharpe estimated from `n` daily observations
is roughly `1/sqrt(n/252)`.

| Window | Bars | Approx. standard error |
|---|---|---|
| 3 months | 63 | 2.0 |
| 1 year | 252 | 1.0 |
| 3 years | 756 | 0.58 |
| 10 years | 2520 | 0.32 |

A Sharpe of 1.8 over three months has a standard error of 2.0 — it is
indistinguishable from zero. Over ten years, distinguishing a Sharpe of 0.5 from
a Sharpe of 1.0 takes most of the decade.

This is not a limitation of this tool; it is how much information a price series
contains. `performance._sharpe` will compute a number from two returns and it
returns `None` only when the ratio is genuinely *undefined*, never for "defined
but meaningless". Judging that is your job.

Same problem in the trade statistics: a win rate over 8 closed trades carries a
standard error of about 18 percentage points. Eight trades cannot distinguish a
60% strategy from a 40% one.

### Costs matter more than you expect

The arithmetic is short and people reliably do not do it.

At 5bp commission and 10bp slippage, one round trip costs 2 × 15bp = **0.30%**
of notional. Compounding a fully-sized sleeve:

| Round trips per year | Annual cost drag |
|---|---|
| 6 | 1.8% |
| 25 | 7.2% |
| 50 | 14.0% |
| 100 | 26.0% |

`0.997^100 = 0.740`, so a rule taking 100 round trips a year gives up about a
quarter of the book to costs before it has an opinion about anything. A gross
return of 20% a year — a good result — is a loss.

Consequences:

- **Cost sensitivity is the first thing to test, not the last.** Run at 0bp, at
  your estimate, and at double it. A strategy whose sign flips between the first
  two is a cost story, not a signal story. Do this before any parameter tuning,
  because it can save you the tuning.
- **Turnover is a strategy parameter even though it is not a field.** It is
  implied by your rules, and it is often the thing a sweep is really optimising
  when the sweep looks like it is optimising a threshold. A parameter change
  that halves the trade count and improves returns may have found nothing except
  that you were paying too much.
- **Slippage is the number you are most wrong about.** Commission is a published
  rate you can look up. Slippage is a flat constant standing in for a quantity
  that scales with your size, widens with volatility, and is worst exactly when
  your stops are firing. Treat your slippage estimate as a lower bound and test
  double.

### And the things no parameter can fix

- **Survivorship bias** in any real ingested universe. Every free source lists
  currently-listed companies. A backtest over today's index membership has
  excluded everything that failed.
- **Unadjusted prices.** A split inside your window is a −50% day that will
  trigger every long stop in the book. The run reports corporate actions in the
  window and never applies them — check that field before believing a result.
- **Intrabar ambiguity.** When a stop and a target sit inside one bar's range,
  the engine takes the stop, because a daily bar does not record the order. See
  EXECUTION_MODEL.md §3 for why the alternative silently flatters everything.

---

## 8. A workflow that resists most of this

1. Write the thesis in a sentence, in English, before touching a parameter.
   "Oversold names in an uptrend bounce within two weeks." If you cannot write
   it, you are pattern-matching on a chart.
2. Pick parameters from the thesis, not from a sweep. Use conventional values.
3. Run once, with realistic costs, on the in-sample window only.
4. Look at `exit_reasons` and the trade count before looking at the return. If
   the strategy took 4 trades or 4,000, nothing else in the output matters yet.
5. Vary each parameter one step in each direction. Look for a plateau, not a
   peak.
6. Test cost sensitivity at 0×, 1× and 2× your estimate.
7. Only now run the held-out window, once, against a threshold you wrote down in
   step 1.
8. Write down how many distinct configurations you tried across all of the
   above, and keep that number attached to the result.

Most strategies die at step 4 or step 6, and that is the point — those two steps
are cheap and the alternative is finding out later with money.
