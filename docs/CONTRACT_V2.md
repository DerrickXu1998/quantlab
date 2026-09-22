# QuantLab API v1 — the strategy, execution and identity contract

The design rationale for the surfaces added in this change, and the document
the backend, frontend and docs were built against.

**The machine-readable contract is
[`quantlab_specs/specs/006-warehouse-experiments/contracts/openapi.yaml`](../quantlab_specs/specs/006-warehouse-experiments/contracts/openapi.yaml)**
(v0.6.0), which is the authored single source of truth the constitution
requires and the file the TypeScript client is generated from. This document
explains *why*; that one defines *what*. Where the two disagree, the OpenAPI
document wins and this one is the bug.

Everything below has been reconciled against the shipped implementation.

The API version stays `v1`. Nothing here removes or renames an existing field,
and every previously valid request stays valid — see [Backwards
compatibility](#backwards-compatibility).

---

## 1. Identity

Until now the API had no notion of a user. Every experiment run lived in one
global table, so any caller could list, rename and delete every other caller's
work. That is the security hole this section closes.

### Token model

Opaque bearer tokens, not JWTs. A session is a row in the database, so
`POST /auth/logout` genuinely revokes it; a signed stateless token cannot be
withdrawn before it expires. The token is 32 bytes from `secrets.token_urlsafe`
and only its SHA-256 is stored — a database read does not yield a usable
credential.

SHA-256 is the right primitive for the *token* and a slow KDF would be the wrong
one: the token is CSPRNG output with no guessable structure, so there is nothing
for key stretching to protect against, and paying it on every authenticated
request would be absurd.

Pinned parameters:

| | |
|---|---|
| Password KDF | PBKDF2-HMAC-SHA256 |
| Iterations | 600,000 (OWASP 2023 floor), recorded in the hash |
| Salt | 16 bytes, per password |
| Encoding | `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>` |
| Password policy | ≥ 12 characters, ≤ 256 bytes, NFKC-normalised, not in a small obvious-password list, ≥ 4 distinct characters |
| Session TTL | 30 days, absolute — not extended by use |

The cost travels inside the hash, so the iteration count can be raised later
without a mass reset: an old hash verifies against its own recorded cost and is
re-derived at the current one on the next successful login. The choice of
PBKDF2 over argon2id is a dependency decision, argued in
[`SECURITY.md`](SECURITY.md).

Authenticated requests carry `Authorization: Bearer <token>`.

### Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | none | Create an account, return a session |
| `POST` | `/api/v1/auth/login` | none | Exchange credentials for a session |
| `POST` | `/api/v1/auth/logout` | bearer | Revoke the calling session |
| `GET` | `/api/v1/auth/me` | bearer | The current user |

`register` and `login` take `{"email": str, "password": str}` and return:

```json
{
  "user": { "id": "…", "email": "…", "created_at": "2026-09-20T12:00:00Z" },
  "token": "…",
  "expires_at": "2026-10-20T12:00:00Z"
}
```

Status codes: `201` register, `200` login, `204` logout, `401` bad credentials
or bad token, `409` email already registered, `422` password fails policy,
`429` too many failed attempts for that email.

`login` answers `401` with the same message and the same timing whether the
email is unknown or the password is wrong, so the endpoint is not an account
enumeration oracle.

### Ownership

`experiment_runs` and `strategies` gain `owner_id`. Every read, write and
delete is filtered by the authenticated user, **in SQL** — a row that is not the
caller's is never loaded, rather than being loaded and then dropped by a check
somebody can forget to write. Reading another user's run is `404`, never `403`:
a `403` confirms the row exists.

`owner_id` is nullable. Runs recorded before accounts existed have none, and are
reachable only in single-user mode; there is no way to know retroactively whose
they were, and inventing an owner would be worse than admitting that.

### Single-user mode

Auth is enforced whenever `QUANTLAB_AUTH_REQUIRED` is unset or true. Setting it
to `false` restores the current open behaviour for the local demo, binding
requests to a built-in `local` user so ownership columns are still populated
and the two modes do not diverge in shape.

---

## 2. Signals

A *signal rule* is unchanged as a concept: bars in, directional events out. What
changes is that a rule is no longer the whole strategy — it is a component of
one.

`GET /api/v1/models` gains three fields per item, none removed:

```jsonc
{
  "name": "macd-crossover",
  "version": "1.0.0",
  "parameters": [ /* ParamSpec[], unchanged */ ],
  "lookback_days": 35,
  "scale_class": "scale_free",
  "direction_semantics": "…",

  "category": "momentum",          // momentum | trend | mean_reversion | volatility | volume
  "summary": "MACD line crossing its signal line.",
  "roles": ["entry", "exit"]        // which strategy roles this rule may fill
}
```

`roles` is the honest part: `adx-trend-filter` emits a regime state rather than
a tradeable event, so it advertises `["filter"]` and the builder will not let a
user wire it as an entry.

### The rule catalogue after this change

| Rule | Category | Roles |
|---|---|---|
| `sma-crossover` | trend | entry, exit |
| `ema-crossover` | trend | entry, exit |
| `macd-crossover` | momentum | entry, exit |
| `rsi-threshold` | mean_reversion | entry, exit |
| `stochastic-threshold` | mean_reversion | entry, exit |
| `bollinger-reversion` | mean_reversion | entry, exit |
| `zscore-reversion` | mean_reversion | entry, exit |
| `roc-momentum` | momentum | entry, exit |
| `breakout-20d` | volatility | entry, exit |
| `donchian-breakout` | volatility | entry, exit |  <!-- takes entry_window and exit_window, not one period -->
| `volume-spike` | volume | filter |
| `adx-trend-filter` | trend | filter |
| `rsi-zone` | mean_reversion | filter |

---

## 3. Strategies

A strategy is the object the user actually onboards: several signals, a rule for
combining them, and the execution criteria that turn the combination into
trades.

```jsonc
{
  "id": "…",
  "name": "RSI oversold in an uptrend",
  "description": "",
  "components": [
    {
      "rule_name": "rsi-threshold",
      "rule_version": "1.0.0",      // optional; latest when omitted
      "parameters": { "period": 14, "oversold": 25 },
      "role": "entry",               // entry | exit | filter
      "weight": 1.0,                 // only read by weighted logic
      "invert": false                // swap bullish/bearish from this component
    },
    {
      "rule_name": "adx-trend-filter",
      "parameters": { "period": 14, "threshold": 25 },
      "role": "filter"
    }
  ],
  "entry_logic": "all",              // all | any | majority | weighted
  "exit_logic": "any",
  "entry_threshold": 1.0,            // weighted only: net weight needed to fire
  "exit_threshold": 1.0,
  "combine_window_days": 1,          // components may agree within N bars, not only the same bar
  "execution": { /* ExecutionConfig, §4 */ },
  "owner_id": "…",
  "created_at": "…",
  "updated_at": "…"
}
```

### Combination semantics

Each component is evaluated independently over the symbol's bars, producing
bullish/bearish events per date. On each date, per symbol:

- A component is **active bullish** on date `T` if it emitted a bullish event in
  `[T - combine_window_days + 1, T]`; likewise bearish. With the default window
  of 1 that means "fired today".
- `all` — every entry-role component must be active bullish.
- `any` — at least one.
- `majority` — strictly more than half.
- `weighted` — the summed `weight` of active bullish entry components is
  `>= entry_threshold`.
- **Filters gate, they never fire.** An entry is suppressed unless every
  filter-role component is active bullish on that date. A filter alone can
  never open a position.
- `invert: true` swaps that component's two directions before any of the above.
- Exit-role components are combined by `exit_logic` into an exit decision.
  Filters do **not** gate exits — a filter turning off must never trap a
  position in the book.
- A strategy with no exit-role components exits only on execution criteria
  (§4). That is legal and the builder warns rather than blocks.

Determinism: components are evaluated in the order listed, and the combined
output is sorted by `(symbol, date)`. The same spec over the same bars is
byte-identical (Constitution VI).

Lookback: the strategy's warm-up is `max(component.lookback_days)`, plus
`combine_window_days - 1`.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/strategies` | The caller's strategies |
| `POST` | `/api/v1/strategies` | Create |
| `GET` | `/api/v1/strategies/{id}` | Read |
| `PUT` | `/api/v1/strategies/{id}` | Replace |
| `DELETE` | `/api/v1/strategies/{id}` | Delete |

All require a bearer token and are scoped to `owner_id`. `422` names the
offending component and parameter on a bad spec, e.g.
`components[0].parameters.period: must be <= 100`.

A read also carries `warnings: string[]` — the things in §3's list that are legal
but probably unintended. They are **computed per request, never stored**: a
strategy with no exit was legal when it was saved and still is, but what is worth
flagging about it changes as the engine does, and a stored copy would go stale.

`GET /api/v1/strategy-templates` (unauthenticated) serves four complete starter
strategies. They are assembled from the registry at request time, so a template
can only ever name rules that exist, and each carries realistic costs — a starter
that charged nothing would teach a new user that turnover is free.

---

## 4. Execution criteria

The gap this closes: entries and exits were previously hardcoded at "the close
of the signal date, whole sleeve, no costs, no stops". Every one of those is now
a field, and every field is reported back on the run so a result carries the
assumptions that produced it.

```jsonc
{
  "initial_capital": 100000.0,

  "position_sizing": "equal_weight",   // equal_weight | fixed_fraction | fixed_notional | volatility_target
  "sizing_value": null,                // fraction of equity | notional per trade | target annual vol
                                       // REJECTED (422) under equal_weight, not ignored
  "max_positions": null,               // cap on concurrent open positions
  "max_position_pct": 1.0,             // cap per name, as a fraction of equity

  "fill_timing": "signal_close",       // signal_close | next_open
  "commission_bps": 0.0,               // charged per side, on notional
  "slippage_bps": 0.0,                 // adverse price move applied per side

  "stop_loss_pct": null,               // 0.05 = exit 5% against entry
  "take_profit_pct": null,
  "trailing_stop_pct": null,           // from the best close seen while held
  "atr_stop_multiple": null,           // stop at entry -/+ k * ATR(atr_period)
  "atr_period": 14,

  "max_holding_days": null,            // force an exit after N bars
  "min_holding_days": 0,               // suppress exits before N bars
  "cooldown_days": 0,                  // bars to wait after an exit before re-entering

  "allow_shorts": false
}
```

### Sleeved and pooled capital

`equal_weight` gives every instrument its own cash sleeve that compounds
independently. That is what the pre-execution engine did, and keeping it is what
makes a legacy run reproduce to the last floating-point bit. The other three
modes draw on a single shared pool.

The difference is visible, so it is worth stating: under `equal_weight` a
position is limited by its own sleeve and `max_positions` rarely binds, while
under a pooled mode every position competes for the same cash and
`rejected_no_cash` becomes a number worth reading.

`sizing_value` is **rejected** rather than ignored when `equal_weight` does not
read it. Silently discarding a number the user typed into a form is how a run
quietly does something other than what the form said.

### Resolution order within one bar

Order matters and is fixed, because two criteria can both be satisfiable on the
same bar and a backtest that resolves them in an arbitrary order is not
reproducible:

1. Mark the bar.
2. **Orders queued yesterday** fill at today's open. This step exists to
   implement `next_open`, and it has to come before the protective checks: a
   position opened at today's open is exposed for the rest of today's session.
3. **Protective exits**, tested against the bar's own range in this order:
   `stop_loss` → `trailing_stop` → `take_profit` → `max_holding_days`.
   A stop and a target that are both inside one bar's high–low resolve to the
   **stop**. That is deliberately the pessimistic reading: intrabar order is
   unknowable from a daily bar, and assuming the favourable one is how
   backtests flatter themselves.
4. **Signal exits**, if `min_holding_days` has elapsed.
5. **Signal entries**, subject to `max_positions`, `cooldown_days`, available
   cash and every filter.

Entries come last because a position closed today frees the capital and the slot
a new one needs; resolving it the other way would silently cap the book at one
rotation per bar.

Protective exits fill at their trigger level, not at the close, and gaps are
resolved pessimistically in **both** directions — which is not symmetric
arithmetic:

- A **stop** is an order to leave on weakness. A session that gaps clean through
  it fills at that session's **open**, which is worse than the level. Pretending
  the stop held is how a backtest hides its worst days.
- A **target** is an order to leave on strength. A session that gaps clean
  through it would really fill at the open, which is *better* than the level —
  so the engine declines it and fills at the **target**. Collecting every
  favourable gap adds up to an edge no live book ever earns.

`fill_timing: "next_open"` moves signal-driven entries and exits to the next
bar's open. Protective exits stay intrabar; they are price-triggered, not
signal-triggered. A signal on the final bar of the window with `next_open` has
no bar to fill on and is dropped, reported in the run's coverage.

Costs: `commission_bps` and `slippage_bps` are each charged on both entry and
exit. Slippage moves the fill price against the position (buys fill higher,
sells fill lower); commission is deducted as cash.

Shorting, when `allow_shorts` is true, mirrors the long path: a bearish entry
opens a short, a bullish signal covers it, and stop/target percentages are
measured in the direction that hurts a short.

---

### Warm-up

A run loads bars from `start_date - lookback`, where lookback is the deepest
component's, plus `combine_window_days - 1`, plus anything execution needs (an
ATR stop needs an ATR). Those bars are **inputs, never results**: no signal is
dated in the warm-up, nothing is traded there, and the reported equity curve and
benchmark both begin at `start_date`. Reading bars before the window is past data
relative to every emitted signal, so it cannot introduce look-ahead; the
forbidden direction is enforced by a CHECK constraint and by the truncation
sweep.

The same warm-up is loaded when re-deriving performance and when replaying, so
all three agree. A window shorter than the strategy's lookback is refused rather
than run — and the comparison converts bars to sessions first, because 60
calendar days hold about 43 of them.

## 5. Runs

`POST /api/v1/runs` accepts either of two request shapes.

**Legacy — unchanged, still supported:**

```json
{ "model_name": "rsi-threshold", "parameters": {}, "symbols": ["ZZTRND"],
  "start_date": "2024-01-01", "end_date": "2024-12-31" }
```

**Strategy:**

```jsonc
{
  "strategy_id": "…",          // OR an inline "strategy" object
  "strategy": { /* §3, without id/owner_id/timestamps */ },
  "execution": { /* §4 — overrides the strategy's own execution */ },
  "symbols": ["ZZTRND", "ZZMEAN"],
  "start_date": "2024-01-01",
  "end_date": "2024-12-31"
}
```

Exactly one of `model_name`, `strategy_id`, `strategy` may be given; `400`
otherwise. A legacy single-model request is internally promoted to a one
component strategy with default execution, so there is one execution path and
not two.

The `Run` response keeps every existing field and gains:

```jsonc
{
  "strategy": { /* the fully resolved spec actually executed */ },
  "execution": { /* the fully resolved config actually executed */ },
  "execution_summary": {
    "orders": 42, "fills": 40,
    "rejected_no_cash": 1, "rejected_max_positions": 3, "rejected_cooldown": 0,
    "rejected_shorts_disabled": 18, "dropped_no_bar": 1,
    "total_commission": 118.44, "total_slippage": 96.10,
    "contradictions": 0
  }
}
```

`model_name` and `model_version` remain populated — for a composed strategy
they carry the first entry component, so existing clients keep working.

### Performance

`GET /api/v1/runs/{id}/performance` keeps its shape and gains per-trade detail:

```jsonc
{
  "trades": [{
    "symbol": "ZZTRND", "side": "long",
    "entry_date": "…", "entry_price": 101.2, "exit_date": "…", "exit_price": 108.0,
    "qty": 96.2, "return_pct": 0.0672, "open": false,
    "exit_reason": "take_profit",   // signal | stop_loss | take_profit | trailing_stop | max_holding | end_of_window
    "pnl": 654.16, "fees": 12.40
  }],
  "costs": { "commission": 118.44, "slippage": 96.10 },
  "exit_reasons": { "signal": 18, "stop_loss": 9, "take_profit": 11, "end_of_window": 2 },
  "assumptions": [ "…" ]
}
```

`assumptions` is now **derived from the resolved ExecutionConfig** rather than
being a fixed tuple, so it states what the run actually did — "0.05% commission
and 0.02% slippage charged per side", not "no transaction costs are charged".

---

## Backwards compatibility

- No field is removed or renamed anywhere.
- A `POST /runs` body with `model_name` behaves exactly as before, including its
  default execution criteria, so stored runs stay reproducible.
- New `Run` and `Trade` fields are additive; `strategy`, `execution` and
  `execution_summary` are nullable on runs recorded before this change.
- With `QUANTLAB_AUTH_REQUIRED=false` the API is reachable exactly as it is
  today, which is what keeps `make smoke` and the existing contract tests
  meaningful.
