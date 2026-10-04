# Strategy ideas from the current feature/signal catalog

Drafted 2026-09-30. Candidate strategies for the Strategy tab, derived from what
the signal-rule registry (`backend/src/quantlab/signals/`) and the research
feature catalog (`quantlab_data/indicators/`, `quantlab_data/derived/` in quantlab-data-pipeline) already
provide. Each entry says whether it is buildable in StrategyBuilder today, and
if not, exactly which gap blocks it. Gap IDs continue the register in
`docs/AI_QUANT_BOOK_STRATEGY_PLAN.md` §3 (F1–F9, D1–D5, U1–U5 already taken).

The 8 existing templates (4 starters + S1/S2/S6/S7 presets) are deliberately
not repeated here; the ideas below complement them.

## A. Buildable today in the Strategy tab

Each lists components (rule → role), combination logic, and the execution
config worth starting with. All are daily, long-only unless noted.

### A1 — Trend pullback (stochastic)

Buy dips inside established uptrends instead of chasing breakouts.

- Entry: `stochastic-threshold` (k_period=14, d_period=3, oversold=20) — fires
  when %K leaves the oversold zone.
- Filter: `adx-trend-filter` (period=14, threshold=25) — trend must exist.
- Exit: `stochastic-threshold` (ob=80) — leaving overbought.
- Logic: entry `all`, exit `any`.
- Execution: `fill_timing: next_open`, `atr_stop_multiple: 2`, `max_holding_days: 20`.
- Why it might work: `adx` as a gate was the strongest structural choice in the
  S1 backtests; this applies the same gate to a faster trigger.
- Falsifier: loses to S1's MACD entry on the same universe — then the gate,
  not the trigger, is doing all the work.

### A2 — Capitulation reversion (z-score + volume)

Buy panic flushes confirmed by volume, exit on normalization.

- Entry: `zscore-reversion` (window=20, threshold=2).
- Filter: `volume-spike` (window=20, multiple=1.5) — the flush must be real.
- Exit: `zscore-reversion` exit side (z crossing back through threshold).
- Execution: `stop_loss_pct: 6` or ATR stop, `max_holding_days: 15`,
  `cooldown_days: 5` to avoid re-fading the same collapse.
- Note: adjacent to template S2 but a different trigger family (price z-score
  vs RSI) and a volume gate S2 lacks. Run both; keep whichever survives costs.

### A3 — 52-week-high breakout

The academic "52-week high" anomaly, expressible as a long-window Donchian.

- Entry: `donchian-breakout` (entry=252, exit=20).
- Filter: `volume-spike` (multiple=1.5) — breakout must be sponsored.
- Exit: the Donchian exit channel, plus `trailing_stop_pct: 15`.
- Execution: `min_holding_days: 5` to ride out first-week noise.
- **Verify before relying**: the rule's `entry` parameter upper bound must
  allow 252; if the bound is lower, that is a one-line metadata fix, not new
  machinery. A 252-bar lookback also pushes warm-up past a year — backtest
  windows must start ≥ ~14 months after series start.

### A4 — Fundamental quality-growth swing

Trade the filing, not the quarter: enter on reported revenue acceleration in
financially clean names.

- Entry: `revenue-growth` (threshold=0.10).
- Filters: `profitability-filter` (min_roe=0.10) + `leverage-filter`
  (max_ratio=1.0).
- Exit: `accrual-reversal` (earnings quality deteriorating) or
  `max_holding_days: 63` (one quarter).
- Logic: `combine_window_days: 21` — filing-day events are sparse; the window
  keeps entries warm while the filters re-confirm.
- Caveat: fundamentals coverage is the binding constraint (see the builder's
  CoverageWarning); expect few events on small-cap universes.

### A5 — Overbought fade, short side

Mirror of the RSI starter, harvesting the short side the default config ignores.

- Entry: `rsi-threshold` (period=14, ob=75) — bearish leg opens the short.
- Filter: `adx-trend-filter` **inverted** (threshold=20) — only fade when there
  is no trend to run you over.
- Exit: `rsi-threshold` bullish leg closes the short.
- Execution: `allow_shorts: true`, `borrow_cost_bps: 100`, tight
  `stop_loss_pct: 5` (short squeezes gap), `max_holding_days: 15`.
- Why: exercises the `invert` + shorts + borrow-cost machinery end-to-end —
  currently no template does.

### A6 — Macro-gated breakout

S6's gate applied to a breakout entry instead of a trend entry.

- Entry: `breakout-20d` (window=20).
- Filters: `macro-risk-off` (vix_max=25) + `adx-trend-filter` (threshold=20).
- Exit: `breakout-20d` exit side; `atr_stop_multiple: 2.5`.
- Note: S1/S6 backtests showed trend entries rarely fire with VIX>30 anyway;
  the sharper test of the macro gate is on breakouts, which *do* fire into
  volatility spikes.

## B. Blocked — what the strategy tab cannot express yet

### B1 — Cross-sectional momentum rotation *(blocked: F10)*

"Monthly, buy the top decile of the universe by 12-1 momentum, hold until it
leaves the top quintile." Every feature needed already exists in the research
engine (`momentum_12_1`, `cs_rank`, `residual_momentum`,
`relative_strength`, `sector_neutral`), all point-in-time clean. What is
missing is portfolio construction: the execution engine trades each instrument
independently against the same rule — there is no cross-instrument ranking, no
rebalance frequency, no target weights. The `weighted` combine logic is
per-instrument only.

- **F10**: portfolio-level execution — rank a universe by a feature, rebalance
  on a schedule, hold N positions with target weights. Touches
  `strategy/spec.py` (new portfolio block), `execution/engine.py`
  (rebalance pass before per-instrument signals), and StrategyBuilder UI.
- **U6**: ranking/rebalance controls in the strategy UI + a holdings table on
  run detail.

### B2 — Pairs / statistical arbitrage *(blocked: F1, F2 — already registered)*

Unchanged from `AI_QUANT_BOOK_STRATEGY_PLAN.md` S3: needs multi-instrument
signal rules and paired-leg execution. Listed here only for completeness.

### B3 — Volatility-regime strategies *(blocked: F11, partially U7)*

Squeeze-release ("enter when `squeeze` turns off with momentum sign") and
choppiness-gating ("ignore trend entries when `choppiness` > 61.8") are the
natural next regime filters after ADX — the indicators exist and are tested in
`quantlab_data/indicators/volatility.py` (quantlab-data-pipeline), but no backend signal rule wraps them.

- **F11**: port `squeeze` and `choppiness` as backend signal rules (filter
  role). Small, mechanical, follows the `adx-trend-filter` pattern.
- **U7**: frontend for custom rules. The backend already exposes
  `indicator-threshold` / `indicator-crossover` / `fundamental-condition`
  templates via `/signal-templates` + `/custom-rules`, but there is no UI to
  create them — with U7, B3-class filters become user-buildable without new
  backend rules at all.

### B4 — Insider & short-squeeze strategies *(blocked: F12; data caveat)*

"Enter on insider cluster buys" (`insider_activity.cluster_buy`) and "crowded
short + non-liquid + momentum" (`short_squeeze_score`) exist as derived
features with PIT discipline, but no backend signal rule consumes them.

- **F12**: signal rules over `insider_activity` (filter or entry on
  `cluster_buy`) and `fca_short_interest` / `short_squeeze_score`.
- Data caveat: `finra_short_volume` carries ~1 month of history — fine for
  live, useless for backtests; `fca_short_interest` is UK-only. Scope B4 to
  US insiders + UK shorts accordingly.

### B5 — Signal-strength sizing *(blocked: F13)*

"Size positions by conviction" (z-score magnitude, weighted-score fraction).
The engine's sizing modes are all signal-blind; `weighted` logic decides
*whether* to enter, never *how much*.

- **F13**: an optional `sizing_from_score` mode scaling `fixed_fraction` by the
  weighted combine score. Cheap once F10's plumbing exists; not worth doing
  standalone.

## Suggested order

1. Backtest A1–A6 as-is (zero code). A1/A3/A5 exercise paths no template
   covers: stochastic triggers, 252-bar warm-up, shorts with invert.
2. **F11** (squeeze/choppiness filters) — hours, unlocks B3.
3. **U7** (custom-rule UI) — days, makes the whole indicator catalog
   user-reachable; the highest-leverage single UI item here.
4. **F10 + U6** (portfolio construction) — the only item that is an
   architecture decision rather than an increment; do it before B4/B5.
