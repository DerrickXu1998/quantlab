"""Performance of a signal run: trades, equity curve, benchmark, metrics.

Library logic, not route logic (Constitution I), and deliberately *not*
frontend logic: Constitution V forbids analytical computation in the browser,
so the terminal UI renders what this module returns rather than deriving it.

Pure functions throughout -- no I/O, no wall-clock, no randomness. Given the
same signals and bars the answer is byte-identical (Constitution VI). Reading
only bars inside the reported window means nothing here can see the future
(Constitution VII); the signals themselves were already stamped point-in-time
by the runner.

What this is *not*: a tradeable backtest. The default path is long-only,
equal-weight, and charges nothing for costs, slippage or sizing. A run may
carry :class:`ExecutionCriteria` (costs, stops, position caps, next-open
fills); those are simulated honestly and disclosed in ``assumptions``, but the
result is still a measurement over daily bars, not an execution engine.
``ASSUMPTIONS`` ships inside the response so that caveat travels with the
numbers instead of living in UI copy a refactor can drop -- the same stance
the corporate-action warning takes.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace
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
    "Prices are unadjusted, so a split or dividend inside the window shows up as a real move.",
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


def _sleeve_multipliers(symbol: str, trades: list[Trade], bars: list[Any]) -> dict[str, float]:
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
    execution: ExecutionCriteria | None = None,
) -> RunPerformance:
    """The whole answer for one run, from its signals and its window's bars.

    ``execution=None`` is the historical measuring instrument: per-symbol
    equal-weight sleeves filled at the close of the signal date, no costs.
    Supplying criteria routes through the fill simulator, which honours them
    and discloses them in the assumptions it ships.
    """
    if execution is None:
        trades = pair_trades(signals, bars_by_symbol)
        equity = equity_series(trades, bars_by_symbol, symbols, initial_capital)
        assumptions = list(ASSUMPTIONS)
    else:
        trades, equity = simulate(signals, bars_by_symbol, symbols, execution)
        initial_capital = execution.initial_capital
        assumptions = execution_assumptions(execution)
    result_metrics = metrics(equity, trades)
    if execution is not None and equity:
        # The first mark already embeds that day's entry costs, so end/start of
        # the curve would miss them. The run's return is measured against the
        # capital it started with (identical to end/start when costless, which
        # is why the historical path needs no such anchor).
        result_metrics = replace(
            result_metrics, total_return=equity[-1].value / initial_capital - 1.0
        )
    return RunPerformance(
        run_id=run_id,
        initial_capital=initial_capital,
        equity=equity,
        benchmark=benchmark_series(bars_by_symbol, symbols, initial_capital),
        metrics=result_metrics,
        trades=trades,
        assumptions=assumptions,
    )


# --- User-settable execution criteria ----------------------------------------
#
# The fill simulator below is the same measuring instrument observed through a
# more honest lens: same long-only signal pairing, but the researcher chooses
# the book size, sizing rule, fill timing, costs and protective exits. With
# every field at its default it reproduces the pair_trades/equity_series path
# (asserted in tests/unit/test_execution.py).

POSITION_SIZINGS: tuple[str, ...] = ("equal_weight", "fixed_fraction")
ENTRY_PRICES: tuple[str, ...] = ("same_close", "next_open")

#: Cash-account key when sizing draws on one shared pool instead of sleeves.
_POOL = "__pool__"


@dataclass(frozen=True)
class ExecutionCriteria:
    """How a run's signals are turned into fills.

    The defaults are the historical behaviour exactly: an equal-weight sleeve
    per selected instrument, filled at the close of the signal date, charged
    nothing, capped at nothing.
    """

    initial_capital: float = INITIAL_CAPITAL
    position_sizing: str = "equal_weight"
    #: Share of the book's current value per entry; fixed_fraction sizing only.
    fraction: float = 0.1
    max_open_positions: int | None = None
    transaction_cost_bps: float = 0.0
    fixed_cost_per_trade: float = 0.0
    #: Fractions of the entry price, e.g. 0.1 exits 10% below/above it.
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    entry_price: str = "same_close"

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")
        if self.position_sizing not in POSITION_SIZINGS:
            raise ValueError(f"position_sizing must be one of {POSITION_SIZINGS}")
        if not 0 < self.fraction <= 1:
            raise ValueError("fraction must be in (0, 1]")
        if self.max_open_positions is not None and self.max_open_positions < 1:
            raise ValueError("max_open_positions must be >= 1 when set")
        if self.transaction_cost_bps < 0:
            raise ValueError("transaction_cost_bps must be >= 0")
        if self.fixed_cost_per_trade < 0:
            raise ValueError("fixed_cost_per_trade must be >= 0")
        if self.stop_loss_pct is not None and not 0 < self.stop_loss_pct < 1:
            raise ValueError("stop_loss_pct must be in (0, 1) when set")
        if self.take_profit_pct is not None and self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be > 0 when set")
        if self.entry_price not in ENTRY_PRICES:
            raise ValueError(f"entry_price must be one of {ENTRY_PRICES}")


def execution_criteria(data: dict[str, Any]) -> ExecutionCriteria:
    """Build criteria from a plain mapping, rejecting unknown keys."""
    try:
        return ExecutionCriteria(**data)
    except TypeError as exc:
        raise ValueError(f"invalid execution criteria: {exc}") from exc


@dataclass
class _Position:
    symbol: str
    qty: float
    entry_date: str
    entry_price: float
    #: Cash spent entering, including entry costs: the denominator that makes a
    #: trade's return_pct net of costs.
    cost_basis: float


class _ExecutionSimulator:
    """One shared fill loop for both sizing conventions.

    ``equal_weight`` keeps a cash sleeve per selected instrument (the
    historical convention, which is what makes the default criteria reproduce
    it); ``fixed_fraction`` holds one shared pool and sizes each entry off the
    book's current value.
    """

    def __init__(self, symbols: list[str], criteria: ExecutionCriteria) -> None:
        self.criteria = criteria
        self._selection = set(symbols)
        if criteria.position_sizing == "equal_weight":
            self._cash = {s: criteria.initial_capital / len(symbols) for s in symbols}
        else:
            self._cash = {_POOL: criteria.initial_capital}
        self._positions: dict[str, _Position] = {}
        self._last_price: dict[str, float] = {}
        #: Signals waiting for the next session's open: (signal_date, symbol, direction).
        self._pending: list[tuple[str, str, str]] = []
        self.trades: list[Trade] = []

    def _cash_key(self, symbol: str) -> str:
        return symbol if self.criteria.position_sizing == "equal_weight" else _POOL

    def _cost_rate(self) -> float:
        return self.criteria.transaction_cost_bps / 10_000.0

    def equity(self) -> float:
        total = sum(self._cash.values())
        for symbol, pos in self._positions.items():
            # A symbol with no bar today keeps its last price -- closed for the
            # day, not worthless (the same carry-forward _combine applies).
            total += pos.qty * self._last_price.get(symbol, pos.entry_price)
        return total

    def enter(self, date: str, symbol: str, price: float) -> None:
        c = self.criteria
        if symbol not in self._selection or symbol in self._positions or price <= 0:
            return
        if c.max_open_positions is not None and len(self._positions) >= c.max_open_positions:
            return
        key = self._cash_key(symbol)
        budget = self._cash[key]
        if c.position_sizing == "fixed_fraction":
            budget = min(budget, c.fraction * self.equity())
        spendable = budget - c.fixed_cost_per_trade
        if spendable <= 0:
            return
        qty = spendable / (price * (1.0 + self._cost_rate()))
        cost = qty * price * self._cost_rate() + c.fixed_cost_per_trade
        self._cash[key] -= qty * price + cost
        self._positions[symbol] = _Position(symbol, qty, date, price, qty * price + cost)

    def exit(self, date: str, symbol: str, price: float) -> None:
        pos = self._positions.pop(symbol, None)
        if pos is None:
            return
        gross = pos.qty * price
        proceeds = gross - gross * self._cost_rate() - self.criteria.fixed_cost_per_trade
        self._cash[self._cash_key(symbol)] += proceeds
        self.trades.append(
            Trade(
                symbol=symbol,
                entry_date=pos.entry_date,
                entry_price=pos.entry_price,
                exit_date=date,
                exit_price=price,
                return_pct=proceeds / pos.cost_basis - 1.0,
                open=False,
            )
        )

    def check_stops(self, date: str, bars_today: dict[str, Any]) -> None:
        c = self.criteria
        if c.stop_loss_pct is None and c.take_profit_pct is None:
            return
        for symbol in sorted(list(self._positions)):
            bar = bars_today.get(symbol)
            if bar is None:
                continue
            pos = self._positions[symbol]
            # A same-close entry fills after this day's range has formed, so it
            # cannot be stopped by it.
            if pos.entry_date == date and c.entry_price == "same_close":
                continue
            stop = (
                pos.entry_price * (1.0 - c.stop_loss_pct) if c.stop_loss_pct is not None else None
            )
            target = (
                pos.entry_price * (1.0 + c.take_profit_pct)
                if c.take_profit_pct is not None
                else None
            )
            # When both levels trigger on one daily bar their order is
            # unknowable; the pessimistic reading (the stop fills first) is the
            # honest one. A gap through the level fills at the open.
            if stop is not None and float(bar.low) <= stop:
                self.exit(date, symbol, min(float(bar.open), stop))
            elif target is not None and float(bar.high) >= target:
                self.exit(date, symbol, max(float(bar.open), target))


def simulate(
    signals: list[dict],
    bars_by_symbol: dict[str, list[Any]],
    symbols: list[str],
    criteria: ExecutionCriteria,
) -> tuple[list[Trade], list[EquityPoint]]:
    """Fill a run's signals day by day under ``criteria``.

    One session at a time, in causal order: the previous session's signals
    fill at this session's open (next_open mode), protective exits trigger off
    this session's range, then this session's signals act at its close (or
    queue for tomorrow's open). The book is marked on every date with a bar,
    the same union of bar dates equity_series reports over.
    """
    sim = _ExecutionSimulator(symbols, criteria)

    bars_on: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        for bar in bars_by_symbol.get(symbol) or []:
            bars_on.setdefault(bar.date, {})[symbol] = bar
    signals_on: dict[str, list[dict]] = {}
    for item in signals:
        if item["symbol"] in sim._selection:
            signals_on.setdefault(item["date"], []).append(item)
    for same_day in signals_on.values():
        same_day.sort(key=lambda s: s["symbol"])  # deterministic within a date

    curve: list[EquityPoint] = []
    for day in sorted(set(bars_on) | set(signals_on)):
        todays = bars_on.get(day, {})
        for symbol, bar in todays.items():
            sim._last_price[symbol] = float(bar.close)

        still_pending: list[tuple[str, str, str]] = []
        for signal_date, symbol, direction in sim._pending:
            bar = todays.get(symbol)
            if bar is None:
                still_pending.append((signal_date, symbol, direction))
            elif direction == "bullish":
                sim.enter(day, symbol, float(bar.open))
            else:
                sim.exit(day, symbol, float(bar.open))
        sim._pending = still_pending

        sim.check_stops(day, todays)

        for item in signals_on.get(day, []):
            symbol, direction = item["symbol"], item["direction"]
            if criteria.entry_price == "next_open":
                sim._pending.append((day, symbol, direction))
                continue
            bar = todays.get(symbol)
            # No bar on the signal date means no price to transact at, so
            # there is no trade -- the same skip pair_trades makes.
            if bar is None:
                continue
            if direction == "bullish":
                sim.enter(day, symbol, float(bar.close))
            else:
                sim.exit(day, symbol, float(bar.close))

        if todays:
            curve.append(EquityPoint(date=day, value=sim.equity()))

    for symbol in sorted(sim._positions):
        pos = sim._positions[symbol]
        last = sim._last_price.get(symbol, pos.entry_price)
        sim.trades.append(
            Trade(
                symbol=symbol,
                entry_date=pos.entry_date,
                entry_price=pos.entry_price,
                exit_date=None,
                exit_price=last,
                return_pct=pos.qty * last / pos.cost_basis - 1.0,
                open=True,
            )
        )
    sim.trades.sort(key=lambda t: (t.symbol, t.entry_date))
    return sim.trades, curve


def execution_assumptions(c: ExecutionCriteria) -> list[str]:
    """The disclosure that travels with a simulated run's numbers."""
    lines = ["Long-only: a bearish signal closes a position, it never opens a short."]
    if c.position_sizing == "equal_weight":
        lines.append(
            "Equal-weight: capital is split evenly across the instruments selected for "
            "the run, and an untraded sleeve sits in cash."
        )
    else:
        lines.append(
            f"Fixed-fraction sizing: each entry invests {c.fraction:.0%} of the book's "
            "current value from a shared cash account; an entry cash cannot fund is skipped."
        )
    if c.entry_price == "same_close":
        lines.append("Entries and exits are marked at the close of the signal date.")
    else:
        lines.append(
            "Signals fill at the open of the next session that has a bar, not at the "
            "close of the signal date."
        )
    if c.transaction_cost_bps == 0 and c.fixed_cost_per_trade == 0:
        lines.append("No transaction costs and no slippage are charged.")
    else:
        lines.append(
            f"Transaction costs: {c.transaction_cost_bps:g} bps of traded value plus "
            f"{c.fixed_cost_per_trade:g} per fill, charged on entry and exit."
        )
    if c.max_open_positions is not None:
        lines.append(
            f"At most {c.max_open_positions} positions may be open at once; entries "
            "beyond the cap are skipped."
        )
    if c.stop_loss_pct is not None:
        lines.append(
            f"Stop-loss: a position exits {c.stop_loss_pct:.0%} below its entry price "
            "when a bar's low trades through the level (filled at the level, or at the "
            "open when the market gaps through it)."
        )
    if c.take_profit_pct is not None:
        lines.append(
            f"Take-profit: a position exits {c.take_profit_pct:.0%} above its entry "
            "price when a bar's high trades through the level (filled at the level, or "
            "at the open when the market gaps through it)."
        )
    if c.stop_loss_pct is not None and c.take_profit_pct is not None:
        lines.append(
            "When a stop and a target trigger on the same bar the stop is assumed to "
            "fill first; their order is unknowable from daily bars."
        )
    lines.append(
        "Prices are unadjusted, so a split or dividend inside the window shows up as a real move."
    )
    return lines
