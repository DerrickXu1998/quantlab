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

from quantlab.execution import ExecutionConfig
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
    # Stored as a run recorded today would be: live replays under the current
    # defaults, so the batch run must name them rather than leave them unset
    # (an unset config means a run from before execution criteria existed).
    run = {"id": "batch", "symbols": list(SYMBOLS), "execution": ExecutionConfig().to_dict()}
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
    """Warm-up shorter than the declared lookback: every in-window signal a
    batch run over the same bars emits is emitted live too (and, see below,
    on its own date)."""
    warmup = 10
    truncated = {}
    for symbol in SYMBOLS:
        series = bars_by_symbol[symbol]
        first_in_window = next(i for i, bar in enumerate(series) if bar.date >= START)
        truncated[symbol] = series[first_in_window - warmup :]
    # tail = slow + 1 = 9, far below the default's declared lookback of 51.
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


# --- causal emission with a short warm-up -------------------------------------


def _short_warmup(bars_by_symbol, warmup=10):
    truncated = {}
    for symbol in SYMBOLS:
        series = bars_by_symbol[symbol]
        first_in_window = next(i for i, bar in enumerate(series) if bar.date >= START)
        truncated[symbol] = series[first_in_window - warmup :]
    return truncated


def _signal_days(events):
    """(signal date, date of the bar frame it was emitted under), in order."""
    current = None
    out = []
    for event in events:
        if isinstance(event, ReplayBar):
            current = event.date
        elif isinstance(event, ReplaySignal):
            out.append((event.date, current))
    return out


@pytest.mark.parametrize(
    "overrides",
    [{"fast": 3, "slow": 8}, {"fast": 5, "slow": 30}, None],
    ids=["tail-below-warmup", "tail-above-warmup", "defaults"],
)
def test_short_warmup_live_is_the_batch_run_event_for_event(bars_by_symbol, overrides):
    """Not just the same set of signals: the same signals in the same order on
    their own dates, the same fills on the same dates at the same prices, the
    same equity curve and the same result."""
    truncated = _short_warmup(bars_by_symbol)
    live_events = list(
        live.live_replay_events(
            "sma-crossover", overrides, list(SYMBOLS), START, END, _stream(truncated)
        )
    )
    batch_events = _batch_events(truncated, overrides=overrides)

    def signals(events):
        return [(e.date, e.symbol, e.direction) for e in events if isinstance(e, ReplaySignal)]

    def fills(events):
        return [
            (e.date, e.symbol, e.side, round(e.qty, 9), round(e.price, 9), e.reason)
            for e in events if isinstance(e, replay_engine.ReplayFill)
        ]

    def marks(events):
        return [(e.date, round(e.equity, 6)) for e in events if isinstance(e, ReplayEquity)]

    assert signals(live_events), "the fixture must fire in-window signals"
    assert signals(live_events) == signals(batch_events)
    assert fills(live_events) == fills(batch_events)
    assert marks(live_events) == marks(batch_events)
    live_summary, batch_summary = live_events[-1], batch_events[-1]
    for field in ("final_equity", "total_return", "trade_count", "win_rate"):
        assert getattr(live_summary, field) == pytest.approx(getattr(batch_summary, field))


def test_a_january_signal_is_never_emitted_or_traded_in_february(bars_by_symbol):
    """The reproduced bug: with 10 warm-up bars and slow=8, replay waited for
    the *declared* 51-bar lookback, then released every January signal on a
    February arrival date -- and the simulator filled them at February prices."""
    truncated = _short_warmup(bars_by_symbol)
    events = list(
        live.live_replay_events(
            "sma-crossover", {"fast": 3, "slow": 8}, list(SYMBOLS), START, END,
            _stream(truncated),
        )
    )
    days = _signal_days(events)
    assert any(signal.startswith("2024-01") for signal, _ in days), "needs a January signal"
    assert all(signal == emitted for signal, emitted in days), days[:5]
    # Every signal's fill (signal-day decision, next-open default) lands after
    # it, never before, and no fill is dated before a bar frame for it.
    bar_dates = [e.date for e in events if isinstance(e, ReplayBar)]
    fill_dates = [e.date for e in events if isinstance(e, replay_engine.ReplayFill)]
    assert fill_dates and set(fill_dates) <= set(bar_dates)
    assert bar_dates == sorted(bar_dates)


def test_a_filter_only_rule_is_refused_by_live_replay_as_by_batch(bars_by_symbol):
    from quantlab.research import runner

    with pytest.raises(errors.ParameterValidationError) as batch_error:
        runner.resolve_spec(model_name="adx-trend-filter")
    with pytest.raises(errors.ParameterValidationError) as live_error:
        live.live_replay_events(
            "adx-trend-filter", None, list(SYMBOLS), START, END, _stream(bars_by_symbol)
        )
    assert str(live_error.value) == str(batch_error.value)
    with pytest.raises(errors.ParameterValidationError):
        live.resolve_rule("adx-trend-filter", {})


def test_an_out_of_order_bar_stops_the_replay_instead_of_rewinding_it(bars_by_symbol):
    stream = [m for m in _stream(bars_by_symbol, start="2024-03-01", end="2024-03-31")]
    late = next(m for m in stream if m.get("date") == "2024-03-05")
    stream.remove(late)
    stream.insert(len(stream) - 1, late)  # after the last March bar, before "end"

    emitted = []
    with pytest.raises(live.OutOfOrderBarError, match="2024-03-05"):
        for event in live.live_replay_events(
            "sma-crossover", {"fast": 3, "slow": 8}, list(SYMBOLS), "2024-03-01",
            "2024-03-31", stream,
        ):
            emitted.append(event)
    dates = [e.date for e in emitted if isinstance(e, ReplayBar | ReplayEquity)]
    assert dates == sorted(dates)
    assert not any(isinstance(e, ReplaySummary) for e in emitted)
