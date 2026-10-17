"""``quantlab-live-ingest``: the gateway manager and its per-user collectors."""

from __future__ import annotations

import asyncio
import logging
import signal
import time

from aiohttp import web

from quantlab_live.bus import Bus
from quantlab_live.collector import Collector
from quantlab_live.config import API_PORT, Settings
from quantlab_live.docker_api import DockerGateways
from quantlab_live.ib import IbGateway
from quantlab_live.manager import Manager
from quantlab_live.server import make_app
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

    bus = await asyncio.to_thread(_bus, settings)
    store = Store(settings.pg_dsn, settings.ch)
    gateways = DockerGateways(settings.image, settings.network)

    def make_collector(owner: str, host: str) -> Collector:
        session = manager.sessions.get(owner)
        mode = session.trading_mode if session else "paper"
        ib = IbGateway(host, API_PORT.get(mode, API_PORT["paper"]), settings.ib_client_id)
        return Collector(owner, ib, store, bus, settings.max_lines)

    manager = Manager(gateways, make_collector, max_gateways=settings.max_gateways)

    runner = web.AppRunner(make_app(manager, settings.token))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.port).start()
    log.info(
        "live gateway manager on :%d, up to %d gateways, topic %s",
        settings.port,
        settings.max_gateways,
        settings.topic,
    )
    try:
        await manager.run(stop)
    finally:
        await runner.cleanup()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # kafka-python narrates every connection at INFO; its warnings are enough.
    logging.getLogger("kafka").setLevel(logging.WARNING)
    asyncio.run(_run(Settings.from_env()))


if __name__ == "__main__":
    main()
