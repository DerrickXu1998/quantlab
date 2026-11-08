"""The pure portfolio allocator: every expected number here is worked by hand."""

from __future__ import annotations

import math

import pytest

from quantlab.execution.allocation import (
    SCORE_KEY,
    AllocationSignal,
    RebalancePlan,
    TargetWeights,
    cap_and_redistribute,
    plan_rebalance,
    signal_score,
    target_weights,
)


def sig(symbol: str, direction: int = 1, score: float = 1.0, vol: float | None = None):
    return AllocationSignal(symbol=symbol, direction=direction, score=score, volatility=vol)


def approx(d: dict[str, float]):
    return pytest.approx(d, abs=1e-12)


# --- signal_score -----------------------------------------------------------


def test_score_key_is_reserved_underscore_name():
    assert SCORE_KEY == "_score"


def test_signal_score_absent_is_full_conviction():
    assert signal_score({}) == 1.0
    assert signal_score({"_logic": "all", "rsi": 28.0}) == 1.0


@pytest.mark.parametrize("value", [1.0, 0.5, 1, 1e-9])
def test_signal_score_valid(value):
    assert signal_score({SCORE_KEY: value}) == float(value)
    assert isinstance(signal_score({SCORE_KEY: value}), float)


@pytest.mark.parametrize(
    "value",
    [math.nan, math.inf, -math.inf, 0, 0.0, -0.5, 1.0000001, 2, "0.5", None, True, [0.5]],
)
def test_signal_score_invalid_is_none(value):
    assert signal_score({SCORE_KEY: value}) is None


# --- the three formulas -----------------------------------------------------


def test_equal_active_signed_normalisation():
    # raw = sign -> (+1, +1, -1); sum|raw| = 3; exposure 0.9 -> 0.3 each.
    result = target_weights(
        [sig("A"), sig("B", score=0.2), sig("C", -1, 0.7)],
        mode="equal_active",
        target_exposure=0.9,
    )
    assert isinstance(result, TargetWeights)
    assert result.weights == approx({"A": 0.3, "B": 0.3, "C": -0.3})
    assert result.selected == ("A", "C", "B")  # by (-score, symbol)
    assert result.excluded == {}


def test_signal_strength_hand_calculated():
    # raw = sign*score -> A 1.0, B -0.5, C 0.5; sum|raw| = 2.0; exposure 1.0.
    result = target_weights(
        [sig("A", 1, 1.0), sig("B", -1, 0.5), sig("C", 1, 0.5)],
        mode="signal_strength",
        target_exposure=1.0,
    )
    assert result.weights == approx({"A": 0.5, "B": -0.25, "C": 0.25})
    assert sum(abs(w) for w in result.weights.values()) == pytest.approx(1.0)
    assert result.selected == ("A", "B", "C")


def test_signal_inverse_volatility_hand_calculated():
    # raw = sign*score/vol -> A 1/0.2=5, B -(0.5/0.1)=-5, C 0.6/0.3=2.
    # sum|raw| = 12; exposure 0.6 -> A 0.25, B -0.25, C 0.1.
    result = target_weights(
        [sig("A", 1, 1.0, 0.2), sig("B", -1, 0.5, 0.1), sig("C", 1, 0.6, 0.3)],
        mode="signal_inverse_volatility",
        target_exposure=0.6,
    )
    assert result.weights == approx({"A": 0.25, "B": -0.25, "C": 0.1})
    assert result.selected == ("A", "C", "B")


def test_single_signal_takes_full_exposure():
    result = target_weights([sig("A", -1, 0.3)], mode="signal_strength", target_exposure=0.8)
    assert result.weights == approx({"A": -0.8})


def test_empty_input():
    for mode in ("equal_active", "signal_strength", "signal_inverse_volatility"):
        result = target_weights([], mode=mode, target_exposure=1.0, max_positions=3)
        assert result == TargetWeights(weights={}, selected=(), excluded={})


def test_zero_exposure_gives_zero_weights():
    result = target_weights([sig("A"), sig("B")], mode="equal_active", target_exposure=0.0)
    assert result.weights == {"A": 0.0, "B": 0.0}


# --- eligibility ------------------------------------------------------------


def test_min_score_excludes_below_and_keeps_equal():
    result = target_weights(
        [sig("A", score=0.4), sig("B", score=0.5), sig("C", score=1.0)],
        mode="signal_strength",
        target_exposure=1.0,
        min_score=0.5,
    )
    assert result.excluded == {"A": "min_score"}
    # B 0.5, C 1.0 -> sum 1.5 -> B 1/3, C 2/3.
    assert result.weights == approx({"C": 2 / 3, "B": 1 / 3})


@pytest.mark.parametrize("score", [math.nan, 0.0, -0.1, 1.5, math.inf])
def test_invalid_score_excluded(score):
    result = target_weights(
        [sig("A", score=score), sig("B")], mode="equal_active", target_exposure=1.0
    )
    assert result.excluded == {"A": "invalid_score"}
    assert result.weights == approx({"B": 1.0})


def test_invalid_score_wins_over_min_score():
    result = target_weights(
        [sig("A", score=math.nan)], mode="equal_active", target_exposure=1.0, min_score=0.5
    )
    assert result.excluded == {"A": "invalid_score"}


@pytest.mark.parametrize("vol", [None, math.nan, math.inf, 0.0, -0.2])
def test_inverse_volatility_needs_finite_positive_vol(vol):
    result = target_weights(
        [sig("A", vol=vol), sig("B", vol=0.25)],
        mode="signal_inverse_volatility",
        target_exposure=1.0,
    )
    assert result.excluded == {"A": "no_volatility"}
    assert result.weights == approx({"B": 1.0})


@pytest.mark.parametrize("mode", ["equal_active", "signal_strength"])
def test_volatility_ignored_outside_inverse_mode(mode):
    result = target_weights(
        [sig("A", vol=None), sig("B", vol=math.nan)], mode=mode, target_exposure=1.0
    )
    assert result.excluded == {}
    assert result.weights == approx({"A": 0.5, "B": 0.5})


# --- top-N ------------------------------------------------------------------


def test_max_positions_keeps_top_scores_with_symbol_tie_break():
    signals = [sig("A", score=0.5), sig("C", score=0.8), sig("B", score=0.8), sig("D", score=0.3)]
    result = target_weights(signals, mode="signal_strength", target_exposure=1.0, max_positions=2)
    assert result.selected == ("B", "C")
    assert result.excluded == {"A": "max_positions", "D": "max_positions"}
    assert result.weights == approx({"B": 0.5, "C": 0.5})

    one = target_weights(signals, mode="equal_active", target_exposure=1.0, max_positions=1)
    assert one.selected == ("B",)  # tie at 0.8 broken by symbol
    assert one.weights == approx({"B": 1.0})


def test_max_positions_selects_before_normalisation_and_after_eligibility():
    # A is ineligible and must not take a slot; top-2 of the rest are C, B.
    result = target_weights(
        [
            sig("A", score=0.9, vol=None),
            sig("B", 1, 0.5, 0.1),
            sig("C", -1, 1.0, 0.4),
            sig("D", 1, 0.2, 0.1),
        ],
        mode="signal_inverse_volatility",
        target_exposure=1.0,
        max_positions=2,
    )
    assert result.excluded == {"A": "no_volatility", "D": "max_positions"}
    # raw C -1.0/0.4 = -2.5, B 0.5/0.1 = 5 -> sum 7.5.
    assert result.weights == approx({"C": -2.5 / 7.5, "B": 5 / 7.5})


def test_max_positions_zero_selects_nothing():
    result = target_weights([sig("A")], mode="equal_active", target_exposure=1.0, max_positions=0)
    assert result.weights == {}
    assert result.excluded == {"A": "max_positions"}


# --- caps -------------------------------------------------------------------


def test_cap_redistributes_to_uncapped_names():
    # raw 1.0, 0.6, 0.4 -> 0.5, 0.3, 0.2; cap 0.4 pins A, 0.6 left split 0.6:0.4.
    result = target_weights(
        [sig("A", score=1.0), sig("B", -1, 0.6), sig("C", score=0.4)],
        mode="signal_strength",
        target_exposure=1.0,
        max_position_pct=0.4,
    )
    assert result.weights == approx({"A": 0.4, "B": -0.36, "C": 0.24})


def test_cap_and_redistribute_cascades():
    # Round 1: 0.5, 0.25, 0.125, 0.125 -> A pinned at 0.3.
    # Round 2: 0.7 over raw 1.0 -> B 0.35 > 0.3, pinned.
    # Round 3: 0.4 over raw 0.5 -> C 0.2, D 0.2.
    out = cap_and_redistribute({"D": 0.25, "A": 1.0, "C": 0.25, "B": 0.5}, total=1.0, cap=0.3)
    assert out == approx({"A": 0.3, "B": 0.3, "C": 0.2, "D": 0.2})
    assert list(out) == ["A", "B", "C", "D"]


def test_cap_infeasible_leaves_residual_cash():
    out = cap_and_redistribute({"A": 3.0, "B": 2.0, "C": 1.0}, total=1.0, cap=0.25)
    assert out == {"A": 0.25, "B": 0.25, "C": 0.25}
    assert sum(out.values()) == pytest.approx(0.75)  # 0.25 stays in cash

    result = target_weights(
        [sig("A"), sig("B", -1), sig("C")],
        mode="equal_active",
        target_exposure=1.0,
        max_position_pct=0.2,
    )
    assert result.weights == approx({"A": 0.2, "B": -0.2, "C": 0.2})


def test_cap_not_binding_is_identity():
    assert cap_and_redistribute({"A": 1.0, "B": 3.0}, total=0.8, cap=1.0) == approx(
        {"A": 0.2, "B": 0.6}
    )


def test_cap_and_redistribute_edges():
    assert cap_and_redistribute({}, total=1.0, cap=0.5) == {}
    assert cap_and_redistribute({"A": 0.0, "B": 0.0}, total=1.0, cap=0.5) == {"A": 0.0, "B": 0.0}
    assert cap_and_redistribute({"A": 0.0, "B": 2.0}, total=1.0, cap=0.5) == {"A": 0.0, "B": 0.5}
    with pytest.raises(ValueError, match="raw"):
        cap_and_redistribute({"A": -1.0}, total=1.0, cap=0.5)
    with pytest.raises(ValueError, match="raw"):
        cap_and_redistribute({"A": math.nan}, total=1.0, cap=0.5)


# --- validation -------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"mode": "equal_weight"}, "position_sizing"),
        ({"target_exposure": -0.1}, "target_exposure"),
        ({"target_exposure": math.nan}, "target_exposure"),
        ({"max_position_pct": 0.0}, "max_position_pct"),
        ({"max_positions": -1}, "max_positions"),
    ],
)
def test_target_weights_rejects_bad_arguments(kwargs, field):
    args = {"mode": "equal_active", "target_exposure": 1.0} | kwargs
    with pytest.raises(ValueError, match=field):
        target_weights([sig("A")], **args)


def test_target_weights_rejects_bad_signals():
    with pytest.raises(ValueError, match="direction"):
        target_weights([sig("A", direction=0)], mode="equal_active", target_exposure=1.0)
    with pytest.raises(ValueError, match="symbol"):
        target_weights([sig("A"), sig("A")], mode="equal_active", target_exposure=1.0)


def test_target_weights_is_order_independent():
    signals = [sig("A", 1, 0.3), sig("B", -1, 0.9), sig("C", 1, 0.6), sig("D", 1, 0.6)]
    forward = target_weights(
        signals, mode="signal_strength", target_exposure=1.0, max_position_pct=0.35
    )
    backward = target_weights(
        list(reversed(signals)), mode="signal_strength", target_exposure=1.0, max_position_pct=0.35
    )
    assert forward == backward
    assert list(forward.weights) == list(backward.weights) == ["B", "C", "D", "A"]


def test_numpy_scalars_are_numbers():
    np = pytest.importorskip("numpy")
    assert signal_score({SCORE_KEY: np.float32(0.5)}) == 0.5
    result = target_weights(
        [sig("A", 1, np.float64(1.0), np.float32(0.5)), sig("B", -1, 1.0, np.float64(0.25))],
        mode="signal_inverse_volatility",
        target_exposure=1.0,
    )
    # raw A 2, B -4 -> sum 6.
    assert result.weights == approx({"B": -4 / 6, "A": 2 / 6})


def test_tiny_volatility_is_excluded_not_an_error():
    # 1.0 / 1e-320 overflows to inf: treated as no usable volatility.
    result = target_weights(
        [sig("A", vol=1e-320), sig("B", vol=0.2)],
        mode="signal_inverse_volatility",
        target_exposure=1.0,
    )
    assert result.excluded == {"A": "no_volatility"}
    assert result.weights == approx({"B": 1.0})


def test_huge_finite_raws_do_not_overflow():
    out = cap_and_redistribute({"A": 1e308, "B": 1e308}, total=1.0, cap=1.0)
    assert out == approx({"A": 0.5, "B": 0.5})


def test_short_with_zero_exposure_is_plain_zero():
    result = target_weights([sig("A", -1)], mode="equal_active", target_exposure=0.0)
    assert math.copysign(1.0, result.weights["A"]) == 1.0


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"min_score": math.nan}, "min_allocation_score"),
        ({"min_score": 1.5}, "min_allocation_score"),
        ({"min_score": -0.1}, "min_allocation_score"),
        ({"max_positions": 2.0}, "max_positions"),
        ({"max_positions": True}, "max_positions"),
    ],
)
def test_target_weights_rejects_bad_filters(kwargs, field):
    with pytest.raises(ValueError, match=field):
        target_weights([sig("A")], mode="equal_active", target_exposure=1.0, **kwargs)


def test_bool_direction_rejected():
    with pytest.raises(ValueError, match="direction"):
        target_weights([sig("A", direction=True)], mode="equal_active", target_exposure=1.0)


# --- plan_rebalance ---------------------------------------------------------

CURRENT = {"A": 0.3, "B": 0.2, "C": 0.1}
TARGET = {"A": 0.32, "B": 0.1, "D": 0.2}  # C held but absent -> target 0


def test_plan_trades_every_change_by_default():
    plan = plan_rebalance(CURRENT, TARGET)
    assert isinstance(plan, RebalancePlan)
    assert plan.targets == {"A": 0.32, "B": 0.1, "C": 0.0, "D": 0.2}
    assert plan.skipped == ()
    assert plan.turnover_scale == 1.0


def test_plan_omits_unchanged_symbols():
    plan = plan_rebalance({"A": 0.5, "B": 0.2}, {"A": 0.5, "B": 0.3})
    assert plan.targets == {"B": 0.3}
    assert plan.skipped == ()


def test_plan_drift_threshold_skips_small_changes():
    # A moves 0.02 < 0.05 -> skipped; B -0.1, C -0.1, D +0.2 all trade.
    plan = plan_rebalance(CURRENT, TARGET, threshold=0.05)
    assert plan.targets == {"B": 0.1, "C": 0.0, "D": 0.2}
    assert plan.skipped == ("A",)
    # Exactly at the threshold is not "below" it.
    assert plan_rebalance({"A": 0.0}, {"A": 0.25}, threshold=0.25).targets == {"A": 0.25}


def test_plan_turnover_cap_scales_discretionary_changes():
    # After threshold: turnover = 0.1 + 0.1 + 0.2 = 0.4 > 0.2 -> scale 0.5.
    plan = plan_rebalance(CURRENT, TARGET, threshold=0.05, max_turnover=0.2)
    assert plan.turnover_scale == pytest.approx(0.5)
    assert plan.targets == approx({"B": 0.15, "C": 0.05, "D": 0.1})
    assert plan.skipped == ("A",)


def test_plan_turnover_within_cap_is_unscaled():
    plan = plan_rebalance(CURRENT, TARGET, max_turnover=1.0)
    assert plan.turnover_scale == 1.0
    assert plan.targets == {"A": 0.32, "B": 0.1, "C": 0.0, "D": 0.2}


def test_plan_zero_turnover_cap_trades_only_mandatory():
    plan = plan_rebalance(CURRENT, TARGET, max_turnover=0.0, mandatory={"C"})
    assert plan.turnover_scale == 0.0
    assert plan.targets == {"C": 0.0}


def test_plan_mandatory_exempt_from_threshold_and_turnover():
    # A and C mandatory: both trade in full (A's 0.02 change despite threshold
    # 0.15) and stay out of the turnover sum. Discretionary: B's 0.1 < 0.15 is
    # skipped; D 0.2 -> turnover 0.2 > 0.1 -> scale 0.5.
    plan = plan_rebalance(CURRENT, TARGET, threshold=0.15, max_turnover=0.1, mandatory=("C", "A"))
    assert plan.skipped == ("B",)
    assert plan.turnover_scale == pytest.approx(0.5)
    assert plan.targets == approx({"A": 0.32, "C": 0.0, "D": 0.1})

    # Only C mandatory: discretionary turnover B 0.1 + D 0.2 = 0.3 > 0.2 ->
    # scale 2/3; A still skipped by the 0.05 threshold.
    plan = plan_rebalance(CURRENT, TARGET, threshold=0.05, max_turnover=0.2, mandatory={"C"})
    assert plan.turnover_scale == pytest.approx(2 / 3)
    assert plan.targets == approx({"B": 0.2 - 0.1 * 2 / 3, "C": 0.0, "D": 0.2 * 2 / 3})
    assert plan.skipped == ("A",)


def test_plan_mandatory_symbol_without_change_is_ignored():
    plan = plan_rebalance({"A": 0.5}, {"A": 0.5}, mandatory={"A", "Z"})
    assert plan.targets == {}


def test_plan_handles_shorts_and_reversals():
    plan = plan_rebalance({"A": 0.2, "B": -0.3}, {"A": -0.2, "B": -0.1}, max_turnover=0.3)
    # turnover = 0.4 + 0.2 = 0.6 -> scale 0.5 -> A 0.0, B -0.2.
    assert plan.turnover_scale == pytest.approx(0.5)
    assert plan.targets == approx({"A": 0.0, "B": -0.2})


def test_plan_empty_and_validation():
    assert plan_rebalance({}, {}) == RebalancePlan(targets={}, skipped=(), turnover_scale=1.0)
    with pytest.raises(ValueError, match="rebalance_threshold"):
        plan_rebalance({}, {}, threshold=-0.1)
    with pytest.raises(ValueError, match="max_turnover"):
        plan_rebalance({}, {}, max_turnover=math.nan)


def test_module_stays_pure():
    import quantlab.execution.allocation as module

    source = open(module.__file__, encoding="utf-8").read()
    # No storage, API, engine or config: the allocator imports nothing from quantlab.
    assert "from quantlab" not in source
    assert "import quantlab" not in source
