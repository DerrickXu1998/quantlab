"""Custom signal rules (feature 008, M2): a fixed template id plus a config.

Same seam as :mod:`quantlab.storage.experiments` and :mod:`quantlab.storage.auth`:
one protocol, two adapters -- the demo's SQLite file and the warehouse's
Postgres catalog (migration 007).

Scoping mirrors experiment runs: a call with ``user_id`` sees that user's
rules plus unscoped ones (``user_id IS NULL``, created with QUANTLAB_AUTH=off),
so another user's rule id reads as absent; ``user_id=None`` applies no scoping
at all. The store is deliberately dumb about what a config means -- template
validation lives in quantlab.signals.templates, at the API/runner boundary.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from quantlab.storage import db


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def slugify(name: str) -> str:
    """Display name -> URL/run identifier. Lowercase, dashes, no edge dashes."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "rule"


class CustomRuleStore(Protocol):
    """What the API is allowed to ask of custom-rule persistence."""

    name: str

    def create_rule(
        self, user_id: int | None, name: str, template: str, config: dict
    ) -> dict: ...

    def get_rule(self, rule_id: str, user_id: int | None = None) -> dict | None: ...

    def list_rules(self, user_id: int | None = None) -> dict: ...

    def update_rule(
        self,
        rule_id: str,
        user_id: int | None,
        *,
        name: str | None = None,
        config: dict | None = None,
    ) -> dict | None: ...

    def delete_rule(self, rule_id: str, user_id: int | None) -> bool: ...


def _row_to_rule(row: tuple, *, config_as_json: bool) -> dict:
    rule_id, user_id, name, slug, template, config, created_at, updated_at = row
    return {
        "rule_id": rule_id,
        "user_id": user_id,
        "name": name,
        "slug": slug,
        "template": template,
        "config": json.loads(config) if config_as_json else config,
        "created_at": str(created_at),
        "updated_at": str(updated_at),
    }


def _unique_slug(existing: set[str], base: str) -> str:
    """``base``, then ``base-2``, ``base-3``... -- per owner scope."""
    slug = base
    suffix = 2
    while slug in existing:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


# ---------------------------------------------------------------------------
# SQLite -- the synthetic demo dataset
# ---------------------------------------------------------------------------


class SqliteCustomRuleStore:
    """Custom rules in the demo's SQLite file."""

    name = "sqlite"

    _COLUMNS = "rule_id, user_id, name, slug, template, config, created_at, updated_at"

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._bootstrapped = False

    def _connect(self) -> sqlite3.Connection:
        conn = db.connect(self.db_path)
        if not self._bootstrapped:
            # Idempotent: creates the table on databases seeded before custom
            # rules existed.
            db.bootstrap(conn)
            self._bootstrapped = True
        return conn

    @staticmethod
    def _scope(user_id: int | None) -> tuple[str, list]:
        """Own rules plus unscoped (NULL-owned) ones -- or no clause at all."""
        if user_id is None:
            return "", []
        return " AND (user_id IS NULL OR user_id = ?)", [user_id]

    def _slugs_in_scope(self, conn, user_id: int | None) -> set[str]:
        scope, params = self._scope(user_id)
        rows = conn.execute(
            f"SELECT slug FROM custom_rules WHERE 1=1{scope}", params
        ).fetchall()
        return {row[0] for row in rows}

    def create_rule(
        self, user_id: int | None, name: str, template: str, config: dict
    ) -> dict:
        with self._connect() as conn:
            slug = _unique_slug(self._slugs_in_scope(conn, user_id), slugify(name))
            now = utcnow()
            rule_id = uuid.uuid4().hex
            conn.execute(
                f"INSERT INTO custom_rules ({self._COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rule_id,
                    user_id,
                    name,
                    slug,
                    template,
                    db.canonical_json(config),
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM custom_rules WHERE rule_id = ?", (rule_id,)
            ).fetchone()
        return _row_to_rule(row, config_as_json=True)

    def get_rule(self, rule_id: str, user_id: int | None = None) -> dict | None:
        with self._connect() as conn:
            scope, params = self._scope(user_id)
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM custom_rules WHERE rule_id = ?{scope}",
                (rule_id, *params),
            ).fetchone()
        return _row_to_rule(row, config_as_json=True) if row else None

    def list_rules(self, user_id: int | None = None) -> dict:
        with self._connect() as conn:
            scope, params = self._scope(user_id)
            rows = conn.execute(
                f"SELECT {self._COLUMNS} FROM custom_rules WHERE 1=1{scope} "
                "ORDER BY created_at, rule_id",
                params,
            ).fetchall()
        items = [_row_to_rule(row, config_as_json=True) for row in rows]
        return {"total": len(items), "items": items}

    def update_rule(
        self,
        rule_id: str,
        user_id: int | None,
        *,
        name: str | None = None,
        config: dict | None = None,
    ) -> dict | None:
        with self._connect() as conn:
            scope, params = self._scope(user_id)
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM custom_rules WHERE rule_id = ?{scope}",
                (rule_id, *params),
            ).fetchone()
            if row is None:
                return None
            existing = _row_to_rule(row, config_as_json=True)
            new_name = name if name is not None else existing["name"]
            new_config = config if config is not None else existing["config"]
            slug = existing["slug"]
            if name is not None and name != existing["name"]:
                others = self._slugs_in_scope(conn, user_id) - {existing["slug"]}
                slug = _unique_slug(others, slugify(new_name))
            conn.execute(
                "UPDATE custom_rules SET name = ?, slug = ?, config = ?, updated_at = ? "
                f"WHERE rule_id = ?{scope}",
                (new_name, slug, db.canonical_json(new_config), utcnow(), rule_id, *params),
            )
            conn.commit()
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM custom_rules WHERE rule_id = ?", (rule_id,)
            ).fetchone()
        return _row_to_rule(row, config_as_json=True)

    def delete_rule(self, rule_id: str, user_id: int | None) -> bool:
        with self._connect() as conn:
            scope, params = self._scope(user_id)
            changed = conn.execute(
                f"DELETE FROM custom_rules WHERE rule_id = ?{scope}", (rule_id, *params)
            ).rowcount
            conn.commit()
        return changed > 0


# ---------------------------------------------------------------------------
# Postgres -- alongside the warehouse catalog
# ---------------------------------------------------------------------------


class PostgresCustomRuleStore:
    """Custom rules in the Postgres catalog.

    The driver is imported inside the methods that need it, never at module
    scope: the demo path must keep working with no database drivers installed
    at all.
    """

    name = "warehouse"

    _COLUMNS = "rule_id, user_id, name, slug, template, config, created_at, updated_at"

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
    def _scope(user_id: int | None) -> tuple[str, list]:
        if user_id is None:
            return "", []
        return " AND (user_id IS NULL OR user_id = %s)", [user_id]

    def create_rule(
        self, user_id: int | None, name: str, template: str, config: dict
    ) -> dict:
        import json

        with self._connect() as conn:
            scope, params = self._scope(user_id)
            existing = {
                row[0]
                for row in conn.execute(
                    f"SELECT slug FROM custom_rules WHERE 1=1{scope}", params
                ).fetchall()
            }
            slug = _unique_slug(existing, slugify(name))
            now = datetime.now(UTC)
            rule_id = uuid.uuid4().hex
            conn.execute(
                f"INSERT INTO custom_rules ({self._COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    rule_id,
                    user_id,
                    name,
                    slug,
                    template,
                    json.dumps(config, sort_keys=True),
                    now,
                    now,
                ),
            )
            conn.commit()
        return {
            "rule_id": rule_id,
            "user_id": user_id,
            "name": name,
            "slug": slug,
            "template": template,
            "config": config,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    def get_rule(self, rule_id: str, user_id: int | None = None) -> dict | None:
        scope, params = self._scope(user_id)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM custom_rules WHERE rule_id = %s{scope}",
                (rule_id, *params),
            ).fetchone()
        if row is None:
            return None
        rule = _row_to_rule(row, config_as_json=False)
        rule["created_at"] = row[6].isoformat()
        rule["updated_at"] = row[7].isoformat()
        return rule

    def list_rules(self, user_id: int | None = None) -> dict:
        scope, params = self._scope(user_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._COLUMNS} FROM custom_rules WHERE 1=1{scope} "
                "ORDER BY created_at, rule_id",
                params,
            ).fetchall()
        items = []
        for row in rows:
            rule = _row_to_rule(row, config_as_json=False)
            rule["created_at"] = row[6].isoformat()
            rule["updated_at"] = row[7].isoformat()
            items.append(rule)
        return {"total": len(items), "items": items}

    def update_rule(
        self,
        rule_id: str,
        user_id: int | None,
        *,
        name: str | None = None,
        config: dict | None = None,
    ) -> dict | None:
        import json

        existing = self.get_rule(rule_id, user_id)
        if existing is None:
            return None
        new_name = name if name is not None else existing["name"]
        new_config = config if config is not None else existing["config"]
        slug = existing["slug"]
        scope, params = self._scope(user_id)
        with self._connect() as conn:
            if name is not None and name != existing["name"]:
                others = {
                    row[0]
                    for row in conn.execute(
                        f"SELECT slug FROM custom_rules WHERE 1=1{scope}", params
                    ).fetchall()
                } - {existing["slug"]}
                slug = _unique_slug(others, slugify(new_name))
            conn.execute(
                "UPDATE custom_rules SET name = %s, slug = %s, config = %s, updated_at = %s "
                f"WHERE rule_id = %s{scope}",
                (
                    new_name,
                    slug,
                    json.dumps(new_config, sort_keys=True),
                    datetime.now(UTC),
                    rule_id,
                    *params,
                ),
            )
            conn.commit()
        return self.get_rule(rule_id, user_id)

    def delete_rule(self, rule_id: str, user_id: int | None) -> bool:
        scope, params = self._scope(user_id)
        with self._connect() as conn:
            changed = conn.execute(
                f"DELETE FROM custom_rules WHERE rule_id = %s{scope}", (rule_id, *params)
            ).rowcount
            conn.commit()
        return changed > 0


def select_custom_rule_store(db_path: str | Path | None = None) -> CustomRuleStore:
    """Mirror ``select_backend``: the warehouse when configured, else the demo."""
    from quantlab.storage import warehouse

    if warehouse.configured():
        return PostgresCustomRuleStore()
    return SqliteCustomRuleStore(db_path or "/data/quantlab.db")


__all__ = [
    "CustomRuleStore",
    "PostgresCustomRuleStore",
    "SqliteCustomRuleStore",
    "select_custom_rule_store",
    "slugify",
]
