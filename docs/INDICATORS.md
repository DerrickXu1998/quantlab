# Indicators: what's worth building, and why

70 built-in indicators plus 22 derived features. The list below is opinionated — it says
which ones actually earn their place and which are here because you will be asked for them.

`quantlab list indicators --tag <tag>` filters by tag at any time.

## The rule that matters most

**Anything you compare across a mixed NYSE/LSE universe must be scale-free.** A $400 New
York name and a 90p London line are not comparable in price units. Every indicator below is
marked:

- ✅ **scale-free** — a ratio, a percentage, a rank or a bounded oscillator. Safe cross-sectionally.
- ⚠️ **price-scaled** — in currency units. Useful per-name, dangerous in a cross-section.

The test suite enforces this: `test_ratio_indicators_are_unit_invariant` checks that
scale-free indicators give identical values in pence and in pounds.

---

## Trend

| Indicator | Outputs | Scale | Verdict |
|---|---|---|---|
| `sma` `ema` `hma` `kama` | overlay | ⚠️ | Building blocks. `hma` has materially less lag; `kama` adapts its speed to noise. |
| `macd` | line, signal, histogram | ⚠️ | Universally expected. The histogram is the part with information. |
| `adx` | adx, di_plus, di_minus | ✅ | **Worth it.** Trend *strength* without direction. Below ~20 means no trend — use it as a gate on other signals. |
| `aroon` | up, down, oscillator | ✅ | Time since the window extreme. Scale-free by construction, underrated. |
| `supertrend` | level, direction | ⚠️/✅ | ATR-banded trailing stop. The `_dir` output is a clean binary regime flag. |
| `ichimoku` | 5 lines | ⚠️ | Included because it is expected. **`chikou` is shifted backward — a deliberate look-ahead for charting. Never feed it to a model.** |
| `psar` | level | ⚠️ | Trailing stop. Whipsaws badly in chop; gate it with `choppiness`. |
| `trend_slope` | annualised log-price slope | ✅ | **Worth it.** A comparable trend measure across any price level. |
| `trend_r2` | fit quality | ✅ | **Worth it, and underused.** Pair with `trend_slope`: slope is size, R² is conviction. High slope + low R² is a jump, not a trend. |
| `ma_distance` | % from MA | ✅ | Stretch relative to trend. |
| `ma_cross_state` | state, **age** | ✅ | The *age* of a golden/death cross matters more than the cross. Fresh and long-held regimes behave differently. |

## Momentum

| Indicator | Scale | Verdict |
|---|---|---|
| `rsi` | ✅ | The default. Note this is **Wilder-smoothed and seeded with the SMA of the first N bars** — the common `ewm(adjust=False)` shortcut is visibly wrong for ~280 bars on a 14-period RSI, which is exactly where newly listed names live. |
| `stoch`, `stoch_rsi` | ✅ | `stoch_rsi` is far more sensitive; good for timing, noisy as a signal. |
| `cci`, `williams_r`, `cmo`, `roc` | ✅ | Conventional. `roc` is the honest one. |
| `momentum_12_1` | ✅ | **Worth it — this is the academic momentum factor.** The skipped final month is the whole point: short-horizon reversal contaminates raw 12-month momentum. |
| `tsi` | ✅ | Double-smoothed momentum. Much less noisy than `roc`. |
| `ultimate_osc` | ✅ | Three horizons weighted 4:2:1. Genuinely reduces the timeframe-choice problem. |
| `connors_rsi` | ✅ | **Worth it for short-horizon mean reversion.** Captures the *persistence* of direction (streak length), which plain RSI does not. |
| `rsi_divergence` | ✅ | ±1 regular divergence, computed strictly causally. Treat as a weak prior, not a signal. |

## Volatility — the section to actually care about

With only free daily bars, the OHLC-based estimators are **5–14× more statistically
efficient** than close-to-close realised volatility for the same window. That is a large
free win and most retail tooling ignores it.

| Indicator | Scale | Verdict |
|---|---|---|
| `atr` | ⚠️ | Wilder ATR. Fine per-name. |
| `natr` | ✅ | **Use this, not `atr`, across markets.** ATR normalised by price. |
| `realised_vol` | ✅ | Close-to-close baseline. Least efficient. |
| `parkinson_vol` | ✅ | ~5× efficiency. **Ignores overnight gaps** — understates vol for gappy names. |
| `garman_klass_vol` | ✅ | ~7× efficiency, uses the full bar. Assumes zero drift. |
| `rogers_satchell_vol` | ✅ | **Drift-independent**, unlike the two above. Right choice for strongly trending windows. |
| `yang_zhang_vol` | ✅ | **The default. Handles gaps *and* drift.** Best free-data daily estimator. |
| `bollinger` | mixed | Bands are ⚠️; `bb_width` and `bb_pctb` are ✅ and are the useful outputs. |
| `keltner` | ⚠️ | ATR-width channels. |
| `squeeze` | ✅ | **Worth it.** Bollinger-inside-Keltner compression. Volatility compression precedes expansion. |
| `donchian` | `dc_pos` is ✅ | The original breakout system. |
| `vol_of_vol` | ✅ | Regime instability. |
| `ulcer_index` | ✅ | RMS drawdown. Penalises depth *and duration* — plain volatility does not. |
| `choppiness` | ✅ | **A useful gate.** Above ~61.8, ignore your trend signals. |
| `drawdown` | ✅ | Depth and duration from the running peak. |
| `gap` | `gap_atr` is ✅ | ATR-normalised overnight gaps. A decent free proxy for news arrival when you have no news feed. |

## Volume, liquidity and microstructure

Liquidity is where a mixed NYSE + LSE universe bites hardest: AIM small caps and NYSE mega
caps differ by six orders of magnitude in turnover. **Nearly every apparent anomaly in the
bottom liquidity tier is an artefact of not being able to trade it.**

| Indicator | Scale | Verdict |
|---|---|---|
| `obv`, `ad_line` | ⚠️ | Cumulative, so level is meaningless — use the slope. |
| `cmf`, `mfi` | ✅ | Bounded volume oscillators. |
| `vwap` | `vwap_dist` is ✅ | Supports **anchored** VWAP (`anchor='ME'`, `'QE'`). Anchored VWAP from an earnings date beats the rolling version as a reference level. |
| `volume_zscore` | ✅ | **The single best free proxy for "something happened".** |
| `dollar_volume` | ⚠️ | Your primary liquidity screen. Normalise currency first. |
| `amihud_illiquidity` | ✅ | **The most valuable one here.** Price impact per unit traded. It is what separates a tradeable AIM name from an untradeable one. |
| `roll_spread` | ✅ | Effective spread from return serial covariance. NaN when the covariance is positive — itself informative. |
| `corwin_schultz_spread` | ✅ | **Worth it.** Recovers an effective bid-ask spread from daily highs and lows alone — the closest you get to quote data on a free feed. |
| `force_index`, `ease_of_movement` | ⚠️ | Conventional. |
| `volume_trend_confirm` | ✅ | Correlation of returns with volume changes. Negative means the trend is running on fumes. |
| `turnover` | ✅ | Needs `shares_outstanding` from a fundamentals provider. Returns NaN rather than inventing a denominator. |

## Statistical — what *kind* of series is this?

More actionable than any single oscillator reading, and the part most retail tooling skips.

| Indicator | Verdict |
|---|---|
| `hurst` | **Worth it.** H > 0.5 trending, < 0.5 mean-reverting, ≈ 0.5 random walk. Use it to decide *which family of signals to trust on this name* rather than applying a trend model everywhere. Note: a random walk *with drift* correctly reads ≈ 0.5 — persistence has to be in the autocorrelation, not the mean. |
| `half_life` | **Worth it.** Ornstein–Uhlenbeck mean-reversion half-life in bars. 3–15 is the sweet spot for daily reversion; NaN or huge means the series is not reverting and the signal should be ignored. |
| `efficiency_ratio` | **The cheapest, most robust trend/chop discriminator there is.** Net move ÷ path length. |
| `autocorr` | Persistently negative lag-1 autocorrelation means mean reversion — *or* bid-ask bounce. Check `roll_spread` before concluding you found alpha. |
| `return_moments` | Rolling skew and excess kurtosis. Negative skew + high kurtosis is the crash-risk fingerprint, and idiosyncratic skewness is a documented cross-sectional predictor. |
| `entropy` | Normalised Shannon entropy of returns. Low = structure a model can use. |
| `sharpe`, `sortino` | Rolling risk-adjusted performance. |
| `var_cvar` | Historical VaR and CVaR. |
| `price_percentile` | **Scale-free 52-week-high proxy.** Directly comparable across a mixed universe with no currency handling at all. |
| `return_zscore` | How unusual is this move *for this name*. |

## Calendar

`calendar`, `turn_of_month`, `days_since_extreme`. Turn-of-month is one of the more durable
effects — pension and index flows have not gone away. Computed from the **exchange
calendar**, not from observed bars, so it does not peek at how many trading days a month
turned out to have.

---

# Derived data (pluggable)

Split by what they need. Panel-only features cost nothing extra; externally-sourced ones
fetch from a free official source and **degrade to NaN with a warning** rather than failing
the run.

## Panel-only — free, no source required

**Cross-sectional** (`cs_zscore`, `cs_rank`, `sector_neutral`, `market_beta`,
`residual_momentum`, `relative_strength`, `correlation_to_market`, `liquidity_tier`)

These only exist because you have a *universe*. A z-score of RSI tells you nothing; a
z-score of RSI against the other 4,999 names tells you a lot.

- `sector_neutral` — without it, a "momentum" screen on a mixed universe is often just a bet
  on whichever sector ran.
- `market_beta` also emits **`idio_vol`** (residual volatility) and `r2_market`. Idiosyncratic
  volatility and residual momentum are both better behaved than their raw equivalents.
- `residual_momentum` strips the beta-driven part of a run, which is where most of plain
  momentum's crash risk lives.
- `liquidity_tier` — essential. See the warning above.

**Regime** (`breadth`, `market_regime`, `dispersion`)

Breadth is free: it comes from the panel you already have, and it is one of the few
genuinely additive signals you can build without paying for data.

- `breadth` — % above MA, % advancing, net new highs, McClellan oscillator. Price/breadth
  divergence is the classic late-cycle tell.
- `market_regime` — volatility percentile × trend, four states. Crude, but conditioning a
  signal on it is usually worth more than adding another oscillator.
- `dispersion` — cross-sectional return dispersion and implied average pairwise correlation.
  High dispersion / low correlation is a stock-pickers' market. When correlation spikes
  toward 1, everything is one trade.

## Externally sourced — free official sources

| Feature | Source | Lag | Notes |
|---|---|---|---|
| `finra_short_volume` | FINRA flat files (US) | 1 | Read the z-score, not the level. |
| `fca_short_interest` | FCA daily file (UK) | 2 | Real disclosed short interest. Matched on ISIN. Genuinely differentiated. |
| `insider_activity` | SEC Form 3/4/5 (US) | 2 | **Buys inform, sales are noise** (liquidity, tax, 10b5-1). **Clusters beat individuals** — `insider_cluster_buy` counts distinct buyers. |
| `valuation` | SEC / Companies House | 1 | P/E, P/B, P/S, EV/EBIT, FCF yield. Point-in-time. |
| `quality` | SEC / Companies House | 1 | ROE, ROA, margins, **accruals**, leverage. Accruals is the one to watch — the gap between accounting earnings and cash flow reliably predicts disappointment. |
| `piotroski_f` | SEC / Companies House | 1 | Nine binary health tests. Still one of the better-documented quality screens, especially on small caps — which is most of a free universe. |
| `altman_z` | SEC / Companies House | 1 | Use as a **filter**, not a signal. Cheap-and-distressed is the classic value trap. |
| `fundamental_momentum` | SEC / Companies House | 1 | YoY revenue/earnings/margin growth. Disagrees with price momentum often enough to be worth measuring separately. |
| `macro_us` | FRED | 1 | Yield curve, HY spreads, VIX, real rates, dollar. Levels and 3-year z-scores. |
| `macro_uk` | BoE IADB | 1 | Bank Rate, GBP/USD, GBP/EUR. |
| `short_squeeze_score` | composite | — | A worked example of composing derived features into a score. |

### Point-in-time discipline

Every fundamental feature is stamped at the **filing date**, never the fiscal period end.
A 2024-Q4 number was not knowable in December 2024 — it was knowable when the 10-K was
accepted in February 2025.

Every externally-sourced feature declares a `lag` in its spec, and the engine shifts it
forward per symbol before it reaches your model. A test enforces that no `external` feature
ships with `lag=0`.

Getting this wrong is the single most common way backtests produce fictitious alpha.
