"""Shared primitives. Every indicator is built from these, so correctness here
buys correctness everywhere."""
from __future__ import annotations

import numpy as np
import pandas as pd


def wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing: EMA with alpha = 1/period, **seeded with the SMA of
    the first `period` observations**.

    The seeding is the part people get wrong. ``ewm(alpha=1/n, adjust=False)``
    seeds with the first observation instead, which leaves RSI/ATR/ADX visibly
    off for the first few hundred bars -- the error decays as (1-1/n)^k, so on
    a 14-period indicator it takes ~280 bars to wash out. Short histories and
    freshly listed names are exactly where that bites.

    Implemented in closed form rather than with a Python loop: the recursion is
    linear, so a different seed only adds a geometrically decaying correction
    term, which we can compute vectorised.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    alpha = 1.0 / period
    x = pd.to_numeric(series, errors="coerce").astype(float)
    valid = x.notna()
    if int(valid.sum()) < period:
        return pd.Series(np.nan, index=x.index)

    # Position of the period-th valid observation -- where Wilder's seed lands.
    i0 = int(np.flatnonzero((valid.cumsum() == period).to_numpy() & valid.to_numpy())[0])

    plain = x.ewm(alpha=alpha, adjust=False, min_periods=1).mean()
    seed_wilder = float(x[valid].iloc[:period].mean())
    seed_plain = float(plain.iloc[i0])

    k = np.arange(len(x), dtype=float) - i0
    with np.errstate(over="ignore", under="ignore"):
        correction = np.where(k >= 0, (1.0 - alpha) ** np.clip(k, 0, None), np.nan)
    out = plain + correction * (seed_wilder - seed_plain)
    out.iloc[:i0] = np.nan
    return out


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def wma(series: pd.Series, period: int) -> pd.Series:
    w = np.arange(1, period + 1, dtype=float)
    w /= w.sum()
    return series.rolling(period, min_periods=period).apply(lambda x: float(np.dot(x, w)), raw=True)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True range.

    The first bar has no previous close, so TR is genuinely undefined there and
    we return NaN rather than silently falling back to high-low. That keeps ATR
    seeding aligned with Wilder's definition (and with TA-Lib).
    """
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    tr.iloc[:1] = np.nan
    return tr


def typical_price(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    return (high + low + close) / 3.0


def _time_index(series: pd.Series) -> pd.Series:
    return pd.Series(np.arange(len(series), dtype=float), index=series.index)


def rolling_slope(series: pd.Series, period: int) -> pd.Series:
    """OLS slope of y on bar number, over a rolling window.

    Uses rolling covariance rather than ``rolling.apply``: covariance with a
    linear ramp is invariant to shifting the ramp, so one vectorised pass
    replaces a Python callback per window. On a 5,000-name panel that is the
    difference between seconds and many minutes.
    """
    if period < 2:
        raise ValueError("period must be >= 2")
    t = _time_index(series)
    denom = t.rolling(period, min_periods=period).var(ddof=1)
    return series.rolling(period, min_periods=period).cov(t) / denom


def rolling_rsquared(series: pd.Series, period: int) -> pd.Series:
    """R-squared of the same linear fit -- the squared correlation with time."""
    if period < 2:
        raise ValueError("period must be >= 2")
    return series.rolling(period, min_periods=period).corr(_time_index(series)) ** 2


def zscore(series: pd.Series, period: int, *, min_std: float = 1e-12) -> pd.Series:
    mu = series.rolling(period, min_periods=period).mean()
    sd = series.rolling(period, min_periods=period).std(ddof=0)
    return (series - mu) / sd.where(sd > min_std)


def percent_rank(series: pd.Series, period: int) -> pd.Series:
    """Percentile rank of the current value within its trailing window, in (0, 1].

    Uses pandas' native ``rolling().rank()`` rather than a Python callback.
    """
    return series.rolling(period, min_periods=period).rank(pct=True)


def safe_div(a: pd.Series, b: pd.Series, *, eps: float = 1e-12) -> pd.Series:
    return a / b.where(b.abs() > eps)


def log_returns(series: pd.Series, period: int = 1) -> pd.Series:
    return np.log(series.where(series > 0)).diff(period)


ANNUALISATION = {"1d": 252.0, "1wk": 52.0, "1mo": 12.0, "1h": 252.0 * 6.5, "5m": 252.0 * 78.0}


def ann_factor(frequency: str = "1d") -> float:
    return ANNUALISATION.get(frequency, 252.0)
