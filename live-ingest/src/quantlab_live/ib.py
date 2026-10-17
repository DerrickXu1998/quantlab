"""The IBKR side, through ib_async. Everything IBKR-specific lives here.

The collector depends on the small ``Gateway`` protocol below rather than on
ib_async, so its logic is tested against a fake. Values IBKR has not sent
arrive as NaN; they leave here as None.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

log = logging.getLogger(__name__)

#: Error codes that mean "this symbol gets no prices", not "IBKR is down".
NO_DATA_CODES = {
    354: "no market data subscription for this symbol",
    10089: "the API needs an additional market data subscription",
    10090: "part of the requested data needs a subscription",
    10168: "market data is not subscribed; delayed data is off",
    10197: "no market data during a competing live session (TWS logged in elsewhere?)",
}


@dataclass(frozen=True)
class Quote:
    last: float | None
    bid: float | None
    ask: float | None
    volume: float | None
    time: datetime | None


def _value(x: Any) -> float | None:
    if x is None:
        return None
    try:
        value = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


class Gateway(Protocol):
    def connected(self) -> bool: ...
    async def connect(self) -> None: ...
    async def qualify(self, ib_symbol: str) -> Any | None: ...
    def subscribe(self, contract: Any) -> Any: ...
    def unsubscribe(self, contract: Any) -> None: ...
    def quote(self, ticker: Any) -> Quote: ...
    async def session_bars(self, contract: Any) -> list[dict]: ...
    async def liquid_hours(self, contract: Any) -> tuple[str, str]: ...
    def on_error(self, handler: Callable[[str, int, str], None]) -> None: ...


class IbGateway:
    """ib_async against IB Gateway (read-only API: this never places orders)."""

    def __init__(self, host: str, port: int, client_id: int) -> None:
        from ib_async import IB

        self._ib = IB()
        self._host, self._port, self._client_id = host, port, client_id
        self._handlers: list[Callable[[str, int, str], None]] = []
        self._ib.errorEvent += self._on_error

    def connected(self) -> bool:
        return self._ib.isConnected()

    async def connect(self) -> None:
        await self._ib.connectAsync(
            self._host, self._port, clientId=self._client_id, timeout=10, readonly=True
        )
        # 1 = live (streaming) prices; never fall back to delayed ones silently.
        self._ib.reqMarketDataType(1)

    async def qualify(self, ib_symbol: str) -> Any | None:
        from ib_async import Stock

        contract = Stock(ib_symbol, "SMART", "USD")
        try:
            qualified = await self._ib.qualifyContractsAsync(contract)
        except Exception:
            log.exception("qualify %s failed", ib_symbol)
            return None
        return qualified[0] if qualified and getattr(qualified[0], "conId", 0) else None

    def subscribe(self, contract: Any) -> Any:
        return self._ib.reqMktData(contract, "", False, False)

    def unsubscribe(self, contract: Any) -> None:
        self._ib.cancelMktData(contract)

    def quote(self, ticker: Any) -> Quote:
        return Quote(
            last=_value(ticker.last),
            bid=_value(ticker.bid),
            ask=_value(ticker.ask),
            volume=_value(ticker.volume),
            time=ticker.time,
        )

    async def session_bars(self, contract: Any) -> list[dict]:
        """The most recent regular session's 1-minute bars: today's so far
        while it trades, else the last full session."""
        bars = await self._ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="1 min",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=2,
        )
        out = []
        for bar in bars or []:
            start = bar.date if isinstance(bar.date, datetime) else None
            if start is None:
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            out.append(
                {
                    "start": start,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": max(0, int(bar.volume or 0)),
                }
            )
        return out

    async def liquid_hours(self, contract: Any) -> tuple[str, str]:
        details = await self._ib.reqContractDetailsAsync(contract)
        if not details:
            return "", ""
        return details[0].liquidHours or "", details[0].timeZoneId or ""

    def on_error(self, handler: Callable[[str, int, str], None]) -> None:
        self._handlers.append(handler)

    def _on_error(self, req_id: int, code: int, message: str, contract: Any = None, *_) -> None:
        symbol = getattr(contract, "symbol", "") if contract is not None else ""
        for handler in self._handlers:
            handler(symbol, code, message)
