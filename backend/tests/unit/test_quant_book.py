"""The AI-quant-book additions (docs/AI_QUANT_BOOK_STRATEGY_PLAN.md).

F9 the MACD histogram-slope rule, F8 short borrow cost, F5 the benchmark
regression, and the macro gate's as-of join. The template-level behaviour
(S1/S2/S6/S7 trade, the macro gate shuts entries in a crisis) lives with the
other template tests in ``test_strategy.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from quantlab.execution import Decision, ExecutionConfig, simulate
from quantlab.research import performance
from quantlab.research.performance import EquityPoint, regression
from quantlab.signals.registry import get_rule
from quantlab.synthetic.generator import Bar


def seq_bars(prices):
    return [
        Bar(f"d{i:04d}", float(p), float(p) * 1.01, float(p) * 0.99, float(p), 1_000)
        for i, p in enumerate(prices)
    ]


# --- F9: MACD histogram slope ------------------------------------------------


def test_macd_slope_fires_when_the_histogram_turns_up_below_zero():
    # Down, then a turn: the histogram is still negative when its slope flips.
    prices = [100 - i * 0.8 for i in range(60)] + [52 + i * 0.6 for i in range(20)]
    events = get_rule("macd-histogram-slope").compute(seq_bars(prices))
    bullish = [e for e in events if e.direction == "bullish"]
    assert bullish, "a V-shaped path must turn the histogram up"
    assert all(e.trigger_values["histogram"] < 0 for e in bullish)
    assert all(e.trigger_values["slope"] > 0 for e in bullish)


def test_macd_slope_leads_the_crossover():
    """The book prefers the slope because it moves first."""
    prices = [100 - i * 0.8 for i in range(60)] + [52 + i * 0.6 for i in range(30)]
    path = seq_bars(prices)
    slope = [
        e.date for e in get_rule("macd-histogram-slope").compute(path) if e.direction == "bullish"
    ]
    cross = [e.date for e in get_rule("macd-crossover").compute(path) if e.direction == "bullish"]
    assert slope and cross
    assert slope[0] < cross[0]


def test_macd_slope_without_the_sign_condition_fires_more():
    rng = np.random.default_rng(3)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, 300)))
    rule = get_rule("macd-histogram-slope")
    strict = rule.compute(seq_bars(prices), require_sign=True)
    loose = rule.compute(seq_bars(prices), require_sign=False)
    assert len(loose) > len(strict) > 0


# --- F8: borrow cost ------------------------------------------------------------


def _short_run(borrow_bps):
    path = seq_bars([100.0] * 253)
    decisions = [
        Decision(
            date="d0000", symbol="AAA", kind="entry", direction="bearish", data_window_end="d0000"
        ),
        Decision(
            date="d0252", symbol="AAA", kind="exit", direction="bullish", data_window_end="d0252"
        ),
    ]
    config = ExecutionConfig(allow_shorts=True, borrow_cost_bps=borrow_bps)
    return simulate(["AAA"], {"AAA": path}, decisions, config)


def test_a_flat_short_held_a_year_pays_the_annual_borrow():
    free = _short_run(0.0)
    charged = _short_run(100.0)  # 1% a year
    # Equal-weight: the whole 100k sleeve is shorted at 100.
    notional = 100_000.0
    # Charged at each close the short is held through: entry day to the day
    # before exit, 252 sessions -- one year at /252.
    expected = notional * 0.01
    assert charged.summary.total_borrow == pytest.approx(expected, rel=1e-6)
    assert free.summary.total_borrow == 0.0
    assert charged.equity[-1].value == pytest.approx(free.equity[-1].value - expected, rel=1e-6)
    (trade,) = charged.trades
    assert trade.fees == pytest.approx(expected, rel=1e-6)
    assert trade.pnl == pytest.approx(-expected, rel=1e-6)


def test_borrow_is_never_charged_on_a_long():
    path = seq_bars([100.0] * 30)
    decisions = [
        Decision(
            date="d0000", symbol="AAA", kind="entry", direction="bullish", data_window_end="d0000"
        )
    ]
    result = simulate(["AAA"], {"AAA": path}, decisions, ExecutionConfig(borrow_cost_bps=300.0))
    assert result.summary.total_borrow == 0.0


def test_borrow_is_disclosed_and_bounded():
    assert any(
        "100 bps a year" in line
        for line in ExecutionConfig(allow_shorts=True, borrow_cost_bps=100).assumptions()
    )
    assert any(
        "shorting is free" in line for line in ExecutionConfig(allow_shorts=True).assumptions()
    )
    with pytest.raises(ValueError, match="basis points"):
        ExecutionConfig(borrow_cost_bps=10_000)
    with pytest.raises(ValueError):
        ExecutionConfig(borrow_cost_bps=-1)


# --- F5: alpha / beta / R squared ---------------------------------------------


def _curve(returns, start=100_000.0):
    value = start
    out = [EquityPoint(date="d0000", value=value)]
    for i, r in enumerate(returns, start=1):
        value *= 1 + r
        out.append(EquityPoint(date=f"d{i:04d}", value=value))
    return out


def test_regression_recovers_a_known_beta_and_alpha():
    rng = np.random.default_rng(7)
    market = rng.normal(0.0004, 0.01, 500)
    noise = rng.normal(0, 0.002, 500)
    daily_alpha = 0.0002
    strategy = daily_alpha + 1.5 * market + noise

    fit = regression(_curve(strategy), _curve(market))
    assert fit is not None
    assert fit.beta == pytest.approx(1.5, abs=0.03)
    assert fit.alpha == pytest.approx(daily_alpha * 252, abs=0.02)
    assert 0.95 < fit.r_squared <= 1.0
    assert fit.correlation == pytest.approx(math.sqrt(fit.r_squared), abs=1e-9)
    assert fit.observations == 500
    assert fit.tracking_error and fit.tracking_error > 0


def test_regression_is_absent_rather_than_zero_when_unmeasurable():
    short = _curve([0.01] * 10)
    assert regression(short, short) is None  # too few observations
    flat = _curve([0.0] * 100)
    assert regression(_curve([0.001] * 100), flat) is None  # benchmark never moved


def test_a_flat_strategy_has_no_beta_and_explains_nothing():
    rng = np.random.default_rng(1)
    fit = regression(_curve([0.0] * 200), _curve(rng.normal(0, 0.01, 200)))
    assert fit is not None
    assert fit.beta == pytest.approx(0.0, abs=1e-12)
    assert fit.r_squared == 0.0


def test_run_performance_carries_the_regression_and_borrow():
    rng = np.random.default_rng(11)
    prices = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, 200)))
    path = seq_bars(prices)
    decisions = [
        Decision(
            date="d0001", symbol="AAA", kind="entry", direction="bullish", data_window_end="d0001"
        )
    ]
    result = performance.compute_performance(
        run_id="r1",
        signals=[
            {
                "date": d.date,
                "symbol": d.symbol,
                "direction": d.direction,
                "trigger_values": {},
                "data_window_end": d.date,
            }
            for d in decisions
        ],
        bars_by_symbol={"AAA": path},
        symbols=["AAA"],
    )
    # Long the only name from day 1: beta to its own buy-and-hold is ~1.
    assert result.regression is not None
    assert result.regression.beta == pytest.approx(1.0, abs=0.02)
    assert result.costs.borrow == 0.0


# --- S6: the macro gate's as-of join -----------------------------------------


def _daily(start, values):
    from datetime import date, timedelta

    day = date.fromisoformat(start)
    out = []
    for value in values:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        out.append(Bar(day.isoformat(), value, value, value, value, 0))
        day += timedelta(days=1)
    return out


def test_the_macro_gate_reads_vix_as_of_each_bar_never_after():
    stock = _daily("2024-03-04", [100.0] * 10)
    # VIX spikes on the 6th session; before it the gate must be open.
    vix = _daily("2024-03-04", [15.0] * 5 + [40.0] * 5)
    events = get_rule("macro-risk-off").compute(stock, series={"VIX.FRED": vix})
    assert [e.direction for e in events] == ["bullish"] * 5 + ["bearish"] * 5
    assert events[5].trigger_values["vix"] == 40.0


def test_the_macro_gate_treats_a_stale_print_as_unknown():
    stock = _daily("2024-03-04", [100.0] * 15)
    vix = _daily("2024-03-04", [15.0] * 3)  # then nothing
    events = get_rule("macro-risk-off").compute(stock, series={"VIX.FRED": vix}, max_stale_days=5)
    # Known for the three prints plus up to five calendar days after the last.
    assert 3 <= len(events) < 15
    assert all(e.direction == "bullish" for e in events)


def test_the_hy_widening_check_is_opt_in_and_needs_its_history():
    stock = _daily("2024-01-01", [100.0] * 40)
    vix = _daily("2024-01-01", [15.0] * 40)
    widening = _daily("2024-01-01", [3.0 + 0.05 * i for i in range(40)])  # +1.0pt over 20 bars
    rule = get_rule("macro-risk-off")

    without = rule.compute(stock, series={"VIX.FRED": vix, "HYSPREAD.FRED": widening})
    assert all(e.direction == "bullish" for e in without)

    with_hy = rule.compute(
        stock, series={"VIX.FRED": vix, "HYSPREAD.FRED": widening}, use_hy_spread=True
    )
    # The first 20 sessions have no 20-bar change yet: unknown, so no event.
    assert len(with_hy) == 20
    assert all(e.direction == "bearish" for e in with_hy)
