"""A deterministic long-only portfolio simulator for historical replay.

Pure python, no I/O, no wall-clock: the same sequence of marks and signals
always produces the same book (Constitution VI).

Sizing deliberately mirrors :mod:`quantlab.research.performance` so a replay
reconciles with ``GET /runs/{id}/performance`` on the same run: capital is
split into one equal-weight sleeve per instrument selected for the run, an
untraded sleeve sits in cash, a bullish signal invests the symbol's whole
sleeve at the close of the signal date, and the next bearish signal on that
symbol returns the sleeve to cash. A repeat signal in the direction already
held is ignored, as is a bearish signal with nothing held. Positions are
fractional -- a sleeve is always fully invested while in a trade, which is
what the sleeve multipliers in ``performance.equity_series`` express. No
costs, no slippage. This is still not a tradeable backtest; it is the same
measuring instrument as ``compute_performance``, observed day by day instead
of after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass

from quantlab.research import performance


@dataclass(frozen=True)
class Fill:
    """One executed trade, at the close of the signal date."""

    date: str
    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    price: float
    value: float
    #: Cash locked in by a sell; zero for a buy.
    realized_pnl: float


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    qty: float
    entry_date: str
    entry_price: float
    last_price: float
    unrealized_pnl: float


@dataclass(frozen=True)
class _OpenPosition:
    qty: float
    entry_date: str
    entry_price: float


class PortfolioSimulator:
    """Per-symbol sleeves over one run's selection.

    ``symbols`` is the run's recorded selection; signals or bars for anything
    else are ignored rather than silently widening the book.
    """

    def __init__(self, symbols: list[str], initial_cash: float = performance.INITIAL_CAPITAL):
        if not symbols:
            raise ValueError("a portfolio needs at least one symbol")
        self.symbols = list(symbols)
        self.initial_cash = float(initial_cash)
        sleeve = self.initial_cash / len(self.symbols)
        self._cash = dict.fromkeys(self.symbols, sleeve)
        self._positions: dict[str, _OpenPosition] = {}
        self._last_price: dict[str, float] = {}
        self.fills: list[Fill] = []
        self.closed_trades: list[performance.Trade] = []

    def mark(self, closes: dict[str, float]) -> None:
        """Mark to a date's closes. A symbol with no bar keeps its last price
        -- it is closed for the day, not worthless (the same carry-forward
        ``performance._combine`` applies)."""
        for symbol, close in closes.items():
            if symbol in self._cash:
                self._last_price[symbol] = float(close)

    def apply_signal(
        self, date: str, symbol: str, direction: str, price: float | None
    ) -> Fill | None:
        """Apply one stored signal, filling at the close of its own date.

        ``price`` must be that date's close for the symbol, or ``None`` when
        the symbol has no bar that day -- in which case there is no price to
        transact at and the signal is skipped, the same skip
        ``performance.pair_trades`` makes.
        """
        if price is None or symbol not in self._cash:
            return None
        if direction == "bullish" and symbol not in self._positions:
            cash = self._cash[symbol]
            qty = cash / price
            self._positions[symbol] = _OpenPosition(qty=qty, entry_date=date, entry_price=price)
            self._cash[symbol] = 0.0
            fill = Fill(date, symbol, "buy", qty, price, cash, 0.0)
            self.fills.append(fill)
            return fill
        if direction == "bearish" and symbol in self._positions:
            position = self._positions.pop(symbol)
            value = position.qty * price
            self._cash[symbol] = value
            realized = position.qty * (price - position.entry_price)
            self.closed_trades.append(
                performance.Trade(
                    symbol=symbol,
                    entry_date=position.entry_date,
                    entry_price=position.entry_price,
                    exit_date=date,
                    exit_price=price,
                    return_pct=price / position.entry_price - 1.0,
                    open=False,
                )
            )
            fill = Fill(date, symbol, "sell", position.qty, price, value, realized)
            self.fills.append(fill)
            return fill
        return None

    @property
    def cash(self) -> float:
        return sum(self._cash.values())

    def equity(self) -> float:
        """Book value, summed per sleeve in selection order -- the same
        summation order as ``performance._combine``."""
        total = 0.0
        for symbol in self.symbols:
            position = self._positions.get(symbol)
            if position is None:
                total += self._cash[symbol]
            else:
                total += position.qty * self._last_price.get(symbol, position.entry_price)
        return total

    def open_positions(self) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol=symbol,
                qty=position.qty,
                entry_date=position.entry_date,
                entry_price=position.entry_price,
                last_price=self._last_price.get(symbol, position.entry_price),
                unrealized_pnl=position.qty
                * (self._last_price.get(symbol, position.entry_price) - position.entry_price),
            )
            for symbol, position in sorted(self._positions.items())
        ]

    def realized_pnl(self) -> float:
        return sum(fill.realized_pnl for fill in self.fills)

    def trades(self) -> list[performance.Trade]:
        """Closed trades plus positions still open, marked at the last known
        price -- the same convention ``performance.pair_trades`` uses, so the
        two trade lists are directly comparable."""
        trades = list(self.closed_trades)
        for symbol, position in self._positions.items():
            last = self._last_price.get(symbol, position.entry_price)
            trades.append(
                performance.Trade(
                    symbol=symbol,
                    entry_date=position.entry_date,
                    entry_price=position.entry_price,
                    exit_date=None,
                    exit_price=last,
                    return_pct=last / position.entry_price - 1.0,
                    open=True,
                )
            )
        trades.sort(key=lambda t: (t.symbol, t.entry_date))
        return trades
