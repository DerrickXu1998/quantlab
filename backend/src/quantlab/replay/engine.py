"""Replay engine: interleave a run's bars and signals into an event stream.

Pure computation (Constitutions I and VI): ``replay_events`` takes the run
record, its stored signals and its window's bars, and yields typed events in
strict chronological order -- bars first on each date, then the signals that
fire that day, then their fills at that day's close, then one equity mark.
A signal therefore never precedes the bar event of its own date, and the
simulator never touches a later bar (Constitution VII).

The summary event reuses ``research.performance.metrics`` over the replayed
equity curve and the simulator's trade list rather than re-implementing
anything, so the replay's bottom line reconciles with
``GET /runs/{id}/performance`` on the same run.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any

from quantlab.replay.portfolio import PortfolioSimulator
from quantlab.research import performance

#: Sizing disclosures, shared with compute_performance so a replayed run and
#: its performance report ship the same caveats.
ASSUMPTIONS = performance.ASSUMPTIONS


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


@dataclass(frozen=True)
class ReplayFill:
    """A trade the simulator executed at the close of the signal date."""

    date: str
    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    price: float
    value: float
    realized_pnl: float


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

    Only the reported window's bars are loaded -- warm-up bars were inputs to
    the signals, not part of the period being replayed.
    """
    signals = experiments.get_run_signals(run["id"])
    bars = backend.load_bars_for(list(run["symbols"]), run["start_date"], run["end_date"])
    return signals, bars


def replay_events(
    run: dict,
    signals: list[dict],
    bars_by_symbol: dict,
    *,
    initial_cash: float = performance.INITIAL_CAPITAL,
    step: int = 1,
) -> Iterator[ReplayEvent]:
    """Yield the run's window as a chronological event stream.

    ``step`` thins bar events to every Nth date (equity, signal and fill
    events are never thinned); a date that carries a signal always gets its
    bar event regardless, so a fill never appears without the price that
    produced it.
    """
    symbols = list(run["symbols"])
    sim = PortfolioSimulator(symbols, initial_cash)

    bars_on: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        for bar in bars_by_symbol.get(symbol) or []:
            bars_on.setdefault(bar.date, {})[symbol] = float(bar.close)

    signals_on: dict[str, list[dict]] = {}
    for signal in signals:
        signals_on.setdefault(signal["date"], []).append(signal)
    for same_day in signals_on.values():
        same_day.sort(key=lambda s: s["symbol"])  # deterministic within a date

    # A signal dated on a day with no bars at all still fires (it cannot
    # transact), but only dates with a bar enter the equity curve -- that is
    # the same union of bar dates performance.equity_series marks over.
    dates = sorted(set(bars_on) | set(signals_on))
    curve: list[performance.EquityPoint] = []

    for index, day in enumerate(dates):
        closes = bars_on.get(day, {})
        if closes:
            if index % step == 0 or day in signals_on:
                yield ReplayBar(date=day, closes=closes)
            sim.mark(closes)
        for signal in signals_on.get(day, []):
            yield ReplaySignal(
                date=day,
                symbol=signal["symbol"],
                direction=signal["direction"],
                trigger_values=signal["trigger_values"],
                data_window_end=signal["data_window_end"],
            )
            fill = sim.apply_signal(
                day, signal["symbol"], signal["direction"], closes.get(signal["symbol"])
            )
            if fill is not None:
                yield ReplayFill(
                    date=fill.date,
                    symbol=fill.symbol,
                    side=fill.side,
                    qty=fill.qty,
                    price=fill.price,
                    value=fill.value,
                    realized_pnl=fill.realized_pnl,
                )
        equity = sim.equity()
        yield ReplayEquity(
            date=day,
            equity=equity,
            cash=sim.cash,
            positions=len(sim.open_positions()),
            realized_pnl=sim.realized_pnl(),
        )
        if closes:
            curve.append(performance.EquityPoint(date=day, value=equity))

    yield summary_event(run["id"], sim, curve)


def summary_event(
    run_id: str,
    sim: PortfolioSimulator,
    curve: list[performance.EquityPoint],
) -> ReplaySummary:
    """Reduce a finished simulation to its terminal event.

    Shared by the batch replay and the live (Kafka-consumed) replay so both
    paths reduce the book with exactly the same helpers.
    """
    metrics = performance.metrics(curve, sim.trades())
    return ReplaySummary(
        run_id=run_id,
        days=len(curve),
        initial_cash=sim.initial_cash,
        final_equity=curve[-1].value if curve else sim.initial_cash,
        total_return=metrics.total_return,
        sharpe_ratio=metrics.sharpe_ratio,
        max_drawdown=metrics.max_drawdown,
        win_rate=metrics.win_rate,
        trade_count=metrics.trade_count,
        winning_trades=metrics.winning_trades,
        losing_trades=metrics.losing_trades,
        assumptions=list(ASSUMPTIONS),
    )


def replay_summary(
    run: dict,
    signals: list[dict],
    bars_by_symbol: dict,
    *,
    initial_cash: float = performance.INITIAL_CAPITAL,
) -> ReplaySummary:
    """Run the same engine to completion and keep only the terminal event."""
    for event in replay_events(run, signals, bars_by_symbol, initial_cash=initial_cash):
        if isinstance(event, ReplaySummary):
            return event
    raise AssertionError("replay_events always ends with a summary")  # pragma: no cover
