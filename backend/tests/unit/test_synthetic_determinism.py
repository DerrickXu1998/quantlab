"""Determinism and coverage tests for the synthetic data generator (FR-004/FR-005)."""

from __future__ import annotations

import re
from datetime import date

from quantlab import config
from quantlab.synthetic import generator


def test_full_universe_byte_identical():
    first = generator.generate_universe()
    second = generator.generate_universe()
    assert list(first) == list(second)
    for symbol in first:
        assert first[symbol] == second[symbol], f"bars diverged for {symbol}"


def test_seed_derivation_deterministic_and_unique():
    seeds = {spec.symbol: config.instrument_seed(spec.symbol) for spec in config.UNIVERSE}
    again = {spec.symbol: config.instrument_seed(spec.symbol) for spec in config.UNIVERSE}
    assert seeds == again
    assert len(set(seeds.values())) == len(seeds), "per-instrument seeds must be distinct"
    for value in seeds.values():
        assert 0 <= value < 2**32


def test_calendar_pinned_weekday_only():
    calendar = config.trading_calendar()
    assert config.CALENDAR_START_DATE == date(2023, 1, 1)
    assert config.END_DATE == date(2025, 12, 31)
    assert calendar[0] == date(2023, 1, 2)  # 2023-01-01 is a Sunday
    assert calendar[-1] == date(2025, 12, 31)  # a Wednesday
    assert all(day.weekday() < 5 for day in calendar)
    assert len(calendar) >= 756  # >= 3 years of trading days per instrument


def test_universe_is_clearly_fictitious():
    assert len(config.UNIVERSE) >= 10
    for spec in config.UNIVERSE:
        assert re.fullmatch(config.SYMBOL_PATTERN, spec.symbol)
        assert spec.symbol not in config.REAL_TICKER_DENYLIST
        assert "synthetic" in spec.name.lower()
        assert spec.regime_profile in config.VALID_REGIME_PROFILES
    config.validate_universe()  # must not raise


def test_full_calendar_coverage_and_bar_invariants():
    universe = generator.generate_universe()
    expected_dates = [day.isoformat() for day in config.trading_calendar()]
    for spec in config.UNIVERSE:
        bars = universe[spec.symbol]
        assert [bar.date for bar in bars] == expected_dates
        for bar in bars:
            assert bar.open > 0
            assert bar.close > 0
            assert bar.high >= max(bar.open, bar.close)
            assert 0 < bar.low <= min(bar.open, bar.close)
            assert bar.volume >= 0
