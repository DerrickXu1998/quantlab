"""The collector loop against a fake IBKR, store and bus."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from quantlab_live import collector as collector_mod
from quantlab_live.collector import Collector
from quantlab_live.ib import Quote
from quantlab_live.plan import Lease

T0 = datetime(2026, 10, 15, 14, 0, 30, tzinfo=UTC)
HOURS = ("20261015:0930-20261015:1600", "US/Eastern")


class Clock:
    def __init__(self) -> None:
        self.now = T0.timestamp()

    def __call__(self) -> float:
        return self.now


class FakeGateway:
    def __init__(self) -> None:
        self.is_connected = True
        self.known = {"AAPL", "MSFT", "SPY", "BRK B"}
        self.open_lines: set[str] = set()
        self.quotes: dict[str, Quote] = {}
        self.history_calls: list[str] = []
        self.handlers = []
        self.fail_history = False

    def connected(self):
        return self.is_connected

    async def connect(self):
        self.is_connected = True

    async def qualify(self, name):
        return SimpleNamespace(symbol=name) if name in self.known else None

    def subscribe(self, contract):
        self.open_lines.add(contract.symbol)
        return contract.symbol

    def unsubscribe(self, contract):
        self.open_lines.discard(contract.symbol)

    def quote(self, ticker):
        return self.quotes.get(ticker, Quote(None, None, None, None, None))

    async def session_bars(self, contract):
        self.history_calls.append(contract.symbol)
        if self.fail_history:
            raise TimeoutError("pacing")
        start = datetime(2026, 10, 15, 13, 30, tzinfo=UTC)
        return [
            {
                "start": start + timedelta(minutes=i),
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
            }
            for i in range(3)
        ]

    async def liquid_hours(self, contract):
        return HOURS

    def on_error(self, handler):
        self.handlers.append(handler)


class FakeStore:
    def __init__(self, leases):
        self.leases_now = leases
        self.statuses = {}
        self.bars = []

    def leases(self, owner):
        self.asked_for = owner
        return list(self.leases_now)

    def write_statuses(self, rows):
        for sid, status, detail, ib in rows:
            self.statuses[sid] = (status, detail, ib)

    def insert_bars(self, rows):
        self.bars.extend(rows)


class FakeBus:
    def __init__(self):
        self.sent = []

    def send(self, key, value):
        self.sent.append((key, value))

    def flush(self):
        pass

    def events(self, kind):
        return [v for _, v in self.sent if v["event"] == kind]


def lease(sid, symbol, consumer="market", minutes=0):
    return Lease(sid, 100 + sid, symbol, consumer, T0 + timedelta(minutes=minutes))


def make(leases, max_lines=5):
    gateway, store, bus, clock = FakeGateway(), FakeStore(leases), FakeBus(), Clock()
    collector = Collector("u1", gateway, store, bus, max_lines, clock=clock)
    return collector, gateway, store, bus, clock


def run(coro):
    return asyncio.run(coro)


def test_leases_become_lines_and_statuses_are_written_back():
    c, gateway, store, bus, clock = make(
        [
            lease(1, "AAPL.US"),
            lease(2, "MSFT.US", minutes=1),
            lease(3, "HSBA.LON"),
            lease(4, "NOPE.US"),
            lease(5, "AAPL.US", minutes=2),
        ],
        max_lines=1,
    )
    run(c.step())

    assert gateway.open_lines == {"AAPL"}
    assert store.statuses[1][0] == "active" and store.statuses[5][0] == "active"
    assert store.statuses[2][0] == "over_budget"
    assert store.statuses[3][0] == "unknown_symbol"
    assert store.statuses[4][0] == "unknown_symbol"

    # Unknown symbols never hold a line, so the next pass gives MSFT nothing
    # new either -- and when AAPL's leases lapse, MSFT gets the line.
    store.leases_now = [lease(2, "MSFT.US", minutes=1)]
    clock.now += 2
    run(c.step())
    assert gateway.open_lines == {"MSFT"}
    assert store.statuses[2][0] == "active"


def test_quotes_publish_only_when_they_change_and_minutes_roll():
    c, gateway, store, bus, clock = make([lease(1, "AAPL.US")])
    run(c.step())
    gateway.quotes["AAPL"] = Quote(100.0, 99.9, 100.1, 1000, None)
    run(c.step())
    run(c.step())  # unchanged: nothing new
    assert len(bus.events("tick")) == 1
    assert bus.events("tick")[0]["symbol"] == "AAPL.US"

    # Minute 14:00 was the partial first one; 14:01 is rolled and stored.
    for second, price, volume in ((40, 101.0, 1100), (60, 102.0, 1200), (80, 99.0, 1300)):
        clock.now = T0.timestamp() + second
        gateway.quotes["AAPL"] = Quote(price, None, None, volume, None)
        run(c.step())
    clock.now = T0.timestamp() + 120
    run(c.step())

    bars = bus.events("bar")
    assert len(bars) == 1
    assert bars[0]["bar"]["ts"] == "2026-10-15T14:01:00.000Z"
    assert bars[0]["bar"]["high"] == 102.0 and bars[0]["bar"]["low"] == 99.0
    rolled = [row for row in store.bars if row[-1] == "rolled"]
    assert len(rolled) == 1 and rolled[0][:2] == ["u1", 101]  # owner, instrument id


def test_a_new_line_is_backfilled_once_and_announced():
    c, gateway, store, bus, clock = make([lease(1, "AAPL.US")])
    run(c.step())
    run(c.step())

    assert gateway.history_calls == ["AAPL"]
    backfilled = [row for row in store.bars if row[-1] == "backfill"]
    assert len(backfilled) == 3
    assert str(backfilled[0][3]) == "2026-10-15"  # the New York session date
    assert bus.events("backfilled") == [{"event": "backfilled", "symbol": "AAPL.US", "user": "u1"}]


def test_backfills_are_paced_and_retried(monkeypatch):
    monkeypatch.setattr(collector_mod, "BACKFILL_LIMIT", 1)
    c, gateway, store, bus, clock = make([lease(1, "AAPL.US"), lease(2, "MSFT.US")])
    gateway.fail_history = True
    run(c.step())  # one request: AAPL fails, requeued
    run(c.step())  # the window is full: nothing
    assert gateway.history_calls == ["AAPL"]
    gateway.fail_history = False
    clock.now += collector_mod.BACKFILL_WINDOW_SECONDS + 1
    run(c.step())
    assert gateway.history_calls == ["AAPL", "MSFT"]


def test_ibkr_refusing_data_frees_the_line_and_says_why():
    c, gateway, store, bus, clock = make([lease(1, "AAPL.US")])
    run(c.step())
    gateway.handlers[0]("AAPL", 354, "Requested market data is not subscribed")
    assert gateway.open_lines == set()
    clock.now += 2
    run(c.step())
    status, detail, _ = store.statuses[1]
    assert status == "error" and "354" in detail
    assert gateway.open_lines == set()  # not reopened


def test_heartbeat_reports_connection_and_ibkr_market_hours():
    c, gateway, store, bus, clock = make([])
    run(c.step())
    beat = bus.events("heartbeat")[-1]
    assert beat["connected"] is True and beat["market"] == "open"

    clock.now = datetime(2026, 10, 15, 21, 0, tzinfo=UTC).timestamp()
    run(c.step())
    assert bus.events("heartbeat")[-1]["market"] == "closed"


def test_the_loop_survives_an_unreachable_gateway_and_reopens_lines():
    c, gateway, store, bus, clock = make([lease(1, "AAPL.US")])
    run(c.step())
    assert gateway.open_lines == {"AAPL"}

    attempts = []

    async def flaky_connect():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("gateway restarting")
        gateway.is_connected = True

    gateway.connect = flaky_connect
    gateway.is_connected = False
    gateway.open_lines.clear()  # IBKR forgets lines on disconnect

    async def scenario():
        stop = asyncio.Event()

        async def stopper():
            while not gateway.open_lines:
                await asyncio.sleep(0.01)
            stop.set()

        await asyncio.wait_for(asyncio.gather(c.run(stop), stopper()), timeout=10)

    run(scenario())
    assert len(attempts) == 2
    assert gateway.open_lines == {"AAPL"}
    assert any(not v["connected"] for _, v in bus.sent if v["event"] == "heartbeat")


def test_everything_a_collector_writes_belongs_to_its_user():
    c, gateway, store, bus, clock = make([lease(1, "AAPL.US")])
    run(c.step())
    gateway.quotes["AAPL"] = Quote(100.0, None, None, 10, None)
    run(c.step())
    clock.now += 120
    gateway.quotes["AAPL"] = Quote(101.0, None, None, 20, None)
    run(c.step())

    assert store.asked_for == "u1"  # only this user's leases
    assert bus.sent and all(value["user"] == "u1" for _, value in bus.sent)
    assert store.bars and all(row[0] == "u1" for row in store.bars)
