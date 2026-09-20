"""Replay the stream: publish warehouse history to a Kafka topic.

The publisher reads deduplicated bars out of ClickHouse, sorts them into one
chronological event stream (date, then symbol) and produces JSON messages:

    {"type": "bar", "symbol", "date", "open", "high", "low", "close", "volume"}
    {"type": "end"}                        # terminal control message

keyed by symbol, so every symbol's partition is internally ordered. The
backend's live-replay consumer (backend ``quantlab.streaming``) runs a signal
rule against the arriving bars; because the rules are causal (Constitution
VII, enforced by the truncation sweep), consuming this stream produces the
same signals the batch engine computes over the whole window.

Determinism (Constitution VI): the event *content* is a pure function of the
stored bars -- same warehouse, same bytes on the topic. ``pace_ms`` is the one
wall-clock exception, and it is transport pacing only (how fast history
arrives), never an input to any computation.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from dataclasses import dataclass
from typing import Sequence

log = logging.getLogger(__name__)

DEFAULT_TOPIC = "quantlab.bars"


@dataclass(frozen=True)
class PublishReport:
    """Outcome of one replay publish."""

    topic: str
    symbols: list[str]
    start: str
    end: str
    bars_published: int
    dates: int

    def summary(self) -> str:
        return (
            f"published {self.bars_published:,} bars "
            f"({len(self.symbols)} symbols x {self.dates} dates) to {self.topic}"
        )


def publish_replay(
    conn,
    client,
    producer,
    symbols: Sequence[str],
    start: str | dt.date,
    end: str | dt.date,
    *,
    topic: str = DEFAULT_TOPIC,
    pace_ms: int = 0,
) -> PublishReport:
    """Publish the window's bars to ``topic`` in chronological order.

    ``conn`` is the Postgres catalog connection (symbols resolve to instrument
    ids there -- ClickHouse holds no symbols by design); ``client`` is the
    ClickHouse client. ``producer`` is anything with the kafka-python shape:
    ``send(topic, key=..., value=...)`` plus ``flush()``.
    """
    from . import store

    symbols = sorted({s.strip() for s in symbols if s.strip()})
    if not symbols:
        raise ValueError("publish_replay needs at least one symbol")

    ids = store.instrument_ids(conn, symbols)
    unknown = [s for s in symbols if s not in ids]
    if unknown:
        raise ValueError(f"unknown symbol(s) in the catalog: {', '.join(unknown)}")
    id_to_symbol = {int(i): s for s, i in ids.items()}

    frame = store.load_bars(client, list(id_to_symbol), start=start, end=end)

    records = []
    if frame is not None and not frame.empty:
        for row in frame.itertuples(index=False):
            records.append(
                (
                    row.ts.date().isoformat(),
                    id_to_symbol[int(row.instrument_id)],
                    {
                        "type": "bar",
                        "symbol": id_to_symbol[int(row.instrument_id)],
                        "date": row.ts.date().isoformat(),
                        "open": float(row.open),
                        "high": float(row.high),
                        "low": float(row.low),
                        "close": float(row.close),
                        "volume": int(row.volume),
                    },
                )
            )
    # The chronological contract: date first, then symbol, so a consumer sees
    # every symbol's bar for day T before anything from day T+1.
    records.sort(key=lambda r: (r[0], r[1]))

    last_date: str | None = None
    dates: set[str] = set()
    for date, symbol, payload in records:
        if pace_ms and last_date is not None and date != last_date:
            # Wall-clock pacing is transport, not computation: the payload
            # bytes are unaffected (Constitution VI).
            time.sleep(pace_ms / 1000)
        producer.send(topic, key=symbol, value=payload)
        last_date = date
        dates.add(date)
    producer.send(topic, key=None, value={"type": "end"})
    producer.flush()

    report = PublishReport(
        topic=topic,
        symbols=symbols,
        start=str(start),
        end=str(end),
        bars_published=len(records),
        dates=len(dates),
    )
    log.info("replay_published %s", report.summary())
    return report


def create_producer(brokers: str):
    """A kafka-python producer with the wire format baked in.

    Imported lazily: kafka-python is only needed by the publisher and the
    backend's live consumer, so the core research library does not require it.
    """
    from kafka import KafkaProducer

    return KafkaProducer(
        bootstrap_servers=[b.strip() for b in brokers.split(",") if b.strip()],
        key_serializer=lambda k: k.encode("utf-8") if k is not None else None,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )


def ensure_topic(brokers: str, topic: str) -> None:
    """Create ``topic`` with a single partition, unless it already exists.

    ``publish_replay`` sorts the whole window into one chronological stream
    across every symbol, and the backend consumer's per-date flush depends on
    that order holding. Kafka only orders within a partition, so the replay
    topic must have exactly one -- a broker that auto-creates with its own
    default (often 3) would interleave the log and silently shuffle the
    replay. Creating it here pins the layout at the one moment we know the
    topic is about to exist.

    Idempotent, and deliberately not corrective: an existing topic is left
    alone whatever its partition count, because repartitioning would discard
    published history. The consumer checks the count it actually got and
    refuses a topic it cannot trust.
    """
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import TopicAlreadyExistsError

    admin = KafkaAdminClient(
        bootstrap_servers=[b.strip() for b in brokers.split(",") if b.strip()]
    )
    try:
        admin.create_topics([NewTopic(name=topic, num_partitions=1, replication_factor=1)])
        log.info("replay_topic_created topic=%s partitions=1", topic)
    except TopicAlreadyExistsError:
        pass
    finally:
        admin.close()
