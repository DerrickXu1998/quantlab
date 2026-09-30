# AI-Quant-Book → QuantLab Strategy Plan

Deep-research distillation of [waylandzhang/ai-quant-book](https://github.com/waylandzhang/ai-quant-book)
("AI Quantitative Trading: From Zero to One", 22 lessons, bilingual CN/EN) mapped onto the
current QuantLab codebase. Written as a plan; the easy tier is now implemented — see §5 for what shipped and the Phase 1 validation results.

- Date: 2026-09-27
- QuantLab capability inventory: see Appendix A
- Book content distillation: see Appendix B

---

## 1. What the book teaches (in one paragraph)

The book is explicitly **not** a "holy grail strategy" book. Its durable takeaways are:

1. **Indicators are features, not signals** — raw indicator crosses are ~51% win rate and net-negative after fees.
2. **Regime first, strategy second** — detect trending / mean-reverting / crisis regimes (ADX, volatility, cross-asset correlation) and gate strategies on regime probabilities.
3. **Decompose returns into Alpha/Beta** before claiming alpha; hedge deliberately (dollar → beta → factor neutral).
4. **ML discipline**: triple-barrier labeling, meta-labeling, purged/embargoed CV, IC/ICIR-based feature selection, never evaluate on accuracy.
5. **Cost-aware execution and risk veto** — transaction costs, slippage, half-Kelly sizing, ATR stops, circuit breakers.
6. **LLMs are a research/enhancement layer, not a trader** — sentiment scoring as one backtested feature, with hard constraints.

The strategies below are chosen to be **replicable in QuantLab** with the smallest possible gap work, ordered from "works today" to "needs new data".

---

## 2. Strategy portfolio (replication plan)

### S1 — Regime-Gated Trend Following (book L05, L12) — *feasible today*
**Book concept**: dual MA cross / MACD entries, but only in trending regimes (ADX > 25); stand aside in ranges.

**QuantLab mapping** (all existing pieces):
- Signals: `sma-crossover` or `macd-crossover` (entry) + `adx-trend-filter` (filter role) — already in `backend/src/quantlab/signals/library.py`.
- Combine with `StrategySpec` combinator `all`, role-weighted via StrategyBuilder UI.
- Execution: `volatility_target` sizing + ATR stops (entry ± 2×ATR per book) — already in `ExecutionConfig`.

**Gap**: none blocking. Nice-to-have: MACD histogram *slope* signal (book prefers slope over raw cross) — small new rule.
**Validation**: run vs. universe equal-weight benchmark across 2010→2026; expect 30–45% win rate with high payoff; confirm it dies in sideways 2015/2022 regimes (that is the book's prediction — a good falsification test).

### S2 — Regime-Gated Mean Reversion (book L05) — *feasible today*
**Book concept**: RSI(14) oversold / Bollinger touch reversion, only in ranging regimes (ADX < 20); mandatory hard stop.

**QuantLab mapping**:
- Signals: `bollinger-reversion` / `zscore-reversion` / `rsi-zone` (entry) + `adx-trend-filter` inverted as filter.
- Execution: tight stop-loss + short max holding (mean-reversion trades are short-lived); no shorts needed for long-only version.

**Gap**: none blocking. The two strategies S1+S2 with opposite ADX gates form the book's "regime routing" baseline (rules-based regime detection — the book's recommended starting point before HMMs).

### S3 — Pairs Trading / Statistical Arbitrage (book L05) — *needs one new signal + engine check*
**Book concept**: Z-score of the **return spread** (not price ratio) of two cointegrated assets; enter |Z|>2 equal-dollar legs, exit at Z→0. Book stresses cointegration ≠ correlation.

**QuantLab mapping**:
- New signal rule: `pair-spread-zscore` — a **multi-instrument rule**, which the current rule contract (`compute(bars, ...) -> [SignalEvent]`, single-instrument bars) does not support.
- Execution: shorts are supported (`ExecutionConfig` has shorts), but **paired-leg atomicity** (both legs entered/sized together, equal-dollar) is not modeled.

**Gaps**:
- *Feature gap F1*: multi-instrument signal rules (pair context, hedge ratio input).
- *Feature gap F2*: paired-leg execution semantics in `execution/engine.py` (sleeved cash exists — one sleeve per leg may be a workable approximation).
- **Workaround today**: none clean. Recommend scoping as the first real feature project.

### S4 — ML Feature-Ranking Pipeline (book L09) — *partially feasible, high leverage*
**Book concept**: compute many features (momentum, volatility, volume ratios, RSI/MACD/Bollinger position, ATR, skew/kurtosis, autocorrelation), select by IC > 0.03 / ICIR > 0.5 / inter-feature corr < 0.7, label with **triple-barrier**, validate with **purged/embargoed CV**, evaluate on IC and long-short quintile spread — never accuracy.

**QuantLab mapping**:
- Features: ~70 indicators + 22 derived features already exist (`src/quantlab/indicators/`, `src/quantlab/derived/`). This is QuantLab's strongest alignment with the book.
- Labels: **triple-barrier labeling does not exist** — new derived-feature module.
- Model: book recommends Ridge (<5k samples) or LightGBM (5k–50k) — with daily bars on ~600 names × 16y you have ~2.4M rows but ~600 independent cross-sections; treat as panel data.
- Evaluation: IC/ICIR computation + quintile spread — new research endpoint.

**Gaps**:
- *Feature gap F3*: triple-barrier label generator (profit-take/stop-loss/time barriers from `ExecutionConfig`-like params).
- *Feature gap F4*: IC/ICIR feature-evaluation service + purged CV splitter (research-only, can live in backend `/research` routes).
- *UI gap U1*: feature-ranking view in Research page (IC table, correlation heatmap, quintile spread chart).
- *Data gap*: none — daily OHLCV + existing fundamentals suffice for a first model.

### S5 — Beta Decomposition & Market-Neutral Overlay (book L08) — *needs benchmark + hedge legs*
**Book concept**: regress excess returns on benchmark → Alpha/Beta/R²; then beta-neutral hedge (short amount = long × β_long/β_hedge).

**QuantLab mapping**:
- Performance module already computes equity vs. equal-weight benchmark (`research/performance.py`) — extend with alpha/beta regression metrics.
- Hedge: short a benchmark instrument (SPY.US is ingestible today via Stooq).

**Gaps**:
- *Feature gap F5*: alpha/beta/R² metrics in run performance + UI display on run detail.
- *Data gap D1*: **no index universes / index price series** (already roadmap Phase 1). Needed for proper beta, sector neutrality, and cross-asset regime correlation.
- *Engine gap*: no borrow cost model for shorts (book: 1–10%/yr) — see F8.

### S6 — Macro Regime Filter (book L12–13) — *needs minor wiring, data mostly present*
**Book concept**: crisis detection via realized vol > 30% annualized, cross-asset correlation > 0.8, VIX level — gate all strategies to defense.

**QuantLab mapping**:
- FRED provider already ingests VIX, UST10Y/2Y, HY spread, dollar index as pseudo-instruments — a genuine asset most backtests lack.
- New filter rule: `macro-risk-off` (VIX > threshold OR HY spread widening) — single-instrument rule against the VIX pseudo-instrument, applied as portfolio-level filter.

**Gaps**:
- *Feature gap F6*: portfolio-level (not per-instrument) filter rules — the current combinator applies rules per instrument. Options: (a) macro rule emits events on every universe member by joining the VIX series, or (b) a true portfolio gate in the runner.
- *UI gap U2*: regime timeline overlay on equity curves (shade crisis periods).

### S7 — Fundamentals + Momentum Composite (book L09 feature stacking) — *feasible today*
**Book concept**: combine value/quality filters with momentum entries; features from different families diversify signal decay.

**QuantLab mapping** (all existing):
- `pe-filter`/`pb-filter`/`profitability-filter` (filter) + `revenue-growth`/`margin-expansion` (quality trend) + `roc-momentum`/`sma-crossover` (entry), combinator `all` or `weighted`.
- PIT fundamentals via `FactSeries` mean no lookahead — matches the book's "restated data" warning.

**Gap**: none blocking. Good second project after S1/S2 because it exercises the `requires_facts` machinery end-to-end.

### S8 — LLM Sentiment Feature (book L14) — *deferred; data gap first*
**Book concept**: news/earnings sentiment scored to structured JSON (event type, −1..1, confidence), used as **one backtested feature among many**, never as a standalone trader. Book's GPT-4 trading experiment: −12% vs +8% S&P — direct LLM trading is an anti-pattern.

**QuantLab mapping**:
- New provider: news feed (NewsAPI / SEC EDGAR filings feed — EDGAR provider already exists and could fetch 8-K text).
- New derived feature: `sentiment_score` (per instrument, per day, PIT by publication timestamp).
- New signal rule: `sentiment-threshold` consuming the feature.

**Gaps**:
- *Data gap D2*: **no news/filings-text data at all** (RNS dropped for UK; no US news feed). Requires provider + storage table + PIT discipline.
- *Feature gap F7*: an LLM-scoring ingest step (offline batch, cached — not in the hot path).
- Recommendation: do this **last**; the book itself says sentiment decays within hours, which daily bars can barely capture. MD&A **tone-change detection across quarters** (book's other LLM use) fits daily-bar QuantLab much better — EDGAR 10-Q sectioned text → tone delta as a quarterly feature.

### S9 — Grid Trading (book L05) — *not recommended*
The book presents grid trading with strong caveats (catastrophic in breakouts) and it requires continuous intraday quotes to fill grid levels. Daily-bar QuantLab cannot simulate it faithfully. **Skip** — documented here so the omission is deliberate.

### S10 — Options strategies (book L05) — *out of scope*
No options data, no Greeks, no plans. Skip.

---

## 3. Gap register

### Feature gaps (engine / signals / API)

| # | Gap | Blocks | Where it lands |
|---|---|---|---|
| F1 | Multi-instrument signal rules (pair context) | S3 | `backend/src/quantlab/signals/` rule contract + runner |
| F2 | Paired-leg atomic execution (equal-dollar legs) | S3 | `execution/engine.py` (sleeved cash is an approximation) |
| F3 | Triple-barrier label generator | S4 | new `research/labeling.py` |
| F4 | IC/ICIR evaluation + purged/embargoed CV | S4 | new `research/ic.py`, `/research` routes |
| F5 | Alpha/Beta/R² regression metrics per run | S5 | `research/performance.py` + run detail UI |
| F6 | Portfolio-level regime gate (macro filter on whole strategy) | S6 | runner/strategy spec (new `gate` role) |
| F7 | Offline LLM-scoring ingest step | S8 | new provider pipeline (batch, cached) |
| F8 | Short borrow cost + financing in execution model | S3, S5 | `execution/config.py` (also listed in `EXECUTION_MODEL.md` §9–10) |
| F9 | MACD histogram slope, ATR-slope variants | S1 polish | `signals/library.py` (small) |

### Data gaps

| # | Gap | Blocks | Notes |
|---|---|---|---|
| D1 | Index universes & index price series (S&P 500 etc.) | S5, S6 | Already roadmap Phase 1; also mitigates survivorship bias |
| D2 | News / filings-text feed (EDGAR 8-K/10-Q text) | S8 | EDGAR provider exists for fundamentals; text fetch is incremental |
| D3 | Adjusted prices / total-return series | S4, S5 (quietly) | Corporate actions "reported, never applied" — return computation over splits is wrong; needed before trusting long-horizon ML labels |
| D4 | Intraday bars | S9 (skipped), book's open-range breakout | Stooq caps ~2k 5-min bars; would need Polygon/Alpaca |
| D5 | Borrow rates for short-cost realism | S3, S5 | No free source; use flat assumption bps first |
| D6 | UK (`.LON`) company accounts | S7 and every fundamental filter on UK names | 0 of 99 `.LON` names have any accounts concept (Sep 2026); only FCA short positions. See ROADMAP "Fundamentals coverage" |
| D7 | US accounts gaps (~20–45% of `.US` names per rule) | S7, fundamental filters | e.g. revenue 376/534, long_term_debt 292/534. Part structural (banks/REITs), part possibly ingest limits. See ROADMAP "Fundamentals coverage" |

### UI workflow gaps

| # | Gap | Blocks | Where |
|---|---|---|---|
| U1 | Feature-ranking workbench (IC table, corr heatmap, quintile spreads) | S4 | Research page, new view |
| U2 | Regime timeline overlay on equity curves | S6 (and S1/S2 interpretation) | Run detail / Replay charts |
| U3 | Alpha/Beta panel on run performance | S5 | Run detail |
| U4 | Pair-strategy builder (two legs, hedge ratio) | S3 | StrategyLab |
| U5 | "Strategy template" presets for S1/S2/S7 so they're one click | adoption | `strategy/templates.py` + StrategyLab |

---

## 4. TODOs (ordered roadmap)

**Phase 1 — replicate book strategies with zero new infra (1–2 weeks)**
1. ✅ Add strategy templates S1 (trend + ADX gate), S2 (reversion + inverted ADX gate), S7 (quality+momentum composite) to `strategy/templates.py`; expose via StrategyLab. [U5] — plus S6.
2. ◐ Partial — 60 names over 2015→2026 so far (see §5). Backtest all three over 2010→2026 on the current 595-name US universe; record win rate/payoff vs. book predictions (trend: 30–45% win, dies sideways; MR: 55–70% win, dies in breakouts). Divergence from predicted *failure modes* is a bug signal, not just underperformance.
3. ✅ Add alpha/beta/R² to run performance + UI panel. [F5, U3]
4. ✅ Add MACD-histogram-slope signal rule. [F9]

**Phase 2 — regime & realism (2–4 weeks)**
5. ✅ (option a — per-member join) Implement portfolio-level regime gate (`macro-risk-off` on VIX/HY-spread pseudo-instruments). [F6]
6. Regime overlay on equity curves. [U2]
7. Apply corporate actions to produce adjusted/total-return series (or at least split-adjusted returns) before any ML work. [D3]
8. ✅ Add flat borrow-cost bps to execution config. [F8]

**Phase 3 — ML pipeline per book L09 (3–5 weeks)**
9. Triple-barrier label generator. [F3]
10. IC/ICIR evaluation service + purged/embargoed CV splitter. [F4]
11. Feature-ranking workbench UI (IC table, heatmap, quintile spread). [U1]
12. First model: Ridge on ~10 selected features, meta-labeling optional; evaluate on long-short quintile spread, not accuracy.

**Phase 4 — pairs & market-neutral (3–4 weeks)**
13. Index universes (roadmap Phase 1 dependency). [D1]
14. Multi-instrument rule contract + `pair-spread-zscore` signal. [F1]
15. Paired-leg execution (or document sleeved-cash approximation explicitly). [F2]
16. Pair-strategy builder UI. [U4]
17. Cointegration screening (Engle-Granger) as a Research-page tool.

**Phase 5 — LLM/alt-data layer (deferred, 4+ weeks)**
18. EDGAR 8-K/10-Q text fetch + PIT storage. [D2]
19. MD&A tone-change quarterly feature (fits daily bars; preferred over news sentiment). [F7]
20. Optional: news sentiment provider, with the book's caveat that it decays intraday.

**Explicitly out of scope**: grid trading (S9), options (S10), intraday/tick strategies, RL execution (book itself calls it frontier, not production).

---

## 5. Implementation status & Phase 1 validation (2026-09-27)

### Shipped

| Item | Where | Notes |
|---|---|---|
| U5 presets S1, S2, S6, S7 | `strategy/templates.py` (`regime-trend`, `regime-reversion`, `macro-gated-trend`, `quality-momentum`) | Served with `collection: ai-quant-book`; the builder shelves them apart from the starters with the D3 caveat. |
| F9 MACD histogram slope | `signals/library.py` `macd-histogram-slope` | Slope sign change; `require_sign` keeps only turns from weakness/strength. Leads `macd-crossover` (tested). |
| F5/U3 alpha/beta/R² | `research/performance.py` `regression()`; `RunPerformance.regression`; UI `BenchmarkPanel` on run detail, Beta/Alpha chips on Overview (laptop) | OLS on shared daily returns vs the run's equal-weight benchmark, rf = 0, null under 60 observations. Also tracking error and information ratio. |
| F8 borrow cost | `ExecutionConfig.borrow_cost_bps`; engine accrues daily on short market value (/252) into cash, trade fees and `CostBreakdown.borrow` | Form field appears only with shorts on; disclosed in assumptions. |
| S6 macro gate (option a) | `signals/library.py` `macro-risk-off` + `requires_series` on the rule registry; runner loads declared series, composer passes them | VIX ≤ `vix_max` as-of each bar (stale > 5 days = unknown). HY-widening check is opt-in: FRED serves `HYSPREAD.FRED` only from 2023-09-19. Refused up front if a declared series is missing. |

### Bugs found and fixed on the way

- **Inverted filters opened during warm-up.** `invert` flips every filter event, so a warm-up bar reported as "shut" became "open" — an inverted ADX gate (S2) passed the first ~30 bars of every series; an inverted fundamental gate passed names with no filing. Gates now emit *no event* where their state is unknown, which reads as shut either way.
- **`margin-expansion` crashed** (`zip(..., strict=True)` over lists of unequal length) on any name with enough filings. Fixed with `pairwise`; covered by a test.

### Phase 1 backtests (TODO 2)

60 US names (AAPL, MSFT, NVDA, JNJ, CVX, ABT, HD, CAT, MMM + the first 51 other `.US` symbols), 2015-01-01 → 2026-09-18, template defaults, 5 bps commission + 2 bps slippage. Benchmark = equal-weight buy-and-hold of the same names: **+989%**, almost all NVDA (×442, split-adjusted in this data).

| Preset | Return | Sharpe | Max DD | Win rate | Payoff | Beta | Alpha (ann.) | Book prediction | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| S1 trend | +66.5% | 0.58 | −18.8% | 27.6% | 3.62 | 0.11 | +2.0% | 30–45% win, high payoff, dies sideways | Shape matches (win slightly low); loses in 2015 (−0.6%), 2019 (−5.9%), 2022 (−15.9%). |
| S2 reversion | −22.9% | −0.29 | −27.7% | 58.4% | 0.66 | 0.09 | −4.2% | 55–70% win, dies in breakouts | Win rate inside prediction, payoff too thin to cover costs on this universe. |
| S6 macro-gated | +66.1% | 0.59 | −19.0% | 26.6% | 3.83 | 0.11 | +2.1% | Defends in crises | Nearly identical to S1: trend entries rarely fire with VIX > 30 anyway. |
| S7 quality+momentum | +41.8% | 0.55 | −13.5% | 46.2% | 2.18 | 0.08 | +1.2% | Diversified feature families | Best drawdown of the four. |

Two template settings changed as a result, both structural rather than tuned for return:
S2's fixed 4% stop sat inside daily noise (435 of 907 exits, 46% win rate — outside the prediction); a 2×ATR stop restored 58%. S7's 63-session agreement window re-armed entries after exits (1,887 trades, $36k costs); 21 sessions gives 327 trades and $6k.

**Read these as falsification tests, not results.** Low betas (0.08–0.11) mean the strategies spend most of the window in cash; none of them beats buy-and-hold of a basket that contains NVDA.

### D3 in this data

The large caps look split-adjusted (NVDA's 2021 and 2024 splits leave no gap), but **11 of the 60 names have single-day moves above ×2.5 or below ×0.4** — e.g. AMPY ×161.8 on 2016-10-24, AVTX ×0.11 then ×4.58 (2023-06-26, 2024-03-28): unadjusted reverse splits / relistings in micro-caps. These fire spurious trend and reversion signals. Adjustment (TODO 7) is still the prerequisite for trusting any long-horizon result, and for S4 labels.

---

## Appendix A — QuantLab capability inventory (as of 2026-09-27)

**Data layer**
- ClickHouse `price_bars`: daily OHLCV only, unadjusted, ~1.8M rows, 634 instruments, 2010→2026.
- Postgres: catalog, `fundamentals` (~5.7M rows, 580 instruments, 18 concepts, PIT by `filed_at`), signals, runs, rules, strategies.
- Providers: Stooq (daily OHLCV US/UK), Yahoo, SEC EDGAR (US fundamentals PIT), Companies House (UK, spotty), OpenFIGI, BoE, **FRED (VIX, UST10Y/2Y, HY spread, dollar index as pseudo-instruments)**, FINRA (short volume, ~1 month only), FCA (UK short interest), CSV.
- Universe: ~595 US symbols ingested; static/LSE/NasdaqTrader universe sources; **no index universes** (roadmap Phase 1).
- Missing: intraday, news/sentiment, options, adjusted prices, analyst estimates.

**Signals**: 70 indicators + 22 derived features (`src/quantlab/indicators/`, `derived/`); 20+ signal rules incl. `sma-crossover`, `macd-crossover`, `adx-trend-filter`, `bollinger-reversion`, `zscore-reversion`, `roc-momentum`, `donchian-breakout`, volume-spike, and 9 fundamental rules with PIT `requires_facts` (`backend/src/quantlab/signals/`). Extension: `@register_signal_rule`, auto-appears in `/models` and builder.

**Engine**: `StrategySpec` (components, `all|any|majority|weighted` combinators); `ExecutionConfig` (17 fields: 4 sizing modes incl. volatility_target, commission/slippage, stop/trailing/ATR stops, shorts); pessimistic intrabar resolution; look-ahead enforced by SQL CHECK + truncation sweep; replay via SSE. Missing: market impact, borrow costs, dividends, financing.

**API/UI**: FastAPI backend (contract: `quantlab_specs/specs/006-warehouse-experiments/contracts/openapi.yaml` v0.6.0); React frontend with Overview / Market / StrategyLab / Replay / Execution / Research (Company + Screen views).

## Appendix B — Book distillation (key lessons)

| Lesson | Content | QuantLab relevance |
|---|---|---|
| L05 | Classic paradigms: dual-MA/MACD trend, RSI/Bollinger reversion, pair Z-score of **return spread**, grid (caveated), options intro | S1, S2, S3; skip S9/S10 |
| L07 | Backtest pitfalls: lookahead, overfitting, cost traps | already enforced by truncation sweep; costs partially modeled |
| L08 | Alpha/Beta decomposition, dollar→beta→factor neutrality, hedging costs/basis risk | S5 |
| L09 | Features not signals; IC>0.03/ICIR>0.5 selection; **triple-barrier + meta-labeling**; **purged CV**; Ridge/RF/LightGBM by sample size; never accuracy | S4, S7 |
| L12–13 | Regime detection: ADX/vol/correlation rules → Gaussian HMM → soft gating; regime-misjudgment collapse modes | S1+S2 routing, S6 |
| L14 | LLMs bad at direct trading (−12% vs +8%); good for sentiment-as-feature, 10-K extraction, MD&A tone-change, postmortems | S8 (deferred) |
| L15–17 | Risk control with veto power, half-Kelly, ATR stops, drawdown circuit breakers | mostly in `ExecutionConfig` already |
| L18–19 | Cost modeling (spread/impact/slippage), execution simulator levels | gaps: impact, borrow, financing (F8) |
| Backgrounds | Data sources (Binance/yfinance/Alpaca/Polygon/EDGAR), alt-data economics, RL caveats | provider roadmap input |
