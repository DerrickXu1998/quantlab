"""Replay engine: a run's window as a chronological event stream.

Pure computation (Constitutions I and VI): ``replay_events`` takes the run
record, its stored signals and its window's bars, and yields typed events in
strict chronological order -- bars first on each date, then the signals that
fire that day, then the fills they produced, then one equity mark. A signal
therefore never precedes the bar event of its own date, and the simulator never
touches a later bar (Constitution VII).

The book is driven by :class:`~quantlab.execution.ExecutionSimulator`, the same
engine that produced the run and that ``research.performance`` re-executes. This
module used to carry its own copy of the sizing and pairing rules, which meant
a replay and its performance report agreed only for as long as somebody kept
two implementations in step by hand. They now cannot disagree.

That change also fixed a quieter bug: the old replay reduced every bar to its
close before the simulator saw it, so a stop or a target -- which are triggered
by a session's high and low -- could never fire in a replay even when the run
that produced the same numbers had them.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any

from quantlab.execution import ExecutionConfig, ExecutionSimulator
from quantlab.research import performance
from quantlab.research.runner import execution_config_for


@dataclass(frozen=True)
class ReplayBar:
    """One trading date's closes, compact: only run symbols with a bar."""

    date: str
    closes: dict[str, float]


@dataclass(frozen=True)
class ReplaySignal:
    """A stored signal as it fires on its date."""

    date: str
    symbol: str
    direction: str
    trigger_values: dict[str, Any]
    data_window_end: str
    #: entry / exit / both -- what the strategy meant by it.
    kind: str = "both"


@dataclass(frozen=True)
class ReplayFill:
    """A trade the simulator executed."""

    date: str
    symbol: str
    side: str  # "buy" | "sell" | "short" | "cover"
    qty: float
    price: float
    value: float
    realized_pnl: float
    #: "signal" on the way in; on the way out, which criterion closed it.
    reason: str = "signal"
    commission: float = 0.0
    slippage: float = 0.0


@dataclass(frozen=True)
class ReplayEquity:
    """End-of-date book state, emitted once per replayed date."""

    date: str
    equity: float
    cash: float
    positions: int
    realized_pnl: float


@dataclass(frozen=True)
class ReplaySummary:
    """Terminal event: the whole replay reduced to its metrics."""

    run_id: str
    days: int
    initial_cash: float
    final_equity: float
    total_return: float
    sharpe_ratio: float | None
    max_drawdown: float
    win_rate: float | None
    trade_count: int
    winning_trades: int
    losing_trades: int
    assumptions: list[str]
    exit_reasons: dict[str, int] | None = None
    total_commission: float = 0.0
    total_slippage: float = 0.0


ReplayEvent = ReplayBar | ReplaySignal | ReplayFill | ReplayEquity | ReplaySummary

_KIND = {
    ReplayBar: "bar",
    ReplaySignal: "signal",
    ReplayFill: "fill",
    ReplayEquity: "equity",
    ReplaySummary: "summary",
}


def to_dict(event: ReplayEvent) -> dict:
    """JSON-ready frame payload; the ``event`` field carries the kind."""
    body = asdict(event)
    body["event"] = _KIND[type(event)]
    return body


def load_replay_inputs(backend, experiments, run: dict) -> tuple[list[dict], dict]:
    """The I/O seam: everything a replay needs, loaded once.

    Bars are loaded from the run's warm-up start, not its window start. The
    reported events still begin at the window -- no decision exists before it --
    but an ATR stop set on the first session needs the sessions behind it, and
    loading only the window silently disabled it.
    """
    from quantlab.research import runner as research_runner

    signals = experiments.get_run_signals(run["id"])
    lookback = _lookback_days(run)
    warmup_start = _shift(run["start_date"], -lookback * research_runner._CALENDAR_DAYS_PER_BAR)
    bars = backend.load_bars_for(list(run["symbols"]), warmup_start, run["end_date"])
    return signals, bars


def _lookback_days(run: dict) -> int:
    """How much warm-up this run's strategy needs, from its stored spec."""
    from quantlab.strategy import StrategySpec, StrategyValidationError

    stored = run.get("strategy")
    if stored:
        try:
            return StrategySpec.from_dict(stored).lookback_days
        except (StrategyValidationError, ValueError):
            pass
    # A run recorded before strategies existed, or one whose spec this build
    # cannot read: fall back to the rule it names, then to nothing.
    from quantlab.signals.registry import get_rule

    try:
        return get_rule(run["model_name"], run.get("model_version")).lookback_days
    except (KeyError, TypeError):
        return 0


def _shift(iso_date: str, days: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def replay_events(
    run: dict,
    signals: list[dict],
    bars_by_symbol: dict,
    *,
    initial_cash: float | None = None,
    step: int = 1,
    config: ExecutionConfig | None = None,
) -> Iterator[ReplayEvent]:
    """Yield the run's window as a chronological event stream.

    ``step`` thins bar events to every Nth date (equity, signal and fill events
    are never thinned); a date that carries a signal always gets its bar event
    regardless, so a fill never appears without the price that produced it.
    """
    symbols = list(run["symbols"])
    config = config or execution_config_for(run)
    if initial_cash is not None and initial_cash != config.initial_capital:
        from dataclasses import replace

        config = replace(config, initial_capital=initial_cash)

    decisions = performance.to_decisions(signals)
    signals_on: dict[str, list[dict]] = {}
    for signal in signals:
        signals_on.setdefault(signal["date"], []).append(signal)
    for same_day in signals_on.values():
        same_day.sort(key=lambda s: s["symbol"])  # deterministic within a date

    simulator = ExecutionSimulator(symbols, bars_by_symbol, config)
    # Absent when a caller hands over only the window's bars and has no warm-up
    # to skip -- in which case every date supplied is part of the replay.
    window_start = run.get("start_date")
    curve: list[performance.EquityPoint] = []
    emitted = 0

    for day in simulator.iter_days(decisions):
        # Warm-up sessions are inputs, not part of the period being replayed.
        # Nothing can have happened in them: no decision is dated there.
        if window_start is not None and day.date < window_start:
            continue

        if day.closes and (emitted % step == 0 or day.date in signals_on):
            yield ReplayBar(date=day.date, closes=day.closes)
        emitted += 1

        for signal in signals_on.get(day.date, []):
            yield ReplaySignal(
                date=day.date,
                symbol=signal["symbol"],
                direction=signal["direction"],
                trigger_values=signal["trigger_values"],
                data_window_end=signal["data_window_end"],
                kind=signal.get("kind") or "both",
            )

        for fill in day.fills:
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
            date=day.date,
            equity=day.equity,
            cash=day.cash,
            positions=day.positions,
            realized_pnl=day.realized_pnl,
        )
        if day.closes:
            curve.append(performance.EquityPoint(date=day.date, value=day.equity))

    yield summary_event(run["id"], simulator, curve)


def summary_event(
    run_id: str,
    simulator: ExecutionSimulator,
    curve: list[performance.EquityPoint],
) -> ReplaySummary:
    """Reduce a finished simulation to its terminal event.

    Shared by the batch replay and the live (Kafka-consumed) replay so both
    paths reduce the book with exactly the same helpers.
    """
    trades = simulator.trades()
    stats = performance.metrics(curve, trades)
    summary = simulator.summary()
    reasons: dict[str, int] = {}
    for trade in trades:
        reasons[trade.exit_reason] = reasons.get(trade.exit_reason, 0) + 1

    return ReplaySummary(
        run_id=run_id,
        days=len(curve),
        initial_cash=simulator.config.initial_capital,
        final_equity=curve[-1].value if curve else simulator.config.initial_capital,
        total_return=stats.total_return,
        sharpe_ratio=stats.sharpe_ratio,
        max_drawdown=stats.max_drawdown,
        win_rate=stats.win_rate,
        trade_count=stats.trade_count,
        winning_trades=stats.winning_trades,
        losing_trades=stats.losing_trades,
        # Generated from the criteria that actually ran, not a fixed tuple.
        assumptions=simulator.config.assumptions(),
        exit_reasons=dict(sorted(reasons.items())),
        total_commission=summary.total_commission,
        total_slippage=summary.total_slippage,
    )


def replay_summary(
    run: dict,
    signals: list[dict],
    bars_by_symbol: dict,
    *,
    initial_cash: float | None = None,
    config: ExecutionConfig | None = None,
) -> ReplaySummary:
    """Run the same engine to completion and keep only the terminal event."""
    for event in replay_events(
        run, signals, bars_by_symbol, initial_cash=initial_cash, config=config
    ):
        if isinstance(event, ReplaySummary):
            return event
    raise AssertionError("replay_events always ends with a summary")  # pragma: no cover


#: Kept as a name for callers that imported it. It is no longer the source of
#: truth -- assumptions are generated per run from the execution criteria that
#: ran -- and reads as the default configuration's disclosure.
ASSUMPTIONS = tuple(ExecutionConfig().assumptions())
