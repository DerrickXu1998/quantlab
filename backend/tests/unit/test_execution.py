"""Execution criteria on runs: the fill simulator behind them.

Every expected number below is hand-computed. The default criteria reproduce
the historical pair_trades/equity_series measuring instrument, which the first
test asserts directly rather than assumes.
"""

from __future__ import annotations

import pytest

from quantlab.research import performance
from quantlab.research.performance import ExecutionCriteria
from quantlab.synthetic.generator import Bar

INITIAL = 100_000.0


def bars(*rows: tuple[float, float, float, float], start_day: int = 1) -> list[Bar]:
    """Daily bars as (open, high, low, close) tuples."""
    return [
        Bar(
            date=f"2024-01-{start_day + i:02d}",
            open=o,
            high=h,
            low=low,
            close=c,
            volume=1_000,
        )
        for i, (o, h, low, c) in enumerate(rows)
    ]


def flat(*closes: float, start_day: int = 1) -> list[Bar]:
    """Bars whose open/high/low/close are all the close."""
    return bars(*[(c, c, c, c) for c in closes], start_day=start_day)


def signal(symbol: str, date: str, direction: str) -> dict:
    return {
        "symbol": symbol,
        "date": date,
        "direction": direction,
        "trigger_values": {},
        "data_window_end": date,
    }


def run(signals, by_symbol, symbols, criteria):
    return performance.compute_performance(
        run_id="r",
        signals=signals,
        bars_by_symbol=by_symbol,
        symbols=symbols,
        execution=criteria,
    )


# --- Defaults reproduce the historical measuring instrument ------------------


def test_default_criteria_reproduce_the_historical_path():
    by_symbol = {
        "AAA": flat(100.0, 110.0, 120.0, 90.0),
        "BBB": flat(50.0, 55.0, 60.0, 65.0),
    }
    signals = [
        signal("AAA", "2024-01-01", "bullish"),
        signal("BBB", "2024-01-02", "bullish"),
        signal("AAA", "2024-01-03", "bearish"),
    ]

    historical = performance.compute_performance(
        run_id="h", signals=signals, bars_by_symbol=by_symbol, symbols=["AAA", "BBB"]
    )
    simulated = run(signals, by_symbol, ["AAA", "BBB"], ExecutionCriteria())

    assert [t for t in simulated.trades] == historical.trades
    assert [p.value for p in simulated.equity] == pytest.approx(
        [p.value for p in historical.equity], rel=1e-12
    )
    assert simulated.metrics.total_return == pytest.approx(
        historical.metrics.total_return, rel=1e-12
    )


def test_default_criteria_ship_the_same_caveats_as_the_historical_path():
    result = run([], {"AAA": flat(100.0, 110.0)}, ["AAA"], ExecutionCriteria())
    joined = " ".join(result.assumptions).lower()
    assert "long-only" in joined
    assert "equal-weight" in joined
    assert "transaction cost" in joined
    assert "unadjusted" in joined


# --- Costs -------------------------------------------------------------------


def test_transaction_costs_reduce_returns_by_the_hand_computed_amount():
    by_symbol = {"AAA": flat(100.0, 110.0, 120.0)}
    signals = [signal("AAA", "2024-01-01", "bullish"), signal("AAA", "2024-01-03", "bearish")]

    free = run(signals, by_symbol, ["AAA"], ExecutionCriteria())
    charged = run(signals, by_symbol, ["AAA"], ExecutionCriteria(transaction_cost_bps=10.0))

    assert free.metrics.total_return == pytest.approx(0.20)
    # qty = 100000 / (100 * 1.001); exit proceeds = qty * 120 * (1 - 0.001).
    qty = 100_000.0 / (100.0 * 1.001)
    expected = qty * 120.0 * 0.999 / 100_000.0 - 1.0
    assert charged.metrics.total_return == pytest.approx(expected)
    assert charged.metrics.total_return < free.metrics.total_return
    assert charged.trades[0].return_pct < free.trades[0].return_pct


def test_fixed_cost_per_trade_is_charged_on_entry_and_exit():
    by_symbol = {"AAA": flat(100.0, 100.0)}
    signals = [signal("AAA", "2024-01-01", "bullish"), signal("AAA", "2024-01-02", "bearish")]

    result = run(signals, by_symbol, ["AAA"], ExecutionCriteria(fixed_cost_per_trade=50.0))

    # A flat trade with costs is a realised loss of exactly the two fees.
    assert result.metrics.total_return == pytest.approx(-100.0 / 100_000.0)
    assert result.metrics.losing_trades == 1


def test_costs_are_disclosed_in_the_assumptions():
    result = run(
        [],
        {"AAA": flat(100.0, 110.0)},
        ["AAA"],
        ExecutionCriteria(transaction_cost_bps=5.0, fixed_cost_per_trade=2.0),
    )
    joined = " ".join(result.assumptions)
    assert "5 bps" in joined and "2" in joined


# --- Stops and targets ---------------------------------------------------------

STOPPER_BARS = {
    # Entry at 100 on day 1. Day 2 trades down through the 10% stop (90) and
    # closes at 95; day 3 the bearish signal arrives at a close of 50.
    "AAA": flat(100.0) + bars((100.0, 101.0, 89.0, 95.0), start_day=2) + flat(50.0, start_day=3)
}


def test_stop_loss_exits_at_the_level_before_the_signal_can():
    signals = [signal("AAA", "2024-01-01", "bullish"), signal("AAA", "2024-01-03", "bearish")]

    no_stop = run(signals, STOPPER_BARS, ["AAA"], ExecutionCriteria())
    with_stop = run(signals, STOPPER_BARS, ["AAA"], ExecutionCriteria(stop_loss_pct=0.1))

    assert no_stop.trades[0].exit_price == 50.0
    stopped = with_stop.trades[0]
    assert stopped.exit_date == "2024-01-02"  # the bar that traded through the level
    assert stopped.exit_price == pytest.approx(90.0)
    assert stopped.return_pct == pytest.approx(-0.10)
    # The book stops tracking the fall after the exit.
    assert [p.value for p in with_stop.equity] == pytest.approx([100_000.0, 90_000.0, 90_000.0])


def test_a_gap_through_the_stop_fills_at_the_open():
    by_symbol = {"AAA": flat(100.0) + bars((80.0, 82.0, 75.0, 81.0), start_day=2)}
    signals = [signal("AAA", "2024-01-01", "bullish")]

    result = run(signals, by_symbol, ["AAA"], ExecutionCriteria(stop_loss_pct=0.1))

    # The open at 80 is already through the 90 stop: the fill is 80, not 90.
    assert result.trades[0].exit_price == pytest.approx(80.0)
    assert result.trades[0].return_pct == pytest.approx(-0.20)


def test_take_profit_exits_at_the_target():
    by_symbol = {
        "AAA": flat(100.0)
        + bars((100.0, 115.0, 99.0, 110.0), start_day=2)
        + flat(130.0, start_day=3)
    }
    signals = [signal("AAA", "2024-01-01", "bullish")]

    result = run(signals, by_symbol, ["AAA"], ExecutionCriteria(take_profit_pct=0.1))

    trade = result.trades[0]
    assert trade.open is False
    assert trade.exit_date == "2024-01-02"
    assert trade.exit_price == pytest.approx(110.0)
    assert trade.return_pct == pytest.approx(0.10)
    # The run to 130 after the exit is not ours.
    assert result.equity[-1].value == pytest.approx(110_000.0)


def test_when_stop_and_target_trigger_on_one_bar_the_stop_fills_first():
    by_symbol = {"AAA": flat(100.0) + bars((100.0, 120.0, 85.0, 110.0), start_day=2)}
    signals = [signal("AAA", "2024-01-01", "bullish")]

    criteria = ExecutionCriteria(stop_loss_pct=0.1, take_profit_pct=0.1)
    result = run(signals, by_symbol, ["AAA"], criteria)

    assert result.trades[0].exit_price == pytest.approx(90.0)
    # The tie-break is stated in the payload, not implied.
    assert any("stop is assumed to fill first" in line for line in result.assumptions)


# --- Position cap --------------------------------------------------------------


def test_max_open_positions_caps_concurrent_entries():
    by_symbol = {
        "AAA": flat(10.0, 20.0),
        "BBB": flat(10.0, 20.0),
        "CCC": flat(10.0, 20.0),
    }
    signals = [
        signal("AAA", "2024-01-01", "bullish"),
        signal("BBB", "2024-01-01", "bullish"),
        signal("CCC", "2024-01-01", "bullish"),
    ]
    symbols = ["AAA", "BBB", "CCC"]

    uncapped = run(signals, by_symbol, symbols, ExecutionCriteria())
    capped = run(signals, by_symbol, symbols, ExecutionCriteria(max_open_positions=1))

    assert uncapped.metrics.trade_count == 3
    assert capped.metrics.trade_count == 1
    # Deterministic: the first symbol of the day gets the single seat.
    assert capped.trades[0].symbol == "AAA"
    assert [p.value for p in capped.equity] == pytest.approx([100_000.0, 133_333.33333333333])
    assert any("At most 1" in line for line in capped.assumptions)


# --- Fill timing ---------------------------------------------------------------


def test_next_open_fills_at_the_next_sessions_open_not_the_signal_close():
    by_symbol = {
        "AAA": bars(
            (100.0, 100.0, 100.0, 100.0),  # day 1: signal fires at close 100
            (110.0, 120.0, 110.0, 120.0),  # day 2: entry fills at the 110 open
            (120.0, 130.0, 120.0, 130.0),  # day 3: exit signal at close 130
            (140.0, 140.0, 140.0, 140.0),  # day 4: exit fills at the 140 open
        )
    }
    signals = [signal("AAA", "2024-01-01", "bullish"), signal("AAA", "2024-01-03", "bearish")]

    result = run(signals, by_symbol, ["AAA"], ExecutionCriteria(entry_price="next_open"))

    (trade,) = result.trades
    assert trade.entry_date == "2024-01-02"
    assert trade.entry_price == 110.0
    assert trade.exit_date == "2024-01-04"
    assert trade.exit_price == 140.0


def test_next_open_entry_is_stopped_by_its_own_sessions_range():
    by_symbol = {
        "AAA": bars(
            (100.0, 100.0, 100.0, 100.0),  # day 1: signal
            (100.0, 101.0, 85.0, 95.0),  # day 2: in at 100, range breaks the stop
        )
    }
    signals = [signal("AAA", "2024-01-01", "bullish")]

    result = run(
        signals,
        by_symbol,
        ["AAA"],
        ExecutionCriteria(entry_price="next_open", stop_loss_pct=0.1),
    )

    assert result.trades[0].open is False
    assert result.trades[0].exit_date == "2024-01-02"
    assert result.trades[0].exit_price == pytest.approx(90.0)


def test_next_open_signal_on_the_last_session_never_fills():
    by_symbol = {"AAA": flat(100.0, 110.0)}
    signals = [signal("AAA", "2024-01-02", "bullish")]

    result = run(signals, by_symbol, ["AAA"], ExecutionCriteria(entry_price="next_open"))

    assert result.trades == []
    assert [p.value for p in result.equity] == pytest.approx([100_000.0, 100_000.0])


# --- Sizing ---------------------------------------------------------------------


def test_fixed_fraction_sizes_entries_off_the_current_book_value():
    by_symbol = {"AAA": flat(100.0, 110.0)}
    signals = [signal("AAA", "2024-01-01", "bullish")]

    result = run(
        signals,
        by_symbol,
        ["AAA"],
        ExecutionCriteria(position_sizing="fixed_fraction", fraction=0.5),
    )

    # 50% of the 100k book invested at 100; the +10% day moves only that half.
    assert [p.value for p in result.equity] == pytest.approx([100_000.0, 105_000.0])


def test_fixed_fraction_compounds_off_the_grown_book():
    by_symbol = {"AAA": flat(100.0, 200.0, 200.0, 200.0)}
    signals = [
        signal("AAA", "2024-01-01", "bullish"),
        signal("AAA", "2024-01-02", "bearish"),
        signal("AAA", "2024-01-03", "bullish"),
    ]

    result = run(
        signals,
        by_symbol,
        ["AAA"],
        ExecutionCriteria(position_sizing="fixed_fraction", fraction=0.5),
    )

    # First round trip: 100k -> 50k invested -> doubles to 100k -> book 150k.
    # Re-entry invests 50% of 150k = 75k, so the position is bigger second time.
    first, second = result.trades
    assert first.return_pct == pytest.approx(1.0)
    assert result.equity[-1].value == pytest.approx(150_000.0)
    assert second.open is True


# --- Validation -------------------------------------------------------------------


def test_unknown_criteria_keys_are_rejected():
    with pytest.raises(ValueError, match="initial_capita"):
        performance.execution_criteria({"initial_capita": 5.0})


def test_out_of_range_criteria_are_rejected():
    with pytest.raises(ValueError):
        ExecutionCriteria(stop_loss_pct=1.5)
    with pytest.raises(ValueError):
        ExecutionCriteria(position_sizing="nope")
    with pytest.raises(ValueError):
        ExecutionCriteria(entry_price="yesterday")
    with pytest.raises(ValueError):
        ExecutionCriteria(transaction_cost_bps=-1.0)
    with pytest.raises(ValueError):
        ExecutionCriteria(initial_capital=0.0)
