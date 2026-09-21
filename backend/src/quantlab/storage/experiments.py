"""Where experiment runs live.

Deliberately a separate seam from :mod:`quantlab.storage.backends`. "Which
dataset am I reading?" and "where do my experiments live?" are different
questions with different lifetimes, and on the warehouse they are different
database systems -- bars in ClickHouse, runs in Postgres. Keeping them apart is
what lets experiment persistence be tested without any bar store, and lets a
future dataset be added without also implementing run storage.

Both adapters satisfy one contract, so a saved experiment means the same thing
whichever store is configured.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from quantlab.storage import db
from quantlab.storage.db import canonical_json


class ExperimentStore(Protocol):
    """What the workbench is allowed to ask of experiment persistence.

    Every read and mutation takes an optional ``user_id`` (feature 007):
    passing one scopes the call to runs that user owns plus pre-auth runs
    (``user_id IS NULL``), which stay visible to everyone. Passing None —
    what ``QUANTLAB_AUTH=off`` does — applies no scoping at all, preserving
    pre-auth behavior byte-for-byte.
    """

    name: str

    def save_run(self, result: Any, user_id: int | None = None) -> None: ...
    def get_run(self, run_id: str, user_id: int | None = None) -> dict | None: ...
    def get_run_signals(self, run_id: str, user_id: int | None = None) -> list[dict]: ...
    def list_runs(self, saved_only: bool = False, user_id: int | None = None) -> dict: ...
    def set_run_name(self, run_id: str, name: str, user_id: int | None = None) -> bool: ...
    def delete_run(self, run_id: str, user_id: int | None = None) -> bool: ...


def _json_or_none(value: object) -> str | None:
    """Warehouse-only provenance: absent on the demo, stored as NULL."""
    return canonical_json(value) if value else None


def _coverage(requested: int, with_data: int, full_warmup: int) -> dict:
    return {
        "instruments_requested": requested,
        "instruments_with_data": with_data,
        "instruments_full_warmup": full_warmup,
    }


# ---------------------------------------------------------------------------
# SQLite -- the synthetic demo dataset
# ---------------------------------------------------------------------------


class SqliteExperimentStore:
    """Experiment storage in the demo's SQLite file, keyed by symbol."""

    name = "sqlite"

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)

    _COLUMNS = (
        "id, name, model_name, model_version, parameters, symbols, start_date, end_date, "
        "status, error, created_at, signal_count, instruments_requested, "
        "instruments_with_data, instruments_full_warmup, dataset, instrument_ids, "
        "ingest_run_ids, corporate_actions, execution, custom_rule"
    )

    @staticmethod
    def _row_to_run(row: tuple) -> dict:
        (
            run_id,
            name,
            model_name,
            model_version,
            parameters,
            symbols,
            start_date,
            end_date,
            status,
            error,
            created_at,
            signal_count,
            requested,
            with_data,
            full_warmup,
            dataset,
            instrument_ids,
            ingest_run_ids,
            actions,
            execution,
            custom_rule,
        ) = row
        return {
            "id": run_id,
            "name": name,
            "model_name": model_name,
            "model_version": model_version,
            "parameters": json.loads(parameters),
            "symbols": json.loads(symbols),
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
            "error": error,
            "created_at": created_at,
            "signal_count": signal_count,
            "coverage": _coverage(requested, with_data, full_warmup),
            "dataset": dataset or "sqlite",
            "instrument_ids": json.loads(instrument_ids) if instrument_ids else None,
            "ingest_run_ids": json.loads(ingest_run_ids) if ingest_run_ids else None,
            "corporate_actions": json.loads(actions) if actions else [],
            "execution": json.loads(execution) if execution else None,
            # Snapshot of the custom rule's definition at run time (feature
            # 008); NULL for builtin-model runs.
            "custom_rule": json.loads(custom_rule) if custom_rule else None,
        }

    def save_run(self, result: Any, user_id: int | None = None) -> None:
        with db.connect(self.db_path) as conn:
            # save_run always writes these columns, so make sure they exist
            # even on a database seeded before they did.
            db.ensure_column(conn, "experiment_runs", "user_id INTEGER")
            db.ensure_column(conn, "experiment_runs", "custom_rule TEXT")
            conn.execute(
                f"INSERT INTO experiment_runs ({self._COLUMNS}, user_id) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.id,
                    result.name,
                    result.model_name,
                    result.model_version,
                    canonical_json(result.parameters),
                    canonical_json(result.symbols),
                    result.start_date,
                    result.end_date,
                    result.status,
                    result.error,
                    result.created_at,
                    result.signal_count,
                    result.coverage.instruments_requested,
                    result.coverage.instruments_with_data,
                    result.coverage.instruments_full_warmup,
                    getattr(result, "dataset", "sqlite"),
                    _json_or_none(getattr(result, "instrument_ids", None)),
                    _json_or_none(getattr(result, "ingest_run_ids", None)),
                    _json_or_none(getattr(result, "corporate_actions", None)),
                    _json_or_none(getattr(result, "execution", None)),
                    _json_or_none(getattr(result, "custom_rule", None)),
                    user_id,
                ),
            )
            conn.executemany(
                "INSERT INTO experiment_signals "
                "(run_id, symbol, date, direction, trigger_values, data_window_end) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        result.id,
                        s.symbol,
                        s.date,
                        s.direction,
                        canonical_json(s.trigger_values),
                        s.data_window_end,
                    )
                    for s in result.signals
                ],
            )
            conn.commit()

    def _scoped(self, conn, user_id: int | None, placeholder: str = "?") -> tuple[str, list]:
        """``AND (user_id IS NULL OR user_id = ?)`` — own runs plus pre-auth
        (NULL-owned) runs — or no clause at all when unscoped."""
        if user_id is None:
            return "", []
        db.ensure_column(conn, "experiment_runs", "user_id INTEGER")
        return f" AND (user_id IS NULL OR user_id = {placeholder})", [user_id]

    def get_run(self, run_id: str, user_id: int | None = None) -> dict | None:
        with db.connect(self.db_path) as conn:
            db.ensure_column(conn, "experiment_runs", "custom_rule TEXT")
            scope, params = self._scoped(conn, user_id)
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs WHERE id = ?{scope}",
                (run_id, *params),
            ).fetchone()
        return self._row_to_run(row) if row else None

    def get_run_signals(self, run_id: str, user_id: int | None = None) -> list[dict]:
        with db.connect(self.db_path) as conn:
            scope, params = self._scoped(conn, user_id)
            if scope:
                scope = " AND run_id IN (SELECT id FROM experiment_runs WHERE 1=1" + scope + ")"
            rows = conn.execute(
                "SELECT symbol, date, direction, trigger_values, data_window_end "
                f"FROM experiment_signals WHERE run_id = ?{scope} ORDER BY symbol, date",
                (run_id, *params),
            ).fetchall()
        return [
            {
                "symbol": symbol,
                "date": date,
                "direction": direction,
                "trigger_values": json.loads(trigger_values),
                "data_window_end": data_window_end,
            }
            for symbol, date, direction, trigger_values, data_window_end in rows
        ]

    def list_runs(self, saved_only: bool = False, user_id: int | None = None) -> dict:
        with db.connect(self.db_path) as conn:
            db.ensure_column(conn, "experiment_runs", "custom_rule TEXT")
            scope, params = self._scoped(conn, user_id)
            where = "WHERE name IS NOT NULL" if saved_only else ""
            if scope:
                where = f"WHERE 1=1{scope}" if not where else where + scope
            rows = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs {where} "
                f"ORDER BY created_at DESC, id DESC",
                params,
            ).fetchall()
        return {"total": len(rows), "items": [self._row_to_run(row) for row in rows]}

    def set_run_name(self, run_id: str, name: str, user_id: int | None = None) -> bool:
        with db.connect(self.db_path) as conn:
            scope, params = self._scoped(conn, user_id)
            changed = conn.execute(
                f"UPDATE experiment_runs SET name = ? WHERE id = ?{scope}",
                (name, run_id, *params),
            ).rowcount
            conn.commit()
        return changed > 0

    def delete_run(self, run_id: str, user_id: int | None = None) -> bool:
        with db.connect(self.db_path) as conn:
            scope, params = self._scoped(conn, user_id)
            # Parent first, so the scope clause decides whether anything is
            # deleted at all. The explicit child delete then covers the case
            # where the foreign_keys pragma is off: SQLite enforces
            # ON DELETE CASCADE only when it is on.
            changed = conn.execute(
                f"DELETE FROM experiment_runs WHERE id = ?{scope}",
                (run_id, *params),
            ).rowcount
            if changed:
                conn.execute("DELETE FROM experiment_signals WHERE run_id = ?", (run_id,))
            conn.commit()
        return changed > 0


# ---------------------------------------------------------------------------
# Postgres -- alongside the warehouse catalog
# ---------------------------------------------------------------------------


class PostgresExperimentStore:
    """Experiment storage in the Postgres catalog, keyed by instrument_id.

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

    _COLUMNS = (
        "run_id, name, model_name, model_version, parameters, symbols, instrument_ids, "
        "ingest_run_ids, corporate_actions, dataset, start_date, end_date, status, "
        "error, created_at, "
        "signal_count, instruments_requested, instruments_with_data, instruments_full_warmup, "
        "execution, custom_rule"
    )

    @staticmethod
    def _row_to_run(row: tuple) -> dict:
        (
            run_id,
            name,
            model_name,
            model_version,
            parameters,
            symbols,
            instrument_ids,
            ingest_run_ids,
            actions,
            dataset,
            start_date,
            end_date,
            status,
            error,
            created_at,
            signal_count,
            requested,
            with_data,
            full_warmup,
            execution,
            custom_rule,
        ) = row
        return {
            "id": run_id,
            "name": name,
            "model_name": model_name,
            "model_version": model_version,
            "parameters": parameters,
            "symbols": symbols,
            "instrument_ids": instrument_ids,
            "ingest_run_ids": ingest_run_ids,
            "corporate_actions": actions or [],
            "dataset": dataset,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "status": status,
            "error": error,
            "created_at": created_at.isoformat(),
            "signal_count": signal_count,
            "coverage": _coverage(requested, with_data, full_warmup),
            "execution": execution,
            "custom_rule": custom_rule,
        }

    def save_run(self, result: Any, user_id: int | None = None) -> None:
        instrument_ids = getattr(result, "instrument_ids", None)
        by_symbol = (
            dict(zip(result.symbols, instrument_ids, strict=False)) if instrument_ids else {}
        )
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO experiment_runs ({self._COLUMNS}, user_id) "
                "VALUES (" + ", ".join(["%s"] * 22) + ")",
                (
                    result.id,
                    result.name,
                    result.model_name,
                    result.model_version,
                    json.dumps(result.parameters, sort_keys=True),
                    json.dumps(result.symbols),
                    json.dumps(instrument_ids) if instrument_ids else None,
                    json.dumps(getattr(result, "ingest_run_ids", None) or []) or None,
                    json.dumps(getattr(result, "corporate_actions", []) or []),
                    getattr(result, "dataset", "warehouse"),
                    result.start_date,
                    result.end_date,
                    result.status,
                    result.error,
                    result.created_at,
                    result.signal_count,
                    result.coverage.instruments_requested,
                    result.coverage.instruments_with_data,
                    result.coverage.instruments_full_warmup,
                    (
                        json.dumps(result.execution, sort_keys=True)
                        if getattr(result, "execution", None)
                        else None
                    ),
                    (
                        json.dumps(result.custom_rule, sort_keys=True)
                        if getattr(result, "custom_rule", None)
                        else None
                    ),
                    user_id,
                ),
            )
            conn.cursor().executemany(
                "INSERT INTO experiment_signals "
                "(run_id, instrument_id, symbol, date, direction, trigger_values, data_window_end) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        result.id,
                        by_symbol.get(s.symbol),
                        s.symbol,
                        s.date,
                        s.direction,
                        json.dumps(s.trigger_values, sort_keys=True),
                        s.data_window_end,
                    )
                    for s in result.signals
                ],
            )
            conn.commit()

    @staticmethod
    def _scoped(user_id: int | None) -> tuple[str, list]:
        """``AND (user_id IS NULL OR user_id = %s)`` — own runs plus pre-auth
        (NULL-owned) runs — or no clause at all when unscoped."""
        if user_id is None:
            return "", []
        return " AND (user_id IS NULL OR user_id = %s)", [user_id]

    def get_run(self, run_id: str, user_id: int | None = None) -> dict | None:
        scope, params = self._scoped(user_id)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs WHERE run_id = %s{scope}",
                (run_id, *params),
            ).fetchone()
        return self._row_to_run(row) if row else None

    def get_run_signals(self, run_id: str, user_id: int | None = None) -> list[dict]:
        scope, params = self._scoped(user_id)
        if scope:
            scope = " AND run_id IN (SELECT run_id FROM experiment_runs WHERE 1=1" + scope + ")"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol, date, direction, trigger_values, data_window_end "
                f"FROM experiment_signals WHERE run_id = %s{scope} ORDER BY symbol, date",
                (run_id, *params),
            ).fetchall()
        return [
            {
                "symbol": symbol,
                "date": date.isoformat(),
                "direction": direction,
                "trigger_values": trigger_values,
                "data_window_end": data_window_end.isoformat(),
            }
            for symbol, date, direction, trigger_values, data_window_end in rows
        ]

    def list_runs(self, saved_only: bool = False, user_id: int | None = None) -> dict:
        scope, params = self._scoped(user_id)
        where = "WHERE name IS NOT NULL" if saved_only else ""
        if scope:
            where = f"WHERE 1=1{scope}" if not where else where + scope
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs {where} "
                f"ORDER BY created_at DESC, run_id DESC",
                params,
            ).fetchall()
        return {"total": len(rows), "items": [self._row_to_run(row) for row in rows]}

    def set_run_name(self, run_id: str, name: str, user_id: int | None = None) -> bool:
        scope, params = self._scoped(user_id)
        with self._connect() as conn:
            changed = conn.execute(
                f"UPDATE experiment_runs SET name = %s WHERE run_id = %s{scope}",
                (name, run_id, *params),
            ).rowcount
            conn.commit()
        return changed > 0

    def delete_run(self, run_id: str, user_id: int | None = None) -> bool:
        scope, params = self._scoped(user_id)
        with self._connect() as conn:
            # experiment_signals cascades from the run's foreign key.
            changed = conn.execute(
                f"DELETE FROM experiment_runs WHERE run_id = %s{scope}",
                (run_id, *params),
            ).rowcount
            conn.commit()
        return changed > 0


def select_experiment_store(db_path: str | Path | None = None) -> ExperimentStore:
    """Mirror ``select_backend``: the warehouse when configured, else the demo."""
    from quantlab.storage import warehouse

    if warehouse.configured():
        return PostgresExperimentStore()
    return SqliteExperimentStore(db_path or "/data/quantlab.db")


__all__ = [
    "ExperimentStore",
    "PostgresExperimentStore",
    "SqliteExperimentStore",
    "select_experiment_store",
]
