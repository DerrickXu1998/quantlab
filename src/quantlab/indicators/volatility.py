"""Volatility, range and risk indicators.

The OHLC-based estimators here (Parkinson, Garman-Klass, Rogers-Satchell,
Yang-Zhang) are 5-14x more efficient than close-to-close realised vol for the
same window, which matters a great deal when you only have free daily bars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import indicator
from ._util import ann_factor, ema, log_returns, safe_div, sma, true_range, wilder


@indicator("atr", params={"period": 14}, min_periods=15, tags=("volatility",))
def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder-smoothed)."""
    return wilder(true_range(df["high"], df["low"], df["close"]), period)


@indicator("natr", params={"period": 14}, min_periods=15, tags=("volatility", "normalised"))
def natr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR as a fraction of price -- the comparable version across a universe.

    Raw ATR is in price units, so a $400 NYSE name and a 90p LSE name are not
    comparable. Always prefer this for cross-sectional work.
    """
    return safe_div(atr(df, period), df["close"])


@indicator(
    "bollinger",
    params={"period": 20, "num_std": 2.0},
    inputs=("close",),
    outputs=("bb_mid", "bb_upper", "bb_lower", "bb_width", "bb_pctb"),
    min_periods=20,
    tags=("volatility", "overlay", "mean-reversion"),
)
def bollinger(df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    """Bollinger bands plus the two derived series that are actually useful:
    bandwidth (a volatility regime read) and %B (position within the bands)."""
    close = df["close"]
    mid = sma(close, period)
    sd = close.rolling(period, min_periods=period).std(ddof=0)
    upper, lower = mid + num_std * sd, mid - num_std * sd
    return pd.DataFrame(
        {
            "bb_mid": mid,
            "bb_upper": upper,
            "bb_lower": lower,
            "bb_width": safe_div(upper - lower, mid),
            "bb_pctb": safe_div(close - lower, upper - lower),
        }
    )


@indicator(
    "keltner",
    params={"period": 20, "atr_period": 10, "multiplier": 2.0},
    outputs=("kc_mid", "kc_upper", "kc_lower"),
    min_periods=25,
    tags=("volatility", "overlay"),
)
def keltner(df: pd.DataFrame, period: int = 20, atr_period: int = 10, multiplier: float = 2.0) -> pd.DataFrame:
    """Keltner channels (EMA centre, ATR width)."""
    mid = ema(df["close"], period)
    a = atr(df, atr_period)
    return pd.DataFrame({"kc_mid": mid, "kc_upper": mid + multiplier * a, "kc_lower": mid - multiplier * a})


@indicator(
    "squeeze",
    params={"bb_period": 20, "kc_period": 20, "bb_std": 2.0, "kc_mult": 1.5},
    outputs=("squeeze_on", "squeeze_momentum"),
    min_periods=30,
    tags=("volatility", "regime", "signal"),
)
def squeeze(df: pd.DataFrame, bb_period: int = 20, kc_period: int = 20, bb_std: float = 2.0, kc_mult: float = 1.5) -> pd.DataFrame:
    """TTM-style squeeze: Bollinger bands inside Keltner channels.

    Volatility compression precedes expansion, so ``squeeze_on`` flags coiled
    names and ``squeeze_momentum`` hints at the likely release direction.
    """
    bb = bollinger(df, bb_period, bb_std)
    kc = keltner(df, kc_period, kc_period // 2 or 1, kc_mult)
    on = ((bb["bb_upper"] < kc["kc_upper"]) & (bb["bb_lower"] > kc["kc_lower"])).astype(float)
    on = on.where(bb["bb_upper"].notna() & kc["kc_upper"].notna())

    high = df["high"].rolling(kc_period, min_periods=kc_period).max()
    low = df["low"].rolling(kc_period, min_periods=kc_period).min()
    basis = (((high + low) / 2) + sma(df["close"], kc_period)) / 2
    mom = (df["close"] - basis).rolling(kc_period, min_periods=kc_period).mean()
    return pd.DataFrame({"squeeze_on": on, "squeeze_momentum": mom})


@indicator(
    "donchian",
    params={"period": 20},
    inputs=("high", "low", "close"),
    outputs=("dc_upper", "dc_lower", "dc_pos"),
    min_periods=20,
    tags=("volatility", "breakout"),
)
def donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Donchian channel and position within it -- the original breakout system."""
    upper = df["high"].rolling(period, min_periods=period).max()
    lower = df["low"].rolling(period, min_periods=period).min()
    return pd.DataFrame(
        {"dc_upper": upper, "dc_lower": lower, "dc_pos": safe_div(df["close"] - lower, upper - lower)}
    )


@indicator("realised_vol", params={"period": 20, "frequency": "1d"}, inputs=("close",), min_periods=21, tags=("volatility",))
def realised_vol(df: pd.DataFrame, period: int = 20, frequency: str = "1d") -> pd.Series:
    """Annualised close-to-close realised volatility."""
    return log_returns(df["close"]).rolling(period, min_periods=period).std(ddof=1) * np.sqrt(
        ann_factor(frequency)
    )


@indicator("parkinson_vol", params={"period": 20, "frequency": "1d"}, inputs=("high", "low"), min_periods=20, tags=("volatility", "ohlc"))
def parkinson_vol(df: pd.DataFrame, period: int = 20, frequency: str = "1d") -> pd.Series:
    """Parkinson high-low volatility -- ~5x more efficient than close-to-close.

    Ignores overnight gaps, so it understates vol for gappy names.
    """
    hl = np.log(safe_div(df["high"], df["low"])) ** 2
    var = hl.rolling(period, min_periods=period).mean() / (4.0 * np.log(2.0))
    return np.sqrt(var * ann_factor(frequency))


@indicator("garman_klass_vol", params={"period": 20, "frequency": "1d"}, min_periods=20, tags=("volatility", "ohlc"))
def garman_klass_vol(df: pd.DataFrame, period: int = 20, frequency: str = "1d") -> pd.Series:
    """Garman-Klass: uses the full OHLC bar, ~7x efficiency of close-to-close."""
    hl = 0.5 * np.log(safe_div(df["high"], df["low"])) ** 2
    co = (2 * np.log(2.0) - 1.0) * np.log(safe_div(df["close"], df["open"])) ** 2
    var = (hl - co).rolling(period, min_periods=period).mean()
    return np.sqrt(var.clip(lower=0) * ann_factor(frequency))


@indicator("rogers_satchell_vol", params={"period": 20, "frequency": "1d"}, min_periods=20, tags=("volatility", "ohlc"))
def rogers_satchell_vol(df: pd.DataFrame, period: int = 20, frequency: str = "1d") -> pd.Series:
    """Rogers-Satchell: drift-independent, unlike Parkinson and Garman-Klass.

    The right choice for names with a strong trend inside the window.
    """
    hi, lo, c, o = df["high"], df["low"], df["close"], df["open"]
    term = (
        np.log(safe_div(hi, c)) * np.log(safe_div(hi, o))
        + np.log(safe_div(lo, c)) * np.log(safe_div(lo, o))
    )
    var = term.rolling(period, min_periods=period).mean()
    return np.sqrt(var.clip(lower=0) * ann_factor(frequency))


@indicator("yang_zhang_vol", params={"period": 20, "frequency": "1d"}, min_periods=21, tags=("volatility", "ohlc"))
def yang_zhang_vol(df: pd.DataFrame, period: int = 20, frequency: str = "1d") -> pd.Series:
    """Yang-Zhang: handles overnight gaps *and* drift. The best free-data
    daily volatility estimator, and the one to default to."""
    o, hi, lo, c = df["open"], df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    overnight = np.log(safe_div(o, prev_c))
    open_to_close = np.log(safe_div(c, o))

    sigma_o = overnight.rolling(period, min_periods=period).var(ddof=1)
    sigma_c = open_to_close.rolling(period, min_periods=period).var(ddof=1)
    rs = (
        np.log(safe_div(hi, c)) * np.log(safe_div(hi, o))
        + np.log(safe_div(lo, c)) * np.log(safe_div(lo, o))
    ).rolling(period, min_periods=period).mean()

    k = 0.34 / (1.34 + (period + 1) / (period - 1))
    var = sigma_o + k * sigma_c + (1.0 - k) * rs
    return np.sqrt(var.clip(lower=0) * ann_factor(frequency))


@indicator("vol_of_vol", params={"period": 20, "outer": 60}, inputs=("close",), min_periods=80, tags=("volatility", "regime"))
def vol_of_vol(df: pd.DataFrame, period: int = 20, outer: int = 60) -> pd.Series:
    """Volatility of realised volatility -- regime instability."""
    rv = realised_vol(df, period)
    return rv.rolling(outer, min_periods=outer).std(ddof=1)


@indicator("ulcer_index", params={"period": 14}, inputs=("close",), min_periods=14, tags=("volatility", "risk"))
def ulcer_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Ulcer Index: RMS drawdown. Penalises depth *and* duration of losses,
    which plain volatility does not."""
    close = df["close"]
    peak = close.rolling(period, min_periods=period).max()
    dd = 100.0 * safe_div(close - peak, peak)
    return np.sqrt((dd**2).rolling(period, min_periods=period).mean())


@indicator("choppiness", params={"period": 14}, min_periods=15, tags=("volatility", "regime"))
def choppiness(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Choppiness Index in [0, 100]: high = ranging, low = trending.

    A useful gate -- most trend signals should be ignored above ~61.8.
    """
    tr_sum = true_range(df["high"], df["low"], df["close"]).rolling(period, min_periods=period).sum()
    rng = df["high"].rolling(period, min_periods=period).max() - df["low"].rolling(period, min_periods=period).min()
    return 100.0 * np.log10(safe_div(tr_sum, rng)) / np.log10(period)


@indicator(
    "drawdown",
    inputs=("close",),
    outputs=("drawdown", "drawdown_duration"),
    params={"window": 0},
    tags=("risk",),
)
def drawdown(df: pd.DataFrame, window: int = 0) -> pd.DataFrame:
    """Drawdown from the running peak and how long it has lasted.

    ``window=0`` uses an expanding peak (since inception); any positive value
    uses a rolling peak instead.
    """
    close = df["close"]
    peak = close.expanding().max() if window <= 0 else close.rolling(window, min_periods=1).max()
    dd = safe_div(close - peak, peak)
    at_peak = close >= peak
    grp = at_peak.cumsum()
    dur = (~at_peak).groupby(grp).cumsum().astype(float)
    return pd.DataFrame({"drawdown": dd, "drawdown_duration": dur})


@indicator("gap", inputs=("open", "close"), outputs=("gap", "gap_atr"), params={"atr_period": 14}, tags=("volatility", "event"))
def gap(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """Overnight gap, raw and normalised by ATR.

    ATR-normalised gaps are the comparable version and a decent free proxy for
    news/event arrival when you have no news feed.
    """
    g = safe_div(df["open"] - df["close"].shift(1), df["close"].shift(1))
    return pd.DataFrame({"gap": g, "gap_atr": safe_div(df["open"] - df["close"].shift(1), atr(df, atr_period))})
