"""Compute signals over warehouse bars and store them in the catalog.

Signals are derived data: reproducible from bars plus deterministic rule
logic (Constitution II/III). The registry stays authoritative and this table
is a cache -- dropping and rebuilding it must change nothing.

Run it after an ingest::

    docker compose run --rm backend python -m quantlab.signals.materialize

Bars come from ClickHouse, signals land in Postgres. That split is on purpose:
a signal row is small, relational, and worth a foreign key to the rule that
produced it, which is exactly what ClickHouse cannot give.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from quantlab.signals.engine import compute_signals
from quantlab.signals.registry import list_rules
from quantlab.storage import warehouse

logger = logging.getLogger(__name__)


def canonical_json(obj: object) -> str:
    """Canonical JSON: sorted keys, compact separators -- stable as a key."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sync_rules(conn) -> dict[tuple[str, str, str], int]:
    """Mirror the registry into signal_rules, returning rule -> rule_id."""
    rules = list_rules()
    out: dict[tuple[str, str, str], int] = {}

    for rule in rules:
        params = canonical_json(rule.params)
        row = conn.execute(
            """
            INSERT INTO signal_rules (
                rule_name, rule_version, parameters, lookback_days,
                scale_class, direction_semantics
            ) VALUES (%s, %s, %s::jsonb, %s, %s, %s)
            ON CONFLICT (rule_name, rule_version, parameters) DO UPDATE SET
                lookback_days       = EXCLUDED.lookback_days,
                scale_class         = EXCLUDED.scale_class,
                direction_semantics = EXCLUDED.direction_semantics
            RETURNING rule_id
            """,
            (
                rule.name,
                rule.version,
                params,
                rule.lookback_days,
                rule.scale_class,
                rule.direction_semantics,
            ),
        ).fetchone()
        out[(rule.name, rule.version, params)] = int(row[0])

    return out


def materialize(
    wh: warehouse.Warehouse | None = None,
    symbols: list[str] | None = None,
    *,
    replace: bool = True,
) -> int:
    """Recompute signals for the given symbols (all of them by default).

    `replace` deletes the existing signals for each instrument first, so a
    rule whose definition changed cannot leave orphaned rows behind claiming
    to come from a version that no longer exists.
    """
    wh = wh or warehouse.Warehouse.from_env()
    written = 0

    with wh.catalog() as conn:
        rule_ids = sync_rules(conn)

        for symbol, instrument_id, bars in warehouse.iter_symbol_bars(wh, symbols):
            if not bars:
                continue

            signals = compute_signals({symbol: bars})

            if replace:
                conn.execute(
                    "DELETE FROM signals WHERE instrument_id = %s", (instrument_id,)
                )

            rows = []
            for signal in signals:
                key = (
                    signal.rule_name,
                    signal.rule_version,
                    canonical_json(signal.parameters),
                )
                rule_id = rule_ids.get(key)
                if rule_id is None:
                    logger.warning("no rule_id for %s, skipping", key)
                    continue
                rows.append(
                    (
                        instrument_id,
                        rule_id,
                        signal.date,
                        signal.direction,
                        canonical_json(signal.trigger_values),
                        signal.data_window_end,
                    )
                )

            if rows:
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        INSERT INTO signals (
                            instrument_id, rule_id, date, direction,
                            trigger_values, data_window_end
                        ) VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                        ON CONFLICT (instrument_id, rule_id, date) DO UPDATE SET
                            direction       = EXCLUDED.direction,
                            trigger_values  = EXCLUDED.trigger_values,
                            data_window_end = EXCLUDED.data_window_end,
                            computed_at     = now()
                        """,
                        rows,
                    )
                written += len(rows)

            logger.info("%s: %d bars -> %d signals", symbol, len(bars), len(rows))

        conn.commit()

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quantlab.signals.materialize",
        description="Compute signals over warehouse bars into the catalog.",
    )
    parser.add_argument("symbols", nargs="*", help="default: every instrument")
    parser.add_argument(
        "--append",
        action="store_true",
        help="keep existing signals instead of replacing per instrument",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if not warehouse.configured():
        print(
            "warehouse is not configured: set QUANTLAB_DB_URL and QUANTLAB_CH_URL",
            file=sys.stderr,
        )
        return 2

    written = materialize(symbols=args.symbols or None, replace=not args.append)
    print(f"{written} signals materialised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
