"""Template interpreter tests (feature 008, M2): semantics, lookback
derivation, config validation, and the differential guard that a custom rule
recreating a builtin produces identical signals."""

from __future__ import annotations

import pytest

from quantlab import config as app_config
from quantlab.signals import builtins as _builtins  # noqa: F401 (registers builtins)
from quantlab.signals import templates
from quantlab.signals.registry import get_rule
from quantlab.synthetic.generator import Bar, generate_universe


def make_bars(closes):
    calendar = app_config.trading_calendar()
    return [
        Bar(calendar[i].isoformat(), c, c, c, c, 1000) for i, c in enumerate(closes)
    ]


def rule(template_id, config):
    return templates.rule_from_definition(template_id, config, name="test-rule")


# --- indicator-threshold -------------------------------------------------------


def test_threshold_crosses_above_fires_on_the_step():
    r = rule(
        "indicator-threshold",
        {
            "input": {"source": "close"},
            "comparator": "crosses_above",
            "threshold": 102.0,
            "bullish_on": "above",
        },
    )
    events = r.compute(make_bars([100.0] * 5 + [105.0]))
    assert [(e.direction, e.trigger_values["value"]) for e in events] == [("bullish", 105.0)]
    assert events[0].data_window_end == events[0].date


def test_threshold_direction_follows_bullish_on():
    config = {
        "input": {"source": "close"},
        "comparator": "crosses_above",
        "threshold": 102.0,
        "bullish_on": "below",
    }
    events = rule("indicator-threshold", config).compute(make_bars([100.0] * 5 + [105.0]))
    assert [e.direction for e in events] == ["bearish"]


def test_enters_zone_only_fires_entering_the_watched_side():
    config = {
        "input": {"source": "close"},
        "comparator": "enters_zone",
        "threshold": 100.0,
        "bullish_on": "above",
    }
    bars = make_bars([100.0, 101.0, 99.0, 100.5, 98.0])
    events = rule("indicator-threshold", config).compute(bars)
    # Up-crosses into the above zone on days 2 and 4; the drops out are not
    # this comparator's business.
    assert [e.direction for e in events] == ["bullish", "bullish"]
    assert [e.date for e in events] == [bars[1].date, bars[3].date]


def test_exits_zone_boundary_matches_the_builtin_convention():
    """Exiting the low zone is `prev < t and curr >= t` exactly -- a landing
    precisely on the threshold is an exit, not a cross."""
    config = {
        "input": {"source": "close"},
        "comparator": "exits_zone",
        "threshold": 30.0,
        "bullish_on": "below",
    }
    bars = make_bars([29.0, 30.0, 29.0, 30.0])
    events = rule("indicator-threshold", config).compute(bars)
    assert [(e.date, e.direction) for e in events] == [
        (bars[1].date, "bullish"),
        (bars[3].date, "bullish"),
    ]


def test_threshold_pct_change_transform_shifts_warmup():
    config = {
        "input": {"source": "indicator", "indicator": "sma", "params": {"window": 5}},
        "transform": "pct_change",
        "transform_window": 2,
        "comparator": "crosses_above",
        "threshold": 0.0,
        "bullish_on": "above",
    }
    r = rule("indicator-threshold", config)
    # first defined: sma(5) at index 4, pct_change(2) pushes to 6; first cross
    # at 7, so lookback 8 -- and nothing on fewer bars.
    assert r.lookback_days == 8
    assert r.compute(make_bars([100.0] * 7)) == []


def test_threshold_on_rsi_is_scale_free_and_on_close_is_price_scaled():
    base = {"comparator": "crosses_above", "threshold": 1.0, "bullish_on": "above"}
    rsi_rule = rule(
        "indicator-threshold",
        {**base, "input": {"source": "indicator", "indicator": "rsi", "params": {"period": 14}}},
    )
    close_rule = rule("indicator-threshold", {**base, "input": {"source": "close"}})
    assert rsi_rule.scale_class == "scale_free"
    assert close_rule.scale_class == "price_scaled"


# --- indicator-crossover ---------------------------------------------------------


def test_crossover_matches_sma_crossover_semantics():
    """close vs sma(3) on a decline-then-rise series: same cross rule as the
    sma-crossover builtin (prev diff <= 0 < diff)."""
    closes = [10.0, 9.0, 8.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    bars = make_bars(closes)
    r = rule(
        "indicator-crossover",
        {"a": {"kind": "close"}, "b": {"kind": "sma", "params": {"window": 3}}},
    )
    events = r.compute(bars)
    assert [e.direction for e in events] == ["bullish"]
    # Index 4: close 8.0 vs sma(3) 7.667; prev diff -1.0 <= 0 < +0.333.
    assert events[0].date == bars[4].date
    assert events[0].trigger_values["a"] == 8.0


def test_crossover_lookback_is_derived_from_the_slower_operand():
    r = rule(
        "indicator-crossover",
        {
            "a": {"kind": "sma", "params": {"window": 20}},
            "b": {"kind": "sma", "params": {"window": 50}},
        },
    )
    assert r.lookback_days == 51  # sma-crossover@1.0.0's own declaration


def test_crossover_rejects_unknown_operands_and_bad_params():
    with pytest.raises(ValueError, match="a.kind"):
        templates.get_template("indicator-crossover").validate(
            {"a": {"kind": "vwap"}, "b": {"kind": "close"}}
        )
    with pytest.raises(ValueError, match="window"):
        templates.get_template("indicator-crossover").validate(
            {"a": {"kind": "sma", "params": {"window": 1}}, "b": {"kind": "close"}}
        )


# --- Validation: indicator-threshold ---------------------------------------------


def test_threshold_validation_names_the_field():
    template = templates.get_template("indicator-threshold")
    with pytest.raises(ValueError, match="comparator"):
        template.validate(
            {
                "input": {"source": "close"},
                "comparator": "touches",
                "threshold": 1,
                "bullish_on": "above",
            }
        )
    with pytest.raises(ValueError, match="input.indicator"):
        template.validate(
            {
                "input": {"source": "indicator", "indicator": "macd"},
                "comparator": "crosses_above",
                "threshold": 1,
                "bullish_on": "above",
            }
        )
    with pytest.raises(ValueError, match="threshold"):
        template.validate(
            {"input": {"source": "close"}, "comparator": "crosses_above", "bullish_on": "above"}
        )


# --- The differential guard --------------------------------------------------------


def test_custom_rules_recreate_rsi_threshold_exactly():
    """The merger gate: two template instances (exits_zone 70/above -> bearish,
    exits_zone 30/below -> bullish) must reproduce rsi-threshold@1.0.0's
    signals date-for-date on the same history."""
    builtin = get_rule("rsi-threshold", "1.0.0")
    overbought = rule(
        "indicator-threshold",
        {
            "input": {"source": "indicator", "indicator": "rsi", "params": {"period": 14}},
            "comparator": "exits_zone",
            "threshold": 70.0,
            "bullish_on": "above",
        },
    )
    oversold = rule(
        "indicator-threshold",
        {
            "input": {"source": "indicator", "indicator": "rsi", "params": {"period": 14}},
            "comparator": "exits_zone",
            "threshold": 30.0,
            "bullish_on": "below",
        },
    )
    assert overbought.lookback_days == builtin.lookback_days == 16

    universe = generate_universe()
    for symbol in sorted(universe)[:3]:
        bars = universe[symbol]
        expected = sorted(
            (e.date, e.direction) for e in builtin.compute(bars, **builtin.params)
        )
        custom = sorted(
            (e.date, e.direction)
            for r in (overbought, oversold)
            for e in r.compute(bars)
        )
        assert custom == expected, f"custom rsi-threshold diverged on {symbol}"
        assert expected, "the universe sample must exercise both rules"


def test_unknown_template_is_a_key_error():
    with pytest.raises(KeyError, match="unknown signal template"):
        templates.get_template("nope")
