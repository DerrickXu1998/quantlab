"""The execution engine: sizing, costs, stops, timing, and what it refuses.

Reference values, not eyeballed ones. Every expected number below is either
hand-computed in the test itself or is the output of the code this engine
replaced -- the parity suite at the bottom is the important one, because the
promise made when execution criteria were introduced was that a run configured
the old way still produces the old answer.
"""

from __future__ import annotations

import pytest

from quantlab.execution import (
    Decision,
    ExecutionConfig,
    ExecutionSimulator,
    simulate,
)
from quantlab.research import performance
from quantlab.signals.registry import get_rule
from quantlab.synthetic.generator import Bar


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


def decision(date, kind, direction, symbol="AAA"):
    return Decision(
        date=date, symbol=symbol, kind=kind, direction=direction, data_window_end=date
    )


# --- sizing -----------------------------------------------------------------


def test_equal_weight_splits_capital_into_one_sleeve_per_instrument():
    """100k across four names is a 25k sleeve; a trade uses the whole sleeve."""
    series = {s: bars([100.0] * 5) for s in ("AAA", "BBB", "CCC", "DDD")}
    result = simulate(
        ["AAA", "BBB", "CCC", "DDD"],
        series,
        [decision("d001", "entry", "bullish")],
        ExecutionConfig(),
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
        ExecutionConfig(position_sizing="fixed_fraction", sizing_value=0.30),
    )
    assert result.trades[0].qty == pytest.approx(300.0)  # 30% of 100_000 / 100


def test_fixed_notional_ignores_book_size():
    series = {"AAA": bars([100.0] * 5)}
    result = simulate(
        ["AAA"],
        series,
        [decision("d001", "entry", "bullish")],
        ExecutionConfig(position_sizing="fixed_notional", sizing_value=7_500.0),
    )
    assert result.trades[0].qty == pytest.approx(75.0)


def test_max_position_pct_caps_a_pooled_position():
    series = {"AAA": bars([100.0] * 5)}
    result = simulate(
        ["AAA"],
        series,
        [decision("d001", "entry", "bullish")],
        ExecutionConfig(
            position_sizing="fixed_fraction", sizing_value=0.90, max_position_pct=0.25
        ),
    )
    assert result.trades[0].qty == pytest.approx(250.0)


def test_max_positions_rejects_the_signal_rather_than_queueing_it():
    series = {s: bars([100.0] * 6) for s in ("AAA", "BBB", "CCC")}
    decisions = [
        decision("d001", "entry", "bullish", symbol) for symbol in ("AAA", "BBB", "CCC")
    ]
    result = simulate(["AAA", "BBB", "CCC"], series, decisions, ExecutionConfig(max_positions=2))
    assert len(result.trades) == 2
    assert result.summary.rejected_max_positions == 1


# --- costs ------------------------------------------------------------------


def test_commission_and_slippage_are_charged_on_both_sides():
    """Hand-computed: 10 bps commission, 5 bps slippage, one round trip."""
    series = {"AAA": bars([100.0, 102.0, 103.0, 104.0])}
    config = ExecutionConfig(commission_bps=10, slippage_bps=5)
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
    free = simulate(["AAA"], series, decisions, ExecutionConfig())
    charged = simulate(
        ["AAA"], series, decisions, ExecutionConfig(commission_bps=25, slippage_bps=10)
    )
    assert charged.equity[-1].value < free.equity[-1].value


# --- protective exits -------------------------------------------------------


def test_stop_loss_fills_at_the_stop_when_the_bar_merely_touches_it():
    series = {"AAA": bars([100.0, 100.0, 96.0], low=[99.0, 99.0, 94.0])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        ExecutionConfig(stop_loss_pct=0.05),
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
        ExecutionConfig(stop_loss_pct=0.05),
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
        ExecutionConfig(stop_loss_pct=0.05, take_profit_pct=0.05),
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
        ExecutionConfig(take_profit_pct=0.05),
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
        ExecutionConfig(take_profit_pct=0.05),
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
        ExecutionConfig(trailing_stop_pct=0.10),
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
        ExecutionConfig(trailing_stop_pct=0.10),
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
        ExecutionConfig(atr_stop_multiple=1.0, atr_period=14),
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
        ExecutionConfig(stop_loss_pct=0.02, atr_stop_multiple=1.0, atr_period=14),
    )
    assert result.trades[0].exit_price == pytest.approx(98.0)


def test_max_holding_days_closes_a_position_that_nothing_else_would():
    series = {"AAA": bars([100.0] * 10)}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish")],
        ExecutionConfig(max_holding_days=3),
    )
    trade = result.trades[0]
    assert (trade.exit_reason, trade.exit_date) == ("max_holding", "d003")


def test_min_holding_days_suppresses_a_signal_exit_but_not_a_stop():
    series = {"AAA": bars([100.0, 100.0, 100.0, 100.0])}
    held = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish"), decision("d001", "exit", "bearish")],
        ExecutionConfig(min_holding_days=3),
    )
    assert held.trades[0].open is True

    stopped = simulate(
        ["AAA"],
        {"AAA": bars([100.0, 80.0, 80.0], low=[99.0, 79.0, 79.0])},
        [decision("d000", "entry", "bullish"), decision("d001", "exit", "bearish")],
        ExecutionConfig(min_holding_days=3, stop_loss_pct=0.05),
    )
    assert stopped.trades[0].exit_reason == "stop_loss"


def test_cooldown_blocks_a_re_entry_inside_the_window():
    series = {"AAA": bars([100.0] * 12)}
    decisions = [
        decision("d000", "entry", "bullish"),
        decision("d001", "exit", "bearish"),
        decision("d003", "entry", "bullish"),
    ]
    free = simulate(["AAA"], series, decisions, ExecutionConfig())
    assert len(free.trades) == 2

    cooled = simulate(["AAA"], series, decisions, ExecutionConfig(cooldown_days=5))
    assert len(cooled.trades) == 1
    assert cooled.summary.rejected_cooldown == 1


# --- fill timing ------------------------------------------------------------


def test_next_open_fills_on_the_following_session():
    series = {"AAA": bars([100.0, 102.0, 104.0, 106.0], opens=[100.0, 101.0, 103.0, 105.0])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bullish"), decision("d002", "exit", "bearish")],
        ExecutionConfig(fill_timing="next_open"),
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
        ExecutionConfig(fill_timing="next_open"),
    )
    assert result.trades == []


# --- shorts -----------------------------------------------------------------


def test_shorts_are_refused_unless_enabled_and_counted_when_refused():
    series = {"AAA": bars([100.0, 90.0, 80.0])}
    result = simulate(
        ["AAA"], series, [decision("d000", "entry", "bearish")], ExecutionConfig()
    )
    assert result.trades == []
    assert result.summary.rejected_shorts_disabled == 1


def test_a_short_makes_money_when_the_price_falls():
    series = {"AAA": bars([100.0, 90.0, 80.0])}
    result = simulate(
        ["AAA"],
        series,
        [decision("d000", "entry", "bearish"), decision("d002", "exit", "bullish")],
        ExecutionConfig(allow_shorts=True),
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
        ExecutionConfig(allow_shorts=True, stop_loss_pct=0.05),
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
        ExecutionConfig(),
    )
    assert len(result.trades) == 1


def test_an_exit_with_nothing_held_does_nothing():
    series = {"AAA": bars([100.0] * 4)}
    result = simulate(
        ["AAA"], series, [decision("d001", "exit", "bearish")], ExecutionConfig()
    )
    assert result.trades == []
    assert result.summary.fills == 0


def test_a_position_open_at_the_end_is_reported_but_never_counted_as_realised():
    series = {"AAA": bars([100.0, 110.0])}
    result = simulate(
        ["AAA"], series, [decision("d000", "entry", "bullish")], ExecutionConfig()
    )
    trade = result.trades[0]
    assert (trade.open, trade.exit_date, trade.exit_reason) == (True, None, "end_of_window")


def test_a_symbol_outside_the_selection_is_ignored_not_silently_traded():
    series = {"AAA": bars([100.0] * 4)}
    result = simulate(
        ["AAA"], series, [decision("d001", "entry", "bullish", symbol="ZZZ")], ExecutionConfig()
    )
    assert result.trades == []


def test_a_decision_on_a_date_with_no_bar_is_counted_as_dropped():
    series = {"AAA": bars([100.0] * 3)}
    result = simulate(
        ["AAA"], series, [decision("d009", "entry", "bullish")], ExecutionConfig()
    )
    assert result.summary.dropped_no_bar == 1


def test_the_same_inputs_produce_the_same_book_twice():
    series = {"AAA": bars([100.0, 105.0, 98.0, 103.0, 99.0])}
    decisions = [decision("d000", "entry", "bullish"), decision("d003", "exit", "bearish")]
    config = ExecutionConfig(commission_bps=5, slippage_bps=2, stop_loss_pct=0.05)
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
        ({"atr_period": 1}, "atr_period"),
        ({"min_holding_days": 10, "max_holding_days": 5}, "min_holding_days must be <="),
    ],
)
def test_invalid_configuration_is_refused_with_the_field_named(kwargs, message):
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
        ExecutionConfig(**kwargs)


def test_a_misspelled_setting_is_an_error_not_a_silent_default():
    """A user who mistypes a stop must not get a run that quietly had no stop."""
    with pytest.raises(ValueError, match="stop_los_pct"):
        ExecutionConfig.from_dict({"stop_los_pct": 0.05})


def test_assumptions_describe_the_config_that_actually_ran():
    quiet = ExecutionConfig().assumptions()
    assert any("No transaction costs" in line for line in quiet)
    assert any("Long-only" in line for line in quiet)

    loud = ExecutionConfig(
        commission_bps=5, slippage_bps=2, stop_loss_pct=0.05, allow_shorts=True
    ).assumptions()
    assert not any("No transaction costs" in line for line in loud)
    assert any("5 bps commission" in line for line in loud)
    assert any("Long and short" in line for line in loud)
    assert any("stop" in line for line in loud)


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
def test_default_config_reproduces_the_pre_execution_engine(rule_name):
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
    new = simulate(symbols, series, decisions, ExecutionConfig())

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
    config = ExecutionConfig(commission_bps=5, stop_loss_pct=0.10)

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
    config = ExecutionConfig(
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
