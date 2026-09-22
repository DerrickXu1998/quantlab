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

-- Identity. Until this existed every run lived in one global table, so any
-- caller could list, rename and delete every other caller's work.
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    -- pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>; the cost travels with
    -- the hash so it can be raised without a mass password reset.
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    disabled      INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1))
);

-- Sessions are rows, not signed tokens: a row can be deleted, so signing out
-- and revoking a stolen token actually mean something. Only the SHA-256 of the
-- token is stored, so reading this table yields no usable credential.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    CHECK (created_at <= expires_at)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions (expires_at);

-- Saved strategies. The spec is stored as canonical JSON rather than shredded
-- into columns: it is validated on the way in and on the way out, its shape is
-- owned by quantlab.strategy, and a schema migration per new execution setting
-- would be a tax on every future one.
CREATE TABLE IF NOT EXISTS strategies (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    spec        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_strategies_owner ON strategies (owner_id, name);

-- Custom signal rules: a fixed template id plus a validated config.
--
-- `user_id` NULL means unscoped -- a rule created while auth is off, visible
-- to everyone. Slug uniqueness is enforced in the store rather than by a
-- UNIQUE index, because SQLite treats NULLs as distinct and the unscoped rows
-- are exactly the ones that would collide.
--
-- `user_id` is TEXT to match `users.id`, which is a uuid here; this branch
-- originally declared it INTEGER against its own identity table, and that
-- table did not survive the merge.
CREATE TABLE IF NOT EXISTS custom_rules (
    rule_id    TEXT PRIMARY KEY,
    user_id    TEXT REFERENCES users (id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    slug       TEXT NOT NULL,
    template   TEXT NOT NULL,
    config     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_custom_rules_owner ON custom_rules (user_id);
"""

#: Columns added to tables that predate them.
#:
#: ``CREATE TABLE IF NOT EXISTS`` is a no-op against an existing table, so the
#: bootstrap DDL above cannot add a column to a database that already has
#: ``experiment_runs``. Without this, an existing demo database silently keeps
#: the old schema and every insert fails at runtime with a column-count error.
#: Each entry is ``(table, column, definition)`` and is applied only when the
#: column is absent, so running it repeatedly is safe.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # Ownership (see `users`). Null on rows that predate accounts; those are
    # visible only in single-user mode, which is the honest outcome -- there is
    # no way to know retroactively whose they were.
    ("experiment_runs", "owner_id", "TEXT"),
    # The resolved strategy and execution config that actually ran. Null on
    # runs recorded before strategies existed.
    ("experiment_runs", "strategy", "TEXT"),
    ("experiment_runs", "execution", "TEXT"),
    ("experiment_runs", "execution_summary", "TEXT"),
    # Whether a stored signal opens, closes, or (for a single-model run) does
    # both. Defaulted so existing rows keep their meaning exactly.
    ("experiment_signals", "kind", "TEXT NOT NULL DEFAULT 'both'"),
)

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
    """Apply the idempotent schema bootstrap, then any pending column adds."""
    conn.executescript(BOOTSTRAP_DDL)
    migrate(conn)
    conn.commit()


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Add columns that this database is missing, and report what was added.

    Runs as part of ``bootstrap`` rather than as a separate step somebody has to
    remember: a database that is opened is a database that is up to date. Every
    change here is additive, so an older build still reads a migrated file --
    which matters because a rollback must not require a restore.
    """
    applied: list[str] = []
    for table, column, definition in _ADDED_COLUMNS:
        if not _table_exists(conn, table):
            continue
        if column in _columns_of(conn, table):
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        applied.append(f"{table}.{column}")
    return applied


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _columns_of(conn: sqlite3.Connection, table: str) -> set[str]:
    # The table name cannot be bound as a parameter in a PRAGMA; it is never
    # user-supplied here, only ever a literal from _ADDED_COLUMNS.
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


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
