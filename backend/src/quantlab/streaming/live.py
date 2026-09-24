"""Live replay over the event bus: a strategy consuming history as it arrives.

The streaming counterpart of ``replay.engine.replay_events``. A publisher
(library-side ``quantlab.streaming.publish_replay``) has already turned a
warehouse window into a chronological bar stream on a Kafka topic; here the
backend consumes that stream, re-runs the rule's ``compute`` on each symbol's
history as every bar arrives, and trades the new signals through the
same ``PortfolioSimulator``. Rules that declare a ``windowed_lookback`` -- a
mathematically bounded window -- are handed only that tail of the history,
keeping the per-day recompute O(lookback) rather than O(history); recursive
rules still see the whole growing window, because truncating an EMA or RSI
would change its values.

The key invariant -- live == batch -- rests on Constitution VII: the rules are
causal, and the truncation sweep proves ``compute`` on a truncated history is
identical to batch, so recomputing on a growing window emits exactly the
signals a batch run over the same bars stores. A ``fired`` set on
``(symbol, signal date)`` keeps each recompute from re-emitting old signals.

Warm-up mirrors ``research.runner``: bars dated before ``start`` extend the
compute windows (a slow SMA needs its lookback) but produce no events and no
trades. Bars after ``end``, symbols outside the selection, and duplicate
(symbol, date) bars -- a re-published overlapping range on the same topic --
are ignored.
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


def resolve_rule(model_name: str, overrides: dict[str, Any]):
    """Same resolution and validation a batch run gets, with its errors.

    Public so the API layer can validate a request eagerly (404/422) before
    opening a stream, without touching the bus first.
    """
    rule = runner.resolve_model(model_name, None)
    effective = runner.validate_overrides(rule, dict(overrides))
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
    fired: set[tuple[str, str]] = set()  # (symbol, signal date)
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
            window = windows[symbol]
            # Engine parity: a rule stays silent until its lookback exists.
            if len(window) < rule.lookback_days:
                continue
            # Truncate only past the day the untruncated compute became
            # possible (len == lookback_days, the `continue` above grows the
            # window one bar at a time). That day's full-window compute emits
            # every retroactive in-window signal and records them in `fired`,
            # so from the next bar on the tail holds nothing new.
            if tail_days is not None and len(window) > max(tail_days, rule.lookback_days):
                window = window[-tail_days:]
            for event in rule.compute(window, **effective):
                key = (symbol, event.date)
                if key in fired:
                    continue
                fired.add(key)
                # Causal rules emit at the arriving bar's date, so new events
                # land on `day`; an out-of-window date is warm-up history.
                if start <= event.date <= day:
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
            # Flush the finished date BEFORE this bar joins a window, so a
            # compute for day T never sees a bar from T+1 (Constitution VII) --
            # an early-discovered signal would both break chronology and
            # poison the fired set, suppressing its own emission.
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
