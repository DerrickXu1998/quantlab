"""Where accounts and sessions live.

Sessions are rows, not signed tokens. A JWT cannot be withdrawn before it
expires, so "sign out" would be a lie told by the client to itself and a stolen
token would stay valid for its full lifetime. A row can be deleted, which is
what makes logout and "sign out everywhere" mean something.

Only the SHA-256 of a token is stored. Reading the database therefore yields no
usable credential -- a backup, a log of a query, or a read-only replica leak
does not hand anyone a session. SHA-256 is the right primitive here and PBKDF2
would be the wrong one: a session token is 32 bytes of CSPRNG output with no
guessable structure, so there is nothing for a slow KDF to protect against, and
paying 600k iterations on every authenticated request would be absurd.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quantlab.storage import db

#: How long a session lasts. Absolute, not sliding: a token stolen on day one
#: cannot be kept alive indefinitely by using it.
SESSION_TTL = timedelta(days=30)

#: 32 bytes of CSPRNG. token_urlsafe(32) yields ~43 characters.
TOKEN_BYTES = 32


class EmailAlreadyRegistered(Exception):
    """Raised on registration only. Login never distinguishes this case."""


@dataclass(frozen=True)
class User:
    id: str
    email: str
    created_at: str
    disabled: bool = False

    def to_dict(self) -> dict:
        return {"id": self.id, "email": self.email, "created_at": self.created_at}


@dataclass(frozen=True)
class Session:
    token: str
    user: User
    expires_at: str


def now() -> datetime:
    return datetime.now(UTC)


def normalise_email(email: str) -> str:
    """Lowercase and stripped.

    Deliberately *not* stripping dots or plus-addressing: those are provider
    conventions, not part of the address, and treating them as equivalent would
    merge accounts the user considers separate.
    """
    return (email or "").strip().lower()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


class SqliteUserStore:
    """Accounts and sessions in the same SQLite file as everything else."""

    name = "sqlite"

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = db.connect(self.db_path)
        db.bootstrap(conn)
        return conn

    # -- accounts ----------------------------------------------------------

    def create_user(self, email: str, password_hash: str) -> User:
        email = normalise_email(email)
        user = User(
            id=uuid.uuid4().hex,
            email=email,
            created_at=now().isoformat(timespec="seconds"),
        )
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (id, email, password_hash, created_at, disabled) "
                    "VALUES (?, ?, ?, ?, 0)",
                    (user.id, user.email, password_hash, user.created_at),
                )
            except sqlite3.IntegrityError as exc:
                raise EmailAlreadyRegistered(email) from exc
            conn.commit()
        return user

    def find_by_email(self, email: str) -> tuple[User, str] | None:
        """The user and their stored hash, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, email, created_at, disabled, password_hash "
                "FROM users WHERE email = ?",
                (normalise_email(email),),
            ).fetchone()
        if row is None:
            return None
        user_id, address, created_at, disabled, password_hash = row
        return User(user_id, address, created_at, bool(disabled)), password_hash

    def get_user(self, user_id: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, email, created_at, disabled FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return User(row[0], row[1], row[2], bool(row[3])) if row else None

    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
            )
            conn.commit()

    def user_count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    # -- sessions ----------------------------------------------------------

    def create_session(self, user: User) -> Session:
        token = new_token()
        issued = now()
        expires = issued + SESSION_TTL
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    token_digest(token),
                    user.id,
                    issued.isoformat(timespec="seconds"),
                    expires.isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
        return Session(token=token, user=user, expires_at=expires.isoformat(timespec="seconds"))

    def resolve_session(self, token: str) -> User | None:
        """The user behind a token, or None if it is unknown, expired or
        belongs to a disabled account.

        An expired row is deleted as it is found. Cheap, and it means the table
        is kept trimmed by ordinary traffic rather than by a job somebody has to
        remember to schedule.
        """
        if not token:
            return None
        digest = token_digest(token)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT u.id, u.email, u.created_at, u.disabled, s.expires_at "
                "FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ?",
                (digest,),
            ).fetchone()
            if row is None:
                return None
            user_id, email, created_at, disabled, expires_at = row
            if expires_at <= now().isoformat(timespec="seconds"):
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
                conn.commit()
                return None
        if disabled:
            return None
        return User(user_id, email, created_at, bool(disabled))

    def delete_session(self, token: str) -> bool:
        with self._connect() as conn:
            changed = conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),)
            ).rowcount
            conn.commit()
        return changed > 0

    def delete_sessions_for(self, user_id: str) -> int:
        """Sign out everywhere. Used after a password change."""
        with self._connect() as conn:
            changed = conn.execute(
                "DELETE FROM sessions WHERE user_id = ?", (user_id,)
            ).rowcount
            conn.commit()
        return changed

    def purge_expired_sessions(self) -> int:
        with self._connect() as conn:
            changed = conn.execute(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (now().isoformat(timespec="seconds"),),
            ).rowcount
            conn.commit()
        return changed


def select_user_store(db_path: str | Path | None = None) -> SqliteUserStore:
    """Where accounts live.

    Unlike bars and experiments there is only one implementation: identity is
    small, and putting it in the same SQLite file as the demo keeps the local
    story simple. A warehouse deployment should move this to Postgres; that is
    recorded as a known gap in ``docs/SECURITY.md`` rather than stubbed here.
    """
    return SqliteUserStore(db_path or "/data/quantlab.db")
