"""Live replay over the event bus: a strategy consuming history as it arrives.

The streaming counterpart of ``replay.engine.replay_events``. A publisher
(library-side ``quantlab.streaming.publish_replay``) has already turned a
warehouse window into a chronological bar stream on a Kafka topic; here the
backend consumes that stream, re-runs the rule's ``compute`` on each symbol's
history as every bar arrives, and trades the new signals through the
same ``ExecutionSimulator``. Rules that declare a ``windowed_lookback`` -- a
mathematically bounded window -- are handed only that tail of the history,
keeping the per-day recompute O(lookback) rather than O(history); recursive
rules still see the whole growing window, because truncating an EMA or RSI
would change its values.

The key invariant -- live == batch -- rests on Constitution VII: the rules are
causal, and the truncation sweep proves ``compute`` on a truncated history is
identical to batch. So each arriving day is computed against exactly the
history that existed that day, and only an event dated that day is emitted
and traded. A signal is never released later than its own date: a backdated
event would be filled at a later session's prices, which no batch run does.
Each ``(symbol, date)`` is computed once -- a duplicate bar is skipped -- so
nothing is ever emitted twice; every event the rule dates that day is kept,
as batch keeps them.

There is no lookback gate here: the rule itself is silent until its
indicators are defined, and gating on a (conservatively declared) lookback
would drop the first in-window events of a short warm-up that a batch run
over the same bars keeps. One divergence is inherent: batch skips a symbol
whose *whole* loaded history is shorter than the lookback, which a stream
cannot know until it ends. Such a symbol (say, listed days before ``end``) can
signal here and not in batch; the summary then does not reconcile.

Warm-up mirrors ``research.runner``: bars dated before ``start`` extend the
compute windows (a slow SMA needs its lookback) but produce no events and no
trades. Bars after ``end``, symbols outside the selection, and duplicate
(symbol, date) bars -- a re-published overlapping range on the same topic --
are ignored. A bar dated *before* one already consumed is not ignored: the
stream has stopped being chronological, and replay refuses it
(:class:`OutOfOrderBarError`) rather than walking the book backwards. So a
re-publish is tolerated only as far as it repeats bars already consumed: one
that brings a selected symbol's history for the first time (publish 1 had
[A, B], publish 2 adds C over the same range) is out of order, and is refused
rather than silently dropping C. Publish a selection's symbols together.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from quantlab.execution import Decision, ExecutionConfig, ExecutionSimulator
from quantlab.replay import engine as replay_engine
from quantlab.replay.engine import (
    ReplayBar,
    ReplayEquity,
    ReplayEvent,
    ReplayFill,
    ReplaySignal,
)
from quantlab.research import errors, performance, runner

# The input shape the signal rules are documented against (date + OHLCV,
# ascending). Reused rather than redeclared so the bus payload and the
# warehouse read path stay the same type.
from quantlab.storage.warehouse import Bar


class OutOfOrderBarError(ValueError):
    """The stream delivered a bar dated before one it already delivered."""

    def __init__(self, symbol: str, date: str, latest: str) -> None:
        self.symbol = symbol
        self.date = date
        self.latest = latest
        super().__init__(
            f"out-of-order bar: {symbol} {date} arrived after {latest}; "
            "a live replay needs a chronological stream (were the selected symbols "
            "published separately? publish them together)"
        )


def resolve_rule(model_name: str, overrides: dict[str, Any]):
    """Same resolution and validation a batch run gets, with its errors.

    Public so the API layer can validate a request eagerly (404/422) before
    opening a stream, without touching the bus first. Role validation goes
    through the batch path itself (``runner.resolve_spec``), so a filter-only
    rule -- one that reports a regime, not a tradeable event -- is refused
    here exactly as a batch run refuses it.
    """
    rule = runner.resolve_model(model_name, None)
    effective = runner.validate_overrides(rule, dict(overrides))
    runner.resolve_spec(model_name=model_name, parameters=dict(overrides))
    return rule, effective


def live_replay_events(
    model_name: str,
    overrides: dict[str, Any] | None,
    symbols: list[str],
    start: str,
    end: str,
    bar_stream,
    *,
    initial_cash: float = performance.INITIAL_CAPITAL,
) -> Iterator[ReplayEvent]:
    """Consume bars and yield the same event types as the batch replay.

    Validation is eager -- an unknown model or a bad override raises before
    the first bar is consumed, so the HTTP layer can answer 404/422 instead of
    failing mid-stream. ``bar_stream`` is any iterable of bar dicts
    (``{"symbol", "date", "open", "high", "low", "close", "volume"}``),
    chronological by (date, symbol), optionally terminated by a
    ``{"type": "end"}`` control message; ``streaming.bus.KafkaBarStream`` is
    the production one, a list the test one.
    """
    if start > end:
        raise errors.InvalidWindowError("start must be on or before end")
    rule, effective = resolve_rule(model_name, overrides or {})
    symbols = sorted(set(symbols))
    if not symbols:
        raise errors.UnknownSymbolError([])
    selected = set(symbols)

    # The same engine the batch replay drives, stepped one date at a time as
    # bars arrive. A live replay and a batch one over the same window cannot
    # disagree about what the strategy did, because there is only one engine.
    config = ExecutionConfig(initial_capital=initial_cash)
    sim = ExecutionSimulator(symbols, {symbol: [] for symbol in symbols}, config)
    windows: dict[str, list[Bar]] = {symbol: [] for symbol in symbols}
    seen_bars: dict[str, set[str]] = {symbol: set() for symbol in symbols}
    curve: list[performance.EquityPoint] = []
    # Rules with a mathematically bounded window (declared on the rule) need
    # only their tail of the history, not the whole growing window -- that
    # turns the per-day recompute from O(history) into O(lookback). Recursive
    # rules declare no bound and keep the full window: front-truncating an
    # EMA or RSI would change its values, not just its length.
    tail_days = (
        rule.windowed_lookback(effective) if rule.windowed_lookback is not None else None
    )

    def process_day(day: str, todays: dict[str, Bar]) -> Iterator[ReplayEvent]:
        """One in-window date: bar, then new signals, their fills, one equity
        mark -- the batch engine's per-date order, exactly."""
        closes = {symbol: bar.close for symbol, bar in sorted(todays.items())}
        yield ReplayBar(date=day, closes=closes)

        new: list[tuple[str, Any]] = []
        for symbol in sorted(todays):
            # The history as of today, and nothing else: the window ends with
            # today's bar. A bounded rule needs only its tail of it.
            window = windows[symbol]
            if tail_days is not None and len(window) > tail_days:
                window = window[-tail_days:]
            for event in rule.compute(window, **effective):
                # Only today's event. An earlier-dated one was either emitted
                # on its own day or could not have been (history too short
                # then); releasing it now would trade a past signal at
                # today's prices -- a fill no batch run makes.
                if event.date != day:
                    continue
                new.append((symbol, event))

        for symbol, event in new:  # already (symbol)-ordered by the scan above
            yield ReplaySignal(
                date=event.date,
                symbol=symbol,
                direction=event.direction,
                trigger_values=dict(event.trigger_values),
                data_window_end=event.data_window_end,
                kind="both",
            )

        # One rule filling both roles, which is what a single-model run is:
        # bullish opens, bearish closes.
        state = sim.step_day(
            day,
            [
                Decision(
                    date=event.date,
                    symbol=symbol,
                    kind="both",
                    direction=event.direction,
                    trigger_values=dict(event.trigger_values),
                    data_window_end=event.data_window_end,
                )
                for symbol, event in new
            ],
        )
        for fill in state.fills:
            yield ReplayFill(
                date=fill.date,
                symbol=fill.symbol,
                side=fill.side,
                qty=fill.qty,
                price=fill.price,
                value=fill.value,
                realized_pnl=fill.realized_pnl,
                reason=fill.reason,
                commission=fill.commission,
                slippage=fill.slippage,
            )
        yield ReplayEquity(
            date=day,
            equity=state.equity,
            cash=state.cash,
            positions=state.positions,
            realized_pnl=state.realized_pnl,
        )
        curve.append(performance.EquityPoint(date=day, value=state.equity))

    def generate() -> Iterator[ReplayEvent]:
        pending_date: str | None = None
        pending: dict[str, Bar] = {}
        latest_date: str | None = None  # the newest bar date consumed so far
        for message in bar_stream:
            if message.get("type") == "end":
                break
            symbol = message.get("symbol")
            date = message.get("date")
            if symbol not in selected or date is None:
                continue
            if date > end:
                break  # the stream is chronological; nothing relevant follows
            if date in seen_bars[symbol]:
                continue  # an overlapping re-publish on the topic, not a new bar
            if latest_date is not None and date < latest_date:
                # Appending it would put a past bar at the end of a window and
                # step the book back to a date it has already closed.
                raise OutOfOrderBarError(symbol, date, latest_date)
            latest_date = date
            # Flush the finished date BEFORE this bar joins a window, so a
            # compute for day T never sees a bar from T+1 (Constitution VII) --
            # an early-discovered signal would break chronology.
            if pending_date is not None and date != pending_date:
                yield from process_day(pending_date, pending)
                pending = {}
            seen_bars[symbol].add(date)
            bar = Bar(
                date=date,
                open=float(message["open"]),
                high=float(message["high"]),
                low=float(message["low"]),
                close=float(message["close"]),
                volume=int(message["volume"]),
            )
            windows[symbol].append(bar)
            sim.ingest(symbol, bar)
            if date < start:
                continue  # warm-up: feeds the compute window, emits nothing
            pending_date = date
            pending[symbol] = bar
        if pending_date is not None:
            yield from process_day(pending_date, pending)
        yield replay_engine.summary_event(f"live:{rule.name}", sim, curve)

    return generate()
