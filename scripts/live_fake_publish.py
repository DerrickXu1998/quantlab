#!/usr/bin/env python3
"""Publish FAKE live ticks to the live topic, for developing without IBKR.

Development only. Stands in for the live-ingest collector so the backend's
live hub and the Market tab's live mode can be exercised off-hours and with no
IBKR account: a random walk per symbol, one tick a second, a `bar` at every
minute close, and a collector `heartbeat` every two seconds. It writes to
Kafka only -- never to ClickHouse -- so no invented price ever lands in the
warehouse, and every message carries `"fake": true`.

    pip install kafka-python
    docker compose --profile streaming up -d redpanda
    python scripts/live_fake_publish.py --symbols AAPL.US,MSFT.US

Stop it (Ctrl-C) and the Market tab should go Stale, then Feed offline.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import UTC, datetime


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", required=True, help="comma-separated, e.g. AAPL.US,MSFT.US")
    parser.add_argument("--brokers", default="localhost:19092")
    parser.add_argument("--topic", default="quantlab.live.ticks")
    parser.add_argument("--market", choices=["open", "closed"], default="open")
    args = parser.parse_args()

    from kafka import KafkaProducer

    producer = KafkaProducer(
        bootstrap_servers=args.brokers.split(","),
        key_serializer=lambda k: k.encode() if k else None,
        value_serializer=lambda v: json.dumps(v).encode(),
    )
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    price = {s: random.uniform(50, 500) for s in symbols}
    volume = dict.fromkeys(symbols, 0)
    minute: dict[str, dict] = {}

    def send(key: str | None, value: dict) -> None:
        producer.send(args.topic, key=key, value={**value, "fake": True})

    print(f"publishing FAKE ticks for {', '.join(symbols)} to {args.topic} @ {args.brokers}")
    last_beat = 0.0
    try:
        while True:
            now = time.time()
            if now - last_beat >= 2:
                send(None, {"event": "heartbeat", "ts": iso(now), "connected": True,
                            "market": args.market})
                last_beat = now
            if args.market == "open":
                start = now - now % 60
                for s in symbols:
                    price[s] *= 1 + random.gauss(0, 0.0005)
                    volume[s] += random.randint(100, 5000)
                    bar = minute.get(s)
                    if bar and bar["start"] != start:
                        send(s, {"event": "bar", "symbol": s, "bar": {
                            "ts": iso(bar["start"]), "open": bar["open"], "high": bar["high"],
                            "low": bar["low"], "close": bar["close"],
                            "volume": volume[s] - bar["volume0"], "kind": "rolled"}})
                        bar = None
                    if bar is None:
                        bar = minute[s] = {"start": start, "open": price[s], "high": price[s],
                                           "low": price[s], "close": price[s],
                                           "volume0": volume[s]}
                    bar["high"] = max(bar["high"], price[s])
                    bar["low"] = min(bar["low"], price[s])
                    bar["close"] = price[s]
                    spread = price[s] * 0.0002
                    send(s, {"event": "tick", "symbol": s, "ts": iso(now),
                             "last": round(price[s], 2), "bid": round(price[s] - spread, 2),
                             "ask": round(price[s] + spread, 2), "volume": volume[s]})
            producer.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        producer.close()


if __name__ == "__main__":
    main()
