"""Builtin indicator plugins: SMA, EMA, RSI (Wilder's), rolling max/min/std.

All functions take a 1-D array-like of floats and return a float ndarray of the
same length, with NaN where there is insufficient history (warmup period).
"""

from __future__ import annotations

import numpy as np

from quantlab.indicators.registry import register_indicator


@register_indicator(
    name="sma",
    version="1.0.0",
    scale_class="price_scaled",
    params={"window": 20},
    description="Simple moving average of the trailing `window` values (inclusive).",
)
def sma(values, window: int = 20) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = np.full(values.shape, np.nan)
    if len(values) >= window:
        cumsum = np.cumsum(np.insert(values, 0, 0.0))
        out[window - 1 :] = (cumsum[window:] - cumsum[:-window]) / window
    return out


@register_indicator(
    name="ema",
    version="1.0.0",
    scale_class="price_scaled",
    params={"window": 20},
    description=(
        "Exponential moving average with alpha = 2/(window+1), seeded with the SMA "
        "of the first `window` defined values. Leading NaNs are skipped, so a "
        "series with its own warmup (e.g. a MACD line) can be smoothed directly."
    ),
)
def ema(values, window: int = 20) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = np.full(values.shape, np.nan)
    # Skip a NaN warmup prefix: the series' own history starts at its first
    # defined value, and the EMA warm-up is measured from there.
    defined = np.flatnonzero(~np.isnan(values))
    if len(defined) == 0:
        return out
    start = int(defined[0])
    series = values[start:]
    if len(series) < window:
        return out
    alpha = 2.0 / (window + 1)
    acc = float(series[:window].mean())
    out[start + window - 1] = acc
    for i in range(start + window, len(values)):
        acc += alpha * (float(values[i]) - acc)
        out[i] = acc
    return out


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        # Convention: a series with only gains is 100; a perfectly flat series is 50.
        return 100.0 if avg_gain > 0.0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


@register_indicator(
    name="rsi",
    version="1.0.0",
    scale_class="scale_free",
    params={"period": 14},
    description="Relative Strength Index with Wilder's smoothing; first value at index `period`.",
)
def rsi(values, period: int = 14) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    n = len(values)
    out = np.full(n, np.nan)
    if n <= period:
        return out
    deltas = np.diff(values)
    gains = np.maximum(deltas, 0.0)
    losses = np.maximum(-deltas, 0.0)
    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())
    out[period] = _rsi_from_averages(avg_gain, avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + float(gains[i - 1])) / period
        avg_loss = (avg_loss * (period - 1) + float(losses[i - 1])) / period
        out[i] = _rsi_from_averages(avg_gain, avg_loss)
    return out


def _rolling(values, window: int, reducer) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = np.full(values.shape, np.nan)
    if len(values) >= window:
        windows = np.lib.stride_tricks.sliding_window_view(values, window)
        out[window - 1 :] = reducer(windows, axis=1)
    return out


@register_indicator(
    name="rolling-max",
    version="1.0.0",
    scale_class="price_scaled",
    params={"window": 20},
    description="Max of the trailing `window` values (inclusive).",
)
def rolling_max(values, window: int = 20) -> np.ndarray:
    return _rolling(values, window, np.max)


@register_indicator(
    name="rolling-min",
    version="1.0.0",
    scale_class="price_scaled",
    params={"window": 20},
    description="Min of the trailing `window` values (inclusive).",
)
def rolling_min(values, window: int = 20) -> np.ndarray:
    return _rolling(values, window, np.min)


@register_indicator(
    name="rolling-std",
    version="1.0.0",
    scale_class="price_scaled",
    params={"window": 20},
    description=(
        "Population standard deviation (ddof=0) of the trailing `window` values "
        "(inclusive) -- the Bollinger convention."
    ),
)
def rolling_std(values, window: int = 20) -> np.ndarray:
    return _rolling(values, window, np.std)
