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

### B1 — Cross-sectional momentum rotation *(still blocked: F10 is only partly supported)*

"Monthly, buy the top decile of the universe by 12-1 momentum, hold until it
leaves the top quintile." Every feature needed already exists in the research
engine (`momentum_12_1`, `cs_rank`, `residual_momentum`,
`relative_strength`, `sector_neutral`), all point-in-time clean. What was
missing is portfolio construction. Half of that now exists, and the half that
B1 needs most does not.

- **F10, partially supported.** The portfolio-allocation sizing modes
  (`equal_active`, `signal_strength`, `signal_inverse_volatility`; see
  [EXECUTION_MODEL.md §4a](EXECUTION_MODEL.md#4a-portfolio-allocation-shared-capital-target-weights))
  give the engine shared-capital target weights across held positions. They
  also give it a scheduled rebalance (`rebalance_frequency`: `daily`, `weekly`,
  `monthly`), a top-N cut by `max_positions`, per-name caps, a drift threshold
  and a turnover cap.
- **Still missing.** Nothing ranks a universe by a raw feature. The allocator's
  top-N ranks only by the strategy's own entry score, and only among names
  whose rules already fired. "Top decile by 12-1 momentum" is a rank across
  instruments, and no per-instrument rule can express it. Full scheduled
  cross-sectional momentum, including "hold until it leaves the top quintile",
  is therefore **not** buildable yet. The remaining F10 work is a
  feature-ranking input to the allocator. It touches `strategy/spec.py` (a
  ranking block) and the allocator's selection step, which today ranks by
  `(score, symbol)`.
- **U6**: ranking controls in the strategy UI + a holdings table on run detail.
  The allocation and rebalance controls themselves have shipped in the
  builder's **Portfolio allocation** subsection.

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

### B5 — Signal-strength sizing *(supported: F13, via `signal_strength`)*

"Size positions by conviction" (weighted-score fraction). Buildable today: set
`position_sizing: signal_strength`, or `signal_inverse_volatility` to also
scale by trailing volatility.

- **F13, supported, but not as first sketched.** The sketch was a
  `sizing_from_score` mode that scaled `fixed_fraction` by the score. What
  shipped is a portfolio target weight instead. Each entry decision carries
  `_score`, the normalised weighted-combine fraction: the weight of the active
  entry components over the weight of all entry components. Filters and exit
  components are excluded. Before caps, a long's weight is
  `target_exposure * score_i / sum(score_j)` across the active names (shorts
  take the negative sign). Held positions are re-sized
  as conviction or the set of names changes
  ([EXECUTION_MODEL.md §4a](EXECUTION_MODEL.md#4a-portfolio-allocation-shared-capital-target-weights)).
- **Not covered: z-score magnitude.** The score never reads a rule's own
  `trigger_values`. A strategy with one entry component, or with `all` logic,
  always scores 1, and `signal_strength` then behaves exactly like
  `equal_active`. Conviction needs several weighted entry components under
  `any`, `majority` or `weighted` logic.

## Suggested order

1. Backtest A1–A6 as-is (zero code). A1/A3/A5 exercise paths no template
   covers: stochastic triggers, 252-bar warm-up, shorts with invert.
2. **F11** (squeeze/choppiness filters) — hours, unlocks B3.
3. **U7** (custom-rule UI) — days, makes the whole indicator catalog
   user-reachable; the highest-leverage single UI item here.
4. ~~**F13**~~ — done: `signal_strength` sizing. Re-run A1–A6 under
   `equal_active` against their `equal_weight` baseline. That measures what
   shared capital does on its own. Every A-idea has a single entry component,
   so every score is 1 and `signal_strength` adds nothing on top. Testing
   conviction weighting needs an idea with two or more weighted entry
   components.
5. **F10 remainder + U6** (feature ranking). Shared-capital target weights and
   scheduled rebalancing have landed. What is left is ranking a universe by a
   feature, which B1 needs. It is still the only item here that is an
   architecture decision rather than an increment. Do it before B4.
