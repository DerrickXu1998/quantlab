"""Per-run parameter overrides and effective-parameter provenance (feature 005).

Constitution VI: a run must be reproducible from its own record. Recording the
registered defaults while having executed overrides would make provenance a lie,
which is the most damaging way this can fail — the record looks fine and cannot
reproduce the result.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from quantlab.signals.engine import compute_signals
from quantlab.signals.registry import get_rule


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def _rising_bars(n: int = 300) -> list[Bar]:
    """An oscillating series long enough that both short and long SMA windows
    cross repeatedly — a monotonic series never crosses a long SMA, which would
    make override differences invisible rather than absent."""
    import math

    bars = []
    for i in range(n):
        price = 100.0 + 20.0 * math.sin(i / 12.0) + 8.0 * math.sin(i / 47.0)
        bars.append(
            Bar(
                date=f"20{24 + i // 336:02d}-{1 + (i // 28) % 12:02d}-{1 + i % 28:02d}",
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1_000,
            )
        )
    return bars


def test_defaults_are_used_when_no_override_given():
    bars = {"AAA": _rising_bars()}
    rule = get_rule("sma-crossover")

    signals = compute_signals(bars, rules=[rule])

    for signal in signals:
        assert signal.parameters == {"fast": 20, "slow": 50}


def test_overrides_are_applied_and_recorded_as_effective_parameters():
    bars = {"AAA": _rising_bars()}
    rule = get_rule("sma-crossover")

    signals = compute_signals(bars, rules=[rule], overrides={"fast": 5, "slow": 10})

    assert signals, "expected the override run to produce signals"
    for signal in signals:
        # The recorded parameters must be what actually executed...
        assert signal.parameters == {"fast": 5, "slow": 10}
        # ...never the registered defaults.
        assert signal.parameters != {"fast": 20, "slow": 50}


def test_partial_override_merges_over_declared_defaults():
    bars = {"AAA": _rising_bars()}
    rule = get_rule("sma-crossover")

    signals = compute_signals(bars, rules=[rule], overrides={"fast": 5})

    assert signals
    for signal in signals:
        assert signal.parameters == {"fast": 5, "slow": 50}


def test_overrides_change_the_output():
    """If overrides were silently ignored, the two runs would be identical —
    this is the test that would catch that."""
    bars = {"AAA": _rising_bars()}
    rule = get_rule("sma-crossover")

    default_run = compute_signals(bars, rules=[rule])
    override_run = compute_signals(bars, rules=[rule], overrides={"fast": 3, "slow": 8})

    assert [(s.date, s.direction) for s in default_run] != [
        (s.date, s.direction) for s in override_run
    ]


def test_unknown_override_key_is_rejected():
    bars = {"AAA": _rising_bars()}
    rule = get_rule("sma-crossover")

    with pytest.raises((TypeError, ValueError, KeyError)):
        compute_signals(bars, rules=[rule], overrides={"not_a_param": 1})


def test_output_remains_deterministic_under_overrides():
    bars = {"AAA": _rising_bars(), "BBB": _rising_bars()}
    rule = get_rule("sma-crossover")

    first = compute_signals(bars, rules=[rule], overrides={"fast": 5, "slow": 10})
    second = compute_signals(bars, rules=[rule], overrides={"fast": 5, "slow": 10})

    assert first == second
