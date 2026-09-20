"""Synthetic generator: determinism, schema conformance, signal coverage.

All offline. The warehouse write path is exercised against the live stack in
tests/test_store.py (`make store-test`).
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from quantlab.schema import BAR_COLUMNS, validate_bars
from quantlab.synthetic import (
    DEFAULT_UNIVERSE,
    PROFILES,
    SyntheticSpec,
    generate_bars,
    instrument_seed,
)

START = dt.date(2022, 1, 1)
END = dt.date(2025, 12, 31)


def test_default_universe_is_fictitious_and_covers_every_profile():
    symbols = [spec.symbol for spec in DEFAULT_UNIVERSE]
    assert len(DEFAULT_UNIVERSE) == 25
    assert len(set(symbols)) == len(symbols)
    assert all(symbol.startswith("ZX") and symbol.endswith(".US") for symbol in symbols)
    assert {spec.profile for spec in DEFAULT_UNIVERSE} == set(PROFILES)
    assert all(spec.profile in PROFILES for spec in DEFAULT_UNIVERSE)


def test_generate_bars_is_deterministic():
    first = generate_bars("ZX1.US", START, END)
    second = generate_bars("ZX1.US", START, END)
    pd.testing.assert_frame_equal(first, second)


def test_seed_salt_changes_the_bars_but_stays_deterministic():
    base = generate_bars("ZX1.US", START, END)
    salted = generate_bars("ZX1.US", START, END, seed="alt")
    assert not base["close"].equals(salted["close"])
    pd.testing.assert_frame_equal(salted, generate_bars("ZX1.US", START, END, seed="alt"))


def test_instrument_seed_is_stable_and_symbol_dependent():
    assert instrument_seed("ZX1.US") == instrument_seed("ZX1.US")
    assert instrument_seed("ZX1.US") != instrument_seed("ZX2.US")
    assert 0 <= instrument_seed("ZX1.US") < 2**32


def test_generate_bars_passes_schema_validation_unchanged():
    frame = generate_bars("ZX3.US", START, END)
    validated = validate_bars(frame, symbol="ZX3.US")
    assert list(validated.columns) == list(BAR_COLUMNS)
    assert validated.index.name == "date"
    pd.testing.assert_frame_equal(validated[frame.columns], frame)


def test_dates_are_weekdays_only():
    frame = generate_bars("ZX2.US", START, END)
    assert (frame.index.dayofweek < 5).all()
    expected = pd.bdate_range(START, END, name="date")
    assert frame.index.equals(expected)


def test_no_nans_and_valid_ohlc_geometry():
    for spec in DEFAULT_UNIVERSE:
        frame = generate_bars(spec.symbol, START, END)
        assert frame.notna().all().all(), spec.symbol
        assert (frame[["open", "high", "low", "close"]] > 0).all().all()
        assert (frame["high"] >= frame[["open", "close"]].max(axis=1)).all()
        assert (frame["low"] <= frame[["open", "close"]].min(axis=1)).all()
        assert (frame["volume"] > 0).all()
        assert (frame["adj_close"] == frame["close"]).all()


def test_unknown_symbol_generates_deterministically():
    first = generate_bars("ZZNOPE.US", START, END)
    assert not first.empty
    pd.testing.assert_frame_equal(first, generate_bars("ZZNOPE.US", START, END))


def test_empty_range_returns_an_empty_canonical_frame():
    frame = generate_bars("ZX1.US", dt.date(2025, 12, 27), dt.date(2025, 12, 28))  # weekend
    assert frame.empty
    assert list(frame.columns) == list(BAR_COLUMNS)


def test_bad_profile_is_rejected():
    with pytest.raises(ValueError, match="unknown regime profile"):
        generate_bars("ZX1.US", START, END, profile="chaotic")


# ---------------------------------------------------------------------------
# Signal coverage: every regime profile must fire at least one starter rule.
# Replicates the three builtin rules (SMA crossover, RSI threshold exit, 20d
# breakout) inline -- the backend package is not importable from here.
# ---------------------------------------------------------------------------


def _sma(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan)
    if len(values) >= window:
        cumsum = np.cumsum(np.insert(values, 0, 0.0))
        out[window - 1 :] = (cumsum[window:] - cumsum[:-window]) / window
    return out


def _rsi(values: np.ndarray, period: int = 14) -> np.ndarray:
    out = np.full(values.shape, np.nan)
    if len(values) <= period:
        return out
    deltas = np.diff(values)
    gains = np.maximum(deltas, 0.0)
    losses = np.maximum(-deltas, 0.0)
    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())

    def to_rsi(g: float, lo: float) -> float:
        if lo == 0.0:
            return 100.0 if g > 0.0 else 50.0
        return 100.0 - 100.0 / (1.0 + g / lo)

    out[period] = to_rsi(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + float(gains[i - 1])) / period
        avg_loss = (avg_loss * (period - 1) + float(losses[i - 1])) / period
        out[i] = to_rsi(avg_gain, avg_loss)
    return out


def _sma_crossover_fires(frame: pd.DataFrame, fast: int = 20, slow: int = 50) -> bool:
    closes = frame["close"].to_numpy(dtype=float)
    fast_sma, slow_sma = _sma(closes, fast), _sma(closes, slow)
    diff = fast_sma - slow_sma
    valid = ~np.isnan(diff)
    prev, curr = diff[:-1], diff[1:]
    crossed = ((prev <= 0) & (curr > 0)) | ((prev >= 0) & (curr < 0))
    return bool((crossed & valid[:-1] & valid[1:]).any())


def _rsi_threshold_fires(
    frame: pd.DataFrame, period: int = 14, overbought: float = 70, oversold: float = 30
) -> bool:
    rsi = _rsi(frame["close"].to_numpy(dtype=float), period)
    prev, curr = rsi[:-1], rsi[1:]
    valid = ~(np.isnan(prev) | np.isnan(curr))
    exited = ((prev > overbought) & (curr <= overbought)) | (
        (prev < oversold) & (curr >= oversold)
    )
    return bool((exited & valid).any())


def _breakout_20d_fires(frame: pd.DataFrame, window: int = 20) -> bool:
    closes = frame["close"].to_numpy(dtype=float)
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    for i in range(window, len(closes)):
        if closes[i] > highs[i - window : i].max():
            return True
        if closes[i] < lows[i - window : i].min():
            return True
    return False


def test_every_profile_fires_at_least_one_signal_rule():
    """The synthetic data exists so the signal engine has something to find."""
    for profile in PROFILES:
        spec = next(spec for spec in DEFAULT_UNIVERSE if spec.profile == profile)
        frame = generate_bars(spec.symbol, START, END)
        fired = {
            "sma_crossover": _sma_crossover_fires(frame),
            "rsi_threshold": _rsi_threshold_fires(frame),
            "breakout_20d": _breakout_20d_fires(frame),
        }
        assert any(fired.values()), f"profile {profile}: no signal fired {fired}"


def test_every_rule_fires_somewhere_in_the_default_universe():
    fired = {"sma_crossover": False, "rsi_threshold": False, "breakout_20d": False}
    for spec in DEFAULT_UNIVERSE:
        frame = generate_bars(spec.symbol, START, END)
        fired["sma_crossover"] |= _sma_crossover_fires(frame)
        fired["rsi_threshold"] |= _rsi_threshold_fires(frame)
        fired["breakout_20d"] |= _breakout_20d_fires(frame)
    assert all(fired.values()), f"rules that never fired: {fired}"


def test_spec_is_hashable_for_use_in_sets():
    assert len({spec for spec in DEFAULT_UNIVERSE}) == len(DEFAULT_UNIVERSE)
    assert SyntheticSpec("ZX1.US", "n", "mixed") == SyntheticSpec("ZX1.US", "n", "mixed")
