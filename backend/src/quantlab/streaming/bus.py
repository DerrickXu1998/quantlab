"""Kafka adapter for the live replay stream (Constitution III: isolated adapter).

Everything kafka-python-specific lives here. The import is lazy -- inside
``KafkaBarStream.open`` -- so the API starts and serves every other route
without the package installed or a broker running; the live endpoint maps a
missing package or an unreachable broker to ``BusUnavailable``, which the
route answers with a clean 503.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Sequence

BROKERS_ENV = "QUANTLAB_KAFKA_BROKERS"
TOPIC_ENV = "QUANTLAB_KAFKA_TOPIC"
DEFAULT_TOPIC = "quantlab.bars"


class BusUnavailable(RuntimeError):
    """The event bus is not configured or cannot be reached."""


def configured() -> bool:
    """True when a broker list is configured (reachability is separate)."""
    return bool(os.environ.get(BROKERS_ENV, "").strip())


def brokers() -> str:
    return os.environ.get(BROKERS_ENV, "")


def topic() -> str:
    return os.environ.get(TOPIC_ENV, "") or DEFAULT_TOPIC


class KafkaBarStream:
    """Consume one replay topic as normalized bar dicts.

    Reads from the beginning of the topic (a replay is history, not a live
    feed) with no consumer group -- each live replay is an independent,
    disposable read. Yields ``{"symbol", "date", "open", "high", "low",
    "close", "volume"}`` dicts for the selected symbols, in topic order (the
    publisher guarantees chronological order); stops at the ``{"type":
    "end"}`` control message or when the stream goes quiet for
    ``idle_timeout_ms``.
    """

    def __init__(
        self,
        brokers: str,
        topic: str,
        symbols: Sequence[str],
        start: str,
        end: str,
        *,
        idle_timeout_ms: int = 600_000,
        connect_timeout_ms: int = 5_000,
    ) -> None:
        self._brokers = [b.strip() for b in brokers.split(",") if b.strip()]
        self._topic = topic
        self._symbols = set(symbols)
        self._start = start
        self._end = end
        self._idle_timeout_ms = idle_timeout_ms
        self._connect_timeout_ms = connect_timeout_ms
        self._consumer = None

    def open(self) -> KafkaBarStream:
        """Connect now, so a dead broker fails the request, not the stream."""
        try:
            from kafka import KafkaConsumer
        except ImportError as exc:  # pragma: no cover - kafka-python ships in the image
            raise BusUnavailable("kafka-python is not installed in this backend") from exc
        if not self._brokers:
            raise BusUnavailable(f"no Kafka brokers configured; set {BROKERS_ENV}")
        try:
            self._consumer = KafkaConsumer(
                self._topic,
                bootstrap_servers=self._brokers,
                # Fail fast when the broker is absent: without this the
                # bootstrap probe blocks for much longer before raising.
                bootstrap_timeout_ms=self._connect_timeout_ms,
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                group_id=None,
                consumer_timeout_ms=self._idle_timeout_ms,
                key_deserializer=lambda b: b.decode("utf-8") if b is not None else None,
                value_deserializer=json.loads,
            )
        except Exception as exc:
            raise BusUnavailable(
                f"Kafka broker(s) {','.join(self._brokers)} unreachable: {exc}"
            ) from exc
        return self

    def __iter__(self) -> Iterator[dict]:
        if self._consumer is None:
            raise BusUnavailable("KafkaBarStream.open() was not called")
        try:
            for message in self._consumer:
                payload = message.value
                if not isinstance(payload, dict):
                    continue
                if payload.get("type") == "end":
                    return
                if payload.get("type") != "bar":
                    continue
                if payload.get("symbol") not in self._symbols:
                    continue
                yield payload
        finally:
            self.close()

    def close(self) -> None:
        if self._consumer is not None:
            try:
                self._consumer.close(autocommit=False)
            finally:
                self._consumer = None
