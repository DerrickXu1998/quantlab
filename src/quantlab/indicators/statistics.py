"""Statistical / stochastic-process features.

These are the indicators that tell you *what kind of series* you are looking
at -- trending, mean-reverting, or random -- which is more actionable than any
single oscillator reading.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import indicator
from ._util import ann_factor, log_returns, percent_rank, safe_div, zscore


@indicator("hurst", params={"period": 100, "max_lag": 20}, inputs=("close",), min_periods=100, tags=("statistical", "regime"))
def hurst(df: pd.DataFrame, period: int = 100, max_lag: int = 20) -> pd.Series:
    """Rolling Hurst exponent via the variance-of-lagged-differences method.

    H > 0.5 trending/persistent, H < 0.5 mean-reverting, H ~ 0.5 random walk.
    Use it to decide *which family* of signals to trust on a given name, rather
    than applying a trend model everywhere.
    """
    logp = np.log(df["close"].where(df["close"] > 0))
    max_lag = min(max_lag, max(2, period // 4))
    lags = np.arange(2, max_lag + 1)
    if len(lags) < 2:
        return pd.Series(np.nan, index=df.index)

    log_lags = np.log(lags.astype(float))
    log_lags_dev = log_lags - log_lags.mean()
    denom = float((log_lags_dev**2).sum())

    # One vectorised pass per lag instead of a Python callback per window.
    # Within a window of `period` points there are exactly `period - lag`
    # lag-differences, so a rolling std of the lag-differenced series over that
    # width is the same quantity -- just computed in C rather than in Python.
    cols = []
    for lag in lags:
        diffs = logp.diff(int(lag))
        width = period - int(lag)
        sd = diffs.rolling(width, min_periods=width).std(ddof=0)
        cols.append(np.log(sd.where(sd > 0)))
    y = pd.concat(cols, axis=1)
    y.columns = range(len(lags))

    y_dev = y.sub(y.mean(axis=1), axis=0)
    slope = y_dev.mul(log_lags_dev, axis=1).sum(axis=1, min_count=len(lags)) / denom
    enough = logp.rolling(period, min_periods=period).count() >= period
    return slope.where(enough)


@indicator("half_life", params={"period": 60}, inputs=("close",), min_periods=60, tags=("statistical", "mean-reversion"))
def half_life(df: pd.DataFrame, period: int = 60) -> pd.Series:
    """Ornstein-Uhlenbeck mean-reversion half-life, in bars.

    Fits dP = lambda*(P - mean) dt by OLS on lagged levels. A half-life of 3-15
    bars is the sweet spot for daily mean reversion; huge or negative values
    mean the series is not reverting and the signal should be ignored.
    """
    logp = np.log(df["close"].where(df["close"] > 0))
    lagged = logp.shift(1)
    delta = logp.diff()
    width = period - 1

    # Rolling OLS of delta on the lagged level, in closed form.
    beta = delta.rolling(width, min_periods=width).cov(lagged) / lagged.rolling(
        width, min_periods=width
    ).var(ddof=1)
    beta = beta.where(beta < 0)          # positive beta => not mean reverting
    return -np.log(2.0) / beta


@indicator("efficiency_ratio", params={"period": 20}, inputs=("close",), min_periods=21, tags=("statistical", "regime"))
def efficiency_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Kaufman efficiency ratio: net move / total path length, in [0, 1].

    1.0 is a straight line, 0.0 is pure noise. The cheapest, most robust
    trend/chop discriminator there is.
    """
    close = df["close"]
    return safe_div(
        close.diff(period).abs(), close.diff().abs().rolling(period, min_periods=period).sum()
    )


@indicator("autocorr", params={"period": 60, "lag": 1}, inputs=("close",), min_periods=61, tags=("statistical",))
def autocorr(df: pd.DataFrame, period: int = 60, lag: int = 1) -> pd.Series:
    """Rolling lag-k autocorrelation of returns.

    Persistently negative lag-1 autocorrelation is the statistical signature of
    a mean-reverting name (and of bid-ask bounce in illiquid ones -- check
    ``roll_spread`` before concluding you found alpha).
    """
    r = log_returns(df["close"])
    return r.rolling(period, min_periods=period).corr(r.shift(lag))


@indicator(
    "return_moments",
    params={"period": 60},
    inputs=("close",),
    outputs=("ret_skew", "ret_kurtosis"),
    min_periods=60,
    tags=("statistical", "risk"),
)
def return_moments(df: pd.DataFrame, period: int = 60) -> pd.DataFrame:
    """Rolling skewness and excess kurtosis of returns.

    Negative skew + high kurtosis is the crash-risk fingerprint, and it is
    priced -- idiosyncratic skewness is a documented cross-sectional predictor.
    """
    r = log_returns(df["close"])
    return pd.DataFrame(
        {
            "ret_skew": r.rolling(period, min_periods=period).skew(),
            "ret_kurtosis": r.rolling(period, min_periods=period).kurt(),
        }
    )


@indicator("entropy", params={"period": 60, "bins": 8}, inputs=("close",), min_periods=60, tags=("statistical", "regime"))
def entropy(df: pd.DataFrame, period: int = 60, bins: int = 8) -> pd.Series:
    """Normalised Shannon entropy of the return distribution, in [0, 1].

    Low entropy means returns are concentrated -- structure a model can use.
    High entropy means maximum disorder.
    """
    r = log_returns(df["close"])

    def ent(x: np.ndarray) -> float:
        finite = x[np.isfinite(x)]
        if len(finite) < bins:
            return np.nan
        counts, _ = np.histogram(finite, bins=bins)
        p = counts[counts > 0] / counts.sum()
        return float(-(p * np.log(p)).sum() / np.log(bins))

    return r.rolling(period, min_periods=period).apply(ent, raw=True)


@indicator("sharpe", params={"period": 252, "frequency": "1d", "risk_free": 0.0}, inputs=("close",), min_periods=60, tags=("risk", "performance"))
def rolling_sharpe(df: pd.DataFrame, period: int = 252, frequency: str = "1d", risk_free: float = 0.0) -> pd.Series:
    """Rolling annualised Sharpe ratio."""
    af = ann_factor(frequency)
    r = log_returns(df["close"]) - (risk_free / af)
    mu = r.rolling(period, min_periods=max(20, period // 4)).mean() * af
    sd = r.rolling(period, min_periods=max(20, period // 4)).std(ddof=1) * np.sqrt(af)
    return safe_div(mu, sd)


@indicator("sortino", params={"period": 252, "frequency": "1d"}, inputs=("close",), min_periods=60, tags=("risk", "performance"))
def rolling_sortino(df: pd.DataFrame, period: int = 252, frequency: str = "1d") -> pd.Series:
    """Rolling Sortino ratio -- Sharpe that only punishes downside deviation."""
    af = ann_factor(frequency)
    r = log_returns(df["close"])
    mu = r.rolling(period, min_periods=max(20, period // 4)).mean() * af
    downside = r.clip(upper=0.0)
    dd = np.sqrt((downside**2).rolling(period, min_periods=max(20, period // 4)).mean()) * np.sqrt(af)
    return safe_div(mu, dd)


@indicator("var_cvar", params={"period": 252, "alpha": 0.05}, inputs=("close",), outputs=("var", "cvar"), min_periods=60, tags=("risk",))
def var_cvar(df: pd.DataFrame, period: int = 252, alpha: float = 0.05) -> pd.DataFrame:
    """Historical Value-at-Risk and Conditional VaR at the given tail level."""
    r = log_returns(df["close"])
    win = max(20, period // 4)
    var = r.rolling(period, min_periods=win).quantile(alpha)

    def cvar_fn(x: np.ndarray) -> float:
        finite = x[np.isfinite(x)]
        if len(finite) < 10:
            return np.nan
        q = np.quantile(finite, alpha)
        tail = finite[finite <= q]
        return float(tail.mean()) if len(tail) else np.nan

    return pd.DataFrame({"var": var, "cvar": r.rolling(period, min_periods=win).apply(cvar_fn, raw=True)})


@indicator("price_percentile", params={"period": 252}, inputs=("close",), min_periods=60, tags=("statistical", "position"))
def price_percentile(df: pd.DataFrame, period: int = 252) -> pd.Series:
    """Where price sits in its own trailing range, in [0, 1].

    The 52-week-high proxy. Scale-free, so it is directly comparable across a
    mixed NYSE/LSE universe without any currency handling.
    """
    return percent_rank(df["close"], period)


@indicator("return_zscore", params={"period": 60, "horizon": 1}, inputs=("close",), min_periods=60, tags=("statistical", "mean-reversion"))
def return_zscore(df: pd.DataFrame, period: int = 60, horizon: int = 1) -> pd.Series:
    """Standardised recent return -- how unusual is this move for this name."""
    return zscore(log_returns(df["close"], horizon), period)
