"""Seed configuration for the synthetic demo universe.

Everything here is fixed and pinned: the symbol universe, the trading
calendar, and every RNG seed. No wall-clock access is allowed anywhere in
this module (Constitution VI) — the as-of end date is a constant.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta

# Pinned "as-of" end date for the trading calendar. Never derived from the
# wall clock so regenerated datasets are byte-identical (SC-002).
END_DATE: date = date(2025, 12, 31)

# Calendar covers at least 3 years of weekdays ending at the pinned as-of date.
CALENDAR_START_DATE: date = date(2023, 1, 1)

# Base seed for the whole demo universe.
BASE_SEED: int = 42

CURRENCY: str = "USD"

VALID_REGIME_PROFILES: tuple[str, ...] = ("trending", "mean_reverting", "volatile", "mixed")

# Symbol shape enforced by the API contract (contracts/openapi.yaml).
SYMBOL_PATTERN: str = r"^[A-Z]{2,8}$"

# Small denylist of real tickers — synthetic symbols MUST NOT collide (FR-006).
REAL_TICKER_DENYLIST: frozenset = frozenset(
    {
        "AAPL",
        "MSFT",
        "GOOG",
        "GOOGL",
        "AMZN",
        "NVDA",
        "META",
        "TSLA",
        "SPY",
        "QQQ",
        "DIA",
        "IWM",
        "VTI",
        "VOO",
        "BRK",
        "JPM",
        "XOM",
    }
)


@dataclass(frozen=True)
class InstrumentSpec:
    """Static definition of one fictitious instrument in the demo universe."""

    symbol: str
    name: str
    regime_profile: str


# Recognizably fake universe (FR-006): every symbol is prefixed ``ZZ`` and
# names no real company.
UNIVERSE: tuple[InstrumentSpec, ...] = (
    InstrumentSpec("ZZTRND", "Zeno Trend Industries (synthetic)", "trending"),
    InstrumentSpec("ZZMEAN", "Zephyr Mean Reversion Co (synthetic)", "mean_reverting"),
    InstrumentSpec("ZZVOLT", "Zircon Volatility Labs (synthetic)", "volatile"),
    InstrumentSpec("ZZMIX", "Zonal Mixed Regimes Inc (synthetic)", "mixed"),
    InstrumentSpec("ZZDRIFT", "Zeta Drift Holdings (synthetic)", "trending"),
    InstrumentSpec("ZZOSC", "Zirconia Oscillator Group (synthetic)", "mean_reverting"),
    InstrumentSpec("ZZSTORM", "Zulu Storm Capital (synthetic)", "volatile"),
    InstrumentSpec("ZZWAVE", "Zebra Wave Systems (synthetic)", "mixed"),
    InstrumentSpec("ZZRALLY", "Zenith Rally Works (synthetic)", "trending"),
    InstrumentSpec("ZZCHOP", "Zygote Chop Trading (synthetic)", "mean_reverting"),
    InstrumentSpec("ZZFURY", "Zambezi Fury Enterprises (synthetic)", "volatile"),
    InstrumentSpec("ZZBLEND", "Xanthic Blend Partners (synthetic)", "mixed"),
)


def instrument_seed(symbol: str) -> int:
    """Derive a deterministic per-instrument seed from the symbol.

    sha256(symbol + base seed) folded into a uint32. Pure function of the
    symbol string — stable across processes, platforms, and runs.
    """
    digest = hashlib.sha256(f"{BASE_SEED}:{symbol}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big") % (2**32)


def validate_universe() -> None:
    """Fail fast if the configured universe violates FR-006 or the contract pattern."""
    import re

    seen: set[str] = set()
    for spec in UNIVERSE:
        if not re.fullmatch(SYMBOL_PATTERN, spec.symbol):
            raise ValueError(f"symbol {spec.symbol!r} does not match {SYMBOL_PATTERN}")
        if spec.symbol in REAL_TICKER_DENYLIST:
            raise ValueError(f"symbol {spec.symbol!r} collides with a real ticker")
        if spec.symbol in seen:
            raise ValueError(f"duplicate symbol {spec.symbol!r}")
        if spec.regime_profile not in VALID_REGIME_PROFILES:
            raise ValueError(f"unknown regime profile {spec.regime_profile!r}")
        seen.add(spec.symbol)


def trading_calendar() -> list[date]:
    """Weekday-only calendar from CALENDAR_START_DATE to END_DATE inclusive.

    No holidays — a fixed weekday calendar keeps the dataset deterministic
    and trivially re-derivable.
    """
    days: list[date] = []
    current = CALENDAR_START_DATE
    while current <= END_DATE:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days
