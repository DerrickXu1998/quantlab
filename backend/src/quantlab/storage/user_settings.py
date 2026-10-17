"""Where each user's settings document lives: beside their account.

Accounts live in the SQLite identity store (quantlab.auth.store), so settings
do too -- one row per user. The document is validated by quantlab.settings;
this module only reads and writes it.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from quantlab.storage import db


class SqliteUserSettingsStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._bootstrapped = False
        self._lock = threading.Lock()

    def _connect(self):
        conn = db.connect(self.db_path)
        if not self._bootstrapped:
            with self._lock:
                if not self._bootstrapped:
                    db.bootstrap(conn)
                    self._bootstrapped = True
        return conn

    def get(self, user_id: str) -> tuple[dict | None, str | None]:
        """(stored document, updated_at), or (None, None) if never saved."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT settings, updated_at FROM user_settings WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            return None, None
        return json.loads(row[0]), row[1]

    def put(self, user_id: str, settings: dict) -> str:
        updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, ?)
                ON CONFLICT (user_id) DO UPDATE
                   SET settings = excluded.settings, updated_at = excluded.updated_at
                """,
                (user_id, json.dumps(settings, sort_keys=True), updated_at),
            )
            conn.commit()
        return updated_at


def select_user_settings_store(db_path: str | Path | None = None) -> SqliteUserSettingsStore:
    """Beside the accounts, in the same SQLite file (see auth.store)."""
    return SqliteUserSettingsStore(db_path or "/data/quantlab.db")
