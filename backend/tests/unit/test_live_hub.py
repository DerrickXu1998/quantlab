"""The live ticks hub: routing, latest-wins buffering, collector state, reconnect.

No broker: the hub's consumer is a factory, and these hand it fakes. Async
parts run under asyncio.run -- the suite has no async test plugin.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from quantlab.streaming import live_hub
from quantlab.streaming.live_hub import LiveHub, Subscription, message_key


def tick(symbol: str, last: float, ts: str = "2026-10-15T14:00:00.000Z", user="u1") -> dict:
    return {"event": "tick", "user": user, "symbol": symbol, "ts": ts, "last": last}


def bar(symbol: str, ts: str, user="u1") -> dict:
    return {"event": "bar", "user": user, "symbol": symbol, "bar": {"ts": ts, "close": 1.0}}


def heartbeat(user="u1", **fields) -> dict:
    return {"event": "heartbeat", "user": user, **fields}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_newer_tick_replaces_the_older_but_bars_are_kept_per_minute():
    assert message_key(tick("A", 1)) == message_key(tick("A", 2))
    assert message_key(tick("A", 1)) != message_key(tick("B", 1))
    assert message_key(bar("A", "t1")) != message_key(bar("A", "t2"))
    assert message_key(bar("A", "t1")) == message_key(bar("A", "t1"))


def test_a_slow_subscriber_gets_the_latest_price_not_a_backlog():
    async def scenario():
        sub = Subscription("u1", {"A", "B"}, asyncio.get_running_loop())
        sub.offer(tick("A", 1))
        sub.offer(bar("A", "t1"))
        sub.offer(tick("B", 5))
        sub.offer(tick("A", 2))
        return await sub.next_batch(timeout=0.1)

    batch = asyncio.run(scenario())
    # A's first tick is gone; its replacement moved behind the bar and B.
    assert [(m["event"], m["symbol"], m.get("last")) for m in batch] == [
        ("bar", "A", None),
        ("tick", "B", 5),
        ("tick", "A", 2),
    ]


def test_pending_is_bounded(monkeypatch):
    monkeypatch.setattr(live_hub, "MAX_PENDING", 3)

    async def scenario():
        sub = Subscription("u1", {"A"}, asyncio.get_running_loop())
        for minute in range(5):
            sub.offer(bar("A", f"t{minute}"))
        return await sub.next_batch(timeout=0.1)

    assert [m["bar"]["ts"] for m in asyncio.run(scenario())] == ["t2", "t3", "t4"]


def test_an_idle_subscriber_times_out_empty():
    async def scenario():
        return await Subscription("u1", {"A"}, asyncio.get_running_loop()).next_batch(timeout=0.01)

    assert asyncio.run(scenario()) == []


def test_messages_reach_only_the_subscribers_that_asked_for_the_symbol():
    hub = LiveHub("broker:9092", "t", consumer_factory=lambda: None)

    async def scenario():
        watching_a = hub.subscribe("u1", {"A"})
        watching_b = hub.subscribe("u1", {"B"})
        hub.dispatch_all([tick("A", 1), tick("C", 9), {"event": "nonsense"}, "not a dict", None])
        await asyncio.sleep(0)  # let call_soon_threadsafe deliver
        got_a = await watching_a.next_batch(timeout=0.05)
        got_b = await watching_b.next_batch(timeout=0.05)
        hub.unsubscribe(watching_a)
        hub.dispatch(tick("A", 2))
        await asyncio.sleep(0)
        after = await watching_a.next_batch(timeout=0.01)
        return got_a, got_b, after

    got_a, got_b, after = asyncio.run(scenario())
    assert [m["last"] for m in got_a] == [1]
    assert got_b == []
    assert after == []


def test_the_collector_is_down_until_a_fresh_connected_heartbeat():
    clock = Clock()
    hub = LiveHub("broker:9092", "t", consumer_factory=lambda: None, clock=clock)
    assert hub.collector_state("u1") == ("down", None)

    hub.dispatch(heartbeat(connected=True, market="open"))
    assert hub.collector_state("u1") == ("up", "open")
    # Another user's collector is their own, and has said nothing.
    assert hub.collector_state("u2") == ("down", None)

    # Running but logged out of IBKR delivers nothing either.
    hub.dispatch(heartbeat(connected=False, market="open"))
    assert hub.collector_state("u1") == ("down", None)

    hub.dispatch(heartbeat(connected=True, market="lunch"))
    assert hub.collector_state("u1") == ("up", None)

    clock.now += live_hub.COLLECTOR_STALE_SECONDS + 0.1
    assert hub.collector_state("u1") == ("down", None)


class FakeConsumer:
    def __init__(self, batches: list[list[dict]], done: threading.Event) -> None:
        self._batches = batches
        self._done = done
        self.closed = False

    def poll(self, timeout_ms: int):
        if not self._batches:
            self._done.set()
            return {}
        records = [SimpleNamespace(value=v) for v in self._batches.pop(0)]
        return {("t", 0): records}

    def close(self, autocommit: bool = False) -> None:
        self.closed = True


def test_the_consumer_reconnects_after_a_failure_and_dispatches():
    done = threading.Event()
    consumer = FakeConsumer([[heartbeat(connected=True, market="closed")]], done)
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("broker down")
        return consumer

    hub = LiveHub("broker:9092", "t", consumer_factory=factory)
    hub.start()
    assert hub.wait_attempted(2.0)
    assert done.wait(5.0), "the hub never reconnected"
    hub.stop()

    assert len(attempts) == 2
    assert hub.bus_ok is True
    assert hub.collector_state("u1") == ("up", "closed")


def test_configured_needs_both_brokers_and_topic(monkeypatch):
    monkeypatch.setenv("QUANTLAB_KAFKA_BROKERS", "broker:9092")
    monkeypatch.delenv(live_hub.TOPIC_ENV, raising=False)
    assert not live_hub.configured()
    monkeypatch.setenv(live_hub.TOPIC_ENV, "quantlab.live.ticks")
    assert live_hub.configured()
    monkeypatch.delenv("QUANTLAB_KAFKA_BROKERS")
    assert not live_hub.configured()


def test_a_user_never_receives_another_users_prices():
    hub = LiveHub("broker:9092", "t", consumer_factory=lambda: None)

    async def scenario():
        mine = hub.subscribe("u1", {"AAPL.US"})
        theirs = hub.subscribe("u2", {"AAPL.US"})
        hub.dispatch_all(
            [
                tick("AAPL.US", 1, user="u1"),
                tick("AAPL.US", 2, user="u2"),
                # No owner: nobody's licence covers it, so nobody gets it.
                {"event": "tick", "symbol": "AAPL.US", "last": 3},
            ]
        )
        await asyncio.sleep(0)
        return (
            await mine.next_batch(timeout=0.05),
            await theirs.next_batch(timeout=0.05),
        )

    mine, theirs = asyncio.run(scenario())
    assert [m["last"] for m in mine] == [1]
    assert [m["last"] for m in theirs] == [2]
