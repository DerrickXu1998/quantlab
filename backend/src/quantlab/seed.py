"""Seed entrypoint: ``python -m quantlab.seed``.

Pipeline: generate the deterministic universe -> persist instruments and raw
price bars FIRST (Constitution III) -> mirror the rule registry into
signal_rules -> compute signals -> persist -> set meta.seeded='1'.

Idempotent: the DB file is rebuilt from clean state (an interrupted seed never
leaves partial data — the half-written file is discarded on the next run), and
the whole load runs inside one transaction in dependency order.

DB path resolution: ``QUANTLAB_DB`` env var, falling back to
``QUANTLAB_DB_PATH`` (set by the Docker image), default /data/quantlab.db.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from quantlab.logging import get_logger
from quantlab.signals import engine
from quantlab.signals.registry import list_rules
from quantlab.storage import db, repository
from quantlab.synthetic import generator

DEFAULT_DB_PATH = "/data/quantlab.db"

logger = get_logger("quantlab.seed")


def resolve_db_path() -> str:
    return os.environ.get("QUANTLAB_DB") or os.environ.get("QUANTLAB_DB_PATH") or DEFAULT_DB_PATH


def run(db_path: str | os.PathLike) -> dict[str, int]:
    """Rebuild the demo database at ``db_path``; returns per-table row counts."""
    started = time.monotonic()
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()  # clean-replace: never resume a possibly partial file

    bars_by_symbol = generator.generate_universe()
    conn = db.connect(path)
    try:
        db.bootstrap(conn)
        with conn:  # single transaction, dependency order
            for table in ("signals", "signal_rules", "price_bars", "instruments"):
                conn.execute(f"DELETE FROM {table}")
            instrument_count = repository.upsert_instruments(conn)
            bar_count = repository.insert_bars(conn, bars_by_symbol)
            rule_count = repository.mirror_rules(conn, list_rules())
            signals = engine.compute_signals(bars_by_symbol)
            signal_count = repository.insert_signals(conn, signals)
            db.set_meta(conn, "seeded", "1")
        counts = db.table_counts(conn)
        logger.info(
            "seed_complete",
            extra={
                "db_path": str(path),
                "instruments": instrument_count,
                "price_bars": bar_count,
                "signal_rules": rule_count,
                "signals": signal_count,
                "elapsed_seconds": round(time.monotonic() - started, 3),
            },
        )
        return counts
    finally:
        conn.close()


def main() -> int:
    run(resolve_db_path())
    return 0


if __name__ == "__main__":
    sys.exit(main())
