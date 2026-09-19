"""Forward-only SQL migrations for both halves of the store.

Numbered ``.sql`` files applied in filename order and recorded in a
``schema_migrations`` table on each side. No downgrade path: rolling a schema
backwards over a warehouse is a restore, not a migration.

Postgres migrations run inside a transaction. ClickHouse has no transactional
DDL, so its migrations must be written idempotently (``IF NOT EXISTS``) and
are applied statement by statement.
"""
from __future__ import annotations

import hashlib
import logging
import pathlib
import re

log = logging.getLogger(__name__)

MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"
CH_MIGRATIONS_DIR = pathlib.Path(__file__).parent / "ch_migrations"

_TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_CH_TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    String,
    checksum   String,
    applied_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(applied_at)
ORDER BY version
"""


class MigrationDrift(RuntimeError):
    """An already-applied migration file changed on disk."""


def discover(directory: pathlib.Path | str) -> list[pathlib.Path]:
    """Return migration files in application order."""
    path = pathlib.Path(directory)
    if not path.is_dir():
        raise FileNotFoundError(f"migrations directory not found: {path}")
    return sorted(path.glob("*.sql"))


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_drift(version: str, digest: str, applied: dict[str, str]) -> bool:
    """True if this version still needs applying. Raises on drift."""
    if version not in applied:
        return True
    if applied[version] != digest:
        raise MigrationDrift(
            f"{version} was already applied but its checksum changed. "
            "Edit history, never an applied migration: add a new file instead."
        )
    return False


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------


def applied(conn) -> dict[str, str]:
    """Version -> checksum for everything already applied to the catalog."""
    conn.execute(_TRACKING_DDL)
    rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    return {row[0]: row[1] for row in rows}


def migrate(conn, directory: pathlib.Path | str = MIGRATIONS_DIR) -> list[str]:
    """Apply every pending catalog migration. Returns the versions applied."""
    done = applied(conn)
    newly: list[str] = []

    for path in discover(directory):
        version = path.stem
        sql = path.read_text(encoding="utf-8")
        digest = _checksum(sql)
        if not _check_drift(version, digest, done):
            continue

        log.info("applying catalog migration %s", version)
        with conn.transaction():
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (version, digest),
            )
        newly.append(version)

    return newly


def current_version(conn) -> str | None:
    """Highest applied catalog migration version, or None on an empty database."""
    conn.execute(_TRACKING_DDL)
    row = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# ClickHouse
# ---------------------------------------------------------------------------


def _split_statements(sql: str) -> list[str]:
    """Split a ClickHouse migration into statements.

    ClickHouse's HTTP interface takes one statement per request. Comment lines
    are stripped first so a semicolon inside a comment cannot split a
    statement in half.
    """
    without_comments = re.sub(r"^\s*--.*$", "", sql, flags=re.MULTILINE)
    return [stmt.strip() for stmt in without_comments.split(";") if stmt.strip()]


def ch_applied(client) -> dict[str, str]:
    """Version -> checksum for everything already applied to ClickHouse."""
    client.command(_CH_TRACKING_DDL)
    rows = client.query("SELECT version, checksum FROM schema_migrations FINAL").result_rows
    return {row[0]: row[1] for row in rows}


def ch_migrate(client, directory: pathlib.Path | str = CH_MIGRATIONS_DIR) -> list[str]:
    """Apply every pending bars migration. Returns the versions applied.

    Each file is applied statement by statement with no transaction, so the
    statements must be individually idempotent. A file that fails halfway is
    not recorded, and re-running resumes it.
    """
    done = ch_applied(client)
    newly: list[str] = []

    for path in discover(directory):
        version = path.stem
        sql = path.read_text(encoding="utf-8")
        digest = _checksum(sql)
        if not _check_drift(version, digest, done):
            continue

        log.info("applying bars migration %s", version)
        for statement in _split_statements(sql):
            client.command(statement)
        client.command(
            "INSERT INTO schema_migrations (version, checksum) VALUES (%(v)s, %(c)s)",
            parameters={"v": version, "c": digest},
        )
        newly.append(version)

    return newly


def ch_current_version(client) -> str | None:
    """Highest applied bars migration version, or None on an empty database."""
    client.command(_CH_TRACKING_DDL)
    rows = client.query("SELECT max(version) FROM schema_migrations").result_rows
    return rows[0][0] if rows and rows[0][0] else None


# ---------------------------------------------------------------------------
# Both
# ---------------------------------------------------------------------------


def migrate_all(conn, client) -> dict[str, list[str]]:
    """Bring both halves of the store up to date."""
    return {"catalog": migrate(conn), "bars": ch_migrate(client)}
