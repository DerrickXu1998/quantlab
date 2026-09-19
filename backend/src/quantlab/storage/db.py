"""SQLite storage library for the signal viewer demo.

Idempotent bootstrap DDL (CREATE TABLE IF NOT EXISTS) per data-model.md,
deterministic upserts keyed on natural keys, and an ordered full-dump
SHA-256 helper used to prove byte-identical reseeds (SC-002, research R8).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

BOOTSTRAP_DDL = """
CREATE TABLE IF NOT EXISTS instruments (
    symbol         TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    currency       TEXT NOT NULL,
    regime_profile TEXT NOT NULL
                   CHECK (regime_profile IN ('trending', 'mean_reverting', 'volatile', 'mixed')),
    seed           INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS price_bars (
    symbol TEXT NOT NULL REFERENCES instruments (symbol),
    date   TEXT NOT NULL,
    open   REAL NOT NULL CHECK (open > 0),
    high   REAL NOT NULL CHECK (high >= max(open, close)),
    low    REAL NOT NULL CHECK (low <= min(open, close) AND low > 0),
    close  REAL NOT NULL CHECK (close > 0),
    volume INTEGER NOT NULL CHECK (volume >= 0),
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS signal_rules (
    rule_name           TEXT NOT NULL,
    rule_version        TEXT NOT NULL,
    parameters          TEXT NOT NULL,
    lookback_days       INTEGER NOT NULL CHECK (lookback_days > 0),
    scale_class         TEXT NOT NULL CHECK (scale_class IN ('scale_free', 'price_scaled')),
    direction_semantics TEXT NOT NULL,
    PRIMARY KEY (rule_name, rule_version, parameters)
);

CREATE TABLE IF NOT EXISTS signals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol           TEXT NOT NULL REFERENCES instruments (symbol),
    date             TEXT NOT NULL,
    rule_name        TEXT NOT NULL,
    rule_version     TEXT NOT NULL,
    parameters       TEXT NOT NULL,
    direction        TEXT NOT NULL CHECK (direction IN ('bullish', 'bearish')),
    trigger_values   TEXT NOT NULL,
    data_window_end  TEXT NOT NULL CHECK (data_window_end <= date),
    UNIQUE (symbol, date, rule_name, rule_version, parameters),
    FOREIGN KEY (rule_name, rule_version, parameters)
        REFERENCES signal_rules (rule_name, rule_version, parameters)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Experiment storage (feature 005). Deliberately separate from `signals`:
-- that table is the Signal Viewer's source, and run output inserted there
-- would appear in the viewer, silently mixing exploratory runs into the
-- curated seeded set.
CREATE TABLE IF NOT EXISTS experiment_runs (
    id                       TEXT PRIMARY KEY,
    name                     TEXT,
    model_name               TEXT NOT NULL,
    model_version            TEXT NOT NULL,
    parameters               TEXT NOT NULL,
    symbols                  TEXT NOT NULL,
    start_date               TEXT NOT NULL,
    end_date                 TEXT NOT NULL,
    status                   TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    error                    TEXT,
    created_at               TEXT NOT NULL,
    signal_count             INTEGER NOT NULL CHECK (signal_count >= 0),
    instruments_requested    INTEGER NOT NULL CHECK (instruments_requested >= 1),
    instruments_with_data    INTEGER NOT NULL CHECK (instruments_with_data >= 0),
    instruments_full_warmup  INTEGER NOT NULL CHECK (instruments_full_warmup >= 0),
    -- Provenance (feature 006): which store produced this run, the surrogate
    -- identities it ran against, and the ingest runs behind the bars it read.
    -- The latter two are warehouse-only and null on the demo.
    dataset                  TEXT NOT NULL DEFAULT 'sqlite'
                                  CHECK (dataset IN ('sqlite', 'warehouse')),
    instrument_ids           TEXT,
    ingest_run_ids           TEXT,
    -- Splits/dividends inside the window. Persisted rather than only
    -- reported, so reopening a saved run still warns that its price series
    -- contains unadjusted discontinuities.
    corporate_actions        TEXT,
    CHECK (start_date <= end_date),
    CHECK ((status = 'failed') = (error IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS experiment_signals (
    run_id           TEXT NOT NULL REFERENCES experiment_runs (id) ON DELETE CASCADE,
    symbol           TEXT NOT NULL REFERENCES instruments (symbol),
    date             TEXT NOT NULL,
    direction        TEXT NOT NULL CHECK (direction IN ('bullish', 'bearish')),
    trigger_values   TEXT NOT NULL,
    -- Same point-in-time proof the seeded `signals` table enforces
    -- (Constitution VII): a signal may never be built from a later bar.
    data_window_end  TEXT NOT NULL CHECK (data_window_end <= date)
);

CREATE INDEX IF NOT EXISTS idx_experiment_signals_run
    ON experiment_signals (run_id, symbol, date);
"""

# Fixed table + ordering for the deterministic dump hash.
#
# Experiment tables are deliberately excluded: this hash proves the *seed* is
# reproducible, and experiment data is user-generated. Including it would make
# the determinism proof depend on whatever runs a user happened to execute.
_DUMP_ORDER: tuple[tuple[str, str], ...] = (
    ("instruments", "symbol"),
    ("price_bars", "symbol, date"),
    ("signal_rules", "rule_name, rule_version, parameters"),
    ("signals", "id"),
    ("meta", "key"),
)


@dataclass(frozen=True)
class InstrumentRow:
    symbol: str
    name: str
    currency: str
    regime_profile: str
    seed: int


@dataclass(frozen=True)
class PriceBarRow:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class SignalRuleRow:
    rule_name: str
    rule_version: str
    parameters: str  # canonical JSON (sorted keys)
    lookback_days: int
    scale_class: str
    direction_semantics: str


@dataclass(frozen=True)
class SignalRow:
    symbol: str
    date: str
    rule_name: str
    rule_version: str
    parameters: str  # canonical JSON (sorted keys)
    direction: str
    trigger_values: str  # canonical JSON (sorted keys)
    data_window_end: str


def canonical_json(obj: object) -> str:
    """Canonical JSON: sorted keys, compact separators — stable for hashing/keys."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the SQLite file with FK enforcement on."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def bootstrap(conn: sqlite3.Connection) -> None:
    """Apply the idempotent schema bootstrap."""
    conn.executescript(BOOTSTRAP_DDL)
    conn.commit()


def upsert_instruments(conn: sqlite3.Connection, rows: list[InstrumentRow]) -> None:
    """Upsert instruments. Does NOT commit — the caller owns the transaction."""
    conn.executemany(
        """
        INSERT INTO instruments (symbol, name, currency, regime_profile, seed)
        VALUES (:symbol, :name, :currency, :regime_profile, :seed)
        ON CONFLICT (symbol) DO UPDATE SET
            name = excluded.name,
            currency = excluded.currency,
            regime_profile = excluded.regime_profile,
            seed = excluded.seed
        """,
        [vars(row) for row in rows],
    )


def upsert_price_bars(conn: sqlite3.Connection, rows: list[PriceBarRow]) -> None:
    """Upsert price bars. Does NOT commit — the caller owns the transaction."""
    conn.executemany(
        """
        INSERT INTO price_bars (symbol, date, open, high, low, close, volume)
        VALUES (:symbol, :date, :open, :high, :low, :close, :volume)
        ON CONFLICT (symbol, date) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume
        """,
        [vars(row) for row in rows],
    )


def upsert_signal_rules(conn: sqlite3.Connection, rows: list[SignalRuleRow]) -> None:
    """Upsert signal rules. Does NOT commit — the caller owns the transaction."""
    conn.executemany(
        """
        INSERT INTO signal_rules
            (rule_name, rule_version, parameters, lookback_days, scale_class, direction_semantics)
        VALUES
            (:rule_name, :rule_version, :parameters, :lookback_days, :scale_class,
             :direction_semantics)
        ON CONFLICT (rule_name, rule_version, parameters) DO UPDATE SET
            lookback_days = excluded.lookback_days,
            scale_class = excluded.scale_class,
            direction_semantics = excluded.direction_semantics
        """,
        [vars(row) for row in rows],
    )


def upsert_signals(conn: sqlite3.Connection, rows: list[SignalRow]) -> None:
    """Insert signals; on natural-key conflict update in place so row ids
    (and therefore dump order) stay stable across reseeds.

    Does NOT commit — the caller owns the transaction.
    """
    conn.executemany(
        """
        INSERT INTO signals
            (symbol, date, rule_name, rule_version, parameters, direction,
             trigger_values, data_window_end)
        VALUES
            (:symbol, :date, :rule_name, :rule_version, :parameters, :direction,
             :trigger_values, :data_window_end)
        ON CONFLICT (symbol, date, rule_name, rule_version, parameters) DO UPDATE SET
            direction = excluded.direction,
            trigger_values = excluded.trigger_values,
            data_window_end = excluded.data_window_end
        """,
        [vars(row) for row in rows],
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Set a meta key. Does NOT commit — the caller owns the transaction."""
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table, _ in _DUMP_ORDER
    }


def dump_hash(conn: sqlite3.Connection) -> str:
    """SHA-256 of an ordered dump of all tables (research R8).

    Rows are serialized canonically (repr of each tuple, one per line) so the
    hash is byte-identical across runs iff the stored data is.
    """
    digest = hashlib.sha256()
    for table, order_by in _DUMP_ORDER:
        digest.update(f"== {table} ==\n".encode())
        cursor = conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}")
        for row in cursor:
            digest.update(repr(tuple(row)).encode())
            digest.update(b"\n")
    return digest.hexdigest()
