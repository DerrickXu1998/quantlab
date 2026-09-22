"""Look-ahead sweep: truncating history at day T must not change any signal <= T.

Constitution VII: recomputing every registered rule on history truncated at T
must reproduce exactly the full-history signals dated <= T, and every emitted
signal must carry data_window_end <= T.
"""

from __future__ import annotations

from quantlab.signals import builtins  # noqa: F401  (registers the builtin rules)
from quantlab.signals.registry import list_rules
from quantlab.synthetic import generator

SAMPLE_EVERY = 20  # sample ~every 20th truncation point for speed


def _as_tuples(events):
    return [(e.date, e.direction, e.trigger_values, e.data_window_end) for e in events]


def test_truncation_sweep_all_rules_all_instruments():
    universe = generator.generate_universe()
    rules = list_rules()
    assert rules, "no signal rules registered"
    min_lookback = min(rule.lookback_days for rule in rules)

    for symbol, bars in universe.items():
        full_run = {rule.name: rule.compute(bars, **rule.params) for rule in rules}
        for k in range(min_lookback, len(bars) + 1, SAMPLE_EVERY):
            truncated = bars[:k]
            last_date = truncated[-1].date
            for rule in rules:
                events = rule.compute(truncated, **rule.params)
                expected = [e for e in full_run[rule.name] if e.date <= last_date]
                assert _as_tuples(events) == _as_tuples(expected), (
                    f"{rule.name} on {symbol} diverged at truncation {last_date}"
                )
                for event in events:
                    assert event.data_window_end <= last_date


# --- Parameter-overridden runs (feature 005) --------------------------------
#
# Overrides are a new execution path this sweep has never covered, and they
# change lookback behaviour (a longer window reaches further back). Causality
# must hold for the parameters a researcher actually chooses, not only for the
# defaults the rule shipped with.

#: Non-default configurations per rule, chosen to sit well away from the
#: registered defaults in both directions.
OVERRIDE_CASES: dict[str, list[dict]] = {
    "sma-crossover": [{"fast": 5, "slow": 12}, {"fast": 30, "slow": 90}],
    "rsi-threshold": [{"period": 5, "overbought": 60, "oversold": 40}, {"period": 30}],
    "breakout-20d": [{"window": 5}, {"window": 60}],
}


def test_truncation_sweep_under_parameter_overrides():
    universe = generator.generate_universe()
    rules = {rule.name: rule for rule in list_rules()}

    # Two instruments is enough signal for a causality property while keeping
    # the sweep fast; the default sweep already covers the full universe.
    sample_symbols = sorted(universe)[:2]

    for rule_name, cases in OVERRIDE_CASES.items():
        rule = rules.get(rule_name)
        if rule is None:  # pragma: no cover - rule removed
            continue
        for overrides in cases:
            effective = rule.effective_params(overrides)
            for symbol in sample_symbols:
                bars = universe[symbol]
                full_run = rule.compute(bars, **effective)
                for k in range(rule.lookback_days, len(bars) + 1, SAMPLE_EVERY):
                    truncated = bars[:k]
                    last_date = truncated[-1].date
                    events = rule.compute(truncated, **effective)
                    expected = [e for e in full_run if e.date <= last_date]
                    assert _as_tuples(events) == _as_tuples(expected), (
                        f"{rule_name} with {overrides} on {symbol} diverged at {last_date}"
                    )
                    for event in events:
                        assert event.data_window_end <= last_date, (
                            f"{rule_name} with {overrides} used a bar after the signal date"
                        )
