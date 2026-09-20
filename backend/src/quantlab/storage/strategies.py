"""Saved strategies, scoped to their owner.

Every method takes ``owner_id`` and filters on it. That is deliberately not a
convenience the caller may skip: a store whose ``get`` can be called without an
owner is one query away from serving somebody else's work, and the type system
will not stop that. A row belonging to another user reads as absent, so the API
answers 404 rather than 403 -- a 403 confirms the row exists, which is itself
information the caller has not earned.

The spec is stored as canonical JSON rather than shredded into columns. It is
validated by :class:`~quantlab.strategy.StrategySpec` on the way in and again on
the way out, its shape is owned by that module, and a schema migration for every
new execution setting would be a tax on all of them.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from quantlab.storage import db
from quantlab.storage.db import canonical_json
from quantlab.strategy import StrategySpec


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SqliteStrategyStore:
    """Strategies in the same SQLite file as everything else."""

    name = "sqlite"

    _COLUMNS = "id, owner_id, name, description, spec, created_at, updated_at"

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)

    def _connect(self):
        conn = db.connect(self.db_path)
        db.bootstrap(conn)
        return conn

    @staticmethod
    def _row_to_strategy(row: tuple) -> dict:
        strategy_id, owner_id, name, description, spec, created_at, updated_at = row
        stored = json.loads(spec)
        # Name and description live in their own columns so they can be
        # indexed and searched; the spec is the authority for everything else.
        stored.update({"name": name, "description": description})
        return {
            "id": strategy_id,
            "owner_id": owner_id,
            "created_at": created_at,
            "updated_at": updated_at,
            **stored,
        }

    def create(self, owner_id: str, spec: StrategySpec) -> dict:
        strategy_id = uuid.uuid4().hex
        timestamp = _now()
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO strategies ({self._COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    strategy_id,
                    owner_id,
                    spec.name,
                    spec.description,
                    canonical_json(spec.to_dict()),
                    timestamp,
                    timestamp,
                ),
            )
            conn.commit()
        return self.get(owner_id, strategy_id)  # type: ignore[return-value]

    def get(self, owner_id: str, strategy_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM strategies WHERE id = ? AND owner_id = ?",
                (strategy_id, owner_id),
            ).fetchone()
        return self._row_to_strategy(row) if row else None

    def list(self, owner_id: str) -> dict:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._COLUMNS} FROM strategies WHERE owner_id = ? "
                f"ORDER BY updated_at DESC, id DESC",
                (owner_id,),
            ).fetchall()
        return {"total": len(rows), "items": [self._row_to_strategy(row) for row in rows]}

    def replace(self, owner_id: str, strategy_id: str, spec: StrategySpec) -> dict | None:
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE strategies SET name = ?, description = ?, spec = ?, updated_at = ? "
                "WHERE id = ? AND owner_id = ?",
                (
                    spec.name,
                    spec.description,
                    canonical_json(spec.to_dict()),
                    _now(),
                    strategy_id,
                    owner_id,
                ),
            ).rowcount
            conn.commit()
        return self.get(owner_id, strategy_id) if changed else None

    def delete(self, owner_id: str, strategy_id: str) -> bool:
        with self._connect() as conn:
            changed = conn.execute(
                "DELETE FROM strategies WHERE id = ? AND owner_id = ?",
                (strategy_id, owner_id),
            ).rowcount
            conn.commit()
        return changed > 0


def select_strategy_store(db_path: str | Path | None = None) -> SqliteStrategyStore:
    return SqliteStrategyStore(db_path or "/data/quantlab.db")


__all__ = ["SqliteStrategyStore", "select_strategy_store"]
