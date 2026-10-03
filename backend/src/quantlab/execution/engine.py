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

    mark -> corporate actions -> fill orders queued yesterday -> protective exits
         -> signal exits -> entries

Corporate actions come first because they happened before the session opened:
a position held into a split's ex-date wakes up holding more shares, and one
held into a dividend's ex-date is owed the payout, whatever it does today.

Protective exits come before signal exits because a stop that was hit intraday
was hit before the close that produced the signal. Entries come last because a
position closed today frees the capital and the slot that a new position needs,
and resolving it the other way would silently cap the book at one rotation a
bar.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from quantlab.execution.adjustments import CorporateAction, applies
from quantlab.execution.adjustments import factors as adjustment_factors
from quantlab.execution.bars import BarSeries, column, unit_of
from quantlab.execution.config import (
    BPS,
    DEFERRED_FILL_TIMING,
    TRADING_DAYS_PER_YEAR,
    ExecutionConfig,
)
from quantlab.execution.minutes import MinuteBar, MinuteSource, vwap
from quantlab.indicators.technical import atr as atr_indicator

#: Resolution order within one date; mirrors the composer's own ordering.
_KIND_ORDER = {"exit": 0, "both": 1, "entry": 2}



def _session_numbers(bars: Any) -> np.ndarray:
    """0, 0, ..., 1, 1, ...: which trading day each bar belongs to.

    A new number wherever the date changes, so it counts the instrument's own
    sessions -- a holiday it did not trade is not a day it was held.
    """
    if isinstance(bars, BarSeries):
        days = bars.stamps.astype("datetime64[D]")
    else:
        days = np.array([str(bar.date)[:10] for bar in (bars or [])])
    if len(days) == 0:
        return np.zeros(0, dtype=np.int64)
    changes = np.concatenate(([0], (days[1:] != days[:-1]).astype(np.int64)))
    return np.cumsum(changes)

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
    #: Exchange-local HH:MM, when minute bars placed the fill inside the
    #: session (a protective exit under intraday_resolution="minute").
    time: str | None = None


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
    #: Dividends received (long) or paid (short, negative) while held.
    dividends: float = 0.0
    #: Exchange-local HH:MM of the exit, when minute bars placed it.
    exit_time: str | None = None


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
    total_borrow: float = 0.0
    #: Net dividend cash: received on longs, minus paid on shorts.
    total_dividends: float = 0.0
    splits_applied: int = 0
    dividends_applied: int = 0
    #: Under intraday_resolution="minute": protective exits whose level and
    #: time came from minute bars, and sessions that had to fall back to the
    #: daily rule (no minute bars, or none reaching the level the daily range
    #: shows) -- including VWAP fills that fell back to the typical price.
    minute_resolved_exits: int = 0
    minute_fallbacks: int = 0


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
    #: Borrow charged so far on a short; folded into the trade's fees on close.
    borrow_accrued: float = 0.0
    #: Dividend cash so far (negative on a short); realised with the trade.
    dividends: float = 0.0
    #: The same per share held, in today's share terms, for the trade's return.
    dividends_per_share: float = 0.0


def _deferred_fill_price(fill_timing: str, bar: Any) -> float:
    """Where a queued order fills on the session after its signal.

    ``next_typical`` is (high + low + close) / 3: the usual stand-in for VWAP
    when all there is is a daily bar. It is not VWAP -- that needs the volume
    at each price -- but it sits inside the session's range the way a patiently
    worked order does, rather than at either extreme.
    """
    if fill_timing == "next_open":
        return float(bar.open)
    if fill_timing == "next_close":
        return float(bar.close)
    if fill_timing == "next_typical":
        return (float(bar.high) + float(bar.low) + float(bar.close)) / 3.0
    raise ValueError(f"{fill_timing!r} does not queue orders")


@dataclass
class _PendingOrder:
    """An order waiting for the next session (``fill_timing`` other than
    ``signal_close``): its open, its close, or its typical price."""

    symbol: str
    #: Already resolved to "open" or "close": what the decision meant given the
    #: book as it stood when the signal fired.
    kind: str
    direction: str
    signal_date: str


@dataclass
class _AtrState:
    """Running Wilder ATR for one instrument, extended in O(1) per bar.

    Mirrors :func:`quantlab.indicators.technical.atr` operation for operation:
    the seed is the mean of TR[1..period] (TR[0] is a partial bar and never
    enters the average), then the recurrence. Replaying the constructor's bars
    through :meth:`observe` lands on exactly the value the batch precompute
    ends with, so an ingested bar continues the series bit-identically.
    """

    period: int
    prev_close: float | None = None
    #: TR[1..] until the seed fires; dropped afterwards.
    seed_ranges: list[float] = field(default_factory=list)
    count: int = 0
    value: float | None = None  # ATR at the latest bar; None while undefined

    def observe(self, high: float, low: float, close: float) -> float:
        index = self.count
        self.count += 1
        if index == 0:
            self.prev_close = close
            return np.nan
        tr = max(high - low, max(abs(high - self.prev_close), abs(low - self.prev_close)))
        self.prev_close = close
        if index < self.period:
            self.seed_ranges.append(tr)
            return np.nan
        if index == self.period:
            self.seed_ranges.append(tr)
            self.value = float(np.asarray(self.seed_ranges, dtype=float).mean())
            self.seed_ranges = []
        else:
            self.value = (self.value * (self.period - 1) + tr) / self.period
        return self.value


@dataclass
class _VolState:
    """Running close-to-close returns for the volatility estimate.

    Keeps the trailing ``window`` returns; one population std per bar replaces
    reslicing and re-averaging the whole history.
    """

    window: int
    prev_close: float | None = None
    returns: deque = field(init=False)
    #: Bars a year: 252 for daily bars, 252 x bars-per-session intraday.
    periods_per_year: int = TRADING_DAYS_PER_YEAR

    def __post_init__(self) -> None:
        self.returns = deque(maxlen=self.window)

    def observe(self, close: float) -> float:
        if self.prev_close is not None:
            self.returns.append((close - self.prev_close) / self.prev_close)
        self.prev_close = close
        if len(self.returns) < self.window:
            return np.nan
        return float(np.asarray(self.returns, dtype=float).std()) * (self.periods_per_year**0.5)


class ExecutionSimulator:
    """Runs one strategy's decisions over one selection's bars."""

    def __init__(
        self,
        symbols: list[str],
        bars_by_symbol: dict[str, list[Any]],
        config: ExecutionConfig | None = None,
        corporate_actions: dict[str, list[CorporateAction]] | None = None,
        minute_source: MinuteSource | None = None,
    ) -> None:
        """``bars_by_symbol`` are raw, as traded. ``corporate_actions`` are the
        splits and dividends to apply; only those the config's
        ``price_adjustment`` covers are used, and none at all under ``none``.
        ``minute_source`` supplies a session's minute bars (also raw, so they
        sit on the same basis as every level the book holds); it is consulted
        only under ``intraday_resolution="minute"``."""
        if not symbols:
            raise ValueError("a run needs at least one symbol")
        self.symbols = list(symbols)
        self.config = config or ExecutionConfig()
        # Intraday bars arrive as columns (BarSeries) and stay columns: turning
        # 2M bars into objects is what this representation exists to avoid.
        self._columnar = any(isinstance(b, BarSeries) for b in bars_by_symbol.values())
        # Daily columns step by day, intraday ones by minute; one run is one.
        self._unit = next(
            (unit_of(b) for b in bars_by_symbol.values() if isinstance(b, BarSeries)), "m"
        )
        self.bars_by_symbol = {
            s: self._series(bars_by_symbol.get(s)) for s in self.symbols
        }
        self._periods_per_year = self.config.periods_per_year

        # Filtered here as well as by the caller: what the config asks for is
        # the engine's to enforce, not something it trusts a caller to have done.
        mode = self.config.price_adjustment
        self._actions: dict[str, list[CorporateAction]] = {
            s: sorted(
                (a for a in (corporate_actions or {}).get(s) or [] if applies(a, mode)),
                key=lambda a: a.ex_date,
            )
            for s in self.symbols
        }
        #: Next action not yet applied, per symbol.
        self._next_action = dict.fromkeys(self.symbols, 0)
        #: Adjusted / raw price per bar. ATR and volatility are measured on the
        #: adjusted series -- a split is not a range -- and an ATR offset is
        #: turned back into raw-price terms at entry.
        self._price_factor: dict[str, list[float]] = {
            s: adjustment_factors(self.bars_by_symbol[s], self._actions[s])[0]
            for s in self.symbols
            if self._actions[s]
        }
        self._dividends = 0.0
        self._splits_applied = 0
        self._dividends_applied = 0

        self._minute_source = (
            minute_source if self.config.intraday_resolution == "minute" else None
        )
        self._minute_resolved = 0
        self._minute_fallbacks = 0

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
        self._borrow = 0.0
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

        # Incremental state so `ingest` can extend both series in O(1) a bar
        # instead of recomputing them over the whole history. Gated on the
        # same truthiness `ingest` tests, evaluated once here: the dicts only
        # ever gain entries, so a gate that starts false stays false (a
        # simulator constructed with no bars at all never maintains ATR,
        # exactly as the recompute this replaces behaved), and one that starts
        # true stays true.
        self._atr_state: dict[str, _AtrState] = {}
        self._vol_state: dict[str, _VolState] = {}
        # Columnar runs are batch-only (no `ingest`), so need no running state.
        if (self._atr or self._vol) and not self._columnar:
            if self.config.atr_stop_multiple is not None:
                self._atr_state = {
                    symbol: self._seed_atr_state(bars)
                    for symbol, bars in self.bars_by_symbol.items()
                }
            if self.config.position_sizing == "volatility_target":
                self._vol_state = {
                    symbol: self._seed_vol_state(bars)
                    for symbol, bars in self.bars_by_symbol.items()
                }

        # Bar lookup by date, and each symbol's own bar index on that date --
        # "how many sessions has this been held" must count the instrument's
        # own sessions, not calendar dates on which some other name traded.
        #
        # Built for row-wise (daily) bars only. A columnar run walks a merged
        # timeline with one pointer per instrument instead: a dict entry per
        # bar is ~100 B, which at 2M intraday bars is most of the budget.
        # Each bar's trading session, numbered from the symbol's first. Holding
        # periods and cooldowns are in *days* at every bar size: on daily bars
        # this is the bar index itself; on 5-minute bars, 78 bars share a
        # number. Two sessions held means two trading days, never two bars.
        self._session_of: dict[str, np.ndarray] = {
            symbol: _session_numbers(bars) for symbol, bars in self.bars_by_symbol.items()
        }

        self._bar_on: dict[str, dict[str, Any]] = {}
        self._index_on: dict[str, dict[str, int]] = {}
        if not self._columnar:
            for symbol, bars in self.bars_by_symbol.items():
                for index, bar in enumerate(bars):
                    self._bar_on.setdefault(bar.date, {})[symbol] = bar
                    self._index_on.setdefault(bar.date, {})[symbol] = index

    def _series(self, bars: Any) -> Any:
        if isinstance(bars, BarSeries):
            return bars
        if self._columnar:
            empty = np.array([], dtype=float)
            stamps = np.array([], dtype=f"datetime64[{self._unit}]")
            return BarSeries(stamps, empty, empty, empty, empty, [])
        return list(bars or [])

    # -- precomputation ----------------------------------------------------

    def _precompute_atr(self) -> dict[str, np.ndarray]:
        if self.config.atr_stop_multiple is None:
            return {}
        out: dict[str, np.ndarray] = {}
        for symbol, bars in self.bars_by_symbol.items():
            if not bars:
                continue
            factor = self._price_factor.get(symbol)
            factor = np.asarray(factor) if factor is not None else 1.0
            out[symbol] = atr_indicator(
                column(bars, "high") * factor,
                column(bars, "low") * factor,
                column(bars, "close") * factor,
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
            closes = column(bars, "close")
            if symbol in self._price_factor:
                closes = closes * np.asarray(self._price_factor[symbol])
            values = np.full(closes.shape, np.nan)
            if len(closes) > window:
                returns = np.diff(closes) / closes[:-1]
                # Population std (ddof=0), the rolling-std idiom; row k of the
                # view is returns[k : k + window], the slice bar k + window
                # used to loop over.
                values[window:] = np.lib.stride_tricks.sliding_window_view(
                    returns, window
                ).std(axis=1) * (self._periods_per_year**0.5)
            out[symbol] = values
        return out

    def _seed_atr_state(self, bars: list[Any]) -> _AtrState:
        """Replay the constructor's bars into an incremental ATR state.

        The recurrence is the batch precompute's arithmetic step for step, so
        the replayed state continues the precomputed array bit-identically.
        """
        state = _AtrState(period=self.config.atr_period)
        for bar in bars:
            state.observe(float(bar.high), float(bar.low), float(bar.close))
        return state

    def _seed_vol_state(self, bars: list[Any]) -> _VolState:
        state = _VolState(window=self.config.atr_period, periods_per_year=self._periods_per_year)
        for bar in bars:
            state.observe(float(bar.close))
        return state

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

    def _sessions_between(self, symbol: str, earlier: int, later: int) -> int:
        """Trading days from bar ``earlier`` to bar ``later`` of one symbol."""
        sessions = self._session_of.get(symbol)
        if sessions is None or later >= len(sessions) or earlier >= len(sessions):
            return later - earlier
        return int(sessions[later] - sessions[earlier])

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
            if (
                last_exit is not None
                and self._sessions_between(symbol, last_exit, index) < config.cooldown_days
            ):
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
                # The ATR is in adjusted terms; the stop sits on raw prices.
                factor = self._price_factor.get(symbol)
                scale = factor[index] if factor is not None and index < len(factor) else 1.0
                offset = config.atr_stop_multiple * float(series[index]) / scale
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
        self,
        date: str,
        symbol: str,
        price: float,
        index: int,
        reason: str,
        time: str | None = None,
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
        # Borrow was debited and dividends credited day by day; both are
        # realised with the trade.
        net = gross - commission - position.borrow_accrued + position.dividends
        self._realized += net

        fees = position.entry_fees + commission + position.borrow_accrued
        self.closed_trades.append(
            ExecutedTrade(
                symbol=symbol,
                side=position.side,
                entry_date=position.entry_date,
                entry_price=position.entry_price,
                exit_date=date,
                exit_price=fill_price,
                qty=position.qty,
                return_pct=self._return_pct(
                    position.side,
                    position.entry_price,
                    fill_price,
                    position.dividends_per_share,
                ),
                open=False,
                exit_reason=reason,
                pnl=gross - fees + position.dividends,
                fees=fees,
                dividends=position.dividends,
                exit_time=time,
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
            time=time,
        )
        self.fills.append(fill)
        self._counters["fills"] += 1
        return fill

    @staticmethod
    def _return_pct(
        side: str, entry_price: float, exit_price: float, dividends_per_share: float = 0.0
    ) -> float:
        """Total return: a long earns its dividends, a short pays them."""
        if entry_price == 0:
            return 0.0
        raw = (exit_price + dividends_per_share) / entry_price - 1.0
        return raw if side == "long" else -raw

    # -- corporate actions -------------------------------------------------

    def _apply_corporate_actions(self, date: str, bars_today: dict[str, Any]) -> None:
        """Apply every action that went ex on or before today.

        Only for an instrument with a bar today: its first session on or after
        the ex-date is when the book learns of it, and the price it marks at is
        already the post-action one. An action is applied once, whether or not
        anything was held, so the pointer only moves forward.
        """
        for symbol in bars_today:
            actions = self._actions.get(symbol)
            if not actions:
                continue
            index = self._next_action[symbol]
            while index < len(actions) and actions[index].ex_date <= date:
                position = self._positions.get(symbol)
                if position is not None and position.entry_date < actions[index].ex_date:
                    self._apply_action(symbol, position, actions[index])
                index += 1
            self._next_action[symbol] = index

    def _apply_action(self, symbol: str, position: _Position, action: CorporateAction) -> None:
        if action.is_split:
            ratio = float(action.split_ratio)
            # Same holding, more shares at a proportionally lower price: equity
            # does not move. Every level fixed in price terms moves with it.
            position.qty *= ratio
            position.entry_price /= ratio
            position.best_close /= ratio
            position.dividends_per_share /= ratio
            if position.stop_price is not None:
                position.stop_price /= ratio
            if position.target_price is not None:
                position.target_price /= ratio
            self._splits_applied += 1
        elif action.is_dividend:
            per_share = float(action.dividend)
            # Owed to whoever held at the previous close: paid to a long,
            # charged to a short (the borrower pays the lender's dividend).
            cash = position.qty * per_share * (1.0 if position.side == "long" else -1.0)
            self._credit(symbol, cash)
            position.dividends += cash
            position.dividends_per_share += per_share
            self._dividends += cash
            self._dividends_applied += 1

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

    # -- inside the session ------------------------------------------------

    def _pending_fill_price(self, symbol: str, date: str, bar: Any) -> float:
        """Where a queued order fills today. Opens and closes are the daily
        bar's auction prices; a VWAP is the session's own, from its minutes,
        falling back to the typical price for a session without any."""
        if self.config.fill_timing != "next_vwap":
            return _deferred_fill_price(self.config.fill_timing, bar)
        minutes = self._minute_source(symbol, date) if self._minute_source else []
        price = vwap(minutes)
        if price is None:
            self._minute_fallbacks += 1
            return _deferred_fill_price("next_typical", bar)
        return price

    def _protective_exit_minutes(
        self, bar: Any, position: _Position, minutes: list[MinuteBar]
    ) -> tuple[str, float, str] | None:
        """The first protective level the session crossed, minute by minute.

        The daily rule has to assume the stop whenever a stop and a target both
        sit inside one bar's range. Minutes say which came first. The same
        conventions hold everywhere else: the official open is checked first
        (a gap through a stop fills there; through a target, at the target);
        a level crossed inside a minute fills at the level, or at that minute's
        open if it opened beyond it; and when one minute contains both, the
        stop wins, because a minute bar cannot say which came first either.

        None when the minutes never reach a level the daily range reached --
        the minute feed is one venue's trades, and its extremes can fall short
        of the consolidated ones. The caller then keeps the daily answer.
        """
        if not minutes:
            return None
        config = self.config
        long = position.side == "long"
        stops: list[tuple[str, float]] = []
        if position.stop_price is not None:
            stops.append(("stop_loss", position.stop_price))
        if config.trailing_stop_pct is not None:
            trail = (
                position.best_close * (1 - config.trailing_stop_pct)
                if long
                else position.best_close * (1 + config.trailing_stop_pct)
            )
            stops.append(("trailing_stop", trail))
        target = position.target_price

        opening = float(bar.open)
        for reason, level in stops:
            if (opening <= level) if long else (opening >= level):
                return reason, opening, minutes[0].time
        if target is not None and ((opening >= target) if long else (opening <= target)):
            return "take_profit", target, minutes[0].time

        for minute in minutes:
            for reason, level in stops:
                if (minute.low <= level) if long else (minute.high >= level):
                    price = min(level, minute.open) if long else max(level, minute.open)
                    return reason, price, minute.time
            if target is not None and (
                (minute.high >= target) if long else (minute.low <= target)
            ):
                return "take_profit", target, minute.time
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
        if self._columnar:
            raise NotImplementedError("a columnar (intraday) run is batch-only")
        if symbol not in self.bars_by_symbol:
            return  # outside this run's selection
        series = self.bars_by_symbol[symbol]
        index = len(series)
        series.append(bar)
        self._bar_on.setdefault(bar.date, {})[symbol] = bar
        self._index_on.setdefault(bar.date, {})[symbol] = index
        # Extend the ATR/vol series in O(1) rather than recomputing them over
        # the whole history per bar, which was quadratic. The state dicts are
        # empty unless the constructor's gate passed, so configs without an
        # ATR stop or volatility sizing -- and the all-empty-constructor ATR
        # corner -- keep paying nothing, as before.
        atr_state = self._atr_state.get(symbol)
        if atr_state is not None:
            atr = atr_state.observe(float(bar.high), float(bar.low), float(bar.close))
            existing = self._atr.get(symbol)
            # A symbol empty at construction has no array yet; the batch
            # precompute only adds one once the symbol has bars.
            self._atr[symbol] = (
                np.array([atr]) if existing is None else np.append(existing, atr)
            )
        vol_state = self._vol_state.get(symbol)
        if vol_state is not None:
            vol = vol_state.observe(float(bar.close))
            self._vol[symbol] = np.append(self._vol[symbol], vol)

    def step_day(self, date: str, decisions_today: list[Decision]) -> DayState:
        """Process exactly one date and return the book at its close.

        The whole ordering contract lives in :meth:`_step`, in one place, used
        by the batch walk, the streaming one and the columnar (intraday) one.
        """
        return self._step(
            date, decisions_today, self._bar_on.get(date, {}), self._index_on.get(date, {})
        )

    def _step(
        self,
        date: str,
        decisions_today: list[Decision],
        bars_today: dict[str, Any],
        indices: dict[str, int],
    ) -> DayState:
        """One step -- a date, or an intraday bar's key -- given its bars."""
        closes = {symbol: float(bar.close) for symbol, bar in bars_today.items()}
        for symbol, close in closes.items():
            self._last_price[symbol] = close

        fills_today: list[Fill] = []

        # 0. Splits and dividends that went ex today, before the session opens.
        self._apply_corporate_actions(date, bars_today)

        # 1. Orders queued yesterday for today's open fill before anything else
        #    can happen in the session.
        if self.config.fill_timing == "next_open":
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
            exit_time = None
            if outcome is not None and self._minute_source is not None:
                # The daily range says a level was touched; the minutes say
                # which one first, and when.
                resolved = self._protective_exit_minutes(
                    bar, position, self._minute_source(symbol, date)
                )
                if resolved is None:
                    self._minute_fallbacks += 1
                else:
                    reason, price, exit_time = resolved
                    outcome = (reason, price)
                    self._minute_resolved += 1
            if outcome is None and self.config.max_holding_days is not None:
                held = self._sessions_between(symbol, position.entry_index, index)
                if held >= self.config.max_holding_days:
                    outcome = ("max_holding", float(bar.close))
            if outcome is not None:
                reason, price = outcome
                fill = self._close(date, symbol, price, index, reason, exit_time)
                if fill is not None:
                    fills_today.append(fill)

        # 2b. Orders queued yesterday for today's close or typical price fill
        #     only now: a stop the session hit on the way happened first, and
        #     re-checking the book below means it wins over the queued exit.
        if self.config.fill_timing in ("next_close", "next_typical", "next_vwap"):
            fills_today.extend(self._drain_pending(date, bars_today, indices))

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

        # 5. Borrow on every short held through today's close, on today's
        # market value. Charged per session the instrument traded, so a
        # holiday on its exchange costs nothing -- the /252 convention.
        rate = self.config.borrow_cost_bps * BPS / self._periods_per_year
        if rate:
            for symbol in sorted(self._positions):
                position = self._positions[symbol]
                close = closes.get(symbol)
                if position.side != "short" or close is None:
                    continue
                charge = position.qty * close * rate
                self._credit(symbol, -charge)
                position.borrow_accrued += charge
                self._borrow += charge

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

        if self._columnar:
            yield from self._iter_columnar(by_date)
            return
        for date in sorted(set(self._bar_on) | set(by_date)):
            yield self.step_day(date, by_date.get(date, []))

    def _iter_columnar(self, by_date: dict[str, list[Decision]]) -> Iterator[DayState]:
        """Walk the union of every instrument's bar times, one pointer each.

        The same steps the row-wise walk takes -- a key with no bar for some
        instrument simply has no bar for it -- without a lookup entry per bar.
        Decision keys with no bar at all still get a step, so they are counted
        as dropped exactly as on daily bars.
        """
        stamps = {s: series.stamps.view(np.int64) for s, series in self.bars_by_symbol.items()}
        extra = np.array(
            [np.datetime64(key, self._unit) for key in by_date],
            dtype=f"datetime64[{self._unit}]",
        ).view(np.int64)
        timeline = np.unique(np.concatenate([*stamps.values(), extra]))
        pointer = dict.fromkeys(stamps, 0)
        for t in timeline.tolist():
            bars_today: dict[str, Any] = {}
            indices: dict[str, int] = {}
            for symbol, column_ in stamps.items():
                i = pointer[symbol]
                if i < len(column_) and column_[i] == t:
                    bars_today[symbol] = self.bars_by_symbol[symbol][i]
                    indices[symbol] = i
                    pointer[symbol] = i + 1
            key = str(np.datetime64(t, self._unit))
            yield self._step(key, by_date.get(key, []), bars_today, indices)

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
            price = self._pending_fill_price(order.symbol, date, bar)
            if order.kind == "close":
                # Re-checked against the book rather than assumed still valid:
                # a stop may have taken this position out in the meantime.
                if order.symbol in self._positions:
                    fill = self._close(date, order.symbol, price, index, "signal")
                    if fill is not None:
                        fills.append(fill)
            elif order.symbol not in self._positions:
                side = "long" if order.direction == "bullish" else "short"
                # Only an open fill has the whole session ahead of it; one at
                # the close or through the day is not exposed to this bar's
                # range, so stops start tomorrow -- as for signal_close.
                at_open = self.config.fill_timing == "next_open"
                fill = self._open(date, order.symbol, side, price, index, at_open=at_open)
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
            if (
                index is not None
                and self._sessions_between(symbol, position.entry_index, index)
                < config.min_holding_days
            ):
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

        if config.fill_timing in DEFERRED_FILL_TIMING:
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
                    return_pct=self._return_pct(
                        position.side, position.entry_price, last, position.dividends_per_share
                    ),
                    open=True,
                    exit_reason="end_of_window",
                    pnl=gross - position.entry_fees - position.borrow_accrued + position.dividends,
                    fees=position.entry_fees + position.borrow_accrued,
                    dividends=position.dividends,
                )
            )
        out.sort(key=lambda t: (t.symbol, t.entry_date))
        return out

    def summary(self) -> ExecutionSummary:
        return ExecutionSummary(
            total_commission=self._commission,
            total_slippage=self._slippage,
            total_borrow=self._borrow,
            total_dividends=self._dividends,
            splits_applied=self._splits_applied,
            dividends_applied=self._dividends_applied,
            minute_resolved_exits=self._minute_resolved,
            minute_fallbacks=self._minute_fallbacks,
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
    corporate_actions: dict[str, list[CorporateAction]] | None = None,
    minute_source: MinuteSource | None = None,
) -> ExecutionResult:
    """Run a whole window and keep the result. The batch entry point."""
    simulator = ExecutionSimulator(
        symbols, bars_by_symbol, config, corporate_actions, minute_source
    )
    curve: list[EquityPoint] = []
    for day in simulator.iter_days(decisions):
        # Only dates with a bar enter the curve: a date on which nothing in the
        # selection traded is not a mark, it is a holiday.
        if day.closes:
            # One mark per session: an intraday run keeps each session's last
            # bar, so the curve -- and every daily statistic built on it -- is
            # in sessions whatever the bar frequency.
            session = day.date[:10]
            if curve and curve[-1].date == session:
                curve[-1] = EquityPoint(date=session, value=day.equity)
            else:
                curve.append(EquityPoint(date=session, value=day.equity))
    return ExecutionResult(
        equity=curve,
        trades=simulator.trades(),
        fills=list(simulator.fills),
        summary=simulator.summary(),
        assumptions=simulator.config.assumptions(),
    )
