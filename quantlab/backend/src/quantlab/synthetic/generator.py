"""Deterministic regime-switching synthetic OHLCV generator (research R4).

All randomness comes from ``numpy.random.Generator(PCG64(per-instrument seed))``
with seeds derived from the instrument symbol (config.instrument_seed). No
wall-clock access: the trading calendar is pinned in config. Regime mixes are
chosen per instrument profile so every starter signal rule fires somewhere in
the dataset (FR-004, verified by tests/unit/test_seed.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from quantlab import config


@dataclass(frozen=True)
class Bar:
    """One daily OHLCV bar; ``date`` is an ISO ``YYYY-MM-DD`` string."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


# Regime kinds -> (daily log-drift, daily log-vol) for GBM-style segments.
_GBM_REGIMES: dict[str, tuple[float, float]] = {
    "trend_up": (0.004, 0.008),
    "trend_down": (-0.004, 0.008),
    "flat": (0.0, 0.004),
    "volatile": (0.0, 0.030),
}

# OU-like mean-reversion parameters (log space, anchor at segment start).
_MEAN_REVERT_THETA = 0.10
_MEAN_REVERT_VOL = 0.012

# Regime mix per instrument profile.
_PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "trending": {"trend_up": 0.45, "trend_down": 0.25, "flat": 0.15, "volatile": 0.15},
    "mean_reverting": {
        "mean_revert": 0.70,
        "flat": 0.15,
        "trend_up": 0.075,
        "trend_down": 0.075,
    },
    "volatile": {"volatile": 0.60, "trend_up": 0.15, "trend_down": 0.15, "flat": 0.10},
    "mixed": {
        "trend_up": 0.25,
        "trend_down": 0.20,
        "mean_revert": 0.30,
        "volatile": 0.15,
        "flat": 0.10,
    },
}

_SEGMENT_MIN_DAYS = 40
_SEGMENT_MAX_DAYS = 90


def _log_returns(rng: np.random.Generator, profile: str, n: int) -> np.ndarray:
    """Concatenated per-segment log returns covering ``n`` days."""
    weights_map = _PROFILE_WEIGHTS[profile]
    kinds = list(weights_map)
    weights = np.array([weights_map[k] for k in kinds], dtype=float)
    weights /= weights.sum()

    returns = np.empty(n, dtype=float)
    pos = 0
    while pos < n:
        kind = kinds[rng.choice(len(kinds), p=weights)]
        length = int(min(rng.integers(_SEGMENT_MIN_DAYS, _SEGMENT_MAX_DAYS), n - pos))
        eps = rng.standard_normal(length)
        if kind == "mean_revert":
            # OU-like deviation x from the segment anchor; the log return of
            # day t is x_t - x_{t-1} (price = anchor * exp(x)).
            x = np.empty(length, dtype=float)
            level = 0.0
            for t in range(length):
                level += _MEAN_REVERT_THETA * (0.0 - level) + _MEAN_REVERT_VOL * eps[t]
                x[t] = level
            returns[pos : pos + length] = np.diff(np.concatenate(([0.0], x)))
        else:
            drift, vol = _GBM_REGIMES[kind]
            returns[pos : pos + length] = drift + vol * eps
        pos += length
    return returns


def generate_bars(spec: config.InstrumentSpec, calendar: list) -> list[Bar]:
    """Generate the full OHLCV history for one instrument (deterministic)."""
    rng = np.random.Generator(np.random.PCG64(config.instrument_seed(spec.symbol)))
    n = len(calendar)
    start_price = float(rng.uniform(40.0, 160.0))
    closes = start_price * np.exp(np.cumsum(_log_returns(rng, spec.regime_profile, n)))
    closes = np.maximum(closes, 2.0)  # keep prices sane; guarantees close > 0

    bars: list[Bar] = []
    prev_close = start_price
    for i, day in enumerate(calendar):
        close = float(closes[i])
        open_price = prev_close * float(np.exp(rng.normal(0.0, 0.003)))
        open_ = round(open_price, 2)
        close_r = round(close, 2)
        # Build high/low around the rounded open/close, then clamp so the
        # price_bars CHECK invariants hold exactly even after rounding.
        high = round(max(open_, close_r) * (1.0 + float(rng.uniform(0.005, 0.025))), 2)
        high = max(high, max(open_, close_r) + 0.01)
        low = round(min(open_, close_r) * (1.0 - float(rng.uniform(0.005, 0.025))), 2)
        low = min(low, min(open_, close_r) - 0.01)
        low = max(low, 0.01)
        volume = int(rng.uniform(100_000, 5_000_000))
        bars.append(Bar(day.isoformat(), open_, high, low, close_r, volume))
        prev_close = close
    return bars


def generate_universe() -> dict[str, list[Bar]]:
    """Generate bars for the full configured universe, keyed by symbol."""
    config.validate_universe()
    calendar = config.trading_calendar()
    return {spec.symbol: generate_bars(spec, calendar) for spec in config.UNIVERSE}
