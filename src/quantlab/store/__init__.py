"""The historical data store: ClickHouse bars over a Postgres catalog.

The split, and why:

  * **ClickHouse holds price_bars.** Append-only, enormous, read by wide
    scans. `ts` is a DateTime64 from day one, so daily bars today and minute
    bars later are the same table. ReplacingMergeTree(run_id) makes
    re-ingesting a range idempotent.
  * **Postgres holds the catalog.** Instruments, vendor symbol mappings,
    universe snapshots, ingest provenance and corporate actions -- small,
    mutable, relational data that wants foreign keys, unique constraints and
    transactions, none of which ClickHouse has.

The rule of thumb: anything with bar-level cardinality goes to ClickHouse;
anything needing a constraint stays in Postgres.

Typical use::

    from quantlab import store

    with store.session() as conn, store.ch_session() as client:
        store.migrate_all(conn, client)
        report = store.ingest_prices(
            conn, client, ["AAPL.US", "HSBA.LON"], start="2015-01-01"
        )
        print(report.summary())

        panel, ctx = store.load_panel(conn, client, return_context=True)
"""
from __future__ import annotations

from .bars import bar_count, load_bars, optimize, storage_stats, validate, write_bars
from .catalog import (
    ensure_instruments,
    finish_run,
    instrument_ids,
    latest_snapshot,
    list_symbols,
    load_securities,
    map_vendor_symbols,
    real_equity_symbols,
    record_cik_mappings,
    record_company_number_mappings,
    record_figi_mappings,
    record_rejects,
    run_history,
    snapshot_members,
    snapshot_universe,
    stale_runs,
    start_run,
    storage_currency,
    symbols_for_ids,
    write_corporate_actions,
)
from .catalog import corporate_actions as corporate_actions
from .conn import (
    CH_ENV_VAR,
    DEFAULT_CH_URL,
    DEFAULT_DSN,
    ENV_VAR,
    StoreNotConfigured,
    ch_connect,
    ch_ping,
    ch_session,
    ch_url,
    connect,
    dsn,
    ping,
    session,
)
from .identifiers import MapReport, map_identifiers
from .fundamentals import (
    ChMapReport,
    flatten_companyfacts,
    ingest_ch_fundamentals,
    ingest_sec_fundamentals,
    map_ch_companies,
    map_sec_tickers,
    write_fundamentals,
)
from .ingest import IngestReport, ingest_corporate_actions, ingest_prices
from .macro import ingest_macro_series, series_to_bars
from .seed import seed_warehouse
from .shorts import ingest_fca_shorts, ingest_finra_shorts
from .migrate import (
    CH_MIGRATIONS_DIR,
    MIGRATIONS_DIR,
    MigrationDrift,
    ch_current_version,
    ch_migrate,
    current_version,
    migrate,
    migrate_all,
)
from .reader import coverage, load_panel, panel_for_modelling

__all__ = [
    "CH_ENV_VAR",
    "CH_MIGRATIONS_DIR",
    "ChMapReport",
    "DEFAULT_CH_URL",
    "DEFAULT_DSN",
    "ENV_VAR",
    "IngestReport",
    "MIGRATIONS_DIR",
    "MapReport",
    "MigrationDrift",
    "StoreNotConfigured",
    "bar_count",
    "ch_connect",
    "ch_current_version",
    "ch_migrate",
    "ch_ping",
    "ch_session",
    "ch_url",
    "connect",
    "corporate_actions",
    "coverage",
    "current_version",
    "dsn",
    "ensure_instruments",
    "finish_run",
    "flatten_companyfacts",
    "ingest_ch_fundamentals",
    "ingest_corporate_actions",
    "ingest_fca_shorts",
    "ingest_finra_shorts",
    "ingest_macro_series",
    "ingest_prices",
    "ingest_sec_fundamentals",
    "instrument_ids",
    "latest_snapshot",
    "list_symbols",
    "load_bars",
    "load_panel",
    "load_securities",
    "map_ch_companies",
    "map_identifiers",
    "map_sec_tickers",
    "map_vendor_symbols",
    "migrate",
    "migrate_all",
    "optimize",
    "panel_for_modelling",
    "ping",
    "real_equity_symbols",
    "record_cik_mappings",
    "record_company_number_mappings",
    "record_figi_mappings",
    "record_rejects",
    "run_history",
    "seed_warehouse",
    "series_to_bars",
    "session",
    "snapshot_members",
    "snapshot_universe",
    "stale_runs",
    "start_run",
    "storage_currency",
    "storage_stats",
    "symbols_for_ids",
    "validate",
    "write_bars",
    "write_corporate_actions",
    "write_fundamentals",
]
