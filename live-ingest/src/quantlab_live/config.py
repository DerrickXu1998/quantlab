"""Settings, from the environment the compose file sets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse


def ch_settings(url: str, password: str = "") -> dict:
    """clickhouse[s]://user:pass@host:port/db -> clickhouse_connect kwargs."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    secure = parsed.scheme in ("clickhouses", "https") or query.get("secure", [""])[0].lower() in (
        "1",
        "true",
        "yes",
    )
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or (8443 if secure else 8123),
        "username": unquote(parsed.username or "default"),
        "password": password or unquote(parsed.password or ""),
        "database": (parsed.path or "/").lstrip("/") or "default",
        "secure": secure,
    }


@dataclass(frozen=True)
class Settings:
    pg_dsn: str
    ch: dict
    brokers: str
    topic: str
    ib_host: str
    ib_port: int
    ib_client_id: int
    max_lines: int

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            pg_dsn=env["QUANTLAB_DB_URL"],
            ch=ch_settings(env["QUANTLAB_CH_URL"], env.get("QUANTLAB_CH_PASSWORD", "")),
            brokers=env.get("QUANTLAB_KAFKA_BROKERS", "redpanda:9092"),
            topic=env.get("QUANTLAB_LIVE_TICKS_TOPIC", "quantlab.live.ticks"),
            ib_host=env.get("IBKR_HOST", "ib-gateway"),
            # 4004: ib-gateway-docker's relay to the paper API (4002 inside).
            ib_port=int(env.get("IBKR_PORT", "4004")),
            ib_client_id=int(env.get("IBKR_CLIENT_ID", "17")),
            # Under IBKR's default 100, leaving room for TWS on a laptop.
            max_lines=int(env.get("QUANTLAB_LIVE_MAX_LINES", "90")),
        )
