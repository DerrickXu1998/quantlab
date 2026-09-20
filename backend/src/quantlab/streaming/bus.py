"""Kafka adapter for the live replay stream (Constitution III: isolated adapter).

Everything kafka-python-specific lives here. The import is lazy -- inside
``KafkaBarStream.open`` -- so the API starts and serves every other route
without the package installed or a broker running; the live endpoint maps a
missing package or an unreachable broker to ``BusUnavailable``, which the
route answers with a clean 503.

``select_bars`` is the pure half: the message filtering and the stop rule,
over any iterable of consumer records, so both are testable without a broker.
"""

from __future__ import annotations

import json
import os
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from typing import Any

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


def select_bars(
    records: Iterable[Any],
    symbols: Collection[str],
    end_offsets: Mapping[tuple[str, int], int],
) -> Iterator[dict]:
    """Yield the selected symbols' bar payloads, stopping at the log's end.

    ``end_offsets`` maps ``(topic, partition)`` to the offset one past the
    last message present when the stream opened.

    ``{"type": "end"}`` means "the publisher finished", not "stop reading".
    A topic published to more than once holds one marker per publish, so
    returning at the first would hide every later publish -- including the
    window the caller actually asked for -- and do it silently, with a
    well-formed stream and a summary computed over the wrong bars. The read
    therefore ends only where two conditions meet: the snapshot end of the
    log, on a message that is itself a terminal marker. A log whose last
    message is a bar is a publish still in flight, so the consumer keeps
    following it until its marker arrives (or the idle timeout fires).

    Overlapping publishes are not deduplicated here: ``live.live_replay_events``
    already drops a ``(symbol, date)`` it has seen, which is exactly the case
    a re-published range produces.
    """
    last_was_end = False
    for record in records:
        payload = record.value
        if isinstance(payload, dict):
            kind = payload.get("type")
            if kind == "end":
                last_was_end = True
            elif kind == "bar":
                last_was_end = False
                if payload.get("symbol") in symbols:
                    yield payload
        # end_offsets is one past the last message, so the final message
        # present at open() is the one whose offset + 1 reaches it. An unknown
        # partition reads as 0, which degrades to "stop at the first marker" --
        # the old behaviour, and the safe direction to fail in.
        at_log_end = record.offset + 1 >= end_offsets.get((record.topic, record.partition), 0)
        if at_log_end and last_was_end:
            return


class KafkaBarStream:
    """Consume one replay topic as normalized bar dicts.

    Reads the whole log from the beginning (a replay is history, not a live
    feed) with no consumer group -- each live replay is an independent,
    disposable read, so the partitions are assigned explicitly rather than
    subscribed, and rewound with an explicit seek. Yields ``{"symbol", "date",
    "open", "high", "low", "close", "volume"}`` dicts for the selected symbols,
    in topic order (the publisher guarantees chronological order); stops per
    ``select_bars``, or when the stream goes quiet for ``idle_timeout_ms``.

    The topic must have exactly one partition. ``publish_replay`` sorts the
    whole window into one chronological stream across every symbol, and the
    consumer's per-date flush depends on that order; Kafka only orders within
    a partition, so more than one would interleave the log. ``open`` refuses a
    topic it cannot trust rather than silently replaying a shuffled history.
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
        self._end_offsets: dict[tuple[str, int], int] = {}

    def open(self) -> KafkaBarStream:
        """Connect now, so a dead broker fails the request, not the stream."""
        try:
            from kafka import KafkaConsumer, TopicPartition
        except ImportError as exc:  # pragma: no cover - kafka-python ships in the image
            raise BusUnavailable("kafka-python is not installed in this backend") from exc
        if not self._brokers:
            raise BusUnavailable(f"no Kafka brokers configured; set {BROKERS_ENV}")
        try:
            consumer = KafkaConsumer(
                # No topic here: assign() below takes the partitions directly,
                # which skips group coordination and makes the rewind explicit.
                bootstrap_servers=self._brokers,
                # Fail fast when the broker is absent: without this the
                # bootstrap probe blocks for much longer before raising.
                bootstrap_timeout_ms=self._connect_timeout_ms,
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
        try:
            partitions = consumer.partitions_for_topic(self._topic)
            if not partitions:
                raise BusUnavailable(
                    f"topic {self._topic!r} does not exist on "
                    f"{','.join(self._brokers)}; publish a replay first"
                )
            if len(partitions) > 1:
                raise BusUnavailable(
                    f"topic {self._topic!r} has {len(partitions)} partitions; a live "
                    "replay needs one chronological log across every symbol, which "
                    "only a single-partition topic guarantees"
                )
            assigned = [TopicPartition(self._topic, p) for p in sorted(partitions)]
            consumer.assign(assigned)
            # Snapshot the log's end before reading, so the read is bounded by
            # where the log was when this replay started.
            self._end_offsets = {
                (tp.topic, tp.partition): offset
                for tp, offset in consumer.end_offsets(assigned).items()
            }
            consumer.seek_to_beginning(*assigned)
        except BusUnavailable:
            consumer.close(autocommit=False)
            raise
        except Exception as exc:
            consumer.close(autocommit=False)
            raise BusUnavailable(f"could not read topic {self._topic!r}: {exc}") from exc
        self._consumer = consumer
        return self

    def __iter__(self) -> Iterator[dict]:
        if self._consumer is None:
            raise BusUnavailable("KafkaBarStream.open() was not called")
        try:
            yield from select_bars(self._consumer, self._symbols, self._end_offsets)
        finally:
            self.close()

    def close(self) -> None:
        if self._consumer is not None:
            try:
                self._consumer.close(autocommit=False)
            finally:
                self._consumer = None
