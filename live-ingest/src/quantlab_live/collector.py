"""The collector loop: leases -> IBKR lines -> ticks, minutes, heartbeats.

Once a second it publishes every quote that changed (so a symbol ticks at
most once a second), rolls minutes, and sends a heartbeat every other
second. Every two seconds it re-reads the leases, plans which symbols get the
account's lines (plan.py), opens and closes lines to match, and writes back
each lease's status. A newly opened line is backfilled from the session's
open, paced to stay inside IBKR's historical-data limits.

Nothing here fails for good. IBKR down, a broker blip, a database hiccup:
each is logged, waited out with backoff, and retried -- the collector gets
slower, never dead, and the heartbeat says which it is.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from quantlab_live.contracts import ib_symbol
from quantlab_live.hours import market_state
from quantlab_live.ib import NO_DATA_CODES, Gateway
from quantlab_live.minutes import MinuteRoller
from quantlab_live.plan import Lease, diff, plan_lines
from quantlab_live.store import bar_row

log = logging.getLogger(__name__)

RECONCILE_SECONDS = 2.0
HEARTBEAT_SECONDS = 2.0
#: IBKR allows 60 historical requests per 10 minutes; stay well inside it.
BACKFILL_LIMIT = 50
BACKFILL_WINDOW_SECONDS = 600.0
BACKFILL_RETRIES = 3
#: Trading hours are re-read this often (and on every reconnect).
HOURS_SECONDS = 30 * 60
#: A contract whose trading hours stand for the whole US equity market.
REFERENCE = "SPY"


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Collector:
    def __init__(
        self,
        owner: str,
        gateway: Gateway,
        store: Any,
        bus: Any,
        max_lines: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        #: The quantlab user whose IBKR login this collector streams. Every
        #: message and row it writes is theirs alone.
        self.owner = owner
        self.gateway = gateway
        self.store = store
        self.bus = bus
        self.max_lines = max_lines
        self.clock = clock

        self.contracts: dict[str, Any] = {}  # canonical -> qualified contract
        self.ib_names: dict[str, str] = {}  # IBKR symbol -> canonical
        self.tickers: dict[str, Any] = {}  # open lines
        self.rollers: dict[str, MinuteRoller] = {}
        self.sent: dict[str, tuple] = {}
        self.unknown: dict[str, str] = {}  # no contract: never given a line
        self.refused: dict[str, str] = {}  # IBKR refused data: line closed
        self.instrument_ids: dict[str, int] = {}
        self.backfills: deque[tuple[str, int]] = deque()
        self.backfill_times: deque[float] = deque()
        self.pending_bars: list[tuple[str, dict]] = []
        self.market: str | None = None
        #: When this user last held any lease (clock seconds); for idle shutdown.
        self.last_lease_at = clock()

        self._last_reconcile = -1e9
        self._last_heartbeat = -1e9
        self._last_hours = -1e9
        self._hours: tuple[str, str] = ("", "")
        gateway.on_error(self._on_ib_error)

    # --- the loop ---------------------------------------------------------

    async def run(self, stop: asyncio.Event) -> None:
        backoff = 1.0
        while not stop.is_set():
            if not self.gateway.connected():
                try:
                    await self.gateway.connect()
                    log.info("connected to IB Gateway")
                    backoff = 1.0
                    self.reset_lines()
                except Exception as exc:
                    log.warning("IB Gateway unreachable, retrying in %.0fs: %s", backoff, exc)
                    self.heartbeat(force=True)
                    await self._sleep(stop, backoff)
                    backoff = min(backoff * 2, 60.0)
                    continue
            try:
                await self.step()
            except Exception:
                log.exception("collector step failed; carrying on")
            await self._sleep(stop, 1.0)

    async def step(self) -> None:
        now = self.clock()
        if now - self._last_reconcile >= RECONCILE_SECONDS:
            self._last_reconcile = now
            await self.reconcile()
        if now - self._last_hours >= HOURS_SECONDS:
            self._last_hours = now
            await self.refresh_hours()
        self.publish_quotes(now)
        await self.flush_minutes(now)
        await self.backfill_one(now)
        self.heartbeat()
        self.bus.flush()

    # --- lines --------------------------------------------------------------

    def reset_lines(self) -> None:
        """After a (re)connect IBKR holds no lines: reopen everything."""
        self.tickers.clear()
        self.rollers.clear()
        self.sent.clear()
        self.refused.clear()
        self.backfills.clear()
        self._last_reconcile = -1e9
        self._last_hours = -1e9

    async def reconcile(self) -> None:
        try:
            leases: list[Lease] = await asyncio.to_thread(self.store.leases, self.owner)
        except Exception:
            log.exception("reading leases failed; keeping the current lines")
            return
        if leases:
            self.last_lease_at = self.clock()
        for lease in leases:
            self.instrument_ids[lease.symbol] = lease.instrument_id
            # Resolve before planning (cached after the first time), so a
            # symbol IBKR does not know is reported as such and never takes a
            # line from one it does.
            if lease.symbol not in self.contracts and lease.symbol not in self.unknown:
                await self._contract(lease.symbol)
        eligible = [
            lease
            for lease in leases
            if lease.symbol not in self.unknown and lease.symbol not in self.refused
        ]
        plan = plan_lines(eligible, self.max_lines, streaming=self.tickers)
        to_open, to_close = diff(self.tickers, plan.lines)

        for symbol in to_close:
            self.gateway.unsubscribe(self.contracts[symbol])
            self.tickers.pop(symbol, None)
            self.rollers.pop(symbol, None)
            self.sent.pop(symbol, None)
        for symbol in to_open:
            contract = await self._contract(symbol)
            if contract is None:
                continue
            self.tickers[symbol] = self.gateway.subscribe(contract)
            self.rollers[symbol] = MinuteRoller()
            self.backfills.append((symbol, 0))

        rows = []
        for lease in leases:
            status, detail = self._status(lease.symbol, plan.over_budget)
            rows.append((lease.subscription_id, status, detail, ib_symbol(lease.symbol)))
        try:
            await asyncio.to_thread(self.store.write_statuses, rows)
        except Exception:
            log.exception("writing line statuses failed")

    def _status(self, symbol: str, over_budget: set[str]) -> tuple[str, str]:
        if symbol in self.unknown:
            return "unknown_symbol", self.unknown[symbol]
        if symbol in self.refused:
            return "error", self.refused[symbol]
        if symbol in self.tickers:
            return "active", ""
        if symbol in over_budget:
            return "over_budget", f"all {self.max_lines} lines are in use"
        return "pending", ""

    async def _contract(self, symbol: str) -> Any | None:
        if symbol in self.contracts:
            return self.contracts[symbol]
        name = ib_symbol(symbol)
        if name is None:
            self.unknown[symbol] = "no IBKR mapping: only US listings (.US) are streamed"
            return None
        contract = await self.gateway.qualify(name)
        if contract is None:
            self.unknown[symbol] = f"IBKR has no US stock contract for {name!r}"
            return None
        self.contracts[symbol] = contract
        self.ib_names[name] = symbol
        return contract

    def _on_ib_error(self, ib_name: str, code: int, message: str) -> None:
        symbol = self.ib_names.get(ib_name)
        if symbol is None or code not in NO_DATA_CODES:
            return
        log.warning("IBKR refused data for %s (%s): %s", symbol, code, message)
        self.refused[symbol] = f"{NO_DATA_CODES[code]} (IBKR {code})"
        # Free the line now; the next reconcile writes the status back.
        if symbol in self.tickers:
            self.gateway.unsubscribe(self.contracts[symbol])
            self.tickers.pop(symbol, None)
            self.rollers.pop(symbol, None)

    # --- prices -------------------------------------------------------------

    def publish_quotes(self, now: float) -> None:
        """Every changed quote, at most once a second per symbol."""
        for symbol, ticker in self.tickers.items():
            quote = self.gateway.quote(ticker)
            key = (quote.last, quote.bid, quote.ask, quote.volume)
            if quote.last is None or key == self.sent.get(symbol):
                continue
            self.sent[symbol] = key
            ts = quote.time.timestamp() if quote.time else now
            self._send(
                symbol,
                {
                    "event": "tick",
                    "symbol": symbol,
                    "ts": iso(ts),
                    "last": quote.last,
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "volume": int(quote.volume) if quote.volume is not None else None,
                },
            )
            closed = self.rollers[symbol].add(quote.last, quote.volume, ts)
            if closed:
                self.pending_bars.append((symbol, closed))

    async def flush_minutes(self, now: float) -> None:
        for symbol, roller in self.rollers.items():
            closed = roller.flush(now)
            if closed:
                self.pending_bars.append((symbol, closed))
        if not self.pending_bars:
            return
        bars, self.pending_bars = self.pending_bars, []
        rows = []
        for symbol, bar in bars:
            start = datetime.fromtimestamp(bar["start"], UTC)
            if symbol in self.instrument_ids:
                rows.append(bar_row(self.owner, self.instrument_ids[symbol], start, bar, "rolled"))
            self._send(
                symbol,
                {
                    "event": "bar",
                    "symbol": symbol,
                    "bar": {
                        "ts": iso(bar["start"]),
                        "open": bar["open"],
                        "high": bar["high"],
                        "low": bar["low"],
                        "close": bar["close"],
                        "volume": bar["volume"],
                        "kind": "rolled",
                    },
                },
            )
        try:
            await asyncio.to_thread(self.store.insert_bars, rows)
        except Exception:
            # The bars still reached open charts over the bus; only the
            # stored copy of these minutes is lost.
            log.exception("storing %d rolled minutes failed", len(rows))

    async def backfill_one(self, now: float) -> None:
        """One paced backfill: the session from the open, IBKR's own bars."""
        while self.backfill_times and now - self.backfill_times[0] > BACKFILL_WINDOW_SECONDS:
            self.backfill_times.popleft()
        if not self.backfills or len(self.backfill_times) >= BACKFILL_LIMIT:
            return
        symbol, attempts = self.backfills.popleft()
        if symbol not in self.tickers:
            return  # its line closed while it waited
        self.backfill_times.append(now)
        try:
            bars = await self.gateway.session_bars(self.contracts[symbol])
            instrument_id = self.instrument_ids[symbol]
            rows = [
                bar_row(self.owner, instrument_id, bar["start"], bar, "backfill") for bar in bars
            ]
            await asyncio.to_thread(self.store.insert_bars, rows)
        except Exception:
            log.exception("backfilling %s failed (attempt %d)", symbol, attempts + 1)
            if attempts + 1 < BACKFILL_RETRIES:
                self.backfills.append((symbol, attempts + 1))
            return
        self._send(symbol, {"event": "backfilled", "symbol": symbol})

    # --- state ----------------------------------------------------------------

    async def refresh_hours(self) -> None:
        try:
            reference = await self.gateway.qualify(REFERENCE)
            if reference is not None:
                self._hours = await self.gateway.liquid_hours(reference)
        except Exception:
            log.exception("reading trading hours failed")

    def heartbeat(self, force: bool = False) -> None:
        now = self.clock()
        if not force and now - self._last_heartbeat < HEARTBEAT_SECONDS:
            return
        self._last_heartbeat = now
        connected = self.gateway.connected()
        hours, zone = self._hours
        self.market = market_state(hours, zone, datetime.fromtimestamp(now, UTC)) if hours else None
        try:
            self._send(
                None,
                {
                    "event": "heartbeat",
                    "ts": iso(now),
                    "connected": connected,
                    "market": self.market,
                },
            )
            if force:
                self.bus.flush()
        except Exception:
            log.exception("heartbeat failed")

    def _send(self, key: str | None, value: dict) -> None:
        """Publish, stamped with the owner: the API forwards a frame only to
        the user it belongs to."""
        self.bus.send(key, {**value, "user": self.owner})

    @staticmethod
    async def _sleep(stop: asyncio.Event, seconds: float) -> None:
        try:
            await asyncio.wait_for(stop.wait(), seconds)
        except TimeoutError:
            pass
