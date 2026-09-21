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
    "macd-crossover": [{"fast": 5, "slow": 12, "signal": 4}, {"fast": 8, "slow": 21, "signal": 5}],
    "bollinger-breakout": [{"window": 10, "num_std": 1.5}, {"window": 40, "num_std": 3.0}],
    "bollinger-mean-reversion": [{"window": 10, "num_std": 2.5}, {"window": 40, "num_std": 1.0}],
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


# --- Template-based custom rules (feature 008, M2) ------------------------------
#
# Custom rules are templates plus configs; the same causality gate that covers
# the builtins must cover the interpreters users compose with. One
# representative config per template shape, plus pct_change and composed
# operands (macd_line, bollinger), swept exactly like the builtins.

from quantlab.signals import templates  # noqa: E402

TEMPLATE_CASES: list[tuple[str, dict]] = [
    (
        "indicator-threshold",
        {
            "input": {"source": "indicator", "indicator": "rsi", "params": {"period": 14}},
            "comparator": "exits_zone",
            "threshold": 70,
            "bullish_on": "above",
        },
    ),
    (
        "indicator-threshold",
        {
            "input": {"source": "indicator", "indicator": "sma", "params": {"window": 20}},
            "transform": "pct_change",
            "transform_window": 5,
            "comparator": "crosses_above",
            "threshold": 0.0,
            "bullish_on": "above",
        },
    ),
    (
        "indicator-threshold",
        {
            "input": {"source": "close"},
            "comparator": "enters_zone",
            "threshold": 100.0,
            "bullish_on": "below",
        },
    ),
    (
        "indicator-crossover",
        {
            "a": {"kind": "sma", "params": {"window": 5}},
            "b": {"kind": "sma", "params": {"window": 20}},
        },
    ),
    (
        "indicator-crossover",
        {
            "a": {"kind": "macd_line", "params": {"fast": 5, "slow": 12}},
            "b": {"kind": "ema", "params": {"window": 9}},
        },
    ),
    (
        "indicator-crossover",
        {
            "a": {"kind": "close"},
            "b": {"kind": "bollinger_upper", "params": {"window": 20, "num_std": 2.0}},
        },
    ),
]


def test_truncation_sweep_custom_rule_templates():
    universe = generator.generate_universe()
    sample_symbols = sorted(universe)[:2]

    for template_id, template_config in TEMPLATE_CASES:
        rule = templates.rule_from_definition(template_id, dict(template_config), name="sweep")
        for symbol in sample_symbols:
            bars = universe[symbol]
            full_run = rule.compute(bars)
            for k in range(rule.lookback_days, len(bars) + 1, SAMPLE_EVERY):
                truncated = bars[:k]
                last_date = truncated[-1].date
                events = rule.compute(truncated)
                expected = [e for e in full_run if e.date <= last_date]
                assert _as_tuples(events) == _as_tuples(expected), (
                    f"template {template_id} on {symbol} diverged at truncation {last_date}"
                )
                for event in events:
                    assert event.data_window_end <= last_date


# --- Fundamental templates (feature 008, M3) --------------------------------------
#
# A fundamental rule's compared series is built from filings, not bars, so the
# sweep runs on both axes: truncating FACTS at filed_at <= T must reproduce
# exactly the signals dated <= T, and truncating bars must change nothing at
# all (the interpreter reads no bar content).


def _fundamental_facts_fixture():
    def fact(value, filed_at, period_end, holder=None, provider="sec_edgar"):
        return {
            "value": float(value),
            "period_start": None,
            "period_end": period_end,
            "filed_at": filed_at,
            "provider": provider,
            "unit": "USD" if provider != "fca" else "pct",
            "holder": holder,
        }

    return [
        # Annual revenue filings, one of them restated later.
        fact(100.0, "2020-02-07", "2019-12-31"),
        fact(100.0, "2021-02-05", "2020-12-31"),
        fact(90.0, "2022-02-04", "2021-12-31"),
        fact(92.0, "2022-03-15", "2021-12-31"),  # restatement supersedes
        fact(110.0, "2023-02-03", "2022-12-31"),
        fact(80.0, "2024-02-02", "2023-12-31"),
        # Per-holder FCA short positions.
        fact(0.5, "2024-01-10", "2024-01-08", holder="A", provider="fca"),
        fact(1.0, "2024-01-12", "2024-01-10", holder="B", provider="fca"),
        fact(0.2, "2024-03-01", "2024-02-28", holder="A", provider="fca"),
    ]


FUNDAMENTAL_CASES: list[tuple[str, dict]] = [
    (
        "fundamental-condition",
        {
            "concept": "revenue",
            "transform": "yoy_growth",
            "comparator": "crosses_above",
            "threshold": 0.0,
            "bullish_on": "above",
        },
    ),
    (
        "fundamental-condition",
        {
            "concept": "revenue",
            "transform": "level",
            "comparator": "crosses_below",
            "threshold": 95.0,
            "bullish_on": "above",
        },
    ),
    (
        "fundamental-condition",
        {
            "concept": "net_short_position",
            "transform": "level",
            "comparator": "crosses_above",
            "threshold": 1.2,
            "bullish_on": "above",
        },
    ),
]


def test_truncation_sweep_fundamental_templates():
    facts = _fundamental_facts_fixture()
    universe = generator.generate_universe()
    bars = universe[sorted(universe)[0]]

    for template_id, template_config in FUNDAMENTAL_CASES:
        rule = templates.rule_from_definition(template_id, dict(template_config), name="sweep-f")
        concept = template_config["concept"]
        selected = [
            f
            for f in facts
            if f["provider"] == ("fca" if concept == "net_short_position" else "sec_edgar")
        ]
        full_run = rule.compute(bars, selected)
        assert full_run, f"{template_id}/{concept} must fire on the fixture"

        # Facts truncated at T reproduce exactly the signals dated <= T.
        cutoff_dates = sorted({f["filed_at"] for f in selected})
        for cutoff in cutoff_dates:
            truncated = [f for f in selected if f["filed_at"] <= cutoff]
            events = rule.compute(bars, truncated)
            expected = [e for e in full_run if e.date <= cutoff]
            assert _as_tuples(events) == _as_tuples(expected), (
                f"{template_id}/{concept} diverged at facts cutoff {cutoff}"
            )

        # Bars carry no information for this interpreter: any truncation of the
        # bar history yields the identical signal set.
        for k in range(1, len(bars) + 1, SAMPLE_EVERY):
            assert _as_tuples(rule.compute(bars[:k], selected)) == _as_tuples(full_run)

        for event in full_run:
            assert event.data_window_end <= event.date
