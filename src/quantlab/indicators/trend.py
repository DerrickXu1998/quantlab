"""Trend and trend-strength indicators."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import indicator
from ._util import ema, rolling_rsquared, rolling_slope, safe_div, sma, true_range, wilder, wma


@indicator("sma", params={"period": 20}, inputs=("close",), tags=("trend", "overlay"))
def sma_ind(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Simple moving average."""
    return sma(df["close"], period)


@indicator("ema", params={"period": 20}, inputs=("close",), tags=("trend", "overlay"))
def ema_ind(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Exponential moving average."""
    return ema(df["close"], period)


@indicator("hma", params={"period": 20}, inputs=("close",), tags=("trend", "overlay"))
def hull_ma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Hull MA -- much less lag than an SMA of the same length, still smooth."""
    half, root = max(1, period // 2), max(1, int(np.sqrt(period)))
    raw = 2 * wma(df["close"], half) - wma(df["close"], period)
    return wma(raw, root)


@indicator("kama", params={"period": 10, "fast": 2, "slow": 30}, inputs=("close",), tags=("trend", "adaptive"))
def kama(df: pd.DataFrame, period: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman Adaptive MA: speeds up in trends, flattens in chop.

    The efficiency ratio it is built on (net move / summed move) is itself a
    useful standalone feature -- see ``efficiency_ratio``.
    """
    close = df["close"]
    change = close.diff(period).abs()
    volatility = close.diff().abs().rolling(period, min_periods=period).sum()
    er = safe_div(change, volatility).fillna(0.0)
    fast_sc, slow_sc = 2.0 / (fast + 1), 2.0 / (slow + 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2

    values = close.to_numpy(dtype=float)
    sc_v = sc.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    start = period
    if len(values) > start:
        out[start] = values[start]
        for i in range(start + 1, len(values)):
            prev = out[i - 1]
            if not np.isfinite(prev):
                out[i] = values[i]
            else:
                out[i] = prev + sc_v[i] * (values[i] - prev)
    return pd.Series(out, index=close.index)


@indicator(
    "macd",
    params={"fast": 12, "slow": 26, "signal": 9},
    inputs=("close",),
    outputs=("macd", "macd_signal", "macd_hist"),
    tags=("trend", "momentum"),
)
def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line, signal and histogram."""
    line = ema(df["close"], fast) - ema(df["close"], slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


@indicator(
    "adx",
    params={"period": 14},
    outputs=("adx", "di_plus", "di_minus"),
    min_periods=30,
    tags=("trend", "strength"),
)
def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average Directional Index with the +DI / -DI components.

    ADX measures trend *strength* without direction; the DI pair supplies
    direction. Below ~20 is usually treated as no trend.
    """
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)

    atr = wilder(true_range(high, low, close), period)
    di_plus = 100.0 * safe_div(wilder(plus_dm, period), atr)
    di_minus = 100.0 * safe_div(wilder(minus_dm, period), atr)
    dx = 100.0 * safe_div((di_plus - di_minus).abs(), di_plus + di_minus)
    return pd.DataFrame({"adx": wilder(dx, period), "di_plus": di_plus, "di_minus": di_minus})


@indicator(
    "aroon",
    params={"period": 25},
    inputs=("high", "low"),
    outputs=("aroon_up", "aroon_down", "aroon_osc"),
    tags=("trend",),
)
def aroon(df: pd.DataFrame, period: int = 25) -> pd.DataFrame:
    """Time since the window's extreme -- a clean, price-scale-free trend read."""
    # Aroon Up = 100 * (period - bars_since_high) / period. With a window of
    # period+1 bars, bars_since_high == (len-1) - argmax, so this reduces to
    # 100 * argmax / period.
    win = period + 1
    up = df["high"].rolling(win, min_periods=win).apply(
        lambda x: 100.0 * int(np.argmax(x)) / (len(x) - 1), raw=True
    )
    down = df["low"].rolling(win, min_periods=win).apply(
        lambda x: 100.0 * int(np.argmin(x)) / (len(x) - 1), raw=True
    )
    return pd.DataFrame({"aroon_up": up, "aroon_down": down, "aroon_osc": up - down})


@indicator(
    "supertrend",
    params={"period": 10, "multiplier": 3.0},
    outputs=("supertrend", "supertrend_dir"),
    min_periods=20,
    tags=("trend", "overlay", "regime"),
)
def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """ATR-banded trailing stop. ``supertrend_dir`` is +1 long / -1 short."""
    high, low, close = df["high"], df["low"], df["close"]
    atr = wilder(true_range(high, low, close), period)
    mid = (high + low) / 2.0
    upper_basic = (mid + multiplier * atr).to_numpy(dtype=float)
    lower_basic = (mid - multiplier * atr).to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)

    n = len(c)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    trend = np.full(n, np.nan)
    st = np.full(n, np.nan)
    direction = 1
    for i in range(n):
        if not np.isfinite(upper_basic[i]):
            continue
        if i == 0 or not np.isfinite(upper[i - 1]):
            upper[i], lower[i] = upper_basic[i], lower_basic[i]
            direction = 1
        else:
            upper[i] = min(upper_basic[i], upper[i - 1]) if c[i - 1] <= upper[i - 1] else upper_basic[i]
            lower[i] = max(lower_basic[i], lower[i - 1]) if c[i - 1] >= lower[i - 1] else lower_basic[i]
            if c[i] > upper[i - 1]:
                direction = 1
            elif c[i] < lower[i - 1]:
                direction = -1
        trend[i] = direction
        st[i] = lower[i] if direction == 1 else upper[i]
    return pd.DataFrame({"supertrend": st, "supertrend_dir": trend}, index=df.index)


@indicator(
    "ichimoku",
    params={"conversion": 9, "base": 26, "span_b": 52},
    inputs=("high", "low", "close"),
    outputs=("tenkan", "kijun", "senkou_a", "senkou_b", "chikou"),
    min_periods=60,
    tags=("trend",),
)
def ichimoku(df: pd.DataFrame, conversion: int = 9, base: int = 26, span_b: int = 52) -> pd.DataFrame:
    """Ichimoku cloud.

    Note the cloud spans are shifted *forward*, which is safe, and chikou is
    shifted *backward*, which is a look-ahead if you use it naively -- it is
    emitted here for charting and flagged in the docs. Do not feed ``chikou``
    to a model without re-lagging it.
    """
    high, low = df["high"], df["low"]
    conv = (high.rolling(conversion).max() + low.rolling(conversion).min()) / 2
    kij = (high.rolling(base).max() + low.rolling(base).min()) / 2
    return pd.DataFrame(
        {
            "tenkan": conv,
            "kijun": kij,
            "senkou_a": ((conv + kij) / 2).shift(base),
            "senkou_b": ((high.rolling(span_b).max() + low.rolling(span_b).min()) / 2).shift(base),
            "chikou": df["close"].shift(-base),
        }
    )


@indicator("psar", params={"step": 0.02, "max_step": 0.2}, min_periods=5, tags=("trend", "overlay"))
def psar(df: pd.DataFrame, step: float = 0.02, max_step: float = 0.2) -> pd.Series:
    """Parabolic SAR trailing stop."""
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(high)
    out = np.full(n, np.nan)
    if n < 2:
        return pd.Series(out, index=df.index)

    bull = True
    af = step
    sar = low[0]
    ep = high[0]
    for i in range(1, n):
        prev_sar = sar
        sar = prev_sar + af * (ep - prev_sar)
        if bull:
            sar = min(sar, low[i - 1], low[max(0, i - 2)])
            if low[i] < sar:
                bull, sar, ep, af = False, ep, low[i], step
            elif high[i] > ep:
                ep, af = high[i], min(max_step, af + step)
        else:
            sar = max(sar, high[i - 1], high[max(0, i - 2)])
            if high[i] > sar:
                bull, sar, ep, af = True, ep, high[i], step
            elif low[i] < ep:
                ep, af = low[i], min(max_step, af + step)
        out[i] = sar
    return pd.Series(out, index=df.index)


@indicator("trend_slope", params={"period": 60}, inputs=("close",), tags=("trend", "statistical"))
def trend_slope(df: pd.DataFrame, period: int = 60) -> pd.Series:
    """Annualised OLS slope of log price -- a clean, comparable trend measure."""
    logp = np.log(df["close"].where(df["close"] > 0))
    return rolling_slope(logp, period) * 252.0


@indicator("trend_r2", params={"period": 60}, inputs=("close",), tags=("trend", "statistical", "quality"))
def trend_r2(df: pd.DataFrame, period: int = 60) -> pd.Series:
    """R-squared of the log-price trend fit: how *orderly* the move has been.

    Pair with ``trend_slope``: slope is size, R2 is conviction. High slope with
    low R2 is a jump, not a trend.
    """
    return rolling_rsquared(np.log(df["close"].where(df["close"] > 0)), period)


@indicator("ma_distance", params={"period": 200}, inputs=("close",), tags=("trend", "mean-reversion"))
def ma_distance(df: pd.DataFrame, period: int = 200) -> pd.Series:
    """Percent distance from a moving average -- stretch relative to trend."""
    m = sma(df["close"], period)
    return safe_div(df["close"] - m, m)


@indicator(
    "ma_cross_state",
    params={"fast": 50, "slow": 200},
    inputs=("close",),
    outputs=("ma_cross_state", "ma_cross_age"),
    tags=("trend", "regime"),
)
def ma_cross_state(df: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.DataFrame:
    """Golden/death cross state plus how many bars it has held.

    The *age* matters more than the cross: freshly crossed and long-held
    regimes behave very differently.
    """
    f, s = sma(df["close"], fast), sma(df["close"], slow)
    state = np.sign(f - s)
    state = state.where(f.notna() & s.notna())
    changed = state.ne(state.shift(1)) & state.notna()
    group = changed.cumsum()
    age = state.groupby(group).cumcount().astype(float).where(state.notna())
    return pd.DataFrame({"ma_cross_state": state, "ma_cross_age": age})
