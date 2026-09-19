"""Oscillators and momentum."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import indicator
from ._util import ema, percent_rank, safe_div, sma, typical_price, wilder


@indicator("rsi", params={"period": 14}, inputs=("close",), min_periods=15, tags=("momentum", "oscillator"))
def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's RSI. Note the Wilder smoothing -- an SMA version reads differently."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    rs = safe_div(wilder(gain, period), wilder(loss, period))
    out = 100.0 - (100.0 / (1.0 + rs))
    # All-gain windows give loss == 0 -> rs == inf -> RSI 100.
    return out.where(wilder(loss, period).fillna(1.0) > 0, 100.0).where(delta.notna().cumsum() >= period)


@indicator(
    "stoch",
    params={"k_period": 14, "k_smooth": 3, "d_period": 3},
    outputs=("stoch_k", "stoch_d"),
    min_periods=20,
    tags=("momentum", "oscillator"),
)
def stochastic(df: pd.DataFrame, k_period: int = 14, k_smooth: int = 3, d_period: int = 3) -> pd.DataFrame:
    """Slow stochastic %K / %D."""
    low = df["low"].rolling(k_period, min_periods=k_period).min()
    high = df["high"].rolling(k_period, min_periods=k_period).max()
    raw_k = 100.0 * safe_div(df["close"] - low, high - low)
    k = sma(raw_k, k_smooth)
    return pd.DataFrame({"stoch_k": k, "stoch_d": sma(k, d_period)})


@indicator("stoch_rsi", params={"period": 14, "rsi_period": 14}, inputs=("close",), min_periods=30, tags=("momentum", "oscillator"))
def stoch_rsi(df: pd.DataFrame, period: int = 14, rsi_period: int = 14) -> pd.Series:
    """Stochastic of RSI -- far more sensitive than RSI, good for timing."""
    r = rsi(df, rsi_period)
    lo = r.rolling(period, min_periods=period).min()
    hi = r.rolling(period, min_periods=period).max()
    return safe_div(r - lo, hi - lo)


@indicator("cci", params={"period": 20}, min_periods=20, tags=("momentum", "oscillator"))
def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Commodity Channel Index, with the conventional 0.015 scaling."""
    tp = typical_price(df["high"], df["low"], df["close"])
    ma = sma(tp, period)
    mad = tp.rolling(period, min_periods=period).apply(
        lambda x: float(np.abs(x - x.mean()).mean()), raw=True
    )
    return safe_div(tp - ma, 0.015 * mad)


@indicator("williams_r", params={"period": 14}, min_periods=14, tags=("momentum", "oscillator"))
def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Williams %R, in [-100, 0]."""
    high = df["high"].rolling(period, min_periods=period).max()
    low = df["low"].rolling(period, min_periods=period).min()
    return -100.0 * safe_div(high - df["close"], high - low)


@indicator("roc", params={"period": 20}, inputs=("close",), tags=("momentum",))
def roc(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Rate of change over `period` bars."""
    return df["close"].pct_change(period)


@indicator(
    "momentum_12_1",
    params={"lookback": 252, "skip": 21},
    inputs=("close",),
    min_periods=253,
    tags=("momentum", "factor"),
)
def momentum_12_1(df: pd.DataFrame, lookback: int = 252, skip: int = 21) -> pd.Series:
    """Classic 12-month-minus-1-month momentum.

    The skipped final month is the point: short-horizon reversal contaminates
    raw 12-month momentum, and dropping it is what makes the factor work.
    """
    close = df["close"]
    return safe_div(close.shift(skip), close.shift(lookback)) - 1.0


@indicator("tsi", params={"long": 25, "short": 13}, inputs=("close",), min_periods=40, tags=("momentum",))
def tsi(df: pd.DataFrame, long: int = 25, short: int = 13) -> pd.Series:
    """True Strength Index: double-smoothed momentum, much less noisy than ROC."""
    m = df["close"].diff()
    num = ema(ema(m, long), short)
    den = ema(ema(m.abs(), long), short)
    return 100.0 * safe_div(num, den)


@indicator("cmo", params={"period": 14}, inputs=("close",), min_periods=15, tags=("momentum", "oscillator"))
def cmo(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Chande Momentum Oscillator, in [-100, 100]."""
    delta = df["close"].diff()
    up = delta.clip(lower=0).rolling(period, min_periods=period).sum()
    dn = (-delta).clip(lower=0).rolling(period, min_periods=period).sum()
    return 100.0 * safe_div(up - dn, up + dn)


@indicator(
    "ultimate_osc",
    params={"short": 7, "medium": 14, "long": 28},
    min_periods=30,
    tags=("momentum", "oscillator"),
)
def ultimate_oscillator(df: pd.DataFrame, short: int = 7, medium: int = 14, long: int = 28) -> pd.Series:
    """Williams' Ultimate Oscillator -- three horizons, weighted 4:2:1."""
    close, low, high = df["close"], df["low"], df["high"]
    prev_close = close.shift(1)
    bp = close - pd.concat([low, prev_close], axis=1).min(axis=1)
    tr = pd.concat([high, prev_close], axis=1).max(axis=1) - pd.concat([low, prev_close], axis=1).min(axis=1)

    def avg(n: int) -> pd.Series:
        return safe_div(bp.rolling(n, min_periods=n).sum(), tr.rolling(n, min_periods=n).sum())

    return 100.0 * (4 * avg(short) + 2 * avg(medium) + avg(long)) / 7.0


@indicator(
    "connors_rsi",
    params={"rsi_period": 3, "streak_period": 2, "rank_period": 100},
    inputs=("close",),
    min_periods=110,
    tags=("momentum", "mean-reversion"),
)
def connors_rsi(df: pd.DataFrame, rsi_period: int = 3, streak_period: int = 2, rank_period: int = 100) -> pd.Series:
    """Connors RSI: short RSI + streak RSI + percentile rank of returns.

    Built for short-horizon mean reversion rather than trend. Worth having
    because it captures something the standard RSI does not: the *persistence*
    of the recent direction, not just its magnitude.
    """
    close = df["close"]
    r1 = rsi(df, rsi_period)

    # Signed run length of consecutive up/down days, vectorised: a run is a
    # block of equal signs, so its length is the within-block cumulative count.
    direction = np.sign(close.diff().fillna(0.0))
    blocks = direction.ne(direction.shift()).cumsum()
    run_length = direction.groupby(blocks).cumcount() + 1
    streak_s = (direction * run_length).astype(float)
    r2 = rsi(pd.DataFrame({"close": streak_s}), streak_period)

    r3 = 100.0 * percent_rank(close.pct_change(), rank_period)
    return (r1 + r2 + r3) / 3.0


@indicator(
    "rsi_divergence",
    params={"period": 14, "lookback": 20},
    inputs=("close",),
    min_periods=40,
    tags=("momentum", "signal"),
)
def rsi_divergence(df: pd.DataFrame, period: int = 14, lookback: int = 20) -> pd.Series:
    """+1 bullish / -1 bearish regular divergence between price and RSI.

    Price makes a new extreme over the lookback but RSI does not. Computed
    strictly causally -- every input is known at the bar it is stamped on.
    """
    close, r = df["close"], rsi(df, period)
    price_low = close.rolling(lookback, min_periods=lookback).min()
    price_high = close.rolling(lookback, min_periods=lookback).max()
    rsi_low = r.rolling(lookback, min_periods=lookback).min()
    rsi_high = r.rolling(lookback, min_periods=lookback).max()

    bullish = (close <= price_low) & (r > rsi_low * 1.02)
    bearish = (close >= price_high) & (r < rsi_high * 0.98)
    return pd.Series(
        np.select([bullish, bearish], [1.0, -1.0], default=0.0), index=df.index
    ).where(r.notna())
