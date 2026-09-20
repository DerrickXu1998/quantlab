"""Historical replay: the portfolio simulator and the event engine.

Reference values, not eyeballed ones: every expected number below is either
hand-computed or produced by research.performance on the same inputs -- the
key invariant is that a replay's bottom line *is* the run's performance,
observed day by day instead of after the fact.
"""

from __future__ import annotations

import pytest

from quantlab.replay import engine as replay_engine
from quantlab.replay.engine import (
    ReplayBar,
    ReplayEquity,
    ReplayFill,
    ReplaySignal,
    ReplaySummary,
)
from quantlab.replay.portfolio import PortfolioSimulator
from quantlab.research import performance, runner
from quantlab.storage import backends, db, experiments, repository
from quantlab.synthetic.generator import Bar, generate_universe

# --- PortfolioSimulator ------------------------------------------------------


def test_hand_computed_two_sleeve_scenario():
    """AAA sleeve 50k buys 500 shares at 100; BBB sleeve stays in cash."""
    sim = PortfolioSimulator(["AAA", "BBB"], initial_cash=100_000.0)

    sim.mark({"AAA": 100.0, "BBB": 50.0})
    assert sim.equity() == pytest.approx(100_000.0)

    fill = sim.apply_signal("2024-01-01", "AAA", "bullish", 100.0)
    assert fill is not None
    assert (fill.side, fill.qty, fill.price, fill.value) == ("buy", 500.0, 100.0, 50_000.0)
    # Buying at the close and marking to the same close moves nothing.
    assert sim.equity() == pytest.approx(100_000.0)
    assert sim.cash == pytest.approx(50_000.0)

    sim.mark({"AAA": 110.0, "BBB": 50.0})
    assert sim.equity() == pytest.approx(105_000.0)
    (position,) = sim.open_positions()
    assert position.symbol == "AAA"
    assert position.unrealized_pnl == pytest.approx(5_000.0)

    fill = sim.apply_signal("2024-01-03", "AAA", "bearish", 120.0)
    assert fill is not None
    assert (fill.side, fill.value) == ("sell", 60_000.0)
    assert fill.realized_pnl == pytest.approx(10_000.0)
    assert sim.cash == pytest.approx(110_000.0)
    assert sim.open_positions() == []

    (trade,) = sim.trades()
    assert trade.open is False
    assert trade.return_pct == pytest.approx(0.20)


def test_fractional_shares_keep_a_sleeve_fully_invested():
    sim = PortfolioSimulator(["AAA"], initial_cash=100_000.0)
    fill = sim.apply_signal("2024-01-01", "AAA", "bullish", 333.0)
    assert fill is not None
    assert fill.qty == pytest.approx(100_000.0 / 333.0)
    assert sim.equity() == pytest.approx(100_000.0)


def test_signals_matching_performance_semantics_are_ignored_or_skipped():
    sim = PortfolioSimulator(["AAA", "BBB"], initial_cash=100_000.0)
    sim.mark({"AAA": 100.0, "BBB": 50.0})

    # A bearish signal with nothing held is not a short.
    assert sim.apply_signal("2024-01-01", "AAA", "bearish", 100.0) is None
    # A second bullish signal while long is not a pyramid.
    assert sim.apply_signal("2024-01-01", "AAA", "bullish", 100.0) is not None
    assert sim.apply_signal("2024-01-01", "AAA", "bullish", 100.0) is None
    # No bar on the signal date means no price to transact at.
    assert sim.apply_signal("2024-06-30", "BBB", "bullish", None) is None
    # A symbol outside the selection cannot widen the book.
    assert sim.apply_signal("2024-01-01", "ZZZ", "bullish", 1.0) is None

    assert sim.cash == pytest.approx(50_000.0)
    assert len(sim.fills) == 1


def test_an_open_position_is_marked_not_realised_at_the_end():
    sim = PortfolioSimulator(["AAA"], initial_cash=100_000.0)
    sim.apply_signal("2024-01-01", "AAA", "bullish", 100.0)
    sim.mark({"AAA": 125.0})

    (trade,) = sim.trades()
    assert trade.open is True
    assert trade.exit_date is None
    assert trade.exit_price == 125.0
    assert trade.return_pct == pytest.approx(0.25)
    assert sim.realized_pnl() == 0.0


# --- The engine over a seeded demo dataset -----------------------------------


@pytest.fixture()
def seeded(tmp_path):
    """A seeded SqliteBackend plus its experiment store, with one run saved."""
    path = tmp_path / "test.db"
    conn = db.connect(path)
    db.bootstrap(conn)
    repository.upsert_instruments(conn)
    repository.insert_bars(conn, generate_universe())
    conn.commit()
    conn.close()

    backend = backends.SqliteBackend(str(path))
    store = experiments.SqliteExperimentStore(str(path))
    symbols = sorted(item["symbol"] for item in backend.list_instruments()["items"][:2])
    result = runner.run_experiment(
        backend,
        model_name="sma-crossover",
        overrides={},
        symbols=symbols,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    assert result.signals, "the fixture needs a run that actually fired"
    store.save_run(result)
    run = store.get_run(result.id)
    return backend, store, run


def _events(seeded):
    backend, store, run = seeded
    signals, bars = replay_engine.load_replay_inputs(backend, store, run)
    return run, signals, bars, list(replay_engine.replay_events(run, signals, bars))


def test_events_are_chronologically_ordered(seeded):
    _, _, _, events = _events(seeded)
    dates = [event.date for event in events if not isinstance(event, ReplaySummary)]
    assert dates == sorted(dates)


def test_a_signal_never_precedes_the_bar_event_of_its_own_date(seeded):
    _, _, _, events = _events(seeded)
    dates_with_bars: set[str] = set()
    for event in events:
        if isinstance(event, ReplayBar):
            dates_with_bars.add(event.date)
        elif isinstance(event, ReplaySignal):
            assert event.date in dates_with_bars
            # The point-in-time guarantee survives the re-streaming.
            assert event.data_window_end <= event.date


def test_every_trading_date_gets_exactly_one_equity_event(seeded):
    _, _, bars, events = _events(seeded)
    bar_dates = sorted({bar.date for symbol_bars in bars.values() for bar in symbol_bars})
    equity_dates = [event.date for event in events if isinstance(event, ReplayEquity)]
    assert equity_dates == bar_dates


def test_signal_and_fill_events_carry_the_stored_signal(seeded):
    _, signals, _, events = _events(seeded)
    fired = {(e.symbol, e.date, e.direction) for e in events if isinstance(e, ReplaySignal)}
    stored = {(s["symbol"], s["date"], s["direction"]) for s in signals}
    assert fired == stored

    fills = [e for e in events if isinstance(e, ReplayFill)]
    assert fills, "the fixture run closed at least one trade"
    for fill in fills:
        assert fill.side in ("buy", "sell")
        assert fill.qty > 0 and fill.price > 0
        # A fill happens on the date of the signal that caused it.
        signal_keys = {(s.symbol, s.date) for s in events if isinstance(s, ReplaySignal)}
        assert (fill.symbol, fill.date) in signal_keys


def test_the_summary_reconciles_with_compute_performance(seeded):
    """The key invariant: the replayed book, reduced, is the performance report."""
    backend, store, run = seeded
    signals, bars = replay_engine.load_replay_inputs(backend, store, run)
    summary = replay_engine.replay_summary(run, signals, bars)

    expected = performance.compute_performance(
        run_id=run["id"],
        signals=signals,
        bars_by_symbol=bars,
        symbols=list(run["symbols"]),
    )

    assert summary.days == len(expected.equity)
    assert summary.total_return == pytest.approx(expected.metrics.total_return)
    assert summary.max_drawdown == pytest.approx(expected.metrics.max_drawdown)
    if expected.metrics.sharpe_ratio is None:
        assert summary.sharpe_ratio is None
    else:
        assert summary.sharpe_ratio == pytest.approx(expected.metrics.sharpe_ratio)
    if expected.metrics.win_rate is None:
        assert summary.win_rate is None
    else:
        assert summary.win_rate == pytest.approx(expected.metrics.win_rate)
    assert summary.trade_count == expected.metrics.trade_count
    assert summary.winning_trades == expected.metrics.winning_trades
    assert summary.losing_trades == expected.metrics.losing_trades
    assert summary.final_equity == pytest.approx(expected.equity[-1].value)


def test_the_replayed_equity_curve_matches_the_performance_curve(seeded):
    """Not just the bottom line: every daily mark agrees, so the only
    difference between replay and performance is when you observe them."""
    backend, store, run = seeded
    signals, bars = replay_engine.load_replay_inputs(backend, store, run)
    events = list(replay_engine.replay_events(run, signals, bars))

    expected = performance.compute_performance(
        run_id=run["id"],
        signals=signals,
        bars_by_symbol=bars,
        symbols=list(run["symbols"]),
    )
    marks = [e for e in events if isinstance(e, ReplayEquity)]
    assert len(marks) == len(expected.equity)
    for mark, point in zip(marks, expected.equity, strict=True):
        assert mark.date == point.date
        assert mark.equity == pytest.approx(point.value)


def test_replaying_twice_yields_identical_event_streams(seeded):
    backend, store, run = seeded
    signals, bars = replay_engine.load_replay_inputs(backend, store, run)

    first = [replay_engine.to_dict(e) for e in replay_engine.replay_events(run, signals, bars)]
    second = [replay_engine.to_dict(e) for e in replay_engine.replay_events(run, signals, bars)]

    assert first == second


def test_step_thins_bar_events_but_never_signals_or_equity(seeded):
    _, signals, bars, events = _events(seeded)
    thinned = list(replay_engine.replay_events(_events(seeded)[0], signals, bars, step=7))

    def count(evts, kind):
        return sum(1 for e in evts if isinstance(e, kind))

    assert count(thinned, ReplayBar) < count(events, ReplayBar)
    assert count(thinned, ReplaySignal) == count(events, ReplaySignal)
    assert count(thinned, ReplayFill) == count(events, ReplayFill)
    assert count(thinned, ReplayEquity) == count(events, ReplayEquity)
    # A date carrying a signal always keeps its bar event.
    signal_dates = {e.date for e in thinned if isinstance(e, ReplaySignal)}
    bar_dates = {e.date for e in thinned if isinstance(e, ReplayBar)}
    assert signal_dates <= bar_dates


def test_a_signal_on_a_date_with_no_bar_fires_but_cannot_transact():
    run = {"id": "r", "symbols": ["AAA"]}
    bars = {
        "AAA": [
            Bar("2024-01-01", 100.0, 100.0, 100.0, 100.0, 1),
            Bar("2024-01-02", 110.0, 110.0, 110.0, 110.0, 1),
        ]
    }
    signals = [
        {
            "symbol": "AAA",
            "date": "2024-06-30",  # no bar anywhere that day
            "direction": "bullish",
            "trigger_values": {},
            "data_window_end": "2024-06-30",
        }
    ]

    events = list(replay_engine.replay_events(run, signals, bars))

    assert any(isinstance(e, ReplaySignal) and e.date == "2024-06-30" for e in events)
    assert not [e for e in events if isinstance(e, ReplayFill)]
    summary = events[-1]
    assert isinstance(summary, ReplaySummary)
    assert summary.total_return == 0.0
    assert summary.trade_count == 0
