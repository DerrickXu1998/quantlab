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
