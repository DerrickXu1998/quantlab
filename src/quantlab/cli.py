"""`quantlab migrate`: bring the warehouse schema up to date.

The one command left in this package. Data ingestion (`ingest`, `ingest-macro`,
`ingest-sec-fundamentals`, ...) moved to quantlab-data-pipeline as
`quantlab-data`; running one of those names here says where it went.
"""

from __future__ import annotations

import argparse
import sys

#: Commands that moved to quantlab-data-pipeline, for a helpful refusal.
MOVED = {
    "ingest", "ingest-macro", "ingest-finra-shorts", "ingest-fca-shorts",
    "ingest-sec-fundamentals", "ingest-ch-fundamentals", "map-identifiers",
    "map-sec-tickers", "map-ch-companies", "universe", "universe-snapshot",
    "seed-synthetic", "replay-publish", "coverage", "fetch", "compute", "run",
    "list", "sources", "doctor", "config",
}


def cmd_migrate(args) -> int:
    from . import store

    with store.session(args.db_url) as conn, store.ch_session(args.ch_url) as client:
        applied = store.migrate_all(conn, client)
        for half, versions in applied.items():
            print(f"{half}: " + (", ".join(versions) if versions else "up to date"))
        print(f"\ncatalog schema {store.current_version(conn)}")
        print(f"bars schema    {store.ch_current_version(client)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quantlab",
        description="Apply the quantlab warehouse schema (Postgres catalog + ClickHouse bars).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("migrate", help="apply every pending Postgres and ClickHouse migration")
    m.add_argument("--db-url", default="", help="Postgres catalog; overrides $QUANTLAB_DB_URL")
    m.add_argument("--ch-url", default="", help="ClickHouse bars; overrides $QUANTLAB_CH_URL")
    m.set_defaults(func=cmd_migrate)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in MOVED:
        print(
            f"`quantlab {argv[0]}` moved to quantlab-data-pipeline: run "
            f'`make quantlab-data ARGS="{" ".join(argv)}"` there. '
            "This package only applies the schema (`quantlab migrate`).",
            file=sys.stderr,
        )
        return 2
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
