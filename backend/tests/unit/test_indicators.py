"""Reference-value tests for indicator plugins (Constitution IV).

Reference implementations below are deliberately independent plain-Python
re-implementations; the RSI anchors are hand-computed (see test_rsi_hand_computed).
"""

from __future__ import annotations

import math

import pytest

from quantlab.indicators import builtins  # noqa: F401  (registers the builtin plugins)
from quantlab.indicators.registry import get_indicator, list_indicators


def ref_sma(values, window):
    out = [math.nan] * len(values)
    for i in range(window - 1, len(values)):
        out[i] = sum(values[i - window + 1 : i + 1]) / window
    return out


def _rsi_from_avgs(avg_gain, avg_loss):
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0.0 else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def ref_rsi(values, period):
    """Independent Wilder's RSI reference (smoothing factor 1/period)."""
    n = len(values)
    out = [math.nan] * n
    if n <= period:
        return out
    deltas = [values[i] - values[i - 1] for i in range(1, n)]
    avg_gain = sum(max(d, 0.0) for d in deltas[:period]) / period
    avg_loss = sum(max(-d, 0.0) for d in deltas[:period]) / period
    out[period] = _rsi_from_avgs(avg_gain, avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + max(deltas[i - 1], 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-deltas[i - 1], 0.0)) / period
        out[i] = _rsi_from_avgs(avg_gain, avg_loss)
    return out


def ref_rolling(values, window, fn):
    out = [math.nan] * len(values)
    for i in range(window - 1, len(values)):
        out[i] = fn(values[i - window + 1 : i + 1])
    return out


def ref_ema(values, window):
    """Independent EMA reference: alpha = 2/(window+1), SMA-seeded, leading
    NaNs skipped (the series' own warmup precedes the EMA warmup)."""
    alpha = 2.0 / (window + 1)
    out = [math.nan] * len(values)
    start = next((i for i, v in enumerate(values) if not math.isnan(v)), None)
    if start is None or len(values) - start < window:
        return out
    acc = sum(values[start : start + window]) / window
    out[start + window - 1] = acc
    for i in range(start + window, len(values)):
        acc += alpha * (values[i] - acc)
        out[i] = acc
    return out


def assert_nan_prefix(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected, strict=True):
        if math.isnan(want):
            assert math.isnan(got)
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


def test_registry_lists_builtin_indicators():
    plugins = {(p.name, p.version): p for p in list_indicators()}
    for key, scale_class in [
        (("sma", "1.0.0"), "price_scaled"),
        (("ema", "1.0.0"), "price_scaled"),
        (("rsi", "1.0.0"), "scale_free"),
        (("rolling-max", "1.0.0"), "price_scaled"),
        (("rolling-min", "1.0.0"), "price_scaled"),
        (("rolling-std", "1.0.0"), "price_scaled"),
    ]:
        assert key in plugins, f"missing indicator {key}"
        assert plugins[key].scale_class == scale_class
        assert plugins[key].params


def test_sma_fixed_series():
    sma = get_indicator("sma", "1.0.0").compute
    assert_nan_prefix(
        list(sma([1.0, 2.0, 3.0, 4.0, 5.0], window=3)), [math.nan, math.nan, 2.0, 3.0, 4.0]
    )
    values = [2.5, 3.5, 4.5, 1.5, 6.0, 7.0, 0.5, 8.0]
    assert_nan_prefix(list(sma(values, window=4)), ref_sma(values, 4))


def test_sma_insufficient_history_is_nan():
    sma = get_indicator("sma").compute
    out = sma([1.0, 2.0, 3.0, 4.0], window=5)
    assert all(math.isnan(v) for v in out)
    assert list(sma([], window=5)) == []


def test_rsi_hand_computed():
    """RSI(14) anchors computed by hand with Wilder's smoothing.

    Series A deltas: +1,+1,-1,+1,+1,+1,-1,+1,+1,+1,-1,+1,+1,+1
    => avg_gain = 11/14, avg_loss = 3/14, RSI = 100 - 300/14 = 78.5714285714...
    Appending a -1 delta: avg_gain = 143/196, avg_loss = 53/196
    => RSI = 100 - 5300/196 = 72.9591836735...
    """
    rsi = get_indicator("rsi", "1.0.0").compute
    closes = [10, 11, 12, 11, 12, 13, 14, 13, 14, 15, 16, 15, 16, 17, 18]
    out = list(rsi(closes, period=14))
    assert all(math.isnan(v) for v in out[:14])
    assert out[14] == pytest.approx(78.57142857142857, rel=1e-12)
    out2 = list(rsi(closes + [17], period=14))
    assert out2[15] == pytest.approx(72.95918367346939, rel=1e-12)


def test_rsi_matches_independent_reference():
    rsi = get_indicator("rsi").compute
    values = [
        44.0,
        44.3,
        44.1,
        43.6,
        44.8,
        45.5,
        45.4,
        45.9,
        46.1,
        46.7,
        46.4,
        46.9,
        47.2,
        46.6,
        47.5,
        48.0,
        47.6,
        48.2,
        47.9,
        48.5,
    ]
    assert_nan_prefix(list(rsi(values, period=14)), ref_rsi(values, 14))


def test_rsi_monotonic_up_is_100_and_flat_is_50():
    rsi = get_indicator("rsi").compute
    up = list(rsi([float(i) for i in range(1, 20)], period=14))
    assert up[-1] == pytest.approx(100.0)
    flat = list(rsi([7.0] * 20, period=14))
    assert all(v == pytest.approx(50.0) for v in flat[14:])


def test_rsi_insufficient_history_is_nan():
    rsi = get_indicator("rsi").compute
    out = rsi([1.0] * 14, period=14)
    assert all(math.isnan(v) for v in out)


def test_rolling_max_min_fixed_series():
    rmax = get_indicator("rolling-max", "1.0.0").compute
    rmin = get_indicator("rolling-min", "1.0.0").compute
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0]
    assert_nan_prefix(list(rmax(values, window=3)), ref_rolling(values, 3, max))
    assert_nan_prefix(list(rmin(values, window=3)), ref_rolling(values, 3, min))
    assert list(rmax(values, window=3))[2:4] == [4.0, 4.0]
    assert list(rmin(values, window=3))[2:4] == [1.0, 1.0]


def test_rolling_insufficient_history_is_nan():
    rmax = get_indicator("rolling-max").compute
    assert all(math.isnan(v) for v in rmax([1.0, 2.0], window=3))


def test_ema_fixed_series():
    ema = get_indicator("ema", "1.0.0").compute
    assert_nan_prefix(
        list(ema([1.0, 2.0, 3.0, 4.0, 5.0], window=3)),
        # seed = mean(1,2,3) = 2; then alpha=0.5: 2+0.5*(4-2)=3, 3+0.5*(5-3)=4
        [math.nan, math.nan, 2.0, 3.0, 4.0],
    )
    values = [2.5, 3.5, 4.5, 1.5, 6.0, 7.0, 0.5, 8.0]
    assert_nan_prefix(list(ema(values, window=4)), ref_ema(values, 4))


def test_ema_skips_a_leading_nan_warmup():
    """A series with its own warmup (e.g. a MACD line) is smoothed from its
    first defined value, not from index 0."""
    ema = get_indicator("ema").compute
    values = [math.nan, math.nan, 1.0, 2.0, 3.0, 4.0, 5.0]
    assert_nan_prefix(list(ema(values, window=3)), ref_ema(values, 3))


def test_ema_insufficient_history_is_nan():
    ema = get_indicator("ema").compute
    out = ema([1.0, 2.0, 3.0, 4.0], window=5)
    assert all(math.isnan(v) for v in out)
    assert list(ema([], window=5)) == []


def test_rolling_std_fixed_series():
    rstd = get_indicator("rolling-std", "1.0.0").compute

    def ref_std(window_values):
        mean = sum(window_values) / len(window_values)
        return math.sqrt(sum((v - mean) ** 2 for v in window_values) / len(window_values))

    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0]
    assert_nan_prefix(list(rstd(values, window=3)), ref_rolling(values, 3, ref_std))
    # A flat window has zero dispersion.
    assert all(v == pytest.approx(0.0) for v in list(rstd([7.0] * 6, window=3))[2:])
