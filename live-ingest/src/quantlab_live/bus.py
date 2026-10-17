"""The live topic: one partition, a day of retention, keyed by symbol."""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

RETENTION_MS = 24 * 60 * 60 * 1000


class Bus:
    def __init__(self, brokers: str, topic: str) -> None:
        from kafka import KafkaProducer

        self.topic = topic
        self._brokers = [b.strip() for b in brokers.split(",") if b.strip()]
        self.ensure_topic()
        self._producer = KafkaProducer(
            bootstrap_servers=self._brokers,
            key_serializer=lambda k: k.encode() if k else None,
            value_serializer=lambda v: json.dumps(v).encode(),
            linger_ms=50,
        )

    def ensure_topic(self) -> None:
        """Create the topic if missing. One partition: the API's hub reads
        every symbol from one log, and a day is all a live view ever needs."""
        from kafka.admin import KafkaAdminClient, NewTopic
        from kafka.errors import TopicAlreadyExistsError

        admin = KafkaAdminClient(bootstrap_servers=self._brokers)
        try:
            admin.create_topics(
                [
                    NewTopic(
                        self.topic,
                        num_partitions=1,
                        replication_factor=1,
                        topic_configs={"retention.ms": str(RETENTION_MS)},
                    )
                ]
            )
            log.info("created topic %s", self.topic)
        except TopicAlreadyExistsError:
            pass
        finally:
            admin.close()

    def send(self, key: str | None, value: dict) -> None:
        self._producer.send(self.topic, key=key, value=value)

    def flush(self) -> None:
        self._producer.flush(timeout=5)
