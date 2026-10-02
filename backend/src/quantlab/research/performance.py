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
    "Prices are back-adjusted for splits and dividends for signals; trades fill at "
    "traded prices, with splits applied to shares held and dividends paid in cash.",
)


#: How the buy-and-hold benchmark is priced, per ExecutionConfig.price_adjustment
#: -- always the strategy's own basis, so "vs hold" compares like with like.
_BENCHMARK_BASIS: dict[str, str] = {
    "split_dividend": (
        "The buy-and-hold benchmark is measured on the same split- and dividend-adjusted "
        "prices: a total return with each dividend reinvested on its ex-date (the "
        "strategy instead receives dividends as cash)."
    ),
    "split": (
        "The buy-and-hold benchmark is measured on split-adjusted prices, like the "
        "strategy: no dividends on either side."
    ),
    "none": (
        "The buy-and-hold benchmark uses traded prices, like the strategy: a split reads "
        "as a price move and dividends are not included."
    ),
}


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
    # Everything below is additive, and defaulted so the pre-execution shape of
    # this record still constructs. A run that predates execution criteria has
    # no stop to have been caught by, so "signal" is the truthful default
    # rather than a placeholder.
    side: str = "long"
    qty: float = 0.0
    exit_reason: str = "signal"
    pnl: float = 0.0
    fees: float = 0.0
    #: Dividends received (long) or paid (short, negative) while held.
    dividends: float = 0.0


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
class CostBreakdown:
    commission: float = 0.0
    slippage: float = 0.0
    #: Short borrow charged over the run (``borrow_cost_bps``); 0 when long-only.
    borrow: float = 0.0
    #: Net dividend cash over the run: income, not a cost, but it sits beside
    #: them so the gap between price return and total return is visible.
    dividends: float = 0.0


#: Fewer paired daily returns than this and a regression is noise: beta from a
#: month of data swings with every bar. ~3 months of sessions.
MIN_REGRESSION_OBSERVATIONS = 60


@dataclass(frozen=True)
class BenchmarkRegression:
    """The strategy's daily returns regressed on its benchmark's (book L08).

    ``r_t = alpha + beta * b_t + e_t`` by ordinary least squares, with the
    risk-free rate taken as zero -- stated, not hidden, because excess returns
    over cash would lower alpha by roughly the cash rate. The benchmark is the
    run's own equal-weight buy-and-hold, not an index (data gap D1), so beta
    here is exposure to *the names the strategy was pointed at*, and alpha is
    what the timing added on top of simply holding them.
    """

    #: Annualised intercept (daily x 252), as a fraction.
    alpha: float
    beta: float
    r_squared: float
    correlation: float
    #: Annualised standard deviation of the active return (strategy - benchmark).
    tracking_error: float | None
    #: Annualised mean active return over tracking error.
    information_ratio: float | None
    observations: int


@dataclass(frozen=True)
class RunPerformance:
    run_id: str
    initial_capital: float
    equity: list[EquityPoint]
    benchmark: list[EquityPoint]
    metrics: PerformanceMetrics
    trades: list[Trade] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=lambda: list(ASSUMPTIONS))
    #: What the trading cost, and why each position was closed. Both are new
    #: with execution criteria: "the strategy said so" and "the stop caught it"
    #: are different facts, and averaging them into one win rate hides which is
    #: doing the work.
    costs: CostBreakdown = field(default_factory=CostBreakdown)
    exit_reasons: dict[str, int] = field(default_factory=dict)
    #: ``None`` when there are too few paired returns to estimate it, or the
    #: benchmark never moved. A beta of 0.0 would read as "market-neutral".
    regression: BenchmarkRegression | None = None


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

    ``bars_by_symbol`` must be on the strategy's price basis -- back-adjusted
    for the run's corporate actions (compute_performance does this). The ratio
    of back-adjusted closes is the holder's return: split-neutral, and with
    dividends the total return with each one reinvested on its ex-date.
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


def _daily_returns(curve: list[EquityPoint]) -> dict[str, float]:
    return {
        curve[i].date: curve[i].value / curve[i - 1].value - 1.0
        for i in range(1, len(curve))
        if curve[i - 1].value != 0
    }


def regression(
    equity: list[EquityPoint], benchmark: list[EquityPoint]
) -> BenchmarkRegression | None:
    """OLS of the strategy's daily returns on the benchmark's, on shared dates."""
    strategy = _daily_returns(equity)
    market = _daily_returns(benchmark)
    dates = sorted(set(strategy) & set(market))
    n = len(dates)
    if n < MIN_REGRESSION_OBSERVATIONS:
        return None
    r = [strategy[d] for d in dates]
    b = [market[d] for d in dates]
    mean_r = statistics.fmean(r)
    mean_b = statistics.fmean(b)
    var_b = sum((x - mean_b) ** 2 for x in b)
    var_r = sum((y - mean_r) ** 2 for y in r)
    if var_b == 0:
        return None
    cov = sum((x - mean_b) * (y - mean_r) for x, y in zip(b, r, strict=True))
    beta = cov / var_b
    alpha_daily = mean_r - beta * mean_b
    # A flat strategy (never traded) explains nothing and is explained by nothing.
    r_squared = (cov * cov) / (var_b * var_r) if var_r > 0 else 0.0
    correlation = cov / (var_b * var_r) ** 0.5 if var_r > 0 else 0.0

    active = [y - x for x, y in zip(b, r, strict=True)]
    deviation = statistics.stdev(active)
    tracking_error = deviation * TRADING_DAYS_PER_YEAR**0.5 if deviation > 0 else None
    information_ratio = (
        statistics.fmean(active) * TRADING_DAYS_PER_YEAR / tracking_error
        if tracking_error
        else None
    )
    return BenchmarkRegression(
        alpha=alpha_daily * TRADING_DAYS_PER_YEAR,
        beta=beta,
        r_squared=r_squared,
        correlation=correlation,
        tracking_error=tracking_error,
        information_ratio=information_ratio,
        observations=n,
    )


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


def to_decisions(signals: list[dict]) -> list[Any]:
    """Stored signals, as the execution engine's input.

    A row recorded before strategies existed has no ``kind``; it came from a
    single-model run, where one rule both opened and closed, which is exactly
    what ``both`` means.
    """
    from quantlab.execution import Decision

    return [
        Decision(
            date=item["date"],
            symbol=item["symbol"],
            kind=item.get("kind") or "both",
            direction=item["direction"],
            trigger_values=item.get("trigger_values") or {},
            data_window_end=item.get("data_window_end", item["date"]),
        )
        for item in signals
    ]


def _within(bars: list[Any], start: str | None, end: str | None) -> list[Any]:
    return [
        bar
        for bar in bars
        if (start is None or bar.date >= start) and (end is None or bar.date <= end)
    ]


def compute_performance(
    *,
    run_id: str,
    signals: list[dict],
    bars_by_symbol: dict[str, list[Any]],
    symbols: list[str],
    initial_capital: float | None = None,
    execution: Any = None,
    window_start: str | None = None,
    window_end: str | None = None,
    corporate_actions: dict | None = None,
) -> RunPerformance:
    """The whole answer for one run, from its signals and its window's bars.

    Re-executed rather than re-derived: the stored decisions are replayed
    through the same simulator the run itself used, under the same criteria.
    Because that simulator is deterministic (Constitution VI), this reproduces
    the original run exactly instead of approximating it with a second
    implementation -- which is what the two hand-kept copies of this logic used
    to do, and how they drifted.
    """
    from quantlab.execution import ExecutionConfig, simulate

    config = execution or ExecutionConfig()
    if initial_capital is not None and initial_capital != config.initial_capital:
        from dataclasses import replace

        config = replace(config, initial_capital=initial_capital)

    # Simulated over everything supplied -- a stop set from an ATR on the first
    # session of the window needs the sessions behind it -- but *reported* over
    # the window only. Warm-up bars are inputs to the signals, not part of the
    # period being measured, and a curve that began in the warm-up would put a
    # flat stretch of untraded capital at the front of every result.
    result = simulate(symbols, bars_by_symbol, to_decisions(signals), config, corporate_actions)

    trades = [
        Trade(
            symbol=t.symbol,
            entry_date=t.entry_date,
            entry_price=t.entry_price,
            exit_date=t.exit_date,
            exit_price=t.exit_price,
            return_pct=t.return_pct,
            open=t.open,
            side=t.side,
            qty=t.qty,
            exit_reason=t.exit_reason,
            pnl=t.pnl,
            fees=t.fees,
            dividends=t.dividends,
        )
        for t in result.trades
    ]
    curve = [
        EquityPoint(date=p.date, value=p.value)
        for p in result.equity
        if (window_start is None or p.date >= window_start)
        and (window_end is None or p.date <= window_end)
    ]

    # The benchmark is normalised from the window's first close, not the
    # warm-up's, or buy-and-hold would be credited with a move that happened
    # before the period under test.
    #
    # And it is held on the same footing as the strategy: the simulator above
    # applies the run's splits (and, under split_dividend, dividends) to its
    # holdings, so buy-and-hold is measured on the same corporate actions,
    # back-adjusted. On raw closes a split reads as a crash -- GOOGL's 20:1 on
    # 2022-07-18 as -95% -- and dividends are missing, which skewed "vs hold"
    # and every regression figure built on the benchmark. The actions are
    # already filtered by the run's price_adjustment, so a "none" run keeps a
    # raw benchmark to match its raw strategy. Adjusting the whole loaded
    # series first and trimming after means an ex-date on the window's first
    # session still finds the session before it.
    from quantlab.execution.adjustments import adjust_all, applies

    # Filtered by the run's mode here as the simulator does internally, so the
    # two sides agree by construction even for a caller passing every action.
    benchmark_actions = {
        symbol: [a for a in actions if applies(a, config.price_adjustment)]
        for symbol, actions in (corporate_actions or {}).items()
    }
    benchmark_bars = adjust_all(bars_by_symbol, benchmark_actions)
    in_window = {
        symbol: _within(bars, window_start, window_end)
        for symbol, bars in benchmark_bars.items()
    }

    reasons: dict[str, int] = {}
    for trade in trades:
        reasons[trade.exit_reason] = reasons.get(trade.exit_reason, 0) + 1

    benchmark = benchmark_series(in_window, symbols, config.initial_capital)

    return RunPerformance(
        run_id=run_id,
        initial_capital=config.initial_capital,
        equity=curve,
        benchmark=benchmark,
        metrics=metrics(curve, trades),
        trades=trades,
        # Generated from the config that actually ran, so the caveats can no
        # longer contradict the numbers they ship with.
        assumptions=[*result.assumptions, _BENCHMARK_BASIS[config.price_adjustment]],
        costs=CostBreakdown(
            commission=result.summary.total_commission,
            slippage=result.summary.total_slippage,
            borrow=result.summary.total_borrow,
            dividends=result.summary.total_dividends,
        ),
        exit_reasons=dict(sorted(reasons.items())),
        regression=regression(curve, benchmark),
    )
