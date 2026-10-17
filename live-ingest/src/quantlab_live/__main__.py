"""``quantlab-live-ingest``: run the collector until stopped."""

from __future__ import annotations

import asyncio
import logging
import signal
import time

from quantlab_live.bus import Bus
from quantlab_live.collector import Collector
from quantlab_live.config import Settings
from quantlab_live.ib import IbGateway
from quantlab_live.store import Store

log = logging.getLogger("quantlab_live")


def _bus(settings: Settings) -> Bus:
    """The broker may start after us; wait for it rather than exit."""
    backoff = 1.0
    while True:
        try:
            return Bus(settings.brokers, settings.topic)
        except Exception as exc:
            log.warning("broker unreachable, retrying in %.0fs: %s", backoff, exc)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def _run(settings: Settings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    collector = Collector(
        IbGateway(settings.ib_host, settings.ib_port, settings.ib_client_id),
        Store(settings.pg_dsn, settings.ch),
        await asyncio.to_thread(_bus, settings),
        settings.max_lines,
    )
    log.info(
        "live-ingest: IB Gateway %s:%s, topic %s, %d lines",
        settings.ib_host,
        settings.ib_port,
        settings.topic,
        settings.max_lines,
    )
    await collector.run(stop)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # kafka-python narrates every connection at INFO; its warnings are enough.
    logging.getLogger("kafka").setLevel(logging.WARNING)
    asyncio.run(_run(Settings.from_env()))


if __name__ == "__main__":
    main()
