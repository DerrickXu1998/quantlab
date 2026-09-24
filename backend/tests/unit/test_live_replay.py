"""Live replay: consuming a chronological bar stream drives the same engine.

No Kafka here -- ``live_replay_events`` takes any iterable of bar dicts, so a
list stands in for the topic. The invariant under test is the point of the
truncation sweep: a rule recomputed on a growing window emits exactly the
signals a batch run computes over the same bars, so the live summary IS the
batch replay summary.
"""

from __future__ import annotations

import dataclasses

import pytest

from quantlab.replay import engine as replay_engine
from quantlab.replay.engine import (
    ReplayBar,
    ReplayEquity,
    ReplaySignal,
    ReplaySummary,
)
from quantlab.research import errors
from quantlab.signals import registry as signal_registry
from quantlab.signals.engine import compute_signals
from quantlab.streaming import live
from quantlab.synthetic.generator import generate_universe

START = "2024-01-01"
END = "2024-12-31"
SYMBOLS = ["ZZMEAN", "ZZTRND"]


@pytest.fixture(scope="module")
def bars_by_symbol():
    return {symbol: generate_universe()[symbol] for symbol in SYMBOLS}


def _stream(bars_by_symbol, symbols=SYMBOLS, start=None, end=None, with_end=True):
    """The publisher's wire format, from a list instead of a topic."""
    messages = [
        {
            "type": "bar",
            "symbol": symbol,
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        for symbol in symbols
        for bar in bars_by_symbol[symbol]
        if (start is None or bar.date >= start) and (end is None or bar.date <= end)
    ]
    messages.sort(key=lambda m: (m["date"], m["symbol"]))
    if with_end:
        messages.append({"type": "end"})
    return messages


def _batch_events(bars_by_symbol, model_name="sma-crossover", overrides=None):
    """The batch counterpart: runner semantics (warm-up compute, in-window
    signals) replayed over the window's bars."""
    rule = signal_registry.get_rule(model_name)
    computed = compute_signals(bars_by_symbol, rules=[rule], overrides=overrides or {})
    signals = [
        {
            "symbol": s.symbol,
            "date": s.date,
            "direction": s.direction,
            "trigger_values": s.trigger_values,
            "data_window_end": s.data_window_end,
        }
        for s in computed
        if START <= s.date <= END
    ]
    window_bars = {
        symbol: [b for b in bars if START <= b.date <= END]
        for symbol, bars in bars_by_symbol.items()
    }
    run = {"id": "batch", "symbols": list(SYMBOLS)}
    return list(replay_engine.replay_events(run, signals, window_bars))


def _live_events(bars_by_symbol, **kwargs):
    stream = _stream(bars_by_symbol)  # full history: warm-up included
    return list(
        live.live_replay_events("sma-crossover", None, list(SYMBOLS), START, END, stream, **kwargs)
    )


def test_live_summary_reconciles_with_batch_replay(bars_by_symbol):
    """THE invariant: live == batch, reduced to the terminal summary."""
    live_summary = _live_events(bars_by_symbol)[-1]
    batch_summary = _batch_events(bars_by_symbol)[-1]

    assert isinstance(live_summary, ReplaySummary)
    assert isinstance(batch_summary, ReplaySummary)
    assert batch_summary.trade_count > 0, "the fixture must actually trade"
    for field in (
        "days",
        "initial_cash",
        "final_equity",
        "total_return",
        "sharpe_ratio",
        "max_drawdown",
        "win_rate",
        "trade_count",
        "winning_trades",
        "losing_trades",
    ):
        assert getattr(live_summary, field) == pytest.approx(
            getattr(batch_summary, field)
        ), field


def test_live_equity_curve_matches_batch_point_for_point(bars_by_symbol):
    live_marks = [e for e in _live_events(bars_by_symbol) if isinstance(e, ReplayEquity)]
    batch_marks = [e for e in _batch_events(bars_by_symbol) if isinstance(e, ReplayEquity)]

    assert len(live_marks) == len(batch_marks)
    for live_mark, batch_mark in zip(live_marks, batch_marks, strict=True):
        assert live_mark.date == batch_mark.date
        assert live_mark.equity == pytest.approx(batch_mark.equity)


def test_recompute_never_reemits_a_signal(bars_by_symbol):
    """Compute re-emits the whole history every bar; the fired set diffs it."""
    events = _live_events(bars_by_symbol)
    fired = [(e.symbol, e.date) for e in events if isinstance(e, ReplaySignal)]
    assert fired, "the fixture must fire signals"
    assert len(fired) == len(set(fired)), "duplicate signal events"
    batch = {(e.symbol, e.date) for e in _batch_events(bars_by_symbol)
             if isinstance(e, ReplaySignal)}
    assert set(fired) == batch


def test_events_are_chronological_and_pit(bars_by_symbol):
    events = _live_events(bars_by_symbol)
    dated = [e.date for e in events if not isinstance(e, ReplaySummary)]
    assert dated == sorted(dated)
    assert all(START <= d <= END for d in dated), "warm-up must emit nothing"

    seen_bar_dates: set[str] = set()
    for event in events:
        if isinstance(event, ReplayBar):
            seen_bar_dates.add(event.date)
        elif isinstance(event, ReplaySignal):
            assert event.date in seen_bar_dates
            assert event.data_window_end <= event.date  # Constitution VII


def test_bars_outside_the_window_and_off_selection_are_ignored(bars_by_symbol):
    extra = dict(bars_by_symbol)
    extra["ZZWAVE"] = generate_universe()["ZZWAVE"]
    events = list(
        live.live_replay_events(
            "sma-crossover", None, list(SYMBOLS), START, END, _stream(extra)
        )
    )
    symbols_seen = {s for e in events if isinstance(e, ReplaySignal) for s in [e.symbol]}
    closes_seen = {s for e in events if isinstance(e, ReplayBar) for s in e.closes}
    assert symbols_seen <= set(SYMBOLS)
    assert closes_seen <= set(SYMBOLS)


def test_duplicate_bars_from_a_republish_are_deduplicated(bars_by_symbol):
    once = _live_events(bars_by_symbol)
    twice = list(
        live.live_replay_events(
            "sma-crossover", None, list(SYMBOLS), START, END,
            _stream(bars_by_symbol, with_end=False) + _stream(bars_by_symbol),
        )
    )
    assert [replay_engine.to_dict(e) for e in once] == [
        replay_engine.to_dict(e) for e in twice
    ]


def test_stream_without_end_message_still_summarises(bars_by_symbol):
    events = list(
        live.live_replay_events(
            "sma-crossover", None, list(SYMBOLS), START, END,
            _stream(bars_by_symbol, with_end=False),
        )
    )
    assert isinstance(events[-1], ReplaySummary)


def test_overrides_flow_to_the_rule(bars_by_symbol):
    overrides = {"fast": 5, "slow": 15}
    live_summary = list(
        live.live_replay_events(
            "sma-crossover", overrides, list(SYMBOLS), START, END,
            _stream(bars_by_symbol),
        )
    )[-1]
    batch_summary = _batch_events(bars_by_symbol, overrides=overrides)[-1]
    assert live_summary.total_return == pytest.approx(batch_summary.total_return)
    assert live_summary.trade_count == batch_summary.trade_count


def test_validation_is_eager_and_typed(bars_by_symbol):
    stream = _stream(bars_by_symbol)
    with pytest.raises(errors.UnknownModelError):
        live.live_replay_events("no-such-model", None, list(SYMBOLS), START, END, stream)
    with pytest.raises(errors.ParameterValidationError):
        live.live_replay_events("sma-crossover", {"fast": 1}, list(SYMBOLS), START, END, stream)
    with pytest.raises(errors.InvalidWindowError):
        live.live_replay_events("sma-crossover", None, list(SYMBOLS), END, START, stream)


# --- Windowed compute: the per-day recompute stays O(lookback) -----------------


def test_bounded_rules_compute_over_a_fixed_tail_not_the_growing_window(
    monkeypatch, bars_by_symbol
):
    """A rule that declares a windowed lookback is handed at most its tail of
    the history, and the run is still the batch run."""
    rule = signal_registry.get_rule("sma-crossover")
    assert rule.windowed_lookback is not None
    window_lengths: list[int] = []
    real_resolve = live.resolve_rule

    def recording_resolve(model_name, overrides):
        resolved, effective = real_resolve(model_name, overrides)
        compute = resolved.compute

        def recording_compute(bars, **kwargs):
            window_lengths.append(len(bars))
            return compute(bars, **kwargs)

        return dataclasses.replace(resolved, compute=recording_compute), effective

    monkeypatch.setattr(live, "resolve_rule", recording_resolve)
    live_summary = _live_events(bars_by_symbol)[-1]
    batch_summary = _batch_events(bars_by_symbol)[-1]

    assert len(window_lengths) > 100, "the fixture must recompute per day per symbol"
    assert max(window_lengths) <= rule.lookback_days + 1
    for field in (
        "days",
        "final_equity",
        "total_return",
        "sharpe_ratio",
        "max_drawdown",
        "win_rate",
        "trade_count",
    ):
        assert getattr(live_summary, field) == pytest.approx(
            getattr(batch_summary, field)
        ), field


def test_short_warmup_still_emits_the_batch_signal_dates(bars_by_symbol):
    """Warm-up shorter than the lookback: the first compute day must run over
    the whole window, or the retroactive in-window signals a batch run emits
    would be truncated away."""
    warmup = 10
    truncated = {}
    for symbol in SYMBOLS:
        series = bars_by_symbol[symbol]
        first_in_window = next(i for i, bar in enumerate(series) if bar.date >= START)
        truncated[symbol] = series[first_in_window - warmup :]
    # tail = slow + 1 = 9 < lookback_days = 51, the case the guard exists for.
    overrides = {"fast": 3, "slow": 8}

    live_signals = [
        (e.symbol, e.date, e.direction)
        for e in live.live_replay_events(
            "sma-crossover", overrides, list(SYMBOLS), START, END, _stream(truncated)
        )
        if isinstance(e, ReplaySignal)
    ]

    rule = signal_registry.get_rule("sma-crossover")
    computed = compute_signals(truncated, rules=[rule], overrides=overrides)
    batch_signals = {
        (s.symbol, s.date, s.direction) for s in computed if START <= s.date <= END
    }

    assert live_signals, "the fixture must fire in-window signals"
    assert len(live_signals) == len(set(live_signals)), "duplicate signal events"
    assert set(live_signals) == batch_signals


# --- The bus adapter, without a broker ----------------------------------------


def test_unconfigured_bus_reports_not_configured(monkeypatch):
    monkeypatch.delenv("QUANTLAB_KAFKA_BROKERS", raising=False)
    from quantlab.streaming import bus

    assert not bus.configured()


def test_unreachable_broker_raises_bus_unavailable():
    kafka = pytest.importorskip("kafka")
    from quantlab.streaming import bus

    stream = bus.KafkaBarStream(
        "127.0.0.1:9",  # discard port: connection refused, no network needed
        "quantlab.bars",
        SYMBOLS,
        START,
        END,
        connect_timeout_ms=1_000,
    )
    with pytest.raises(bus.BusUnavailable):
        stream.open()
    assert kafka  # the skip above is the real guard
