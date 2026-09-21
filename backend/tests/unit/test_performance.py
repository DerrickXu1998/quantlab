"""Performance of a signal run: reference values, not eyeballed ones.

This is the analytical library behind ``GET /runs/{id}/performance``. It exists
in the backend rather than the browser because Constitution V forbids
analytical computation in the frontend -- and because a Sharpe ratio that is
wrong looks exactly like one that is right (Constitution IV).

Every expected number below is either hand-computed or true by construction.
"""

from __future__ import annotations

import math

import pytest

from quantlab.research import performance
from quantlab.synthetic.generator import Bar

INITIAL = 100_000.0


def bars(*closes: float, start_day: int = 1) -> list[Bar]:
    """Daily bars whose close is the supplied series. OHLC are all the close:
    the library marks to close and must not quietly reach for another field."""
    return [
        Bar(
            date=f"2024-01-{start_day + i:02d}",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1_000,
        )
        for i, close in enumerate(closes)
    ]


def signal(symbol: str, date: str, direction: str) -> dict:
    """The shape ExperimentStore.get_run_signals returns."""
    return {
        "symbol": symbol,
        "date": date,
        "direction": direction,
        "trigger_values": {},
        "data_window_end": date,
    }


# --- Trade pairing ---------------------------------------------------------


def test_a_bullish_then_bearish_signal_is_one_closed_trade():
    by_symbol = {"AAA": bars(100.0, 110.0, 120.0, 130.0)}
    signals = [signal("AAA", "2024-01-01", "bullish"), signal("AAA", "2024-01-03", "bearish")]

    trades = performance.pair_trades(signals, by_symbol)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_date == "2024-01-01"
    assert trade.entry_price == 100.0
    assert trade.exit_date == "2024-01-03"
    assert trade.exit_price == 120.0
    assert trade.return_pct == pytest.approx(0.20)
    assert trade.open is False


def test_a_position_left_open_is_marked_at_the_last_bar_and_says_so():
    """An open position is not a closed trade. Reporting it as one would
    inflate the win rate with a result that has not happened yet."""
    by_symbol = {"AAA": bars(100.0, 110.0, 125.0)}
    signals = [signal("AAA", "2024-01-01", "bullish")]

    (trade,) = performance.pair_trades(signals, by_symbol)

    assert trade.open is True
    assert trade.exit_date is None
    assert trade.exit_price == 125.0  # marked, not realised
    assert trade.return_pct == pytest.approx(0.25)


def test_a_second_bullish_signal_while_already_long_is_ignored():
    by_symbol = {"AAA": bars(100.0, 110.0, 120.0, 130.0)}
    signals = [
        signal("AAA", "2024-01-01", "bullish"),
        signal("AAA", "2024-01-02", "bullish"),
        signal("AAA", "2024-01-04", "bearish"),
    ]

    (trade,) = performance.pair_trades(signals, by_symbol)

    assert trade.entry_date == "2024-01-01"  # the first one, not the second
    assert trade.exit_date == "2024-01-04"


def test_a_bearish_signal_with_no_position_open_is_ignored():
    """Long-only. A sell with nothing held is not a short."""
    by_symbol = {"AAA": bars(100.0, 110.0)}

    assert performance.pair_trades([signal("AAA", "2024-01-01", "bearish")], by_symbol) == []


def test_signals_are_paired_per_symbol_not_across_the_universe():
    by_symbol = {"AAA": bars(100.0, 200.0), "BBB": bars(50.0, 25.0)}
    signals = [
        signal("AAA", "2024-01-01", "bullish"),
        signal("BBB", "2024-01-02", "bearish"),  # must not close AAA
    ]

    (trade,) = performance.pair_trades(signals, by_symbol)

    assert trade.symbol == "AAA"
    assert trade.open is True


def test_a_signal_on_a_date_with_no_bar_is_skipped():
    """There is no price to transact at, so there is no trade to report."""
    by_symbol = {"AAA": bars(100.0, 110.0)}

    assert performance.pair_trades([signal("AAA", "2024-06-30", "bullish")], by_symbol) == []


# --- Equity and benchmark --------------------------------------------------


def test_equity_starts_at_the_initial_capital():
    by_symbol = {"AAA": bars(100.0, 110.0, 120.0)}
    trades = performance.pair_trades([signal("AAA", "2024-01-01", "bullish")], by_symbol)

    equity = performance.equity_series(trades, by_symbol, ["AAA"], INITIAL)

    assert equity[0].value == pytest.approx(INITIAL)
    assert [point.date for point in equity] == ["2024-01-01", "2024-01-02", "2024-01-03"]


def test_a_single_symbol_fully_invested_tracks_the_price():
    by_symbol = {"AAA": bars(100.0, 110.0, 120.0)}
    trades = performance.pair_trades([signal("AAA", "2024-01-01", "bullish")], by_symbol)

    equity = performance.equity_series(trades, by_symbol, ["AAA"], INITIAL)

    assert [p.value for p in equity] == pytest.approx([100_000.0, 110_000.0, 120_000.0])


def test_capital_is_split_equally_and_an_unselected_sleeve_stays_in_cash():
    """Two symbols, only one traded: half the book moves, half does not."""
    by_symbol = {"AAA": bars(100.0, 200.0), "BBB": bars(50.0, 50.0)}
    trades = performance.pair_trades([signal("AAA", "2024-01-01", "bullish")], by_symbol)

    equity = performance.equity_series(trades, by_symbol, ["AAA", "BBB"], INITIAL)

    # AAA sleeve doubles 50k -> 100k; BBB sleeve sits in cash at 50k.
    assert [p.value for p in equity] == pytest.approx([100_000.0, 150_000.0])


def test_a_closed_trade_locks_in_its_gain_and_stops_tracking_the_price():
    by_symbol = {"AAA": bars(100.0, 120.0, 60.0)}
    signals = [signal("AAA", "2024-01-01", "bullish"), signal("AAA", "2024-01-02", "bearish")]
    trades = performance.pair_trades(signals, by_symbol)

    equity = performance.equity_series(trades, by_symbol, ["AAA"], INITIAL)

    # Sold at 120; the crash to 60 on day 3 is not ours.
    assert [p.value for p in equity] == pytest.approx([100_000.0, 120_000.0, 120_000.0])


def test_a_missing_bar_forward_fills_rather_than_dropping_to_zero():
    """A symbol with no bar on a date is closed for the day, not worthless."""
    aaa = bars(100.0, 110.0, 120.0)
    bbb = [
        aaa[0].__class__("2024-01-01", 50.0, 50.0, 50.0, 50.0, 1),
    ]
    by_symbol = {"AAA": aaa, "BBB": bbb}
    trades = performance.pair_trades([signal("BBB", "2024-01-01", "bullish")], by_symbol)

    equity = performance.equity_series(trades, by_symbol, ["AAA", "BBB"], INITIAL)

    assert [p.value for p in equity] == pytest.approx([100_000.0, 100_000.0, 100_000.0])


def test_benchmark_is_equal_weight_buy_and_hold_over_the_same_symbols():
    by_symbol = {"AAA": bars(100.0, 200.0), "BBB": bars(50.0, 25.0)}

    benchmark = performance.benchmark_series(by_symbol, ["AAA", "BBB"], INITIAL)

    # AAA sleeve 50k -> 100k, BBB sleeve 50k -> 25k.
    assert [p.value for p in benchmark] == pytest.approx([100_000.0, 125_000.0])


# --- Metrics ---------------------------------------------------------------


def _equity(*values: float) -> list[performance.EquityPoint]:
    return [
        performance.EquityPoint(date=f"2024-01-{i + 1:02d}", value=v) for i, v in enumerate(values)
    ]


def test_total_return_is_end_over_start():
    result = performance.metrics(_equity(100.0, 150.0), [])
    assert result.total_return == pytest.approx(0.5)


def test_max_drawdown_is_the_worst_peak_to_trough_and_is_reported_negative():
    # Peak 121, trough 108.9 -> -10%. The earlier 100 -> 110 rise is not a drawdown.
    result = performance.metrics(_equity(100.0, 110.0, 121.0, 108.9), [])
    assert result.max_drawdown == pytest.approx(-0.10)


def test_a_monotonically_rising_curve_has_exactly_zero_drawdown():
    result = performance.metrics(_equity(100.0, 110.0, 121.0), [])
    assert result.max_drawdown == 0.0


def test_sharpe_matches_a_hand_computed_value():
    # Daily returns: +0.1, +0.1, -0.1. mean = 1/30, sample stdev = sqrt(0.0133..)
    # sharpe = (mean / stdev) * sqrt(252)
    mean = 1 / 30
    stdev = math.sqrt(0.0266666666666667 / 2)
    expected = (mean / stdev) * math.sqrt(252)

    result = performance.metrics(_equity(100.0, 110.0, 121.0, 108.9), [])

    assert result.sharpe_ratio == pytest.approx(expected)
    assert result.sharpe_ratio == pytest.approx(4.5826, rel=1e-4)


def test_a_flat_curve_has_no_sharpe_rather_than_a_fabricated_zero():
    """Zero variance makes the ratio undefined. Returning 0.0 would read as
    'measured, and mediocre' instead of 'not measurable'."""
    result = performance.metrics(_equity(100.0, 100.0, 100.0), [])

    assert result.sharpe_ratio is None
    assert result.total_return == 0.0
    assert result.max_drawdown == 0.0


def test_a_single_point_curve_has_no_sharpe():
    assert performance.metrics(_equity(100.0), []).sharpe_ratio is None


def test_win_rate_counts_closed_trades_only():
    trades = [
        performance.Trade("AAA", "2024-01-01", 100.0, "2024-01-02", 120.0, 0.2, False),
        performance.Trade("BBB", "2024-01-01", 100.0, "2024-01-02", 80.0, -0.2, False),
        performance.Trade("CCC", "2024-01-01", 100.0, "2024-01-02", 150.0, 0.5, False),
        # Open: marked up, but not a win yet.
        performance.Trade("DDD", "2024-01-01", 100.0, None, 900.0, 8.0, True),
    ]

    result = performance.metrics(_equity(100.0, 150.0), trades)

    assert result.trade_count == 4
    assert result.winning_trades == 2
    assert result.losing_trades == 1
    assert result.win_rate == pytest.approx(2 / 3)


def test_win_rate_is_absent_when_nothing_has_closed():
    trades = [performance.Trade("AAA", "2024-01-01", 100.0, None, 110.0, 0.1, True)]

    result = performance.metrics(_equity(100.0, 110.0), trades)

    assert result.win_rate is None
    assert result.trade_count == 1


def test_metrics_on_an_empty_curve_are_defined_rather_than_an_exception():
    result = performance.metrics([], [])

    assert result.total_return == 0.0
    assert result.max_drawdown == 0.0
    assert result.sharpe_ratio is None
    assert result.win_rate is None
    assert result.trade_count == 0


# --- The composed result ---------------------------------------------------


def test_compute_performance_assembles_the_whole_answer():
    by_symbol = {"AAA": bars(100.0, 110.0, 120.0)}
    signals = [signal("AAA", "2024-01-01", "bullish"), signal("AAA", "2024-01-03", "bearish")]

    result = performance.compute_performance(
        run_id="run-1", signals=signals, bars_by_symbol=by_symbol, symbols=["AAA"]
    )

    assert result.run_id == "run-1"
    assert result.initial_capital == performance.INITIAL_CAPITAL
    assert len(result.trades) == 1
    assert len(result.equity) == 3
    assert len(result.benchmark) == 3
    assert result.metrics.total_return == pytest.approx(0.2)


def test_a_run_that_produced_no_signals_reports_a_flat_book_not_an_error():
    """A model finding nothing is a result (the same stance RunResults takes)."""
    by_symbol = {"AAA": bars(100.0, 110.0, 120.0)}

    result = performance.compute_performance(
        run_id="quiet", signals=[], bars_by_symbol=by_symbol, symbols=["AAA"]
    )

    assert result.trades == []
    assert [p.value for p in result.equity] == pytest.approx([100_000.0] * 3)
    assert result.metrics.total_return == 0.0
    assert result.metrics.win_rate is None
    # The benchmark still moved, which is the point of showing it.
    assert result.benchmark[-1].value == pytest.approx(120_000.0)


def test_the_caveats_travel_with_the_numbers():
    """The assumptions are part of the payload, not UI copy that a refactor
    can drop. These numbers are not tradeable and must never look like they are."""
    result = performance.compute_performance(
        run_id="r", signals=[], bars_by_symbol={"AAA": bars(100.0, 110.0)}, symbols=["AAA"]
    )

    joined = " ".join(result.assumptions).lower()
    assert "long-only" in joined
    assert "equal-weight" in joined
    assert "transaction cost" in joined
    assert "slippage" in joined
    assert "unadjusted" in joined
