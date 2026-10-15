"""The collector's pure parts: mapping, the line plan, minutes, trading hours."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from quantlab_live.contracts import ib_symbol
from quantlab_live.hours import market_state
from quantlab_live.minutes import MinuteRoller
from quantlab_live.plan import Lease, diff, plan_lines

T = datetime(2026, 10, 15, 14, 0, tzinfo=UTC)


def test_us_listings_map_to_ibkr_symbols_and_nothing_else_does():
    assert ib_symbol("AAPL.US") == "AAPL"
    assert ib_symbol("BRK.B.US") == "BRK B"
    assert ib_symbol("BRK-B.US") == "BRK B"
    assert ib_symbol("HSBA.LON") is None
    assert ib_symbol("AAPL") is None
    assert ib_symbol("0700.HK") is None


def lease(sid, symbol, consumer="market", minutes=0):
    return Lease(sid, sid, symbol, consumer, T + timedelta(minutes=minutes))


def test_deployments_get_lines_first_and_a_symbol_takes_one_line():
    leases = [
        lease(1, "A.US", minutes=0),
        lease(2, "B.US", minutes=1),
        lease(3, "A.US", minutes=2),  # a second watcher of A shares its line
        lease(4, "C.US", "deployment", minutes=5),
    ]
    plan = plan_lines(leases, max_lines=2)
    assert plan.lines == ["C.US", "A.US"]
    assert plan.over_budget == {"B.US"}


def test_a_streaming_symbol_is_not_evicted_by_an_earlier_newcomer_of_its_rank():
    leases = [lease(1, "OLD.US", minutes=0), lease(2, "LIVE.US", minutes=9)]
    plan = plan_lines(leases, max_lines=1, streaming={"LIVE.US"})
    assert plan.lines == ["LIVE.US"]
    assert plan.over_budget == {"OLD.US"}


def test_diff_says_what_to_open_and_close():
    assert diff({"A", "B"}, ["B", "C"]) == (["C"], ["A"])


def ts(minute: int, second: int) -> float:
    return (T + timedelta(minutes=minute, seconds=second)).timestamp()


def test_minutes_roll_and_the_partial_first_minute_is_dropped():
    roller = MinuteRoller()
    # Minute 0 is where the line opened: partial, dropped.
    assert roller.add(10.0, 1000, ts(0, 30)) is None
    assert roller.add(11.0, 1100, ts(1, 0)) is None  # closes minute 0, dropped
    assert roller.add(13.0, 1300, ts(1, 20)) is None
    assert roller.add(9.0, 1350, ts(1, 40)) is None
    closed = roller.add(12.0, 1500, ts(2, 5))
    assert closed == {
        "start": int(ts(1, 0)),
        "open": 11.0,
        "high": 13.0,
        "low": 9.0,
        "close": 9.0,
        # 1350 at minute 1's last tick, less 1000 where minute 0 ended: the
        # shares traded before minute 1's first tick belong to minute 1 too.
        "volume": 350,
    }


def test_a_quiet_minute_closes_on_the_clock_and_late_ticks_are_ignored():
    roller = MinuteRoller()
    roller.add(10.0, 100, ts(0, 10))
    roller.add(10.5, 120, ts(1, 10))
    roller.add(99.0, 130, ts(0, 59))  # out of order: belongs to a closed minute
    assert roller.flush(ts(1, 59)) is None
    bar = roller.flush(ts(2, 1))
    assert bar is not None and bar["high"] == 10.5 and bar["close"] == 10.5


HOURS = "20261015:0930-20261015:1600;20261016:0930-20261016:1300;20261017:CLOSED"


def test_market_state_follows_ibkrs_hours_including_half_days_and_holidays():
    ny = "US/Eastern"
    assert market_state(HOURS, ny, datetime(2026, 10, 15, 13, 29, tzinfo=UTC)) == "closed"
    assert market_state(HOURS, ny, datetime(2026, 10, 15, 13, 30, tzinfo=UTC)) == "open"
    assert market_state(HOURS, ny, datetime(2026, 10, 15, 19, 59, tzinfo=UTC)) == "open"
    assert market_state(HOURS, ny, datetime(2026, 10, 15, 20, 0, tzinfo=UTC)) == "closed"
    # Half day: closes at 13:00 New York.
    assert market_state(HOURS, ny, datetime(2026, 10, 16, 17, 30, tzinfo=UTC)) == "closed"
    assert market_state(HOURS, ny, datetime(2026, 10, 17, 15, 0, tzinfo=UTC)) == "closed"
    assert market_state("", ny, T) == "closed"
