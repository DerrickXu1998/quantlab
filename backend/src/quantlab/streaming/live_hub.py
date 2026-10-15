"""The live ticks hub: one tailing consumer per API process, fanned out.

The live-ingest collector publishes IBKR prices to ``quantlab.live.ticks``:
``tick`` (about once a second per symbol), ``bar`` (a closed minute),
``backfilled`` (the session from the open is stored) and its own
``heartbeat`` every couple of seconds. Every open Market tab wants a slice of
that log from *now* on -- never history -- so unlike the replay adapter
(``bus.KafkaBarStream``, which reads a finite log from its start, once per
request) this holds a single consumer at the end of the log and hands each
message to the subscribers that asked for its symbol. Fifty tabs is still one
Kafka connection.

Threads: the consumer blocks, so it runs on its own daemon thread. Each
subscriber lives on the event loop of the request that made it, and the
thread hands messages over with ``call_soon_threadsafe`` -- the subscriber's
state is only ever touched on its loop.

Back-pressure: a subscriber keeps the *latest* tick per symbol, not a queue
of every tick. A tab that falls behind skips stale prices instead of building
an ever-later backlog, and cannot slow the hub or anyone else down. Bars and
``backfilled`` are rare and all kept (up to a bound).

Failure: the consumer reconnects with backoff, forever -- a broker restart is
a pause, not an outage. The collector being down is not this module's error
either; it shows as a stale heartbeat, which ``collector_state`` reports.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Collection, Iterable
from typing import Any

from quantlab.streaming import bus

log = logging.getLogger(__name__)

TOPIC_ENV = "QUANTLAB_LIVE_TICKS_TOPIC"

#: A collector heartbeat older than this means the collector is down.
COLLECTOR_STALE_SECONDS = 10.0

#: Most pending non-tick events one subscriber holds before dropping the oldest.
MAX_PENDING = 4096

#: Events that belong to one symbol; the rest (heartbeat) are the hub's own.
SYMBOL_EVENTS = frozenset({"tick", "bar", "backfilled"})


def configured() -> bool:
    """True when both the brokers and the live topic are set."""
    return bus.configured() and bool(topic())


def topic() -> str:
    return os.environ.get(TOPIC_ENV, "").strip()


def message_key(message: dict) -> tuple:
    """What a newer message replaces in a subscriber's pending set.

    One tick per symbol (the latest wins); one bar per symbol and minute (a
    re-sent minute replaces the earlier copy); one ``backfilled`` per symbol.
    """
    event = message.get("event")
    symbol = message.get("symbol")
    if event == "bar":
        return ("bar", symbol, (message.get("bar") or {}).get("ts"))
    return (event, symbol)


class Subscription:
    """One stream's view of the hub. Owned by the loop that created it."""

    def __init__(self, symbols: Collection[str], loop: asyncio.AbstractEventLoop) -> None:
        self.symbols = frozenset(symbols)
        self._loop = loop
        self._pending: dict[tuple, dict] = {}
        self._ready = asyncio.Event()

    def offer(self, message: dict) -> None:
        """Called on the subscriber's loop. Latest-wins per key."""
        key = message_key(message)
        # Pop first so a replaced entry moves to the end: pending stays in
        # arrival order of the newest version of each key.
        self._pending.pop(key, None)
        self._pending[key] = message
        while len(self._pending) > MAX_PENDING:
            self._pending.pop(next(iter(self._pending)))
        self._ready.set()

    def offer_threadsafe(self, message: dict) -> None:
        try:
            self._loop.call_soon_threadsafe(self.offer, message)
        except RuntimeError:
            # The request's loop has closed; its stream is gone.
            pass

    async def next_batch(self, timeout: float) -> list[dict]:
        """Everything pending, in arrival order; [] if ``timeout`` passes first."""
        if not self._pending:
            try:
                await asyncio.wait_for(self._ready.wait(), timeout)
            except TimeoutError:
                return []
        batch = list(self._pending.values())
        self._pending.clear()
        self._ready.clear()
        return batch


class LiveHub:
    """Tails the live topic and fans its messages out to subscriptions."""

    def __init__(
        self,
        brokers: str,
        topic_name: str,
        *,
        consumer_factory: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._brokers = [b.strip() for b in brokers.split(",") if b.strip()]
        self._topic = topic_name
        self._consumer_factory = consumer_factory or self._kafka_consumer
        self._clock = clock
        self._subscriptions: set[Subscription] = set()
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._attempted = threading.Event()
        self._thread: threading.Thread | None = None
        self.bus_ok = False
        self.bus_error = ""
        self._heartbeat_at: float | None = None
        self._heartbeat: dict = {}

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="live-hub", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()

    def wait_attempted(self, timeout: float) -> bool:
        """Block until the first connection attempt has finished either way."""
        return self._attempted.wait(timeout)

    # --- subscribers ------------------------------------------------------

    def subscribe(self, symbols: Collection[str]) -> Subscription:
        subscription = Subscription(symbols, asyncio.get_running_loop())
        with self._lock:
            self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            self._subscriptions.discard(subscription)

    # --- state ------------------------------------------------------------

    def collector_state(self) -> tuple[str, str | None]:
        """(``up`` | ``down``, ``open`` | ``closed`` | None).

        Up means a collector heartbeat arrived within COLLECTOR_STALE_SECONDS
        and the collector says it is connected to IBKR: a collector that is
        running but logged out delivers no prices either.
        """
        at = self._heartbeat_at
        if at is None or self._clock() - at > COLLECTOR_STALE_SECONDS:
            return "down", None
        if not self._heartbeat.get("connected", False):
            return "down", None
        market = self._heartbeat.get("market")
        return "up", market if market in ("open", "closed") else None

    # --- dispatch ---------------------------------------------------------

    def dispatch(self, message: Any) -> None:
        """Route one topic message. Called on the consumer thread."""
        if not isinstance(message, dict):
            return
        event = message.get("event")
        if event == "heartbeat":
            self._heartbeat = message
            self._heartbeat_at = self._clock()
            return
        if event not in SYMBOL_EVENTS:
            return
        symbol = message.get("symbol")
        with self._lock:
            targets = [s for s in self._subscriptions if symbol in s.symbols]
        for subscription in targets:
            subscription.offer_threadsafe(message)

    def dispatch_all(self, messages: Iterable[Any]) -> None:
        for message in messages:
            self.dispatch(message)

    # --- consumer thread --------------------------------------------------

    def _run(self) -> None:
        backoff = 1.0
        while not self._stopping.is_set():
            consumer = None
            try:
                consumer = self._consumer_factory()
                self.bus_ok, self.bus_error = True, ""
                self._attempted.set()
                backoff = 1.0
                while not self._stopping.is_set():
                    polled = consumer.poll(timeout_ms=500)
                    for records in polled.values():
                        self.dispatch_all(record.value for record in records)
            except Exception as exc:  # reconnect on anything; never die
                self.bus_ok, self.bus_error = False, str(exc)
                self._attempted.set()
                log.warning("live hub: bus unavailable, retrying in %.0fs: %s", backoff, exc)
                self._stopping.wait(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                if consumer is not None:
                    try:
                        consumer.close(autocommit=False)
                    except Exception:
                        pass

    def _kafka_consumer(self):
        """A consumer assigned to every partition of the topic, at its end."""
        try:
            from kafka import KafkaConsumer, TopicPartition
        except ImportError as exc:  # pragma: no cover - kafka-python ships in the image
            raise bus.BusUnavailable("kafka-python is not installed in this backend") from exc
        consumer = KafkaConsumer(
            bootstrap_servers=self._brokers,
            bootstrap_timeout_ms=5000,
            enable_auto_commit=False,
            group_id=None,
            value_deserializer=_json_or_none,
        )
        try:
            partitions = consumer.partitions_for_topic(self._topic)
            if not partitions:
                raise bus.BusUnavailable(
                    f"topic {self._topic!r} does not exist yet; is live-ingest running?"
                )
            assigned = [TopicPartition(self._topic, p) for p in sorted(partitions)]
            consumer.assign(assigned)
            # Now, not history: a live view starts at the newest price.
            consumer.seek_to_end(*assigned)
        except Exception:
            consumer.close(autocommit=False)
            raise
        return consumer


def _json_or_none(raw: bytes | None):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        # One malformed message must not take the consumer down with it.
        return None
