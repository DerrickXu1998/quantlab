"""The execution simulator: decisions in, fills and an equity curve out.

This is the one place that decides what a signal *does*. Before it existed the
same rules were written twice -- once in ``research.performance.pair_trades``
for the batch report and once in ``replay.portfolio`` for the day-by-day
stream -- and keeping two implementations agreeing by hand is a bug waiting for
a quiet afternoon. Both now drive this class, so a replay and its performance
report cannot disagree by construction.

Pure computation: no I/O, no wall clock, no randomness. Given the same bars,
decisions and config the fills are byte-identical (Constitution VI). Nothing
reads a bar later than the one being processed (Constitution VII).

Ordering within a bar is fixed and is the whole game::

    mark -> fill orders queued yesterday -> protective exits -> signal exits -> entries

Protective exits come before signal exits because a stop that was hit intraday
was hit before the close that produced the signal. Entries come last because a
position closed today frees the capital and the slot that a new position needs,
and resolving it the other way would silently cap the book at one rotation a
bar.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from quantlab.execution.config import BPS, TRADING_DAYS_PER_YEAR, ExecutionConfig
from quantlab.indicators.technical import atr as atr_indicator

#: Resolution order within one date; mirrors the composer's own ordering.
_KIND_ORDER = {"exit": 0, "both": 1, "entry": 2}


@dataclass(frozen=True)
class Decision:
    """One instruction from a strategy: open something, or close it.

    ``kind`` separates the two questions a strategy answers. An entry decision
    with no position is an order; an exit decision with no position is nothing
    at all. Collapsing them into a bare direction, as the pre-strategy code
    did, is why a rule could never be used for entries only.

    ``both`` is one rule wearing both hats -- the shape every single-model run
    has, where a bullish event opens and a bearish one closes. It is a distinct
    kind rather than two decisions so that a legacy run records exactly the
    signals it always did.
    """

    date: str
    symbol: str
    kind: str  # "entry" | "exit" | "both"
    direction: str  # "bullish" | "bearish"
    trigger_values: dict[str, Any] = field(default_factory=dict)
    data_window_end: str = ""


@dataclass(frozen=True)
class Fill:
    date: str
    symbol: str
    #: buy / sell open and close a long; short / cover do the same for a short.
    side: str
    qty: float
    price: float
    value: float
    commission: float
    slippage: float
    realized_pnl: float
    #: "signal" on the way in; the exit reason on the way out.
    reason: str


@dataclass(frozen=True)
class ExecutedTrade:
    symbol: str
    side: str  # "long" | "short"
    entry_date: str
    entry_price: float
    exit_date: str | None
    exit_price: float
    qty: float
    return_pct: float
    open: bool
    exit_reason: str
    pnl: float
    fees: float


@dataclass(frozen=True)
class EquityPoint:
    date: str
    value: float


@dataclass(frozen=True)
class ExecutionSummary:
    """What the engine did, including what it refused to do.

    The rejection counters matter as much as the fills: a strategy whose
    signals were mostly dropped for want of a free slot has not been tested,
    and without these it looks identical to one that simply signalled rarely.
    """

    orders: int = 0
    fills: int = 0
    rejected_no_cash: int = 0
    rejected_max_positions: int = 0
    rejected_cooldown: int = 0
    rejected_shorts_disabled: int = 0
    dropped_no_bar: int = 0
    total_commission: float = 0.0
    total_slippage: float = 0.0


@dataclass(frozen=True)
class DayState:
    """End-of-bar book state, emitted once per date the replay walks."""

    date: str
    closes: dict[str, float]
    fills: list[Fill]
    equity: float
    cash: float
    positions: int
    realized_pnl: float


@dataclass
class _Position:
    symbol: str
    side: str
    qty: float
    entry_date: str
    entry_index: int
    entry_price: float
    entry_fees: float
    #: True when the entry filled at an open, which means the rest of that same
    #: session is live for protective exits.
    filled_at_open: bool
    stop_price: float | None
    target_price: float | None
    #: Best close seen while held, for the trailing stop. Updated only after a
    #: bar has been tested, so today's close never sets today's trigger.
    best_close: float


@dataclass
class _PendingOrder:
    """An order waiting for the next session's open (``fill_timing``)."""

    symbol: str
    #: Already resolved to "open" or "close": what the decision meant given the
    #: book as it stood when the signal fired.
    kind: str
    direction: str
    signal_date: str


class ExecutionSimulator:
    """Runs one strategy's decisions over one selection's bars."""

    def __init__(
        self,
        symbols: list[str],
        bars_by_symbol: dict[str, list[Any]],
        config: ExecutionConfig | None = None,
    ) -> None:
        if not symbols:
            raise ValueError("a run needs at least one symbol")
        self.symbols = list(symbols)
        self.config = config or ExecutionConfig()
        self.bars_by_symbol = {s: list(bars_by_symbol.get(s) or []) for s in self.symbols}

        self.sleeved = self.config.position_sizing == "equal_weight"
        sleeve = self.config.initial_capital / len(self.symbols)
        # Equal-weight keeps one cash sleeve per instrument, which is what the
        # pre-strategy engine did and what makes a legacy run reproduce
        # exactly. Every other mode draws on one shared pool.
        self._sleeve_cash = dict.fromkeys(self.symbols, sleeve)
        self._pool_cash = self.config.initial_capital

        self._positions: dict[str, _Position] = {}
        self._last_price: dict[str, float] = {}
        self._last_exit_index: dict[str, int] = {}
        self._pending: list[_PendingOrder] = []

        self.fills: list[Fill] = []
        self.closed_trades: list[ExecutedTrade] = []
        self._realized = 0.0
        self._commission = 0.0
        self._slippage = 0.0
        self._counters = dict.fromkeys(
            (
                "orders",
                "fills",
                "rejected_no_cash",
                "rejected_max_positions",
                "rejected_cooldown",
                "rejected_shorts_disabled",
                "dropped_no_bar",
            ),
            0,
        )

        self._atr = self._precompute_atr()
        self._vol = self._precompute_volatility()

        # Bar lookup by date, and each symbol's own bar index on that date --
        # "how many sessions has this been held" must count the instrument's
        # own sessions, not calendar dates on which some other name traded.
        self._bar_on: dict[str, dict[str, Any]] = {}
        self._index_on: dict[str, dict[str, int]] = {}
        for symbol, bars in self.bars_by_symbol.items():
            for index, bar in enumerate(bars):
                self._bar_on.setdefault(bar.date, {})[symbol] = bar
                self._index_on.setdefault(bar.date, {})[symbol] = index

    # -- precomputation ----------------------------------------------------

    def _precompute_atr(self) -> dict[str, np.ndarray]:
        if self.config.atr_stop_multiple is None:
            return {}
        out: dict[str, np.ndarray] = {}
        for symbol, bars in self.bars_by_symbol.items():
            if not bars:
                continue
            out[symbol] = atr_indicator(
                np.array([b.high for b in bars], dtype=float),
                np.array([b.low for b in bars], dtype=float),
                np.array([b.close for b in bars], dtype=float),
                period=self.config.atr_period,
            )
        return out

    def _precompute_volatility(self) -> dict[str, np.ndarray]:
        """Trailing annualised volatility of close-to-close returns.

        Estimated over ``atr_period`` sessions, the same lookback the ATR stop
        uses -- one risk horizon rather than two that can be tuned against each
        other.
        """
        if self.config.position_sizing != "volatility_target":
            return {}
        window = self.config.atr_period
        out: dict[str, np.ndarray] = {}
        for symbol, bars in self.bars_by_symbol.items():
            closes = np.array([b.close for b in bars], dtype=float)
            values = np.full(closes.shape, np.nan)
            if len(closes) > window:
                returns = np.diff(closes) / closes[:-1]
                for i in range(window, len(closes)):
                    values[i] = float(returns[i - window : i].std()) * (
                        TRADING_DAYS_PER_YEAR**0.5
                    )
            out[symbol] = values
        return out

    # -- cash and book -----------------------------------------------------

    def _available(self, symbol: str) -> float:
        return self._sleeve_cash[symbol] if self.sleeved else self._pool_cash

    def _credit(self, symbol: str, amount: float) -> None:
        if self.sleeved:
            self._sleeve_cash[symbol] += amount
        else:
            self._pool_cash += amount

    @property
    def cash(self) -> float:
        return sum(self._sleeve_cash.values()) if self.sleeved else self._pool_cash

    def equity(self) -> float:
        """Cash plus the market value of what is held.

        A short contributes negatively: opening one credits its proceeds to
        cash, so the two cancel at entry and the position's P&L is the gap
        between them thereafter.
        """
        total = self.cash
        # Summed in selection order so the floating-point result is stable.
        for symbol in self.symbols:
            position = self._positions.get(symbol)
            if position is None:
                continue
            mark = self._last_price.get(symbol, position.entry_price)
            total += position.qty * mark if position.side == "long" else -position.qty * mark
        return total

    def realized_pnl(self) -> float:
        return self._realized

    def open_positions(self) -> list[_Position]:
        return [self._positions[s] for s in sorted(self._positions)]

    # -- pricing -----------------------------------------------------------

    def _slipped(self, price: float, side: str) -> float:
        """Slippage always moves the price against the trade."""
        adjustment = price * self.config.slippage_bps * BPS
        return price + adjustment if side in ("buy", "cover") else price - adjustment

    def _commission_on(self, notional: float) -> float:
        return abs(notional) * self.config.commission_bps * BPS

    # -- sizing ------------------------------------------------------------

    def _size(self, symbol: str, price: float, index: int) -> float:
        """Quantity to open, or 0.0 when the config leaves no room for one."""
        config = self.config
        available = self._available(symbol)
        if available <= 0 or price <= 0:
            return 0.0

        equity = self.equity()
        if config.position_sizing == "equal_weight":
            notional = available
        elif config.position_sizing == "fixed_fraction":
            notional = equity * float(config.sizing_value or 0.0)
        elif config.position_sizing == "fixed_notional":
            notional = float(config.sizing_value or 0.0)
        else:
            volatility = self._vol.get(symbol)
            if volatility is None or index >= len(volatility) or np.isnan(volatility[index]):
                return 0.0
            realised = float(volatility[index])
            # A name that has not moved at all would size to infinity.
            if realised <= 0:
                return 0.0
            notional = equity * float(config.sizing_value or 0.0) / realised

        notional = min(notional, equity * config.max_position_pct, available)
        return notional / price if notional > 0 else 0.0

    # -- opening and closing -----------------------------------------------

    def _open(
        self, date: str, symbol: str, side: str, price: float, index: int, at_open: bool
    ) -> Fill | None:
        config = self.config
        if config.max_positions is not None and len(self._positions) >= config.max_positions:
            self._counters["rejected_max_positions"] += 1
            return None
        if config.cooldown_days:
            last_exit = self._last_exit_index.get(symbol)
            if last_exit is not None and index - last_exit < config.cooldown_days:
                self._counters["rejected_cooldown"] += 1
                return None

        action = "buy" if side == "long" else "short"
        fill_price = self._slipped(price, action)
        qty = self._size(symbol, fill_price, index)
        if qty <= 0:
            self._counters["rejected_no_cash"] += 1
            return None

        notional = qty * fill_price
        commission = self._commission_on(notional)
        slippage = abs(fill_price - price) * qty

        # Cash: a long spends the notional, a short receives it. Both pay the
        # commission.
        self._credit(symbol, (-notional if side == "long" else notional) - commission)
        self._commission += commission
        self._slippage += slippage
        self._realized -= commission

        stop_price, target_price = self._protective_levels(symbol, side, fill_price, index)
        self._positions[symbol] = _Position(
            symbol=symbol,
            side=side,
            qty=qty,
            entry_date=date,
            entry_index=index,
            entry_price=fill_price,
            entry_fees=commission,
            filled_at_open=at_open,
            stop_price=stop_price,
            target_price=target_price,
            best_close=fill_price,
        )
        fill = Fill(
            date=date,
            symbol=symbol,
            side=action,
            qty=qty,
            price=fill_price,
            value=notional,
            commission=commission,
            slippage=slippage,
            realized_pnl=0.0,
            reason="signal",
        )
        self.fills.append(fill)
        self._counters["fills"] += 1
        return fill

    def _protective_levels(
        self, symbol: str, side: str, entry_price: float, index: int
    ) -> tuple[float | None, float | None]:
        """Stop and target, fixed at entry.

        A percentage stop and an ATR stop can both be set; the tighter of the
        two wins, because a user who asks for both is asking for whichever
        binds first, not for the looser one.
        """
        config = self.config
        stops: list[float] = []
        if config.stop_loss_pct is not None:
            stops.append(
                entry_price * (1 - config.stop_loss_pct)
                if side == "long"
                else entry_price * (1 + config.stop_loss_pct)
            )
        if config.atr_stop_multiple is not None:
            series = self._atr.get(symbol)
            if series is not None and index < len(series) and not np.isnan(series[index]):
                offset = config.atr_stop_multiple * float(series[index])
                stops.append(
                    entry_price - offset if side == "long" else entry_price + offset
                )
        stop_price = None
        if stops:
            stop_price = max(stops) if side == "long" else min(stops)

        target_price = None
        if config.take_profit_pct is not None:
            target_price = (
                entry_price * (1 + config.take_profit_pct)
                if side == "long"
                else entry_price * (1 - config.take_profit_pct)
            )
        return stop_price, target_price

    def _close(
        self, date: str, symbol: str, price: float, index: int, reason: str
    ) -> Fill | None:
        position = self._positions.get(symbol)
        if position is None:
            return None

        action = "sell" if position.side == "long" else "cover"
        fill_price = self._slipped(price, action)
        notional = position.qty * fill_price
        commission = self._commission_on(notional)
        slippage = abs(fill_price - price) * position.qty

        self._credit(symbol, (notional if position.side == "long" else -notional) - commission)
        self._commission += commission
        self._slippage += slippage

        gross = (
            position.qty * (fill_price - position.entry_price)
            if position.side == "long"
            else position.qty * (position.entry_price - fill_price)
        )
        net = gross - commission
        self._realized += net

        fees = position.entry_fees + commission
        self.closed_trades.append(
            ExecutedTrade(
                symbol=symbol,
                side=position.side,
                entry_date=position.entry_date,
                entry_price=position.entry_price,
                exit_date=date,
                exit_price=fill_price,
                qty=position.qty,
                return_pct=self._return_pct(position.side, position.entry_price, fill_price),
                open=False,
                exit_reason=reason,
                pnl=gross - fees,
                fees=fees,
            )
        )
        del self._positions[symbol]
        self._last_exit_index[symbol] = index

        fill = Fill(
            date=date,
            symbol=symbol,
            side=action,
            qty=position.qty,
            price=fill_price,
            value=notional,
            commission=commission,
            slippage=slippage,
            realized_pnl=net,
            reason=reason,
        )
        self.fills.append(fill)
        self._counters["fills"] += 1
        return fill

    @staticmethod
    def _return_pct(side: str, entry_price: float, exit_price: float) -> float:
        if entry_price == 0:
            return 0.0
        raw = exit_price / entry_price - 1.0
        return raw if side == "long" else -raw

    # -- protective exits --------------------------------------------------

    def _protective_exit(self, bar: Any, position: _Position) -> tuple[str, float] | None:
        """The first protective level this bar touched, and where it filled.

        Tested in a fixed order -- stop, trailing stop, target, time -- so a bar
        that contains both a stop and a target resolves to the stop. A daily bar
        cannot say which came first, and taking the favourable one is how a
        backtest quietly awards itself the benefit of every doubt.

        Gaps are resolved pessimistically in *both* directions, which is not
        symmetric arithmetic and is easy to get wrong:

        * A **stop** is an order to leave on weakness. A session that gaps clean
          through it fills at the open, which is worse than the level. That is
          what actually happens, and pretending the stop held is how a backtest
          hides its worst days.
        * A **target** is an order to leave on strength. A session that gaps
          clean through it would really fill at the open, which is *better* than
          the level -- so the engine deliberately does not take it, and fills at
          the target. Awarding yourself every favourable gap adds up to a
          material edge that no live book ever collects.
        """
        config = self.config
        long = position.side == "long"

        if position.stop_price is not None:
            hit = bar.low <= position.stop_price if long else bar.high >= position.stop_price
            if hit:
                price = (
                    min(position.stop_price, bar.open)
                    if long
                    else max(position.stop_price, bar.open)
                )
                return "stop_loss", price

        if config.trailing_stop_pct is not None:
            trail = (
                position.best_close * (1 - config.trailing_stop_pct)
                if long
                else position.best_close * (1 + config.trailing_stop_pct)
            )
            hit = bar.low <= trail if long else bar.high >= trail
            if hit:
                price = min(trail, bar.open) if long else max(trail, bar.open)
                return "trailing_stop", price

        if position.target_price is not None:
            hit = (
                bar.high >= position.target_price if long else bar.low <= position.target_price
            )
            if hit:
                # The target itself, never the open: see the docstring. A gap
                # past a profit target is a windfall the backtest declines.
                return "take_profit", position.target_price

        return None

    # -- the main loop -----------------------------------------------------

    def ingest(self, symbol: str, bar: Any) -> None:
        """Append one bar to an instrument's history.

        The streaming path has no ``bars_by_symbol`` up front -- bars arrive on
        a topic -- so it builds the series as it goes and then calls
        :meth:`step_day`. Both paths end up in the same loop, which is the
        point: a live replay and a batch one cannot disagree about what a
        strategy did.
        """
        if symbol not in self.bars_by_symbol:
            return  # outside this run's selection
        series = self.bars_by_symbol[symbol]
        index = len(series)
        series.append(bar)
        self._bar_on.setdefault(bar.date, {})[symbol] = bar
        self._index_on.setdefault(bar.date, {})[symbol] = index
        if self._atr or self._vol:
            # Only configs with an ATR stop or volatility sizing pay this, and
            # they pay it per bar. Recomputing a whole series per arrival is
            # quadratic; acceptable for a replay of a single window, and the
            # default config recomputes nothing at all.
            self._atr = self._precompute_atr()
            self._vol = self._precompute_volatility()

    def step_day(self, date: str, decisions_today: list[Decision]) -> DayState:
        """Process exactly one date and return the book at its close.

        The whole ordering contract lives here, in one place, used by both the
        batch walk and the streaming one.
        """
        bars_today = self._bar_on.get(date, {})
        indices = self._index_on.get(date, {})
        closes = {symbol: float(bar.close) for symbol, bar in bars_today.items()}
        for symbol, close in closes.items():
            self._last_price[symbol] = close

        fills_today: list[Fill] = []

        # 1. Orders queued yesterday fill at today's open.
        fills_today.extend(self._drain_pending(date, bars_today, indices))

        # 2. Protective exits, against this bar's own range.
        for symbol in sorted(self._positions):
            position = self._positions[symbol]
            bar = bars_today.get(symbol)
            if bar is None:
                continue
            index = indices[symbol]
            # A position entered at today's close has no exposure left today;
            # one entered at today's open has the whole session.
            live = index > position.entry_index or (
                index == position.entry_index and position.filled_at_open
            )
            if not live:
                continue
            outcome = self._protective_exit(bar, position)
            if outcome is None and self.config.max_holding_days is not None:
                if index - position.entry_index >= self.config.max_holding_days:
                    outcome = ("max_holding", float(bar.close))
            if outcome is not None:
                reason, price = outcome
                fill = self._close(date, symbol, price, index, reason)
                if fill is not None:
                    fills_today.append(fill)

        # 3 and 4. Today's decisions: closers first, then openers.
        for decision in sorted(
            decisions_today, key=lambda d: (_KIND_ORDER.get(d.kind, 9), d.symbol)
        ):
            fill = self._apply(decision, date, bars_today, indices)
            if fill is not None:
                fills_today.append(fill)

        # The trailing stop advances only after the bar has been tested, so
        # today's close can never have set today's own trigger.
        for symbol, position in self._positions.items():
            close = closes.get(symbol)
            if close is None:
                continue
            position.best_close = (
                max(position.best_close, close)
                if position.side == "long"
                else min(position.best_close, close)
            )

        return DayState(
            date=date,
            closes=closes,
            fills=fills_today,
            equity=self.equity(),
            cash=self.cash,
            positions=len(self._positions),
            realized_pnl=self._realized,
        )

    def iter_days(self, decisions: list[Decision]) -> Iterator[DayState]:
        """Walk the window, yielding one state per date.

        The replay consumes this directly; :func:`simulate` drains it. There is
        only one loop, so the two can never drift.
        """
        by_date: dict[str, list[Decision]] = {}
        for decision in decisions:
            by_date.setdefault(decision.date, []).append(decision)

        for date in sorted(set(self._bar_on) | set(by_date)):
            yield self.step_day(date, by_date.get(date, []))

    def _drain_pending(
        self, date: str, bars_today: dict[str, Any], indices: dict[str, int]
    ) -> list[Fill]:
        if not self._pending:
            return []
        still_waiting: list[_PendingOrder] = []
        fills: list[Fill] = []
        for order in self._pending:
            bar = bars_today.get(order.symbol)
            if bar is None:
                # No session for this instrument yet; the order keeps waiting
                # rather than filling at some other instrument's price.
                still_waiting.append(order)
                continue
            index = indices[order.symbol]
            price = float(bar.open)
            if order.kind == "close":
                # Re-checked against the book rather than assumed still valid:
                # a stop may have taken this position out in the meantime.
                if order.symbol in self._positions:
                    fill = self._close(date, order.symbol, price, index, "signal")
                    if fill is not None:
                        fills.append(fill)
            elif order.symbol not in self._positions:
                side = "long" if order.direction == "bullish" else "short"
                fill = self._open(date, order.symbol, side, price, index, at_open=True)
                if fill is not None:
                    fills.append(fill)
        self._pending = still_waiting
        return fills

    def _apply(
        self,
        decision: Decision,
        date: str,
        bars_today: dict[str, Any],
        indices: dict[str, int],
    ) -> Fill | None:
        symbol = decision.symbol
        if symbol not in self._sleeve_cash:
            return None  # not in this run's selection
        position = self._positions.get(symbol)
        config = self.config

        # A bullish decision closes a short and opens a long; a bearish one does
        # the reverse. Which of the two applies depends on what is held, so the
        # book is consulted before the kind is.
        closes_position = position is not None and (
            (decision.direction == "bearish" and position.side == "long")
            or (decision.direction == "bullish" and position.side == "short")
        )
        may_close = decision.kind in ("exit", "both")
        may_open = decision.kind in ("entry", "both")

        if closes_position and may_close:
            index = indices.get(symbol)
            if index is not None and index - position.entry_index < config.min_holding_days:
                return None
            action = "close"
        elif position is None and may_open:
            if decision.direction == "bearish" and not config.allow_shorts:
                self._counters["rejected_shorts_disabled"] += 1
                return None
            action = "open"
        else:
            # Already positioned the way this decision points (no pyramiding),
            # or an exit with nothing to exit.
            return None
        self._counters["orders"] += 1

        bar = bars_today.get(symbol)
        if bar is None:
            # No bar means no price to transact at. Counted, not silently
            # dropped -- a run that lost half its signals this way should say so.
            self._counters["dropped_no_bar"] += 1
            return None

        if config.fill_timing == "next_open":
            self._pending.append(
                _PendingOrder(
                    symbol=symbol,
                    kind=action,
                    direction=decision.direction,
                    signal_date=date,
                )
            )
            return None

        index = indices[symbol]
        price = float(bar.close)
        if action == "close":
            return self._close(date, symbol, price, index, "signal")
        side = "long" if decision.direction == "bullish" else "short"
        return self._open(date, symbol, side, price, index, at_open=False)

    # -- results -----------------------------------------------------------

    def trades(self) -> list[ExecutedTrade]:
        """Closed trades plus whatever is still open, marked at the last price.

        An open position is reported with ``open=True`` and the reason
        ``end_of_window``: it is not a realised trade and never counts toward
        the win rate.
        """
        out = list(self.closed_trades)
        for symbol in sorted(self._positions):
            position = self._positions[symbol]
            last = self._last_price.get(symbol, position.entry_price)
            gross = (
                position.qty * (last - position.entry_price)
                if position.side == "long"
                else position.qty * (position.entry_price - last)
            )
            out.append(
                ExecutedTrade(
                    symbol=symbol,
                    side=position.side,
                    entry_date=position.entry_date,
                    entry_price=position.entry_price,
                    exit_date=None,
                    exit_price=last,
                    qty=position.qty,
                    return_pct=self._return_pct(position.side, position.entry_price, last),
                    open=True,
                    exit_reason="end_of_window",
                    pnl=gross - position.entry_fees,
                    fees=position.entry_fees,
                )
            )
        out.sort(key=lambda t: (t.symbol, t.entry_date))
        return out

    def summary(self) -> ExecutionSummary:
        return ExecutionSummary(
            total_commission=self._commission,
            total_slippage=self._slippage,
            **self._counters,
        )


@dataclass(frozen=True)
class ExecutionResult:
    equity: list[EquityPoint]
    trades: list[ExecutedTrade]
    fills: list[Fill]
    summary: ExecutionSummary
    assumptions: list[str]


def simulate(
    symbols: list[str],
    bars_by_symbol: dict[str, list[Any]],
    decisions: list[Decision],
    config: ExecutionConfig | None = None,
) -> ExecutionResult:
    """Run a whole window and keep the result. The batch entry point."""
    simulator = ExecutionSimulator(symbols, bars_by_symbol, config)
    curve: list[EquityPoint] = []
    for day in simulator.iter_days(decisions):
        # Only dates with a bar enter the curve: a date on which nothing in the
        # selection traded is not a mark, it is a holiday.
        if day.closes:
            curve.append(EquityPoint(date=day.date, value=day.equity))
    return ExecutionResult(
        equity=curve,
        trades=simulator.trades(),
        fills=list(simulator.fills),
        summary=simulator.summary(),
        assumptions=simulator.config.assumptions(),
    )
