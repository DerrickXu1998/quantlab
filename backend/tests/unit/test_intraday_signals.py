"""Signals on intraday bars: columnar bars, the engine's timeline, the limits.

Built on hand-made sessions. Where a daily answer exists, the intraday path is
checked against it rather than against numbers typed in here.
"""

from __future__ import annotations

import numpy as np
import pytest

from quantlab.execution import (
    CorporateAction,
    Decision,
    ExecutionConfig,
    adjustments,
    simulate,
)
from quantlab.execution.bars import BarSeries, as_of_day
from quantlab.research import errors, runner
from quantlab.storage.facts import build_series
from quantlab.synthetic.generator import Bar


def session(day, closes, start="09:30", step=5):
    """One session of 5-minute bars from a close series (o=h=l=c)."""
    first = np.datetime64(f"{day}T{start}", "m")
    stamps = first + np.arange(len(closes)) * np.timedelta64(step, "m")
    c = np.asarray(closes, dtype=float)
    return stamps, c


def series(*sessions_):
    stamps = np.concatenate([s for s, _ in sessions_])
    c = np.concatenate([c for _, c in sessions_])
    return BarSeries(stamps, c, c, c, c, np.full(len(c), 100))


# --- BarSeries ----------------------------------------------------------------


def test_a_bar_series_reads_like_a_list_of_bars():
    bars = series(session("2024-01-02", [10, 11, 12]), session("2024-01-03", [13, 14]))
    assert len(bars) == 5
    assert (bars[0].date, bars[0].close) == ("2024-01-02T09:30", 10.0)
    assert bars[-1].date == "2024-01-03T09:35"
    assert [b.close for b in bars[1:3]] == [11.0, 12.0]
    assert bars.raw_close is bars.close  # unadjusted: the traded close


def test_sessions_collapse_to_one_daily_bar_each():
    s1, c1 = session("2024-01-02", [10, 12, 9, 11])
    bars = BarSeries(s1, c1, c1 + 1, c1 - 1, c1, [1, 2, 3, 4])
    (day,) = bars.sessions()
    assert (day.date, day.open, day.high, day.low, day.close, day.volume) == (
        "2024-01-02",
        10.0,
        13.0,
        8.0,
        11.0,
        10,
    )


def test_daily_data_is_read_as_of_the_previous_session_intraday():
    assert as_of_day("2024-03-05") == "2024-03-05"  # a daily bar sees its own close
    assert as_of_day("2024-03-05T09:30") == "2024-03-04"


def test_a_filing_dated_today_is_not_visible_mid_session():
    facts = build_series(
        [
            {
                "concept": "equity",
                "value": 100.0,
                "period_start": None,
                "period_end": "2023-12-31",
                "filed_at": "2024-03-05",
            }
        ]
    )
    assert facts.value("equity", "2024-03-05") is not None  # at the close
    assert facts.value("equity", "2024-03-05T15:55") is None  # not before it


# --- splits on intraday bars ---------------------------------------------------


def test_a_split_adjusts_every_bar_of_earlier_sessions_only():
    bars = series(session("2024-01-02", [2000, 2010]), session("2024-01-03", [100, 101]))
    adjusted = adjustments.adjust(bars, [CorporateAction("2024-01-03", "split", split_ratio=20.0)])
    assert adjusted.close.tolist() == pytest.approx([100.0, 100.5, 100.0, 101.0])
    assert adjusted.raw_close.tolist() == [2000.0, 2010.0, 100.0, 101.0]


def test_a_position_held_overnight_into_a_split_keeps_its_value():
    bars = series(session("2024-01-02", [2000, 2000]), session("2024-01-03", [100, 100]))
    buy = Decision(date="2024-01-02T09:30", symbol="AAA", kind="entry", direction="bullish")
    result = simulate(
        ["AAA"],
        {"AAA": bars},
        [buy],
        ExecutionConfig(bar_frequency="5m"),
        {"AAA": [CorporateAction("2024-01-03", "split", split_ratio=20.0)]},
    )
    assert result.equity[-1].value == pytest.approx(100_000.0)


# --- the engine on a timeline ----------------------------------------------------


def test_intraday_execution_matches_the_same_bars_as_rows():
    """The columnar walk is the row-wise walk with a different index."""
    closes = [100, 101, 99, 102, 104, 103, 105, 101]
    bars = series(session("2024-01-02", closes[:4]), session("2024-01-03", closes[4:]))
    rows = [Bar(b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars]
    decisions = [
        Decision(date="2024-01-02T09:35", symbol="AAA", kind="both", direction="bullish"),
        Decision(date="2024-01-03T09:35", symbol="AAA", kind="both", direction="bearish"),
    ]
    config = ExecutionConfig(bar_frequency="5m", stop_loss_pct=0.02)
    columnar = simulate(["AAA"], {"AAA": bars}, decisions, config)
    row_wise = simulate(["AAA"], {"AAA": rows}, decisions, config)
    assert columnar.trades == row_wise.trades
    assert columnar.fills == row_wise.fills


def test_the_equity_curve_has_one_point_per_session():
    bars = series(session("2024-01-02", [100] * 78), session("2024-01-03", [100] * 78))
    result = simulate(["AAA"], {"AAA": bars}, [], ExecutionConfig(bar_frequency="5m"))
    assert [p.date for p in result.equity] == ["2024-01-02", "2024-01-03"]


def test_instruments_with_different_bar_times_each_step_on_their_own_bars():
    a = series(session("2024-01-02", [10, 11, 12]))
    b = series(session("2024-01-02", [20, 21], start="09:35"))
    buy_b = Decision(date="2024-01-02T09:35", symbol="BBB", kind="entry", direction="bullish")
    result = simulate(
        ["AAA", "BBB"], {"AAA": a, "BBB": b}, [buy_b], ExecutionConfig(bar_frequency="5m")
    )
    (trade,) = result.trades
    assert (trade.symbol, trade.entry_price) == ("BBB", 20.0)


def test_volatility_is_annualised_per_bar():
    assert ExecutionConfig(bar_frequency="5m").periods_per_year == 252 * 78
    assert ExecutionConfig().periods_per_year == 252


@pytest.mark.parametrize(
    "bad",
    [
        {"bar_frequency": "2m"},
        {"bar_frequency": "5m", "intraday_resolution": "minute"},
    ],
)
def test_intraday_configs_that_cannot_run_are_refused(bad):
    with pytest.raises(ValueError):
        ExecutionConfig(**bad)


# --- the runner: limits, the demo, the slot --------------------------------------


class IntradayStore:
    """The smallest backend an intraday run needs."""

    name = "warehouse"

    def __init__(self, bars):
        self.bars = bars

    def validate_symbols(self, symbols):
        return [s for s in symbols if s not in self.bars]

    def load_intraday_bars(self, symbols, start, end, frequency):
        return {s: self.bars[s].within(start, end) for s in symbols if s in self.bars}

    def load_bars_for(self, symbols, start, end):
        return {}

    def corporate_actions(self, symbols, start, end):
        return []

    def load_facts_for(self, symbols, concepts, start, end):
        return {}

    def instrument_ids(self, symbols):
        return {}

    def ingest_run_ids(self, symbols, start, end):
        return []

    def earliest_bar_dates(self, symbols):
        return {s: "2024-01-02" for s in symbols}


def _store():
    days = np.busday_offset("2024-01-02", np.arange(60), roll="forward")
    rng = np.random.default_rng(1)
    parts = []
    for day in days:
        closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, 78)))
        parts.append(session(str(day), closes))
    return IntradayStore({"AAA": series(*parts)})


def test_an_intraday_run_executes_on_its_bars():
    result = runner.run_experiment(
        _store(),
        symbols=["AAA"],
        start_date="2024-02-01",
        end_date="2024-03-22",
        model_name="sma-crossover",
        overrides={"fast": 5, "slow": 20},
        execution={"bar_frequency": "5m"},
    )
    assert result.status == "completed" and result.signals
    assert all("T" in s.date for s in result.signals)  # bar times, not dates


def test_an_intraday_run_past_the_bar_limit_is_refused_before_reading(monkeypatch):
    store = _store()
    monkeypatch.setattr(store, "load_intraday_bars", lambda *a: pytest.fail("read anyway"))
    monkeypatch.setattr(runner, "MAX_INTRADAY_BARS", 1_000)
    with pytest.raises(errors.IntradaySelectionTooLargeError, match="5m bars"):
        runner.run_experiment(
            store,
            symbols=["AAA"],
            start_date="2024-02-01",
            end_date="2024-03-22",
            model_name="sma-crossover",
            execution={"bar_frequency": "5m"},
        )


def test_the_estimate_counts_weekdays_times_bars_per_session():
    # 2024-01-01..07: Mon-Fri are 5 sessions; 5m is 78 bars a session.
    assert runner.estimate_bars(2, "2024-01-01", "2024-01-07", "5m") == 2 * 5 * 78


def test_the_demo_refuses_intraday_bars():
    from quantlab.storage.backends import SqliteBackend

    class Demo(IntradayStore):
        name = "sqlite"

    with pytest.raises(errors.DatasetUnsupportedError, match="5m bars"):
        runner.run_experiment(
            Demo({}),
            symbols=["AAA"],
            start_date="2024-02-01",
            end_date="2024-03-22",
            model_name="sma-crossover",
            execution={"bar_frequency": "5m"},
        )
    assert SqliteBackend.load_intraday_bars(object(), ["AAA"], "a", "b", "5m") == {}


def test_a_large_run_waits_for_the_slot_then_is_refused(monkeypatch):
    from contextlib import contextmanager

    store = _store()

    @contextmanager
    def busy(timeout):
        yield False  # someone else holds it

    monkeypatch.setattr(store, "large_run_slot", busy, raising=False)
    monkeypatch.setattr(runner, "LARGE_RUN_BARS", 100)
    with pytest.raises(errors.LargeRunBusyError):
        runner.run_experiment(
            store,
            symbols=["AAA"],
            start_date="2024-02-01",
            end_date="2024-03-22",
            model_name="sma-crossover",
            execution={"bar_frequency": "5m"},
        )


def test_a_small_run_never_asks_for_the_slot(monkeypatch):
    store = _store()
    monkeypatch.setattr(
        store, "large_run_slot", lambda timeout: pytest.fail("asked"), raising=False
    )
    monkeypatch.setattr(runner, "LARGE_RUN_BARS", 10_000_000)
    runner.run_experiment(
        store,
        symbols=["AAA"],
        start_date="2024-02-01",
        end_date="2024-03-22",
        model_name="sma-crossover",
        execution={"bar_frequency": "5m"},
    )


def test_the_demo_slot_is_exclusive():
    from quantlab.storage.backends import SqliteBackend

    demo = SqliteBackend.__new__(SqliteBackend)
    with demo.large_run_slot(1) as first:
        assert first
        with demo.large_run_slot(0) as second:
            assert not second
    with demo.large_run_slot(0) as again:
        assert again


def test_warm_up_is_counted_in_sessions_of_bars():
    from datetime import date

    # 48 bars of 5m lookback is one session: two calendar days of padding.
    assert runner.warmup_start_for(date(2024, 3, 5), 48, "5m") == "2024-03-03"
    assert runner.warmup_start_for(date(2024, 3, 5), 48, "1d") == "2023-11-30"  # as before
