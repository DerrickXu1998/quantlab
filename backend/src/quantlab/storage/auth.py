"""User accounts and session tokens (feature 007).

Same seam as :mod:`quantlab.storage.experiments`: one protocol, two adapters
— the demo's SQLite file and the warehouse's Postgres catalog. The Postgres
tables come from migration 006_auth.sql; the SQLite tables are created by the
idempotent bootstrap in :mod:`quantlab.storage.db`.

Sessions are opaque bearer tokens. Only the SHA-256 of a token is stored, so
a leaked database does not hand out usable sessions; expiry is rolling — every
authenticated request renews the session for another ``SESSION_TTL``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from quantlab.storage import db

#: How long a session lives since its last authenticated request.
SESSION_TTL = timedelta(days=14)


def utcnow() -> datetime:
    return datetime.now(UTC)


class AuthStore(Protocol):
    """What the API is allowed to ask of account persistence."""

    name: str

    def count_users(self) -> int: ...
    def create_user(self, username: str, password_hash: str, is_admin: bool) -> dict: ...
    def get_user_by_username(self, username: str) -> dict | None: ...
    def create_session(self, user_id: int, token_hash: str, now: datetime) -> None: ...
    def get_session_user(self, token_hash: str, now: datetime) -> dict | None: ...
    def delete_session(self, token_hash: str) -> bool: ...


# ---------------------------------------------------------------------------
# SQLite -- the synthetic demo dataset
# ---------------------------------------------------------------------------


class SqliteAuthStore:
    """Accounts and sessions in the demo's SQLite file."""

    name = "sqlite"

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._bootstrapped = False

    def _connect(self) -> sqlite3.Connection:
        conn = db.connect(self.db_path)
        if not self._bootstrapped:
            # Idempotent: creates the auth tables on databases seeded before
            # accounts existed, and adds experiment_runs.user_id there too.
            db.bootstrap(conn)
            self._bootstrapped = True
        return conn

    @staticmethod
    def _row_to_user(row: tuple) -> dict:
        user_id, username, password_hash, created_at, is_admin = row
        return {
            "id": user_id,
            "username": username,
            "password_hash": password_hash,
            "created_at": created_at,
            "is_admin": bool(is_admin),
        }

    _USER_COLUMNS = "id, username, password_hash, created_at, is_admin"

    def count_users(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_user(self, username: str, password_hash: str, is_admin: bool) -> dict:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, created_at, is_admin) "
                "VALUES (?, ?, ?, ?)",
                (username, password_hash, utcnow().isoformat(), int(is_admin)),
            )
            conn.commit()
            row = conn.execute(
                f"SELECT {self._USER_COLUMNS} FROM users WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._row_to_user(row)

    def get_user_by_username(self, username: str) -> dict | None:
        with self._connect() as conn:
            # username is COLLATE NOCASE, so this match is case-insensitive.
            row = conn.execute(
                f"SELECT {self._USER_COLUMNS} FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def create_session(self, user_id: int, token_hash: str, now: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (token_hash, user_id, now.isoformat(), (now + SESSION_TTL).isoformat()),
            )
            conn.commit()

    def get_session_user(self, token_hash: str, now: datetime) -> dict | None:
        """The session's user, or None when the token is unknown or expired.

        Rolling expiry: a live session is renewed for another SESSION_TTL on
        every lookup, so only 14 idle days log a user out.
        """
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT u.{', u.'.join(self._USER_COLUMNS.split(', '))}, s.expires_at "
                "FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ?",
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            *user_fields, expires_at = row
            if datetime.fromisoformat(expires_at) <= now:
                return None
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                ((now + SESSION_TTL).isoformat(), token_hash),
            )
            conn.commit()
        return self._row_to_user(tuple(user_fields))

    def delete_session(self, token_hash: str) -> bool:
        with self._connect() as conn:
            changed = conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (token_hash,)
            ).rowcount
            conn.commit()
        return changed > 0


# ---------------------------------------------------------------------------
# Postgres -- alongside the warehouse catalog
# ---------------------------------------------------------------------------


class PostgresAuthStore:
    """Accounts and sessions in the Postgres catalog (migration 006_auth.sql).

    The driver is imported inside the methods that need it, never at module
    scope: the demo path must keep working with no database drivers installed
    at all.
    """

    name = "warehouse"

    def __init__(self, dsn: str = "") -> None:
        self._dsn = dsn

    def _connect(self):
        try:
            import psycopg
        except ModuleNotFoundError as exc:  # pragma: no cover - import guard
            raise RuntimeError(
                "psycopg is not installed. Install the warehouse extras:\n"
                "    pip install 'quantlab[store]'"
            ) from exc
        import os

        dsn = self._dsn or os.environ.get(
            "QUANTLAB_DB_URL", "postgresql://quantlab:quantlab@localhost:5432/quantlab"
        )
        return psycopg.connect(dsn)

    @staticmethod
    def _row_to_user(row: tuple) -> dict:
        user_id, username, password_hash, created_at, is_admin = row
        return {
            "id": user_id,
            "username": username,
            "password_hash": password_hash,
            "created_at": created_at.isoformat(),
            "is_admin": bool(is_admin),
        }

    _USER_COLUMNS = "id, username, password_hash, created_at, is_admin"

    def count_users(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_user(self, username: str, password_hash: str, is_admin: bool) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                f"INSERT INTO users (username, password_hash, is_admin) "
                f"VALUES (%s, %s, %s) RETURNING {self._USER_COLUMNS}",
                (username, password_hash, is_admin),
            ).fetchone()
            conn.commit()
        return self._row_to_user(row)

    def get_user_by_username(self, username: str) -> dict | None:
        with self._connect() as conn:
            # users_username_ci indexes lower(username), keeping identity
            # case-insensitive like the demo store's COLLATE NOCASE.
            row = conn.execute(
                f"SELECT {self._USER_COLUMNS} FROM users WHERE lower(username) = lower(%s)",
                (username,),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def create_session(self, user_id: int, token_hash: str, now: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (%s, %s, %s, %s)",
                (token_hash, user_id, now, now + SESSION_TTL),
            )
            conn.commit()

    def get_session_user(self, token_hash: str, now: datetime) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT u.{', u.'.join(self._USER_COLUMNS.split(', '))}, s.expires_at "
                "FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = %s",
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            *user_fields, expires_at = row
            if expires_at <= now:
                return None
            conn.execute(
                "UPDATE sessions SET expires_at = %s WHERE token_hash = %s",
                (now + SESSION_TTL, token_hash),
            )
            conn.commit()
        return self._row_to_user(tuple(user_fields))

    def delete_session(self, token_hash: str) -> bool:
        with self._connect() as conn:
            changed = conn.execute(
                "DELETE FROM sessions WHERE token_hash = %s", (token_hash,)
            ).rowcount
            conn.commit()
        return changed > 0


def select_auth_store(db_path: str | Path | None = None) -> AuthStore:
    """Mirror ``select_experiment_store``: the warehouse when configured, else the demo."""
    from quantlab.storage import warehouse

    if warehouse.configured():
        return PostgresAuthStore()
    return SqliteAuthStore(db_path or "/data/quantlab.db")


__all__ = [
    "SESSION_TTL",
    "AuthStore",
    "PostgresAuthStore",
    "SqliteAuthStore",
    "select_auth_store",
    "utcnow",
]
