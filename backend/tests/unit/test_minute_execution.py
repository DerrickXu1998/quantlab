"""Minute-resolution execution: what happens between the open and the close.

Hand-built sessions throughout. The daily bar is the consolidated one; the
minutes are a single venue's, so their extremes can fall inside the daily
range -- one of the cases below is exactly that.
"""

from __future__ import annotations

import pytest

from quantlab.execution import (
    CorporateAction,
    Decision,
    ExecutionConfig,
    simulate,
)
from quantlab.execution.minutes import MinuteBar, MonthlyMinuteCache, vwap
from quantlab.synthetic.generator import Bar


def day(date, o, h, lo, c, volume=1_000_000):
    return Bar(date=date, open=o, high=h, low=lo, close=c, volume=volume)


def minute(time, o, h, lo, c, volume=1_000):
    return MinuteBar(time=time, open=o, high=h, low=lo, close=c, volume=volume)


def buy(date):
    return Decision(date=date, symbol="AAA", kind="entry", direction="bullish")


def run(sessions, minutes, decisions, **config):
    """``minutes``: {date: [MinuteBar, ...]}; a stub source that records calls."""
    calls: list[tuple[str, str]] = []

    def source(symbol, date):
        calls.append((symbol, date))
        return minutes.get(date, [])

    result = simulate(
        ["AAA"],
        {"AAA": sessions},
        decisions,
        ExecutionConfig(**config),
        minute_source=source,
    )
    return result, calls


# Entry at 100 on d1's close; d2's range (94..106) holds both the 5% stop (95)
# and the 5% target (105).
SESSIONS = [day("2024-01-02", 100, 100, 100, 100), day("2024-01-03", 100, 106, 94, 100)]
STOP_AND_TARGET = {"stop_loss_pct": 0.05, "take_profit_pct": 0.05}


def test_daily_resolution_assumes_the_stop_when_both_are_in_range():
    result, calls = run(SESSIONS, {}, [buy("2024-01-02")], **STOP_AND_TARGET)
    assert result.trades[0].exit_reason == "stop_loss"
    assert calls == []  # a daily run never reads a minute


def test_minutes_take_the_target_when_it_was_reached_first():
    minutes = {
        "2024-01-03": [
            minute("09:30", 100, 101, 99.5, 101),
            minute("10:15", 101, 105.5, 101, 105),  # target 105 here
            minute("14:00", 105, 105, 94, 95),  # the stop, later
        ]
    }
    result, _ = run(
        SESSIONS, minutes, [buy("2024-01-02")], intraday_resolution="minute", **STOP_AND_TARGET
    )
    trade = result.trades[0]
    assert (trade.exit_reason, trade.exit_price, trade.exit_time) == ("take_profit", 105, "10:15")
    assert result.summary.minute_resolved_exits == 1


def test_minutes_take_the_stop_when_it_came_first():
    minutes = {
        "2024-01-03": [
            minute("09:30", 100, 100, 96, 96),
            minute("09:45", 96, 96, 94, 94.5),  # stop 95 here
            minute("15:00", 95, 106, 95, 106),
        ]
    }
    result, _ = run(
        SESSIONS, minutes, [buy("2024-01-02")], intraday_resolution="minute", **STOP_AND_TARGET
    )
    trade = result.trades[0]
    assert (trade.exit_reason, trade.exit_price, trade.exit_time) == ("stop_loss", 95, "09:45")


def test_one_minute_containing_both_still_resolves_to_the_stop():
    minutes = {"2024-01-03": [minute("11:00", 100, 106, 94, 100)]}
    result, _ = run(
        SESSIONS, minutes, [buy("2024-01-02")], intraday_resolution="minute", **STOP_AND_TARGET
    )
    assert result.trades[0].exit_reason == "stop_loss"


def test_a_minute_that_opens_through_the_stop_fills_at_its_open():
    minutes = {
        "2024-01-03": [
            minute("09:30", 100, 100, 97, 97),
            minute("09:31", 93.5, 94, 93, 94),  # jumped past 95 within a minute
        ]
    }
    sessions = [SESSIONS[0], day("2024-01-03", 100, 100, 93, 94)]
    result, _ = run(
        sessions, minutes, [buy("2024-01-02")], intraday_resolution="minute", stop_loss_pct=0.05
    )
    assert result.trades[0].exit_price == pytest.approx(93.5)


def test_a_gap_at_the_official_open_fills_at_the_official_open():
    """The auction price, not the minute feed's first print."""
    sessions = [SESSIONS[0], day("2024-01-03", 92, 96, 91, 95)]
    minutes = {"2024-01-03": [minute("09:30", 92.4, 93, 92, 93)]}
    result, _ = run(
        sessions, minutes, [buy("2024-01-02")], intraday_resolution="minute", stop_loss_pct=0.05
    )
    trade = result.trades[0]
    assert (trade.exit_reason, trade.exit_price) == ("stop_loss", 92)


def test_minutes_that_never_reach_the_level_fall_back_to_the_daily_rule():
    """The consolidated low touched the stop; the one venue's minutes did not."""
    minutes = {"2024-01-03": [minute("09:30", 100, 100.5, 95.5, 100)]}
    result, _ = run(
        SESSIONS, minutes, [buy("2024-01-02")], intraday_resolution="minute", stop_loss_pct=0.05
    )
    trade = result.trades[0]
    assert (trade.exit_reason, trade.exit_price, trade.exit_time) == ("stop_loss", 95, None)
    assert result.summary.minute_fallbacks == 1


def test_a_session_without_minutes_falls_back_too():
    result, _ = run(
        SESSIONS, {}, [buy("2024-01-02")], intraday_resolution="minute", **STOP_AND_TARGET
    )
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.summary.minute_fallbacks == 1


# --- VWAP -------------------------------------------------------------------


def test_vwap_weights_each_minute_by_its_volume():
    bars = [
        minute("09:30", 10, 10, 10, 10, volume=100),
        minute("15:00", 11, 11, 11, 11, volume=900),
    ]
    assert vwap(bars) == pytest.approx(10.9)
    assert vwap([]) is None


def test_next_vwap_fills_at_the_sessions_vwap():
    sessions = [day("2024-01-02", 100, 100, 100, 100), day("2024-01-03", 100, 112, 100, 110)]
    minutes = {
        "2024-01-03": [
            minute("09:30", 100, 100, 100, 100, volume=100),
            minute("15:59", 110, 110, 110, 110, volume=900),
        ]
    }
    result, _ = run(
        sessions,
        minutes,
        [buy("2024-01-02")],
        intraday_resolution="minute",
        fill_timing="next_vwap",
    )
    assert result.trades[0].entry_price == pytest.approx(109.0)


def test_next_vwap_without_minutes_falls_back_to_the_typical_price():
    sessions = [day("2024-01-02", 100, 100, 100, 100), day("2024-01-03", 100, 112, 100, 110)]
    result, _ = run(
        sessions, {}, [buy("2024-01-02")], intraday_resolution="minute", fill_timing="next_vwap"
    )
    assert result.trades[0].entry_price == pytest.approx((112 + 100 + 110) / 3)
    assert result.summary.minute_fallbacks == 1


def test_next_vwap_needs_minute_resolution():
    with pytest.raises(ValueError, match="next_vwap"):
        ExecutionConfig(fill_timing="next_vwap")


def test_daily_is_the_default():
    assert ExecutionConfig().intraday_resolution == "daily"


# --- splits: raw minutes against raw levels ---------------------------------


def test_minute_stops_after_a_split_see_no_cliff():
    """50 shares at 2,000 become 1,000 at 100; the 5% stop moves to 95, and the
    raw post-split minutes are compared with it, not with 1,900."""
    sessions = [
        day("2024-01-02", 2000, 2000, 2000, 2000),
        day("2024-01-03", 100, 101, 96, 100),
    ]
    minutes = {"2024-01-03": [minute("09:30", 100, 101, 96, 100)]}
    result = simulate(
        ["AAA"],
        {"AAA": sessions},
        [buy("2024-01-02")],
        ExecutionConfig(intraday_resolution="minute", stop_loss_pct=0.05),
        {"AAA": [CorporateAction("2024-01-03", "split", split_ratio=20.0)]},
        lambda symbol, date: minutes.get(date, []),
    )
    assert result.trades[0].open  # the low of 96 never reached 95


# --- the cache ---------------------------------------------------------------


def test_the_cache_reads_one_symbol_month_once():
    loads: list[tuple[str, str, str]] = []

    def load(symbol, start, end):
        loads.append((symbol, start, end))
        return {"2024-02-05": [minute("09:30", 1, 1, 1, 1)]}

    cache = MonthlyMinuteCache(load)
    assert len(cache("AAA", "2024-02-05")) == 1
    assert cache("AAA", "2024-02-06") == []
    assert loads == [("AAA", "2024-02-01", "2024-02-29")]
