"""Performance of a signal run: trades, equity curve, benchmark, metrics.

Library logic, not route logic (Constitution I), and deliberately *not*
frontend logic: Constitution V forbids analytical computation in the browser,
so the terminal UI renders what this module returns rather than deriving it.

Pure functions throughout -- no I/O, no wall-clock, no randomness. Given the
same signals and bars the answer is byte-identical (Constitution VI). Reading
only bars inside the reported window means nothing here can see the future
(Constitution VII); the signals themselves were already stamped point-in-time
by the runner.

What this is *not*: a tradeable backtest. It is long-only, equal-weight, and
charges nothing for costs, slippage or sizing. ``ASSUMPTIONS`` ships inside the
response so that caveat travels with the numbers instead of living in UI copy a
refactor can drop -- the same stance the corporate-action warning takes.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

#: Notional book size. Arbitrary but fixed: the shape of the curve and every
#: ratio below are scale-invariant, so this only sets the axis labels.
INITIAL_CAPITAL = 100_000.0

#: Trading days per year, for annualising a daily Sharpe ratio.
TRADING_DAYS_PER_YEAR = 252

ASSUMPTIONS: tuple[str, ...] = (
    "Long-only: a bearish signal closes a position, it never opens a short.",
    "Equal-weight: capital is split evenly across the instruments selected for "
    "the run, and an untraded sleeve sits in cash.",
    "Entries and exits are marked at the close of the signal date.",
    "No transaction costs and no slippage are charged.",
    "No position sizing, leverage or risk budgeting is applied.",
    "Prices are unadjusted, so a split or dividend inside the window shows up "
    "as a real move.",
)


@dataclass(frozen=True)
class Trade:
    symbol: str
    entry_date: str
    entry_price: float
    #: ``None`` while the position is still open at the end of the window.
    exit_date: str | None
    #: Realised exit for a closed trade; the last close for an open one.
    exit_price: float
    return_pct: float
    open: bool


@dataclass(frozen=True)
class EquityPoint:
    date: str
    value: float


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return: float
    #: ``None`` when undefined (fewer than two points, or zero variance).
    #: A fabricated 0.0 would read as "measured, and mediocre".
    sharpe_ratio: float | None
    #: Negative fraction, e.g. -0.153 for a 15.3% peak-to-trough fall.
    max_drawdown: float
    #: Over *closed* trades only; ``None`` when nothing has closed.
    win_rate: float | None
    trade_count: int
    winning_trades: int
    losing_trades: int


@dataclass(frozen=True)
class RunPerformance:
    run_id: str
    initial_capital: float
    equity: list[EquityPoint]
    benchmark: list[EquityPoint]
    metrics: PerformanceMetrics
    trades: list[Trade] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=lambda: list(ASSUMPTIONS))


def _closes(bars: list[Any]) -> dict[str, float]:
    return {bar.date: float(bar.close) for bar in bars}


def pair_trades(signals: list[dict], bars_by_symbol: dict[str, list[Any]]) -> list[Trade]:
    """Pair each symbol's signals into positions.

    A ``bullish`` signal opens a position; the next ``bearish`` signal on the
    same symbol closes it. A repeat signal in the direction already held is
    ignored rather than pyramided, and a ``bearish`` signal with nothing held is
    ignored rather than shorted -- both would be sizing decisions this module
    does not make.

    A position still held at the end of the window is marked at the last bar
    and flagged ``open``. It is not a realised trade and never counts toward the
    win rate.
    """
    by_symbol: dict[str, list[dict]] = {}
    for item in signals:
        by_symbol.setdefault(item["symbol"], []).append(item)

    trades: list[Trade] = []
    for symbol in sorted(by_symbol):
        bars = bars_by_symbol.get(symbol) or []
        if not bars:
            continue
        closes = _closes(bars)
        entry: tuple[str, float] | None = None

        for item in sorted(by_symbol[symbol], key=lambda s: s["date"]):
            price = closes.get(item["date"])
            # No bar on that date means no price to transact at, so there is no
            # trade to report -- silently inventing one would be worse.
            if price is None:
                continue
            direction = item["direction"]
            if direction == "bullish" and entry is None:
                entry = (item["date"], price)
            elif direction == "bearish" and entry is not None:
                entry_date, entry_price = entry
                trades.append(
                    Trade(
                        symbol=symbol,
                        entry_date=entry_date,
                        entry_price=entry_price,
                        exit_date=item["date"],
                        exit_price=price,
                        return_pct=price / entry_price - 1.0,
                        open=False,
                    )
                )
                entry = None

        if entry is not None:
            entry_date, entry_price = entry
            last = float(bars[-1].close)
            trades.append(
                Trade(
                    symbol=symbol,
                    entry_date=entry_date,
                    entry_price=entry_price,
                    exit_date=None,
                    exit_price=last,
                    return_pct=last / entry_price - 1.0,
                    open=True,
                )
            )

    trades.sort(key=lambda t: (t.symbol, t.entry_date))
    return trades


def _sleeve_multipliers(
    symbol: str, trades: list[Trade], bars: list[Any]
) -> dict[str, float]:
    """Value of one unit of capital in this symbol's sleeve, per bar date."""
    own = sorted((t for t in trades if t.symbol == symbol), key=lambda t: t.entry_date)
    out: dict[str, float] = {}
    realised = 1.0
    held: Trade | None = None
    pending = list(own)

    for bar in bars:
        if held is None and pending and pending[0].entry_date == bar.date:
            held = pending.pop(0)
        if held is None:
            out[bar.date] = realised
            continue
        out[bar.date] = realised * (float(bar.close) / held.entry_price)
        if held.exit_date == bar.date:
            realised *= held.exit_price / held.entry_price
            held = None
    return out


def _combine(
    per_symbol: dict[str, dict[str, float]], symbols: list[str], initial_capital: float
) -> list[EquityPoint]:
    """Sum equal-weight sleeves across the union of bar dates.

    A symbol with no bar on a date is closed for the day, not worthless, so its
    sleeve carries its last known value forward.
    """
    dates = sorted({date for values in per_symbol.values() for date in values})
    if not dates or not symbols:
        return []

    sleeve = initial_capital / len(symbols)
    carried = dict.fromkeys(symbols, 1.0)
    out: list[EquityPoint] = []
    for date in dates:
        for symbol in symbols:
            value = per_symbol.get(symbol, {}).get(date)
            if value is not None:
                carried[symbol] = value
        out.append(EquityPoint(date=date, value=sleeve * sum(carried.values())))
    return out


def equity_series(
    trades: list[Trade],
    bars_by_symbol: dict[str, list[Any]],
    symbols: list[str],
    initial_capital: float = INITIAL_CAPITAL,
) -> list[EquityPoint]:
    """Mark the book to market on every date in the window."""
    per_symbol = {
        symbol: _sleeve_multipliers(symbol, trades, bars_by_symbol.get(symbol) or [])
        for symbol in symbols
    }
    return _combine(per_symbol, symbols, initial_capital)


def benchmark_series(
    bars_by_symbol: dict[str, list[Any]],
    symbols: list[str],
    initial_capital: float = INITIAL_CAPITAL,
) -> list[EquityPoint]:
    """Equal-weight buy-and-hold of the same selection.

    Deliberately the run's own universe rather than an index: it isolates the
    model's timing from the question of which names it was pointed at.
    """
    per_symbol: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        bars = bars_by_symbol.get(symbol) or []
        if not bars:
            continue
        first = float(bars[0].close)
        if first == 0:
            continue
        per_symbol[symbol] = {bar.date: float(bar.close) / first for bar in bars}
    return _combine(per_symbol, symbols, initial_capital)


def _max_drawdown(equity: list[EquityPoint]) -> float:
    peak = float("-inf")
    worst = 0.0
    for point in equity:
        peak = max(peak, point.value)
        if peak > 0:
            worst = min(worst, point.value / peak - 1.0)
    return worst


def _sharpe(equity: list[EquityPoint]) -> float | None:
    returns = [
        equity[i].value / equity[i - 1].value - 1.0
        for i in range(1, len(equity))
        if equity[i - 1].value != 0
    ]
    if len(returns) < 2:
        return None
    deviation = statistics.stdev(returns)
    # Zero variance leaves the ratio undefined, not zero.
    if deviation == 0:
        return None
    return (statistics.fmean(returns) / deviation) * (TRADING_DAYS_PER_YEAR**0.5)


def metrics(equity: list[EquityPoint], trades: list[Trade]) -> PerformanceMetrics:
    """Summary statistics over the curve and the realised trades."""
    if equity and equity[0].value != 0:
        total_return = equity[-1].value / equity[0].value - 1.0
    else:
        total_return = 0.0

    closed = [t for t in trades if not t.open]
    winning = sum(1 for t in closed if t.return_pct > 0)
    losing = sum(1 for t in closed if t.return_pct < 0)

    return PerformanceMetrics(
        total_return=total_return,
        sharpe_ratio=_sharpe(equity),
        max_drawdown=_max_drawdown(equity),
        win_rate=(winning / len(closed)) if closed else None,
        trade_count=len(trades),
        winning_trades=winning,
        losing_trades=losing,
    )


def compute_performance(
    *,
    run_id: str,
    signals: list[dict],
    bars_by_symbol: dict[str, list[Any]],
    symbols: list[str],
    initial_capital: float = INITIAL_CAPITAL,
) -> RunPerformance:
    """The whole answer for one run, from its signals and its window's bars."""
    trades = pair_trades(signals, bars_by_symbol)
    equity = equity_series(trades, bars_by_symbol, symbols, initial_capital)
    return RunPerformance(
        run_id=run_id,
        initial_capital=initial_capital,
        equity=equity,
        benchmark=benchmark_series(bars_by_symbol, symbols, initial_capital),
        metrics=metrics(equity, trades),
        trades=trades,
        assumptions=list(ASSUMPTIONS),
    )
