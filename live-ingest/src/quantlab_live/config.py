"""Settings, from the environment the compose file sets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

#: ib-gateway-docker, pinned by digest. 4004 inside it relays to the paper
#: API (4002) and 4003 to the live one (4001).
DEFAULT_IMAGE = (
    "ghcr.io/gnzsnz/ib-gateway:10.37"
    "@sha256:b248e4dad68cc1de8dd1905ea8598089e92307dfec57f59e08a28182bbb002d5"
)
API_PORT = {"paper": 4004, "live": 4003}


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
    #: Shared secret the backend presents; the manager refuses calls without it.
    token: str
    port: int
    #: The compose network the per-user gateways join (so collectors reach them).
    network: str
    image: str
    max_gateways: int
    max_lines: int
    ib_client_id: int

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            pg_dsn=env["QUANTLAB_DB_URL"],
            ch=ch_settings(env["QUANTLAB_CH_URL"], env.get("QUANTLAB_CH_PASSWORD", "")),
            brokers=env.get("QUANTLAB_KAFKA_BROKERS", "redpanda:9092"),
            topic=env.get("QUANTLAB_LIVE_TICKS_TOPIC", "quantlab.live.ticks"),
            token=env["QUANTLAB_LIVE_MANAGER_TOKEN"],
            port=int(env.get("QUANTLAB_LIVE_MANAGER_PORT", "8790")),
            network=env["QUANTLAB_LIVE_NETWORK"],
            image=env.get("QUANTLAB_IBGW_IMAGE", DEFAULT_IMAGE),
            # Each gateway is a ~1 GB JVM; two fit beside the stack on the VM.
            max_gateways=int(env.get("QUANTLAB_LIVE_MAX_GATEWAYS", "2")),
            # Per account: IBKR's default is 100 lines; leave headroom.
            max_lines=int(env.get("QUANTLAB_LIVE_MAX_LINES", "90")),
            ib_client_id=int(env.get("IBKR_CLIENT_ID", "17")),
        )
