"""Deterministic synthetic OHLCV generator for seeding the warehouse.

All randomness comes from ``numpy.random.Generator(PCG64(seed))`` with the
seed derived from sha256(symbol + optional seed salt). There is no wall-clock
access anywhere in this module (Constitution VI): the calendar is a plain
weekday range between the caller's dates, so the same inputs produce
byte-identical bars on any machine.

Regime mixes are chosen per instrument profile (trending / mean_reverting /
volatile / mixed) so every starter signal rule -- SMA crossover, RSI
threshold, 20d breakout -- fires somewhere in a full history.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .schema import BAR_COLUMNS

DEFAULT_START = dt.date(2022, 1, 1)
DEFAULT_END = dt.date(2025, 12, 31)
DEFAULT_SEED = "quantlab-synthetic"

# Provenance label used for the ingest run and the bars' source column.
SOURCE = "synthetic"

PROFILES: tuple[str, ...] = ("trending", "mean_reverting", "volatile", "mixed")


@dataclass(frozen=True)
class SyntheticSpec:
    """Static definition of one fictitious instrument."""

    symbol: str
    name: str
    profile: str


# Recognisably fake universe: every symbol is ZX<n>.US and names no real
# company. Profiles cycle so a prefix of any size covers every regime.
DEFAULT_UNIVERSE: tuple[SyntheticSpec, ...] = tuple(
    SyntheticSpec(
        symbol=f"ZX{i}.US",
        name=f"ZX{i} Synthetic {PROFILES[(i - 1) % len(PROFILES)].replace('_', ' ').title()} Corp",
        profile=PROFILES[(i - 1) % len(PROFILES)],
    )
    for i in range(1, 26)
)


def instrument_seed(symbol: str, seed: str | None = None) -> int:
    """Derive a deterministic per-instrument seed from the symbol.

    sha256(seed salt + symbol) folded into a uint32. Pure function of the
    strings -- stable across processes, platforms, and runs.
    """
    digest = hashlib.sha256(f"{seed or DEFAULT_SEED}:{symbol}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**32)


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


def _profile_for(symbol: str, seed: str | None) -> str:
    """The regime profile for a symbol: its universe profile, else a
    deterministic pick so any symbol string still generates."""
    for spec in DEFAULT_UNIVERSE:
        if spec.symbol == symbol:
            return spec.profile
    return PROFILES[instrument_seed(symbol, seed) % len(PROFILES)]


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


def generate_bars(
    symbol: str,
    start: str | dt.date = DEFAULT_START,
    end: str | dt.date = DEFAULT_END,
    seed: str | None = None,
    *,
    profile: str | None = None,
) -> pd.DataFrame:
    """Daily OHLCV bars for ``symbol`` over the weekday calendar start..end.

    Deterministic: same (symbol, start, end, seed) always yields an identical
    frame. The output carries the canonical bar schema (DatetimeIndex named
    ``date``, columns ``open..volume, adj_close``) and passes
    ``schema.validate_bars`` unchanged.
    """
    profile = profile or _profile_for(symbol, seed)
    if profile not in _PROFILE_WEIGHTS:
        raise ValueError(f"unknown regime profile {profile!r}")

    calendar = pd.bdate_range(pd.Timestamp(start), pd.Timestamp(end), name="date")
    n = len(calendar)
    if n == 0:
        return pd.DataFrame(
            {c: pd.Series(dtype="float64") for c in BAR_COLUMNS}, index=calendar
        )

    rng = np.random.Generator(np.random.PCG64(instrument_seed(symbol, seed)))
    start_price = float(rng.uniform(40.0, 160.0))
    closes = start_price * np.exp(np.cumsum(_log_returns(rng, profile, n)))
    closes = np.maximum(closes, 2.0)  # keep prices sane; guarantees close > 0

    rows: list[tuple[float, float, float, float, float, int]] = []
    prev_close = start_price
    for close in closes:
        open_price = prev_close * float(np.exp(rng.normal(0.0, 0.003)))
        open_ = round(open_price, 2)
        close_r = round(float(close), 2)
        # Build high/low around the rounded open/close, then clamp so the
        # OHLC ordering invariants hold exactly even after rounding.
        high = round(max(open_, close_r) * (1.0 + float(rng.uniform(0.005, 0.025))), 2)
        high = max(high, max(open_, close_r) + 0.01)
        low = round(min(open_, close_r) * (1.0 - float(rng.uniform(0.005, 0.025))), 2)
        low = min(low, min(open_, close_r) - 0.01)
        low = max(low, 0.01)
        volume = int(rng.uniform(100_000, 5_000_000))
        rows.append((open_, high, low, close_r, close_r, volume))
        prev_close = float(close)

    frame = pd.DataFrame(
        rows, columns=["open", "high", "low", "close", "adj_close", "volume"], index=calendar
    )
    return frame[list(BAR_COLUMNS)]
