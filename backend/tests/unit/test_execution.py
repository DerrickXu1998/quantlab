"""The execution engine: sizing, costs, stops, timing, and what it refuses.

Reference values, not eyeballed ones. Every expected number below is either
hand-computed in the test itself or is the output of the code this engine
replaced -- the parity suite at the bottom is the important one, because the
promise made when execution criteria were introduced was that a run configured
the old way still produces the old answer.
"""

from __future__ import annotations

import re

import pytest

from quantlab.execution import (
    ALLOCATION_SIZING,
    EXIT_REASONS,
    POSITION_SIZING,
    REBALANCE_FREQUENCY,
    AllocationSettings,
    Decision,
    ExecutionConfig,
    ExecutionSimulator,
    simulate,
)
from quantlab.research import performance
from quantlab.signals.registry import get_rule
from quantlab.synthetic.generator import Bar


def idealized_config(**kwargs):
    settings = {
        "fill_timing": "signal_close", "commission_bps": 0.0,
        "slippage_bps": 0.0, "max_volume_participation": None,
    }
    settings.update(kwargs)
    return ExecutionConfig(**settings)


def bars(prices, *, high=None, low=None, opens=None):
    """Bars from a close series; high/low default to +/-1% of the close."""
    out = []
    for i, close in enumerate(prices):
        out.append(
            Bar(
                date=f"d{i:03d}",
                open=float(opens[i]) if opens else float(close),
                high=float(high[i]) if high else float(close) * 1.01,
                low=float(low[i]) if low else float(close) * 0.99,
                close=float(close),
                volume=1_000,
            )
        )
    return out


def decision(date, kind, direction, symbol="AAA", *, trigger_values=None):
    return Decision(
        date=date, symbol=symbol, kind=kind, direction=direction,
        trigger_values=dict(trigger_values or {}), data_window_end=date,
    )


# --- sizing -----------------------------------------------------------------


def test_new_runs_default_to_next_open_and_base_costs():
    config = ExecutionConfig()
    assert config.fill_timing == "next_open"
    assert config.commission_bps == 1.0
    assert config.slippage_bps == 5.0
    assert config.max_volume_participation == 0.01
    assert config.order_expiry_days == 5


def test_equal_weight_splits_capital_into_one_sleeve_per_instrument():
    """100k across four names is a 25k sleeve; a trade uses the whole sleeve."""
    series = {s: bars([100.0] * 5) for s in ("AAA", "BBB", "CCC", "DDD")}
    result = simulate(
        ["AAA", "BBB", "CCC", "DDD"],
        series,
        [decision("d001", "entry", "bullish")],
        idealized_config(),
    )
    trade = result.trades[0]
    assert trade.qty == pytest.approx(250.0)  # 25_000 / 100
    # Buying at a close and marking to that same close moves nothing.
    assert result.equity[1].value == pytest.approx(100_000.0)


def test_fixed_fraction_sizes_against_equity_not_the_sleeve():
    series = {"AAA": bars([100.0] * 5), "BBB": bars([100.0] * 5)}
    result = simulate(
        ["AAA", "BBB"],
        series,
        [decision("d001", "entry", "bullish")],
        idealized_config(position_sizing="fixed_fraction", sizing_value=0.30),
    )
    assert result.trades[0].qty == pytest.approx(300.0)  # 30% of 100_000 / 100


def test_fixed_notional_ignores_book_size():
    series = {"AAA": bars([100.0] * 5)}
    result = simulate(
        ["AAA"],
        series,
        [decision("d001", "entry", "bullish")],
        idealized_config(position_sizing="fixed_notional", sizing_value=7_500.0),
    )
    assert result.trades[0].qty == pytest.approx(75.0)


def test_max_position_pct_caps_a_pooled_position():
    series = {"AAA": bars([100.0] * 5)}
    result = simulate(
        ["AAA"],
        series,
        [decision("d001", "entry", "bullish")],
        idealized_config(
            position_sizing="fixed_fraction", sizing_value=0.90, max_position_pct=0.25
        ),
    )
    assert result.trades[0].qty == pytest.approx(250.0)


def test_max_positions_rejects_the_signal_rather_than_queueing_it():
    series = {s: bars([100.0] * 6) for s in ("AAA", "BBB", "CCC")}
    decisions = [
        decision("d001", "entry", "bullish", symbol) for symbol in ("AAA", "BBB", "CCC")
    ]
    result = simulate(["AAA", "BBB", "CCC"], series, decisions, idealized_config(max_positions=2))
    assert len(result.trades) == 2
    assert result.summary.rejected_max_positions == 1


# --- costs ------------------------------------------------------------------


def test_commission_and_slippage_are_charged_on_both_sides():
    """Hand-computed: 10 bps commission, 5 bps slippage, one round trip."""
    series = {"AAA": bars([100.0, 102.0, 103.0, 104.0])}
    config = idealized_config(commission_bps=10, slippage_bps=5)
    result = simulate(
        ["AAA"],
        series,
        [decision("d001", "entry", "bullish"), decision("d002", "exit", "bearish")],
        config,
    )
    trade = result.trades[0]

    # Slippage moves the price against the trade on each side.
    assert trade.entry_price == pytest.approx(102.0 * 1.0005)
    assert trade.exit_price == pytest.approx(103.0 * 0.9995)

    qty = 100_000.0 / (102.0 * 1.0005)
    assert trade.qty == pytest.approx(qty)

    expected_fees = qty * 102.0 * 1.0005 * 0.001 + qty * 103.0 * 0.9995 * 0.001
    assert trade.fees == pytest.approx(expected_fees)
    assert result.summary.total_commission == pytest.approx(expected_fees)

    gross = qty * (103.0 * 0.9995 - 102.0 * 1.0005)
    assert trade.pnl == pytest.approx(gross - expected_fees)


def test_costs_only_ever_reduce_the_result():
    series = {"AAA": bars([100.0, 105.0, 110.0, 115.0])}
    decisions = [decision("d001", "entry", "bullish"), decision("d003", "exit", "bearish")]
    free = simulate(["AAA"], series, decisions, idealized_config())
    charged = simulate(
        ["AAA"], series, decisions, idealized_config(commission_bps=25, slippage_bps=10)
    )
    assert charged.equity[-1].value < free.equity[-1].value


# --- protective exits -------------------------------------------------------


def test_stop_loss_fills_at_the_stop_when_the_bar_merely_touches_it():
    series = {"AAA": bars([100.0, 100.0, 96.0], low=[99.0, 99.0, 94.0])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        idealized_config(stop_loss_pct=0.05),
    )
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price == pytest.approx(95.0)


def test_stop_fills_at_the_open_when_the_session_gapped_through_it():
    """A gap does not respect your stop; the fill is the open, which is worse."""
    series = {
        "AAA": bars(
            [100.0, 100.0, 80.0], opens=[100.0, 100.0, 80.0], high=[101, 101, 82], low=[99, 99, 78]
        )
    }
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        idealized_config(stop_loss_pct=0.05),
    )
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price == pytest.approx(80.0)


def test_stop_wins_when_a_single_bar_contains_both_stop_and_target():
    """The pessimistic reading, on purpose: a daily bar cannot say which came
    first, and taking the target would flatter every backtest."""
    series = {"AAA": bars([100.0, 100.0], high=[101.0, 120.0], low=[99.0, 90.0])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        idealized_config(stop_loss_pct=0.05, take_profit_pct=0.05),
    )
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.trades[0].exit_price == pytest.approx(95.0)


def test_take_profit_fires_when_no_stop_is_in_range():
    series = {
        "AAA": bars(
            [100.0, 108.0], opens=[100.0, 101.0], high=[101.0, 112.0], low=[99.0, 99.0]
        )
    }
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        idealized_config(take_profit_pct=0.05),
    )
    assert result.trades[0].exit_reason == "take_profit"
    assert result.trades[0].exit_price == pytest.approx(105.0)


def test_a_target_does_not_collect_a_favourable_gap():
    """The session opens far above the target. A live limit order might fill
    there; the backtest takes the target and declines the windfall."""
    series = {
        "AAA": bars(
            [100.0, 130.0], opens=[100.0, 128.0], high=[101.0, 132.0], low=[99.0, 127.0]
        )
    }
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        idealized_config(take_profit_pct=0.05),
    )
    assert result.trades[0].exit_price == pytest.approx(105.0)


def test_trailing_stop_measures_from_the_best_close_not_the_entry():
    # Rises to 120, then falls. A 10% trail from the best close of 120 sits at
    # 108; the final session opens at 119 and trades down through it, so the
    # fill is the trail itself rather than a gapped open.
    series = {
        "AAA": bars(
            [100.0, 110.0, 120.0, 105.0],
            opens=[100.0, 110.0, 120.0, 119.0],
            high=[101.0, 111.0, 121.0, 121.0],
            low=[99.0, 109.0, 119.0, 104.0],
        )
    }
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        idealized_config(trailing_stop_pct=0.10),
    )
    trade = result.trades[0]
    assert trade.exit_reason == "trailing_stop"
    assert trade.exit_price == pytest.approx(108.0)


def test_todays_close_cannot_set_todays_trailing_trigger():
    """The trail advances only after a bar is tested, so a single bar that both
    makes a new high and falls back cannot stop itself out on its own high."""
    series = {"AAA": bars([100.0, 100.0], high=[101.0, 200.0], low=[99.0, 99.5])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        idealized_config(trailing_stop_pct=0.10),
    )
    # Trail is 90 from the entry close of 100, and the low of 99.5 never reaches it.
    assert result.trades[0].open is True


def test_atr_stop_scales_with_the_instruments_own_range():
    prices = [100.0] * 20 + [90.0]
    series = {"AAA": bars(prices, high=[p * 1.02 for p in prices], low=[p * 0.98 for p in prices])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d018", "entry", "bullish")],
        idealized_config(atr_stop_multiple=1.0, atr_period=14),
    )
    assert result.trades[0].exit_reason == "stop_loss"


def test_the_tighter_of_a_percentage_and_an_atr_stop_wins():
    prices = [100.0] * 20 + [97.0]
    series = {"AAA": bars(prices, high=[p * 1.02 for p in prices], low=[p * 0.98 for p in prices])}
    # ATR is about 4 (a 4% range), so a 1x ATR stop sits near 96; a 2% stop sits
    # at 98 and is tighter, so the 98 stop is the one that binds.
    result = simulate(
        ["AAA"],
        series,
        [decision("d018", "entry", "bullish")],
        idealized_config(stop_loss_pct=0.02, atr_stop_multiple=1.0, atr_period=14),
    )
    assert result.trades[0].exit_price == pytest.approx(98.0)


def test_max_holding_days_closes_a_position_that_nothing_else_would():
    series = {"AAA": bars([100.0] * 10)}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        idealized_config(max_holding_days=3),
    )
    trade = result.trades[0]
    assert (trade.exit_reason, trade.exit_date) == ("max_holding", "d003")


def test_min_holding_days_suppresses_a_signal_exit_but_not_a_stop():
    series = {"AAA": bars([100.0, 100.0, 100.0, 100.0])}
    held = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish"), decision("d001", "exit", "bearish")],
        idealized_config(min_holding_days=3),
    )
    assert held.trades[0].open is True

    stopped = simulate(
        ["AAA"],
        {"AAA": bars([100.0, 80.0, 80.0], low=[99.0, 79.0, 79.0])},
        [decision("d000", "entry", "bullish"), decision("d001", "exit", "bearish")],
        idealized_config(min_holding_days=3, stop_loss_pct=0.05),
    )
    assert stopped.trades[0].exit_reason == "stop_loss"


def test_cooldown_blocks_a_re_entry_inside_the_window():
    series = {"AAA": bars([100.0] * 12)}
    decisions = [
        decision("d000", "entry", "bullish"),
        decision("d001", "exit", "bearish"),
        decision("d003", "entry", "bullish"),
    ]
    free = simulate(["AAA"], series, decisions, idealized_config())
    assert len(free.trades) == 2

    cooled = simulate(["AAA"], series, decisions, idealized_config(cooldown_days=5))
    assert len(cooled.trades) == 1
    assert cooled.summary.rejected_cooldown == 1


# --- fill timing ------------------------------------------------------------


def test_next_open_fills_on_the_following_session():
    series = {"AAA": bars([100.0, 102.0, 104.0, 106.0], opens=[100.0, 101.0, 103.0, 105.0])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish"), decision("d002", "exit", "bearish")],
        idealized_config(fill_timing="next_open"),
    )
    trade = result.trades[0]
    assert (trade.entry_date, trade.entry_price) == ("d001", 101.0)
    assert (trade.exit_date, trade.exit_price) == ("d003", 105.0)


def test_a_next_open_signal_on_the_last_bar_has_nowhere_to_fill():
    series = {"AAA": bars([100.0, 102.0])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d001", "entry", "bullish")],
        idealized_config(fill_timing="next_open"),
    )
    assert result.trades == []


def test_next_close_fills_at_the_following_sessions_close():
    series = {"AAA": bars([100.0, 102.0, 104.0, 106.0], opens=[100.0, 101.0, 103.0, 105.0])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish"), decision("d002", "exit", "bearish")],
        idealized_config(fill_timing="next_close"),
    )
    trade = result.trades[0]
    assert (trade.entry_date, trade.entry_price) == ("d001", 102.0)
    assert (trade.exit_date, trade.exit_price) == ("d003", 106.0)


def test_next_typical_fills_inside_the_following_sessions_range():
    """(high + low + close) / 3 -- a VWAP stand-in, never an extreme of the bar."""
    series = {
        "AAA": bars(
            [100.0, 102.0, 104.0, 106.0],
            high=[101.0, 108.0, 105.0, 110.0],
            low=[99.0, 96.0, 103.0, 100.0],
        )
    }
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish"), decision("d002", "exit", "bearish")],
        idealized_config(fill_timing="next_typical"),
    )
    trade = result.trades[0]
    assert trade.entry_date == "d001"
    assert trade.entry_price == pytest.approx((108.0 + 96.0 + 102.0) / 3)
    assert trade.exit_date == "d003"
    assert trade.exit_price == pytest.approx((110.0 + 100.0 + 106.0) / 3)


def test_a_stop_hit_during_the_session_beats_an_exit_queued_for_its_close():
    """The stop happened intraday; the queued exit would only have filled at the close."""
    series = {
        "AAA": bars(
            [100.0, 100.0, 100.0, 99.0],
            low=[99.0, 99.0, 99.0, 90.0],
        )
    }
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish"), decision("d002", "exit", "bearish")],
        idealized_config(fill_timing="next_close", stop_loss_pct=0.05),
    )
    trade = result.trades[0]
    assert trade.exit_date == "d003"
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price == pytest.approx(95.0)


def test_a_position_filled_at_the_close_is_not_stopped_by_that_sessions_range():
    """Entered at d001's close, it held none of d001's low -- stops start tomorrow."""
    series = {"AAA": bars([100.0, 100.0, 100.0], low=[99.0, 80.0, 99.0])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        idealized_config(fill_timing="next_close", stop_loss_pct=0.05),
    )
    trade = result.trades[0]
    assert trade.entry_date == "d001"
    assert trade.exit_reason == "end_of_window"


@pytest.mark.parametrize("timing", ["next_close", "next_typical"])
def test_a_deferred_signal_on_the_last_bar_has_nowhere_to_fill(timing):
    series = {"AAA": bars([100.0, 102.0])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d001", "entry", "bullish")],
        idealized_config(fill_timing=timing),
    )
    assert result.trades == []


@pytest.mark.parametrize("timing", ["next_open", "next_close", "next_typical", "next_vwap"])
@pytest.mark.parametrize("execution_price", [200.0, 50.0])
def test_deferred_entries_size_once_at_the_execution_price(timing, execution_price):
    series = {
        "AAA": bars(
            [100.0, execution_price, execution_price],
            opens=[100.0, execution_price, execution_price],
            high=[101.0, execution_price, execution_price],
            low=[99.0, execution_price, execution_price],
        )
    }
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        idealized_config(
            fill_timing=timing,
            intraday_resolution="minute" if timing == "next_vwap" else "daily",
            position_sizing="fixed_notional",
            sizing_value=10_000.0,
        ),
    )

    assert len(result.fills) == 1
    fill = result.fills[0]
    assert (fill.date, fill.price) == ("d001", execution_price)
    assert fill.qty == pytest.approx(10_000.0 / execution_price)
    assert result.summary.filled_notional == pytest.approx(10_000.0)
    assert result.summary.unfilled_orders == 0


def test_deferred_partial_entry_keeps_its_execution_sized_target():
    result = simulate(
        ["AAA"],
        {"AAA": volume_bars([100.0, 200.0, 400.0, 400.0], [1_000, 200, 200, 100])},
        [decision("d000", "entry", "bullish")],
        volume_config(
            fill_timing="next_open",
            position_sizing="fixed_notional",
            sizing_value=10_000.0,
        ),
    )

    assert [fill.qty for fill in result.fills] == [20.0, 20.0, 10.0]
    assert result.trades[0].qty == pytest.approx(50.0)
    assert result.summary.unfilled_orders == 0


@pytest.mark.parametrize(
    ("timing", "phrase"),
    [
        ("signal_close", "close of the signal date"),
        ("next_open", "open of the session after"),
        ("next_close", "close of the session after"),
        ("next_typical", "stand-in for VWAP"),
    ],
)
def test_every_fill_timing_states_its_price_in_the_assumptions(timing, phrase):
    assert any(phrase in line for line in idealized_config(fill_timing=timing).assumptions())


# --- shorts -----------------------------------------------------------------


def test_shorts_are_refused_unless_enabled_and_counted_when_refused():
    series = {"AAA": bars([100.0, 90.0, 80.0])}
    result = simulate(
        ["AAA"], series, [decision("d000", "entry", "bearish")], idealized_config()
    )
    assert result.trades == []
    assert result.summary.rejected_shorts_disabled == 1


def test_a_short_makes_money_when_the_price_falls():
    series = {"AAA": bars([100.0, 90.0, 80.0])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bearish"), decision("d002", "exit", "bullish")],
        idealized_config(allow_shorts=True),
    )
    trade = result.trades[0]
    assert trade.side == "short"
    assert trade.return_pct == pytest.approx(0.20)  # 100 -> 80
    assert result.equity[-1].value > result.equity[0].value


def test_a_short_stop_triggers_on_the_way_up():
    # Opens at 101, below the 105 stop, and rallies through it intraday.
    series = {
        "AAA": bars(
            [100.0, 106.0], opens=[100.0, 101.0], high=[101.0, 108.0], low=[99.0, 100.0]
        )
    }
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bearish")],
        idealized_config(allow_shorts=True, stop_loss_pct=0.05),
    )
    trade = result.trades[0]
    assert (trade.exit_reason, trade.exit_price) == ("stop_loss", pytest.approx(105.0))


# --- book keeping -----------------------------------------------------------


def test_no_pyramiding_a_repeat_entry_is_ignored():
    series = {"AAA": bars([100.0] * 5)}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish"), decision("d002", "entry", "bullish")],
        idealized_config(),
    )
    assert len(result.trades) == 1


def test_an_exit_with_nothing_held_does_nothing():
    series = {"AAA": bars([100.0] * 4)}
    result = simulate(
        ["AAA"], series, [decision("d001", "exit", "bearish")], idealized_config()
    )
    assert result.trades == []
    assert result.summary.fills == 0


def test_a_position_open_at_the_end_is_reported_but_never_counted_as_realised():
    series = {"AAA": bars([100.0, 110.0])}
    result = simulate(
        ["AAA"], series, [decision("d000", "entry", "bullish")], idealized_config()
    )
    trade = result.trades[0]
    assert (trade.open, trade.exit_date, trade.exit_reason) == (True, None, "end_of_window")


def test_a_symbol_outside_the_selection_is_ignored_not_silently_traded():
    series = {"AAA": bars([100.0] * 4)}
    result = simulate(
        ["AAA"], series, [decision("d001", "entry", "bullish", symbol="ZZZ")], idealized_config()
    )
    assert result.trades == []


def test_a_decision_on_a_date_with_no_bar_is_counted_as_dropped():
    series = {"AAA": bars([100.0] * 3)}
    result = simulate(
        ["AAA"], series, [decision("d009", "entry", "bullish")], idealized_config()
    )
    assert result.summary.dropped_no_bar == 1


def test_the_same_inputs_produce_the_same_book_twice():
    series = {"AAA": bars([100.0, 105.0, 98.0, 103.0, 99.0])}
    decisions = [decision("d000", "entry", "bullish"), decision("d003", "exit", "bearish")]
    config = idealized_config(commission_bps=5, slippage_bps=2, stop_loss_pct=0.05)
    first = simulate(["AAA"], series, decisions, config)
    second = simulate(["AAA"], series, decisions, config)
    assert first == second


# --- configuration validation ----------------------------------------------


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"initial_capital": 0}, "initial_capital"),
        ({"position_sizing": "martingale"}, "position_sizing"),
        ({"fill_timing": "whenever"}, "fill_timing"),
        ({"position_sizing": "fixed_fraction"}, "sizing_value is required"),
        ({"sizing_value": 0.5}, "not used by equal_weight"),
        ({"stop_loss_pct": 5.0}, "fraction in (0, 1]"),
        ({"max_positions": 0}, "max_positions"),
        ({"max_position_pct": 1.5}, "max_position_pct"),
        ({"max_volume_participation": 0.0}, "max_volume_participation"),
        ({"order_expiry_days": 0}, "order_expiry_days"),
        ({"atr_period": 1}, "atr_period"),
        ({"min_holding_days": 10, "max_holding_days": 5}, "min_holding_days must be <="),
        # Portfolio allocation: settings only those modes read are refused
        # elsewhere, and the modes take no sizing_value.
        *[
            ({field: value}, f"{field} is only used by portfolio allocation sizing")
            for field, value in [
                ("target_exposure", 0.8),
                ("min_allocation_score", 0.5),
                ("rebalance_frequency", "weekly"),
                ("rebalance_threshold", 0.02),
                ("max_turnover", 0.5),
            ]
        ],
        (
            {"position_sizing": "fixed_fraction", "sizing_value": 0.1, "target_exposure": 0.5},
            "target_exposure is only used by portfolio allocation sizing (equal_active, "
            "signal_strength, signal_inverse_volatility); leave it unset",
        ),
        (
            {"position_sizing": "signal_strength", "sizing_value": 0.1},
            "sizing_value is not used by signal_strength sizing",
        ),
        (
            {"position_sizing": "equal_active", "target_exposure": 0.0},
            "target_exposure must be a fraction in (0, 1]",
        ),
        (
            {"position_sizing": "equal_active", "target_exposure": 1.5},
            "target_exposure must be a fraction in (0, 1]",
        ),
        (
            {"position_sizing": "signal_strength", "min_allocation_score": -0.1},
            "min_allocation_score must be in [0, 1]",
        ),
        (
            {"position_sizing": "signal_strength", "min_allocation_score": 1.1},
            "min_allocation_score must be in [0, 1]",
        ),
        (
            {"position_sizing": "equal_active", "rebalance_frequency": "hourly"},
            "rebalance_frequency must be one of",
        ),
        (
            {"position_sizing": "equal_active", "rebalance_threshold": 1.0},
            "rebalance_threshold must be a fraction in [0, 1)",
        ),
        (
            {"position_sizing": "equal_active", "rebalance_threshold": -0.01},
            "rebalance_threshold must be a fraction in [0, 1)",
        ),
        (
            {"position_sizing": "equal_active", "max_turnover": 0.0},
            "max_turnover must be a fraction in (0, 2]",
        ),
        (
            {"position_sizing": "equal_active", "max_turnover": 2.5},
            "max_turnover must be a fraction in (0, 2]",
        ),
        (
            {"position_sizing": "equal_active", "target_exposure": float("nan")},
            "target_exposure",
        ),
    ],
)
def test_invalid_configuration_is_refused_with_the_field_named(kwargs, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        idealized_config(**kwargs)


def test_a_misspelled_setting_is_an_error_not_a_silent_default():
    """A user who mistypes a stop must not get a run that quietly had no stop."""
    with pytest.raises(ValueError, match="stop_los_pct"):
        ExecutionConfig.from_dict({"stop_los_pct": 0.05})


def test_assumptions_describe_the_config_that_actually_ran():
    quiet = idealized_config().assumptions()
    assert any("No transaction costs" in line for line in quiet)
    assert any("Long-only" in line for line in quiet)

    loud = idealized_config(
        commission_bps=5, slippage_bps=2, stop_loss_pct=0.05, allow_shorts=True
    ).assumptions()
    assert not any("No transaction costs" in line for line in loud)
    assert any("5 bps commission" in line for line in loud)
    assert any("Long and short" in line for line in loud)
    assert any("stop" in line for line in loud)


# --- portfolio allocation settings ------------------------------------------


@pytest.mark.parametrize("mode", ALLOCATION_SIZING)
def test_allocation_modes_resolve_their_defaults(mode):
    config = idealized_config(position_sizing=mode)
    assert mode in POSITION_SIZING
    assert config.allocation() == AllocationSettings(
        target_exposure=1.0, min_score=0.0, frequency="on_signal", threshold=0.0,
        max_turnover=None,
    )


def test_allocation_settings_are_carried_when_set():
    config = idealized_config(
        position_sizing="signal_strength",
        target_exposure=0.8,
        min_allocation_score=0.0,
        rebalance_frequency="monthly",
        rebalance_threshold=0.02,
        max_turnover=2.0,
    )
    assert config.allocation() == AllocationSettings(
        target_exposure=0.8, min_score=0.0, frequency="monthly", threshold=0.02,
        max_turnover=2.0,
    )
    assert ExecutionConfig.from_dict(config.to_dict()) == config


@pytest.mark.parametrize(
    "mode, value", [("equal_weight", None), ("fixed_fraction", 0.1),
                    ("fixed_notional", 5_000.0), ("volatility_target", 0.15)],
)
def test_legacy_modes_have_no_allocation_and_serialise_as_before(mode, value):
    config = idealized_config(position_sizing=mode, sizing_value=value)
    assert config.allocation() is None
    serialised = config.to_dict()
    # The keys a config had before allocation existed, and no others: a
    # stored legacy config must read back -- and write out -- unchanged.
    assert not set(serialised) & {
        "target_exposure", "min_allocation_score", "rebalance_frequency",
        "rebalance_threshold", "max_turnover",
    }
    assert ExecutionConfig.from_dict(serialised) == config


def test_rebalance_is_an_exit_reason():
    assert "rebalance" in EXIT_REASONS
    assert REBALANCE_FREQUENCY == ("on_signal", "daily", "weekly", "monthly")


def test_inverse_volatility_allocation_warms_up_its_volatility():
    assert idealized_config(position_sizing="signal_inverse_volatility",
                            atr_period=20).extra_lookback_days == 21
    assert idealized_config(position_sizing="equal_active").extra_lookback_days == 0
    assert idealized_config(position_sizing="signal_strength").extra_lookback_days == 0
    # Legacy warm-up is untouched: volatility_target never added any.
    assert idealized_config(position_sizing="volatility_target",
                            sizing_value=0.15).extra_lookback_days == 0


def _text(config) -> str:
    return "\n".join(config.assumptions())


def test_allocation_assumptions_state_normalisation_and_shared_capital():
    text = _text(idealized_config(position_sizing="equal_active"))
    assert "split evenly across every instrument with an active entry signal" in text
    assert "targets 100.0% of equity." in text
    assert "can be bought up or trimmed" in text
    assert "on each session whose signals change the allocation" in text
    assert "reductions and closes first, then increases" in text
    # Legacy sentences that would be false here are not emitted.
    assert "Equal-weight" not in text
    assert "dropped, not queued" not in text
    # Unset settings are not described.
    assert "not traded, so small drift" not in text
    assert "Each rebalance trades at most" not in text
    assert "score below" not in text


def test_signal_strength_assumptions_define_the_score():
    text = _text(idealized_config(position_sizing="signal_strength", target_exposure=0.6))
    assert "in proportion to that signal's score" in text
    assert "weight of the entry components that fired divided by" in text
    assert "targets 60.0% of equity; the rest stays in cash." in text


def test_inverse_volatility_assumptions_name_the_lookback():
    text = _text(idealized_config(position_sizing="signal_inverse_volatility", atr_period=20))
    assert "divided by the instrument's trailing annualised volatility" in text
    assert "over 20 bars" in text
    assert "not yet defined, or is zero, gets no allocation" in text


def test_allocation_assumptions_describe_every_setting_that_ran():
    text = _text(
        idealized_config(
            position_sizing="signal_strength",
            min_allocation_score=0.5,
            rebalance_frequency="weekly",
            rebalance_threshold=0.02,
            max_turnover=0.25,
            max_positions=3,
            max_position_pct=0.4,
        )
    )
    assert "score below 0.50 (under 50.0% of the entry-component weight" in text
    assert "first session of each ISO week" in text
    assert "wait for the next one" in text
    assert "smaller than 2.0% of equity" in text
    assert "trades at most 25.0% of equity in total weight change" in text
    assert "scaled down in proportion" in text
    assert "Strategy and protective exits are neither counted nor scaled" in text
    assert "At most 3 positions are allocated" in text
    assert "highest scores are kept (ties broken by symbol)" in text
    assert "exceeds 40.0% of equity; weight above the cap is redistributed" in text
    monthly = _text(idealized_config(position_sizing="equal_active",
                                     rebalance_frequency="monthly"))
    assert "first session of each calendar month" in monthly
    assert "A signal's score is" not in monthly
    ranked = _text(idealized_config(position_sizing="equal_active", max_positions=2))
    assert "weight of the entry components that fired divided by" in ranked
    assert "only which signals are allocated" in ranked
    daily = _text(idealized_config(position_sizing="equal_active", rebalance_frequency="daily"))
    assert "recomputed every session" in daily
    assert "wait for the next one" not in daily


def test_legacy_assumptions_are_unchanged_by_allocation():
    config = idealized_config(
        position_sizing="fixed_fraction", sizing_value=0.1, max_positions=2,
        max_position_pct=0.5,
    )
    text = _text(config)
    assert "At most 2 positions are held at once; a signal arriving when the book is full is " \
        "dropped, not queued." in text
    assert "No single position exceeds 50% of equity." in text
    assert "allocation" not in text.lower()


# --- parity with the engine this one replaced -------------------------------


def _synthetic(seed: int, n: int = 300):
    """A deterministic price path with trend and reversion in it."""
    import numpy as np

    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0004, 0.018, n) + 0.015 * np.sin(np.arange(n) / 9.0)
    closes = 100 * np.exp(np.cumsum(steps))
    out = []
    for i, close in enumerate(closes):
        high = close * (1 + abs(rng.normal(0, 0.012)))
        low = close * (1 - abs(rng.normal(0, 0.012)))
        open_ = float(min(max(close * (1 + rng.normal(0, 0.006)), low), high))
        out.append(Bar(f"d{i:04d}", open_, float(high), float(low), float(close), 1_000_000))
    return out


@pytest.mark.parametrize("rule_name", ["rsi-threshold", "sma-crossover", "breakout-20d"])
def test_idealized_config_reproduces_the_pre_execution_engine(rule_name):
    """The compatibility promise, checked against the old code rather than
    against a recorded number: same trades, same curve, same metrics."""
    symbols = ["AAA", "BBB", "CCC"]
    series = {symbol: _synthetic(index + 1) for index, symbol in enumerate(symbols)}

    rule = get_rule(rule_name)
    stored = [
        {
            "symbol": symbol,
            "date": event.date,
            "direction": event.direction,
            "trigger_values": event.trigger_values,
            "data_window_end": event.data_window_end,
        }
        for symbol in symbols
        for event in rule.compute(series[symbol], **rule.params)
    ]
    stored.sort(key=lambda item: (item["symbol"], item["date"]))
    assert stored, "the rule must actually fire for this test to mean anything"

    old_trades = performance.pair_trades(stored, series)
    old_equity = performance.equity_series(old_trades, series, symbols)

    # A single-model run is one rule wearing both hats.
    decisions = [
        Decision(
            date=item["date"],
            symbol=item["symbol"],
            kind="both",
            direction=item["direction"],
            trigger_values=item["trigger_values"],
            data_window_end=item["data_window_end"],
        )
        for item in stored
    ]
    new = simulate(symbols, series, decisions, idealized_config())

    assert [p.date for p in new.equity] == [p.date for p in old_equity]
    for fresh, original in zip(new.equity, old_equity, strict=True):
        assert fresh.value == pytest.approx(original.value, rel=1e-12)

    assert len(new.trades) == len(old_trades)
    for fresh, original in zip(new.trades, old_trades, strict=True):
        assert (fresh.symbol, fresh.entry_date, fresh.exit_date) == (
            original.symbol,
            original.entry_date,
            original.exit_date,
        )
        assert fresh.return_pct == pytest.approx(original.return_pct, rel=1e-12)


def test_iter_days_and_simulate_agree_because_there_is_only_one_loop():
    series = {"AAA": _synthetic(7, 120)}
    decisions = [decision("d010", "entry", "bullish"), decision("d090", "exit", "bearish")]
    config = idealized_config(commission_bps=5, stop_loss_pct=0.10)

    simulator = ExecutionSimulator(["AAA"], series, config)
    days = list(simulator.iter_days(decisions))
    batch = simulate(["AAA"], series, decisions, config)

    assert days[-1].equity == pytest.approx(batch.equity[-1].value)
    assert simulator.trades() == batch.trades


def test_ingest_extends_atr_and_volatility_bit_identically_to_the_batch_precompute():
    """Half constructor, half ingest: the incrementally maintained ATR and
    volatility series are bit-identical to the batch precompute, and the run
    they drive -- equity curve and trades -- is exactly the same run."""
    import numpy as np

    series = _synthetic(11, 200)
    config = idealized_config(
        position_sizing="volatility_target",
        sizing_value=0.10,
        atr_stop_multiple=2.0,
    )
    decisions = []
    for i in range(20, 195, 10):
        decisions.append(decision(f"d{i:04d}", "both", "bullish"))
        decisions.append(decision(f"d{i + 5:04d}", "both", "bearish"))

    batch = ExecutionSimulator(["AAA"], {"AAA": series}, config)
    streamed = ExecutionSimulator(["AAA"], {"AAA": series[:100]}, config)
    for bar in series[100:]:
        streamed.ingest("AAA", bar)

    assert np.array_equal(streamed._atr["AAA"], batch._atr["AAA"], equal_nan=True)
    assert np.array_equal(streamed._vol["AAA"], batch._vol["AAA"], equal_nan=True)

    batch_days = list(batch.iter_days(decisions))
    streamed_days = list(streamed.iter_days(decisions))
    assert [
        (day.date, day.equity, day.cash, day.realized_pnl, day.fills) for day in streamed_days
    ] == [(day.date, day.equity, day.cash, day.realized_pnl, day.fills) for day in batch_days]
    assert streamed.trades() == batch.trades()
    assert batch.closed_trades, "the fixture must actually trade"


# --- volume participation ---------------------------------------------------


def volume_bars(prices, volumes):
    return [
        Bar(date=f"d{i:03d}", open=float(price), high=float(price) * 1.01,
            low=float(price) * 0.99, close=float(price), volume=volume)
        for i, (price, volume) in enumerate(zip(prices, volumes, strict=True))
    ]


def volume_config(**kwargs):
    settings = {"max_volume_participation": 0.10, "order_expiry_days": 5}
    settings.update(kwargs)
    return idealized_config(**settings)


def test_a_capped_entry_carries_and_completes_over_multiple_bars():
    result = simulate(
        ["AAA"], {"AAA": volume_bars([100.0] * 4, [1_000] * 4)},
        [decision("d000", "entry", "bullish")], volume_config(),
    )
    assert [fill.qty for fill in result.fills] == [100.0] * 4
    assert result.trades[0].qty == 400.0
    assert result.summary.volume_limited_fills == 4
    assert result.summary.requested_notional == 100_000.0
    assert result.summary.filled_notional == 40_000.0
    assert result.summary.unfilled_orders == 1
    assert result.summary.unfilled_notional == 60_000.0


def test_a_signal_remainder_expires_after_its_session_budget():
    result = simulate(
        ["AAA"], {"AAA": volume_bars([100.0] * 4, [1_000] * 4)},
        [decision("d000", "entry", "bullish")], volume_config(order_expiry_days=2),
    )
    assert result.trades[0].qty == 300.0
    assert result.summary.expired_orders == 1
    assert result.summary.unfilled_orders == 0


def test_zero_volume_waits_for_a_later_bar():
    result = simulate(
        ["AAA"], {"AAA": volume_bars([100.0, 100.0], [0, 1_000])},
        [decision("d000", "entry", "bullish")], volume_config(),
    )
    assert [(fill.date, fill.qty) for fill in result.fills] == [("d001", 100.0)]


def test_partial_exits_produce_one_weighted_trade():
    result = simulate(
        ["AAA"], {"AAA": volume_bars([100.0, 100.0, 110.0, 120.0], [1_000] * 4)},
        [decision("d000", "entry", "bullish"), decision("d002", "exit", "bearish")],
        volume_config(initial_capital=20_000.0),
    )
    (trade,) = result.trades
    assert trade.qty == 200.0
    assert trade.entry_price == 100.0
    assert trade.exit_price == 115.0
    assert trade.return_pct == pytest.approx(0.15)
    assert trade.pnl == pytest.approx(3_000.0)


def test_a_protective_exit_remainder_stays_active_until_filled():
    series = volume_bars([100.0, 100.0, 95.0, 95.0], [1_000] * 4)
    series[2] = Bar(date="d002", open=95.0, high=96.0, low=90.0, close=95.0, volume=1_000)
    series[3] = Bar(date="d003", open=95.0, high=96.0, low=90.0, close=95.0, volume=1_000)
    result = simulate(
        ["AAA"], {"AAA": series}, [decision("d000", "entry", "bullish")],
        volume_config(stop_loss_pct=0.05, order_expiry_days=5),
    )
    (trade,) = result.trades
    assert trade.exit_reason == "stop_loss"
    assert trade.qty == 200.0
    assert result.summary.expired_orders == 0


# --- allocation primitives (unused by legacy sizing) --------------------------


def _pending_open(qty, *, frozen, reason="rebalance"):
    from quantlab.execution.engine import _PendingOrder

    return _PendingOrder(
        symbol="AAA", kind="open", direction="bullish", signal_date="d000",
        remaining_qty=qty, created_index=0, at_open=True, reason=reason,
        frozen_qty=frozen,
    )


def test_a_frozen_deferred_order_keeps_its_quantity_when_equity_and_price_move():
    # fixed_notional would re-size to 1_000 / 200 = 5 shares on d001; the
    # frozen target of 50 is filled as is.
    series = bars([100.0, 200.0, 200.0])
    config = idealized_config(
        fill_timing="next_open", position_sizing="fixed_notional", sizing_value=1_000.0
    )
    frozen = ExecutionSimulator(["AAA"], {"AAA": series}, config)
    frozen.step_day("d000", [])
    frozen._pending.append(_pending_open(50.0, frozen=True))
    frozen.step_day("d001", [])
    (fill,) = frozen.fills
    assert fill.qty == 50.0
    assert fill.price == 200.0
    assert fill.reason == "rebalance"
    assert frozen._pending == []

    resized = ExecutionSimulator(["AAA"], {"AAA": series}, config)
    resized.step_day("d000", [])
    resized._pending.append(_pending_open(50.0, frozen=False, reason="signal"))
    resized.step_day("d001", [])
    assert [f.qty for f in resized.fills] == [5.0]


def test_a_capacity_limited_frozen_remainder_keeps_its_frozen_quantity():
    # 10% of 100 shares a session caps each fill at 10; the 25-share target
    # carries over, never re-sized down to fixed_notional's 5 shares.
    series = volume_bars([100.0, 100.0, 120.0, 150.0, 150.0], [100] * 5)
    config = volume_config(
        fill_timing="next_open", position_sizing="fixed_notional", sizing_value=500.0
    )
    simulator = ExecutionSimulator(["AAA"], {"AAA": series}, config)
    simulator.step_day("d000", [])
    simulator._pending.append(_pending_open(25.0, frozen=True))
    simulator.step_day("d001", [])
    (remainder,) = simulator._pending
    assert remainder.frozen_qty is True
    assert remainder.remaining_qty == 15.0
    assert remainder.reason == "rebalance"
    simulator.step_day("d002", [])
    simulator.step_day("d003", [])
    assert [(f.date, f.qty, f.reason) for f in simulator.fills] == [
        ("d001", 10.0, "rebalance"), ("d002", 10.0, "rebalance"), ("d003", 5.0, "rebalance"),
    ]
    assert simulator._pending == []
    assert simulator._positions["AAA"].qty == 25.0
    # Requested once, at the first attempt: 25 shares at d001's open.
    assert simulator._requested_notional == pytest.approx(25.0 * 100.0)


def test_a_partial_close_requests_only_the_quantity_asked_for():
    series = bars([100.0, 110.0])
    config = idealized_config(position_sizing="fixed_notional", sizing_value=10_000.0)
    simulator = ExecutionSimulator(["AAA"], {"AAA": series}, config)
    simulator.step_day("d000", [decision("d000", "entry", "bullish")])
    assert simulator._positions["AAA"].qty == 100.0
    before = simulator._requested_notional
    fill = simulator._close(
        "d001", "AAA", 110.0, 1, "rebalance", qty_limit=40.0, request=True
    )
    assert fill.qty == 40.0
    assert fill.reason == "rebalance"
    assert simulator._requested_notional - before == pytest.approx(40.0 * 110.0)
    assert simulator._positions["AAA"].qty == 60.0


def test_an_explicit_quantity_open_sets_levels_and_charges_costs():
    series = bars([100.0, 100.0])
    config = idealized_config(
        commission_bps=10.0, slippage_bps=10.0, stop_loss_pct=0.05,
        take_profit_pct=0.10, position_sizing="fixed_notional", sizing_value=1_000.0,
    )
    simulator = ExecutionSimulator(["AAA"], {"AAA": series}, config)
    fill = simulator._open(
        "d000", "AAA", "long", 100.0, 0, at_open=False, request=True,
        qty=30.0, reason="rebalance",
    )
    # 30 shares, not fixed_notional's 10.
    assert fill.qty == 30.0
    assert fill.reason == "rebalance"
    assert fill.price == pytest.approx(100.1)
    assert fill.slippage == pytest.approx(0.1 * 30.0)
    assert fill.commission == pytest.approx(30.0 * 100.1 * 0.001)
    position = simulator._positions["AAA"]
    assert position.stop_price == pytest.approx(100.1 * 0.95)
    assert position.target_price == pytest.approx(100.1 * 1.10)
    assert simulator.cash == pytest.approx(100_000.0 - 30.0 * 100.1 - fill.commission)
    assert simulator._requested_notional == pytest.approx(30.0 * 100.1)

    # Adding to the holding takes the weighted-average entry.
    add = simulator._open(
        "d001", "AAA", "long", 110.0, 1, at_open=False, qty=10.0, reason="rebalance"
    )
    assert add.qty == 10.0
    assert position.qty == 40.0
    assert position.entry_price == pytest.approx((100.1 * 30.0 + add.price * 10.0) / 40.0)


def test_an_explicit_quantity_open_is_capped_by_cash_capacity_and_limit():
    series = volume_bars([100.0], [1_000])
    simulator = ExecutionSimulator(
        ["AAA"], {"AAA": series}, volume_config(initial_capital=5_000.0)
    )
    # Cash buys 50, capacity allows 100, the limit 40: the limit binds.
    fill = simulator._open(
        "d000", "AAA", "long", 100.0, 0, at_open=False, qty=1_000.0, qty_limit=40.0
    )
    assert fill.qty == 40.0
    # Cash left buys 10 more, below the 100 capacity.
    fill = simulator._open("d000", "AAA", "long", 100.0, 0, at_open=False, qty=1_000.0)
    assert fill.qty == pytest.approx(10.0)
    # Capacity binds when cash does not.
    rich = ExecutionSimulator(["AAA"], {"AAA": series}, volume_config())
    fill = rich._open("d000", "AAA", "long", 100.0, 0, at_open=False, qty=500.0)
    assert fill.qty == 100.0


def test_an_explicit_quantity_open_requests_its_target_even_when_cash_is_short():
    series = volume_bars([100.0], [100_000])
    simulator = ExecutionSimulator(
        ["AAA"], {"AAA": series}, volume_config(initial_capital=5_000.0)
    )
    fill = simulator._open(
        "d000", "AAA", "long", 100.0, 0, at_open=False, qty=1_000.0, request=True
    )
    assert fill.qty == 50.0
    assert simulator._requested_notional == pytest.approx(100_000.0)
    assert simulator._filled_notional == pytest.approx(5_000.0)


def test_an_explicit_quantity_open_never_nets_against_the_opposite_side():
    series = bars([100.0, 100.0])
    simulator = ExecutionSimulator(
        ["AAA"], {"AAA": series}, idealized_config(allow_shorts=True)
    )
    simulator.step_day("d000", [decision("d000", "entry", "bearish")])
    assert simulator._positions["AAA"].side == "short"
    assert simulator._open("d001", "AAA", "long", 100.0, 1, at_open=False, qty=10.0) is None
    assert simulator._positions["AAA"].side == "short"


def test_an_explicit_quantity_open_respects_the_cooldown():
    series = bars([100.0, 100.0, 100.0])
    simulator = ExecutionSimulator(["AAA"], {"AAA": series}, idealized_config(cooldown_days=5))
    simulator.step_day("d000", [decision("d000", "entry", "bullish")])
    simulator.step_day("d001", [decision("d001", "exit", "bearish")])
    assert simulator._open("d002", "AAA", "long", 100.0, 2, at_open=False, qty=10.0) is None
    assert simulator._counters["rejected_cooldown"] == 1


def test_volatility_series_is_built_for_both_volatility_sizing_modes():
    series = bars([100.0 + (i % 3) for i in range(30)])
    legacy = ExecutionSimulator(["AAA"], {"AAA": series}, idealized_config())
    assert not legacy._needs_volatility()
    assert legacy._vol == {}

    target = ExecutionSimulator(
        ["AAA"], {"AAA": series},
        idealized_config(position_sizing="volatility_target", sizing_value=0.1),
    )
    assert target._needs_volatility()
    assert "AAA" in target._vol and "AAA" in target._vol_state

    # The allocation mode lands in config separately; force it here.
    config = idealized_config()
    object.__setattr__(config, "position_sizing", "signal_inverse_volatility")
    allocation = ExecutionSimulator(["AAA"], {"AAA": series}, config)
    assert allocation._needs_volatility()
    assert allocation._vol["AAA"].tolist() == pytest.approx(
        target._vol["AAA"].tolist(), nan_ok=True
    )
    assert "AAA" in allocation._vol_state


# --- portfolio allocation: the simulator integration ------------------------


def scored(date, symbol, score=1.0, kind="entry", direction="bullish"):
    return decision(date, kind, direction, symbol, trigger_values={"_score": score})


def alloc_config(mode="equal_active", **kwargs):
    return idealized_config(position_sizing=mode, **kwargs)


def dated_bars(prices, *, start="2024-01-01"):
    """Bars on real business days (2024-01-01 is a Monday)."""
    import numpy as np

    days = np.busday_offset(start, np.arange(len(prices)), roll="forward")
    return [
        Bar(
            date=str(day), open=float(close), high=float(close) * 1.01,
            low=float(close) * 0.99, close=float(close), volume=1_000,
        )
        for day, close in zip(days, prices, strict=True)
    ]


def trail(result):
    return [(f.date, f.symbol, f.side, round(f.qty, 6), f.reason) for f in result.fills]


def test_a_new_signal_resizes_the_position_already_held():
    """Shared capital: B's entry trims A from 100% to 50% before buying B."""
    series = {"AAA": bars([100.0] * 6), "BBB": bars([50.0] * 6)}
    result = simulate(
        ["AAA", "BBB"], series,
        [scored("d001", "AAA"), scored("d003", "BBB")],
        alloc_config(),
    )
    assert trail(result) == [
        ("d001", "AAA", "buy", 1000.0, "rebalance"),
        ("d003", "AAA", "sell", 500.0, "rebalance"),  # reduction first
        ("d003", "BBB", "buy", 1000.0, "rebalance"),
    ]
    assert result.equity[-1].value == pytest.approx(100_000.0)


def test_weakening_conviction_reduces_a_position_rather_than_liquidating_it():
    series = {"AAA": bars([100.0] * 8), "BBB": bars([100.0] * 8)}
    result = simulate(
        ["AAA", "BBB"], series,
        [scored("d001", "AAA", 1.0), scored("d001", "BBB", 1.0), scored("d004", "AAA", 0.5)],
        alloc_config("signal_strength"),
    )
    # 50/50, then AAA 0.5 / (0.5 + 1) = 1/3 and BBB 2/3.
    assert trail(result) == [
        ("d001", "AAA", "buy", 500.0, "rebalance"),
        ("d001", "BBB", "buy", 500.0, "rebalance"),
        ("d004", "AAA", "sell", round(500 - 100_000 / 3 / 100, 6), "rebalance"),
        ("d004", "BBB", "buy", round(200_000 / 3 / 100 - 500, 6), "rebalance"),
    ]
    aaa, bbb = result.trades
    assert aaa.open and bbb.open  # trimmed, not closed


def test_an_unchanged_repeat_entry_trades_nothing():
    series = {"AAA": bars([100.0, 100.0, 120.0, 90.0])}
    result = simulate(
        ["AAA"], series,
        [scored("d001", "AAA"), scored("d002", "AAA"), scored("d003", "AAA")],
        alloc_config("signal_strength"),
    )
    assert [f.date for f in result.fills] == ["d001"]


def test_a_strategy_exit_closes_in_full_and_its_capital_moves_to_the_rest():
    series = {"AAA": bars([100.0] * 6), "BBB": bars([100.0] * 6)}
    result = simulate(
        ["AAA", "BBB"], series,
        [scored("d001", "AAA"), scored("d001", "BBB"), decision("d003", "exit", "bearish", "BBB")],
        alloc_config(),
    )
    assert trail(result)[2:] == [
        ("d003", "BBB", "sell", 500.0, "signal"),  # the strategy's own exit
        ("d003", "AAA", "buy", 500.0, "rebalance"),
    ]
    aaa, bbb = result.trades
    assert bbb.exit_reason == "signal" and not bbb.open


def test_a_protective_exit_clears_the_allocation_and_is_not_rebought():
    # AAA falls 10% on d003 through its 5% stop; BBB takes the freed capital.
    series = {
        "AAA": bars([100.0, 100.0, 100.0, 90.0, 90.0, 90.0]),
        "BBB": bars([100.0] * 6),
    }
    result = simulate(
        ["AAA", "BBB"], series,
        [scored("d001", "AAA"), scored("d001", "BBB")],
        alloc_config(stop_loss_pct=0.05),
    )
    fills = trail(result)
    assert fills[2][:3] == ("d003", "AAA", "sell") and fills[2][4] == "stop_loss"
    assert fills[3][:3] == ("d003", "BBB", "buy") and fills[3][4] == "rebalance"
    assert len(fills) == 4  # AAA's stale entry is gone: nothing re-buys it
    assert [t.symbol for t in result.trades if t.open] == ["BBB"]


def test_a_reversal_closes_the_old_side_before_opening_the_new():
    series = {"AAA": bars([100.0] * 5)}
    result = simulate(
        ["AAA"], series,
        [scored("d001", "AAA"), scored("d003", "AAA", direction="bearish")],
        alloc_config(allow_shorts=True),
    )
    assert trail(result) == [
        ("d001", "AAA", "buy", 1000.0, "rebalance"),
        ("d003", "AAA", "sell", 1000.0, "rebalance"),
        ("d003", "AAA", "short", 1000.0, "rebalance"),
    ]


def test_a_reversal_is_not_blocked_by_its_own_close_under_a_cooldown():
    series = {"AAA": bars([100.0] * 5)}
    result = simulate(
        ["AAA"], series,
        [scored("d001", "AAA"), scored("d003", "AAA", direction="bearish")],
        alloc_config(allow_shorts=True, cooldown_days=3),
    )
    assert [f.side for f in result.fills] == ["buy", "sell", "short"]
    assert result.summary.rejected_cooldown == 0


def test_a_re_entry_while_its_exit_is_in_flight_is_traded_once_the_exit_completes():
    """on_signal: the rebalance that could not touch AAA (its close still
    queued) keeps the next session due, so the re-entry is not lost."""
    series = {"AAA": volume_bars([100.0] * 8, [1_000] * 8)}
    result = simulate(
        ["AAA"], series,
        [
            scored("d000", "AAA"),
            decision("d002", "exit", "bearish"),
            scored("d003", "AAA"),
        ],
        alloc_config(fill_timing="next_open", max_volume_participation=0.6),
    )
    # 1000 bought over d001 (600) and d002 (400); the exit's close takes
    # d003 and d004; the re-entry rebalances once the close is done.
    sides = [(f.date, f.side, f.reason) for f in result.fills]
    assert sides[-1][1:] == ("buy", "rebalance")
    assert ("d004", "sell", "signal") in sides


def test_a_zero_close_on_a_rebalance_session_is_skipped_not_a_crash():
    series = {"AAA": bars([100.0, 0.0, 100.0, 100.0])}
    result = simulate(
        ["AAA"], series, [scored("d001", "AAA")], alloc_config()
    )
    assert [(f.date, f.qty) for f in result.fills] == [("d002", 1000.0)]
    assert result.summary.dropped_no_bar == 1


def test_long_only_drops_a_bearish_entry_as_the_legacy_modes_do():
    series = {"AAA": bars([100.0] * 5)}
    result = simulate(
        ["AAA"], series,
        [scored("d001", "AAA"), scored("d003", "AAA", direction="bearish")],
        alloc_config(),
    )
    assert [f.date for f in result.fills] == ["d001"]
    assert result.summary.rejected_shorts_disabled == 1


def test_a_both_decision_that_closes_does_not_also_open():
    series = {"AAA": bars([100.0] * 5)}
    result = simulate(
        ["AAA"], series,
        [decision("d001", "both", "bullish"), decision("d003", "both", "bearish")],
        alloc_config(allow_shorts=True),
    )
    assert trail(result) == [
        ("d001", "AAA", "buy", 1000.0, "rebalance"),
        ("d003", "AAA", "sell", 1000.0, "signal"),
    ]


def test_max_positions_keeps_the_highest_scores():
    series = {s: bars([100.0] * 5) for s in ("AAA", "BBB", "CCC")}
    result = simulate(
        ["AAA", "BBB", "CCC"], series,
        [scored("d001", "AAA", 0.5), scored("d001", "BBB", 1.0), scored("d001", "CCC", 0.5)],
        alloc_config("signal_strength", max_positions=2),
    )
    # BBB, then AAA wins the tie with CCC by symbol: 1/1.5 and 0.5/1.5.
    assert trail(result) == [
        ("d001", "AAA", "buy", round(100_000 / 3 / 100, 6), "rebalance"),
        ("d001", "BBB", "buy", round(200_000 / 3 / 100, 6), "rebalance"),
    ]


def test_a_slot_is_reserved_when_a_capped_turnover_cannot_free_it():
    """max_turnover scales AAA's close to a partial one, so AAA keeps its slot
    and the new name's open is refused rather than overfilling the book."""
    series = {s: bars([100.0] * 5) for s in ("AAA", "BBB")}
    simulator = ExecutionSimulator(
        ["AAA", "BBB"], series,
        alloc_config("signal_strength", max_positions=1, max_turnover=0.5),
    )
    days = list(simulator.iter_days([scored("d000", "AAA", 0.5), scored("d002", "BBB", 1.0)]))
    assert all(day.positions <= 1 for day in days)
    assert simulator.summary().rejected_max_positions == 1
    # d000 trades 0.5 of the 1.0 target (the cap). On d002 BBB outranks AAA:
    # AAA 0.5 -> 0 and BBB 0 -> 1 is 1.5 of turnover, scaled by 1/3, so AAA
    # only falls to 1/3 and still holds the one slot.
    assert [(f.date, f.symbol, f.side, round(f.qty, 6)) for f in simulator.fills] == [
        ("d000", "AAA", "buy", 500.0), ("d002", "AAA", "sell", round(50_000 / 3 / 100, 6)),
    ]


def test_position_caps_leave_the_excess_in_cash():
    series = {"AAA": bars([100.0] * 3), "BBB": bars([100.0] * 3)}
    result = simulate(
        ["AAA", "BBB"], series,
        [scored("d001", "AAA"), scored("d001", "BBB")],
        alloc_config(max_position_pct=0.3),
    )
    assert [f.qty for f in result.fills] == [pytest.approx(300.0), pytest.approx(300.0)]


def test_target_exposure_is_gross():
    series = {"AAA": bars([100.0] * 3), "BBB": bars([100.0] * 3)}
    result = simulate(
        ["AAA", "BBB"], series,
        [scored("d001", "AAA"), scored("d001", "BBB", direction="bearish")],
        alloc_config(allow_shorts=True, target_exposure=0.6),
    )
    assert trail(result) == [
        ("d001", "AAA", "buy", 300.0, "rebalance"),
        ("d001", "BBB", "short", 300.0, "rebalance"),
    ]


def test_inverse_volatility_weights_the_calmer_name_more():
    import numpy as np

    calm = [100.0 * (1.01 if i % 2 else 1.0) for i in range(30)]
    wild = [100.0 * (1.04 if i % 2 else 1.0) for i in range(30)]
    series = {"AAA": bars(calm), "BBB": bars(wild)}
    config = alloc_config("signal_inverse_volatility", atr_period=10)
    simulator = ExecutionSimulator(["AAA", "BBB"], series, config)
    list(simulator.iter_days([scored("d020", "AAA"), scored("d020", "BBB")]))
    vol_a, vol_b = simulator._vol["AAA"][20], simulator._vol["BBB"][20]
    assert np.isfinite(vol_a) and vol_b > vol_a
    a, b = simulator.fills
    assert a.value / (a.value + b.value) == pytest.approx(
        (1 / vol_a) / (1 / vol_a + 1 / vol_b)
    )


def test_inverse_volatility_gives_nothing_before_the_volatility_is_defined():
    series = {"AAA": bars([100.0 + i % 2 for i in range(30)])}
    result = simulate(
        ["AAA"], series, [scored("d003", "AAA")],
        alloc_config("signal_inverse_volatility", atr_period=10),
    )
    assert result.fills == []


def test_weekly_rebalance_waits_for_the_next_week_but_exits_do_not():
    # 2024-01-03 is a Wednesday; the next ISO week starts Monday 2024-01-08.
    series = {"AAA": dated_bars([100.0] * 15), "BBB": dated_bars([100.0] * 15)}
    result = simulate(
        ["AAA", "BBB"], series,
        [
            scored("2024-01-03", "AAA"),
            scored("2024-01-09", "BBB"),
            decision("2024-01-11", "exit", "bearish", "AAA"),
        ],
        alloc_config(rebalance_frequency="weekly"),
    )
    assert trail(result) == [
        ("2024-01-08", "AAA", "buy", 1000.0, "rebalance"),
        ("2024-01-11", "AAA", "sell", 1000.0, "signal"),  # never held for Monday
        ("2024-01-15", "BBB", "buy", 1000.0, "rebalance"),
    ]


def test_monthly_rebalance_runs_on_the_first_session_of_each_month():
    series = {"AAA": dated_bars([100.0] * 30, start="2024-01-15")}
    result = simulate(
        ["AAA"], series, [scored("2024-01-16", "AAA")],
        alloc_config(rebalance_frequency="monthly"),
    )
    assert [f.date for f in result.fills] == ["2024-02-01"]


def test_daily_rebalance_restores_drifted_weights_every_session():
    series = {"AAA": bars([100.0, 100.0, 110.0, 110.0]), "BBB": bars([100.0] * 4)}
    result = simulate(
        ["AAA", "BBB"], series,
        [scored("d000", "AAA"), scored("d000", "BBB")],
        alloc_config(rebalance_frequency="daily"),
    )
    # AAA's 10% rise on d002 drifts the book to 52.4/47.6; d002 trades back.
    assert [(f.symbol, f.side) for f in result.fills if f.date == "d002"] == [
        ("AAA", "sell"), ("BBB", "buy"),
    ]
    assert not [f for f in result.fills if f.date in ("d001", "d003")]


def test_a_drift_threshold_skips_small_changes():
    series = {"AAA": bars([100.0, 100.0, 110.0, 110.0]), "BBB": bars([100.0] * 4)}
    result = simulate(
        ["AAA", "BBB"], series,
        [scored("d000", "AAA"), scored("d000", "BBB")],
        alloc_config(rebalance_frequency="daily", rebalance_threshold=0.05),
    )
    assert [f.date for f in result.fills] == ["d000", "d000"]


def test_the_drift_threshold_and_turnover_cap_never_delay_a_mandatory_exit():
    series = {"AAA": bars([100.0] * 6)}
    result = simulate(
        ["AAA"], series,
        [scored("d001", "AAA"), decision("d003", "exit", "bearish")],
        alloc_config(rebalance_threshold=0.005, max_turnover=0.01),
    )
    # The open is scaled to the 1% turnover budget; the exit is taken in full.
    buy, sell = result.fills
    assert buy.qty == pytest.approx(10.0)
    assert (sell.date, sell.qty, sell.reason) == ("d003", pytest.approx(10.0), "signal")


def test_turnover_scales_every_discretionary_change_but_not_the_exit():
    series = {s: bars([100.0] * 5) for s in ("AAA", "BBB", "CCC")}
    result = simulate(
        ["AAA", "BBB", "CCC"], series,
        [
            scored("d000", "AAA"), scored("d000", "BBB"),
            decision("d002", "exit", "bearish", "BBB"), scored("d002", "CCC"),
        ],
        alloc_config(max_turnover=0.5),
    )
    # d000: 1.0 of turnover against a 0.5 budget, so 0.25 each. d002: BBB's
    # exit is full and uncounted; AAA 0.25 -> 0.5 and CCC 0 -> 0.5 is 0.75,
    # scaled by 2/3. (Counting the exit would have made it 1.0, scaled 1/2.)
    assert [t for t in trail(result) if t[0] == "d000"] == [
        ("d000", "AAA", "buy", 250.0, "rebalance"),
        ("d000", "BBB", "buy", 250.0, "rebalance"),
    ]
    assert [t for t in trail(result) if t[0] == "d002"] == [
        ("d002", "BBB", "sell", 250.0, "signal"),
        ("d002", "AAA", "buy", round(25_000 * 2 / 3 / 100, 6), "rebalance"),
        ("d002", "CCC", "buy", round(50_000 * 2 / 3 / 100, 6), "rebalance"),
    ]

    capped = simulate(
        ["AAA", "BBB", "CCC"], series,
        [scored("d000", "AAA"), scored("d000", "BBB"), scored("d002", "CCC")],
        alloc_config(max_turnover=1 / 3),
    )
    # d000 reaches 1/6 each (1.0 requested, 1/3 allowed). d002 requests AAA
    # and BBB 1/6 -> 1/3 and CCC 0 -> 1/3: turnover 2/3, so every change halves.
    assert [t[1:4] for t in trail(capped) if t[0] == "d002"] == [
        ("AAA", "buy", round(100_000 / 12 / 100, 6)),
        ("BBB", "buy", round(100_000 / 12 / 100, 6)),
        ("CCC", "buy", round(100_000 / 6 / 100, 6)),
    ]


def test_a_next_open_order_keeps_its_signal_time_quantity():
    # Target set at d001's close of 100: 1000 shares. The d002 open is 80;
    # re-sizing there would buy 1250.
    prices = [100.0, 100.0, 80.0, 80.0]
    series = {"AAA": bars(prices, opens=prices)}
    result = simulate(
        ["AAA"], series, [scored("d001", "AAA")], alloc_config(fill_timing="next_open")
    )
    (fill,) = result.fills
    assert (fill.date, fill.qty, fill.price, fill.reason) == ("d002", 1000.0, 80.0, "rebalance")


def test_a_capacity_limited_rebalance_keeps_its_signal_time_quantity():
    prices = [100.0, 100.0, 90.0, 80.0, 70.0, 60.0, 50.0]
    series = {"AAA": volume_bars(prices, [1_000] * len(prices))}
    result = simulate(
        ["AAA"], series, [scored("d000", "AAA")],
        alloc_config(max_volume_participation=0.25, order_expiry_days=20),
    )
    assert [round(f.qty, 6) for f in result.fills] == [250.0, 250.0, 250.0, 250.0]
    assert {f.reason for f in result.fills} == {"rebalance"}
    assert result.summary.volume_limited_fills >= 3


def test_deferred_orders_reduce_before_they_increase():
    """Under next_open the sell that funds the buy is queued ahead of it."""
    series = {"AAA": bars([100.0] * 5), "BBB": bars([100.0] * 5)}
    result = simulate(
        ["AAA", "BBB"], series,
        [scored("d000", "AAA"), scored("d002", "BBB")],
        alloc_config(fill_timing="next_open"),
    )
    assert trail(result) == [
        ("d001", "AAA", "buy", 1000.0, "rebalance"),
        ("d003", "AAA", "sell", 500.0, "rebalance"),
        ("d003", "BBB", "buy", 500.0, "rebalance"),
    ]


def test_a_strategy_exit_replaces_a_pending_rebalance_remainder():
    series = {"AAA": volume_bars([100.0] * 5, [1_000] * 5)}
    result = simulate(
        ["AAA"], series,
        [scored("d001", "AAA"), decision("d002", "exit", "bearish")],
        alloc_config(fill_timing="next_open", max_volume_participation=0.1),
    )
    # 100 shares fill on d002's open; the exit at d002's close cancels the
    # 900-share remainder and closes the 100 held, at d003's open.
    assert [(f.date, f.side, f.qty, f.reason) for f in result.fills] == [
        ("d002", "buy", 100.0, "rebalance"),
        ("d003", "sell", 100.0, "signal"),
    ]
    assert result.summary.unfilled_orders == 0


def _synthetic_pair(n=160):
    return {"AAA": _synthetic(3, n), "BBB": _synthetic(5, n)}


def _scored_stream(n=160):
    out = []
    for i in range(30, n - 5, 9):
        out.append(scored(f"d{i:04d}", "AAA", 0.5 + (i % 2) / 2))
        out.append(scored(f"d{i + 2:04d}", "BBB", 1.0 if i % 3 else 0.5))
        if i % 4 == 0:
            out.append(decision(f"d{i + 4:04d}", "exit", "bearish", "BBB"))
    return out


@pytest.mark.parametrize("mode", ALLOCATION_SIZING)
def test_truncating_future_bars_changes_no_earlier_fill(mode):
    series = _synthetic_pair()
    decisions = _scored_stream()
    config = alloc_config(
        mode, fill_timing="next_open", commission_bps=1.0, slippage_bps=5.0,
        rebalance_frequency="daily", atr_period=10,
    )
    full = simulate(["AAA", "BBB"], series, decisions, config)
    cut = "d0100"
    truncated = simulate(
        ["AAA", "BBB"],
        {s: [b for b in rows if b.date <= cut] for s, rows in series.items()},
        [d for d in decisions if d.date <= cut],
        config,
    )
    assert full.fills, "the fixture must trade"
    assert [f for f in full.fills if f.date <= cut] == truncated.fills
    assert [p for p in full.equity if p.date <= cut] == truncated.equity


@pytest.mark.parametrize("mode", ALLOCATION_SIZING)
def test_streaming_and_batch_allocation_runs_are_identical(mode):
    series = _synthetic_pair()
    decisions = _scored_stream()
    config = alloc_config(
        mode, fill_timing="next_open", atr_period=10, max_volume_participation=0.5,
        stop_loss_pct=0.04, max_positions=1,
    )
    batch = ExecutionSimulator(["AAA", "BBB"], series, config)
    batch_days = list(batch.iter_days(decisions))
    streamed = ExecutionSimulator(
        ["AAA", "BBB"], {s: rows[:60] for s, rows in series.items()}, config
    )
    by_date: dict[str, list] = {}
    for d in decisions:
        by_date.setdefault(d.date, []).append(d)
    streamed_days = []
    for i in range(160):
        if i >= 60:
            for symbol in ("AAA", "BBB"):
                streamed.ingest(symbol, series[symbol][i])
        date = f"d{i:04d}"
        streamed_days.append(streamed.step_day(date, by_date.get(date, [])))
    assert batch.fills, "the fixture must trade"
    assert [(d.date, d.equity, d.cash, d.fills) for d in streamed_days] == [
        (d.date, d.equity, d.cash, d.fills) for d in batch_days
    ]
    assert streamed.trades() == batch.trades()
    assert streamed.summary() == batch.summary()


def test_legacy_sizing_ignores_the_score():
    series = {"AAA": bars([100.0, 101.0, 99.0, 103.0, 104.0])}
    plain = [decision("d001", "entry", "bullish"), decision("d003", "exit", "bearish")]
    with_scores = [scored("d001", "AAA", 0.25), decision("d003", "exit", "bearish")]
    for config in (
        idealized_config(),
        idealized_config(position_sizing="fixed_fraction", sizing_value=0.3),
    ):
        a = simulate(["AAA"], series, plain, config)
        b = simulate(["AAA"], series, with_scores, config)
        assert (a.fills, a.equity, a.trades, a.summary) == (b.fills, b.equity, b.trades, b.summary)


def test_an_invalid_score_makes_the_signal_ineligible():
    series = {"AAA": bars([100.0] * 4), "BBB": bars([100.0] * 4)}
    result = simulate(
        ["AAA", "BBB"], series,
        [scored("d001", "AAA", 1.5), scored("d001", "BBB", 1.0)],
        alloc_config("signal_strength"),
    )
    assert [(f.symbol, f.qty) for f in result.fills] == [("BBB", 1000.0)]


def test_costs_are_charged_on_rebalance_fills():
    series = {"AAA": bars([100.0] * 4)}
    result = simulate(
        ["AAA"], series, [scored("d001", "AAA")],
        alloc_config(commission_bps=10.0, slippage_bps=10.0),
    )
    (fill,) = result.fills
    assert fill.price == pytest.approx(100.1)
    assert fill.commission == pytest.approx(fill.value * 0.001)
    assert result.summary.total_commission == pytest.approx(fill.commission)
