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
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from quantlab.storage import db
from quantlab.storage.db import canonical_json

if TYPE_CHECKING:
    from quantlab.storage import warehouse


class ExperimentStore(Protocol):
    """What the workbench is allowed to ask of experiment persistence."""

    name: str

    def save_run(self, result: Any) -> None: ...
    def get_run(self, run_id: str, owner_id: str | None = None) -> dict | None: ...
    def get_run_signals(self, run_id: str) -> list[dict]: ...
    def list_runs(self, saved_only: bool = False, owner_id: str | None = None) -> dict: ...
    def set_run_name(self, run_id: str, name: str, owner_id: str | None = None) -> bool: ...
    def delete_run(self, run_id: str, owner_id: str | None = None) -> bool: ...


def _json_or_none(value: object) -> str | None:
    """Warehouse-only provenance: absent on the demo, stored as NULL."""
    return canonical_json(value) if value else None


def _pg_json(value: object) -> str | None:
    """A JSONB column value, or NULL. Kept separate from _json_or_none so the
    two stores' encodings stay independently changeable."""
    return json.dumps(value, sort_keys=True) if value else None


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
        "ingest_run_ids, corporate_actions, owner_id, strategy, execution, execution_summary"
    )

    @staticmethod
    def _row_to_run(row: tuple) -> dict:
        (
            run_id, name, model_name, model_version, parameters, symbols, start_date,
            end_date, status, error, created_at, signal_count, requested, with_data,
            full_warmup, dataset, instrument_ids, ingest_run_ids, actions, owner_id,
            strategy, execution, execution_summary,
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
            "owner_id": owner_id,
            # Null on runs recorded before strategies and execution criteria
            # existed. The API reports them as such rather than inventing a
            # spec those runs never had.
            "strategy": json.loads(strategy) if strategy else None,
            "execution": json.loads(execution) if execution else None,
            "execution_summary": (
                json.loads(execution_summary) if execution_summary else None
            ),
        }

    def save_run(self, result: Any) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT INTO experiment_runs ({self._COLUMNS}) "
                f"VALUES ({', '.join(['?'] * 23)})",
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
                    getattr(result, "owner_id", None),
                    _json_or_none(getattr(result, "strategy", None)),
                    _json_or_none(getattr(result, "execution", None)),
                    _json_or_none(getattr(result, "execution_summary", None)),
                ),
            )
            conn.executemany(
                "INSERT INTO experiment_signals "
                "(run_id, symbol, date, kind, direction, trigger_values, data_window_end) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        result.id,
                        s.symbol,
                        s.date,
                        getattr(s, "kind", "both"),
                        s.direction,
                        canonical_json(s.trigger_values),
                        s.data_window_end,
                    )
                    for s in result.signals
                ],
            )
            conn.commit()

    @staticmethod
    def _scope(owner_id: str | None, prefix: str = "WHERE") -> tuple[str, tuple]:
        """The ownership filter, or nothing in single-user mode.

        Applied in SQL rather than by filtering afterwards: a row that is not
        the caller's must never be loaded at all, let alone loaded and then
        dropped by a check somebody can forget to write.
        """
        if owner_id is None:
            return "", ()
        return f"{prefix} owner_id = ?", (owner_id,)

    def get_run(self, run_id: str, owner_id: str | None = None) -> dict | None:
        scope, params = self._scope(owner_id, "AND")
        with db.connect(self.db_path) as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs WHERE id = ? {scope}",
                (run_id, *params),
            ).fetchone()
        return self._row_to_run(row) if row else None

    def get_run_signals(self, run_id: str) -> list[dict]:
        with db.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT symbol, date, direction, trigger_values, data_window_end, kind "
                "FROM experiment_signals WHERE run_id = ? ORDER BY symbol, date",
                (run_id,),
            ).fetchall()
        return [
            {
                "symbol": symbol,
                "date": date,
                "direction": direction,
                "trigger_values": json.loads(trigger_values),
                "data_window_end": data_window_end,
                # Rows written before strategies existed have no kind; they came
                # from a single-model run, where one rule both opened and closed.
                "kind": kind or "both",
            }
            for symbol, date, direction, trigger_values, data_window_end, kind in rows
        ]

    def list_runs(self, saved_only: bool = False, owner_id: str | None = None) -> dict:
        clauses, params = [], []
        if saved_only:
            clauses.append("name IS NOT NULL")
        if owner_id is not None:
            clauses.append("owner_id = ?")
            params.append(owner_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with db.connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs {where} "
                f"ORDER BY created_at DESC, id DESC",
                tuple(params),
            ).fetchall()
        return {"total": len(rows), "items": [self._row_to_run(row) for row in rows]}

    def set_run_name(self, run_id: str, name: str, owner_id: str | None = None) -> bool:
        scope, params = self._scope(owner_id, "AND")
        with db.connect(self.db_path) as conn:
            changed = conn.execute(
                f"UPDATE experiment_runs SET name = ? WHERE id = ? {scope}",
                (name, run_id, *params),
            ).rowcount
            conn.commit()
        return changed > 0

    def delete_run(self, run_id: str, owner_id: str | None = None) -> bool:
        scope, params = self._scope(owner_id, "AND")
        with db.connect(self.db_path) as conn:
            # The run row goes first and its rowcount is what decides the
            # answer, so a delete scoped to the wrong owner removes nothing. A
            # child-first delete would already have destroyed the signals before
            # discovering the run was not the caller's to delete.
            changed = conn.execute(
                f"DELETE FROM experiment_runs WHERE id = ? {scope}", (run_id, *params)
            ).rowcount
            if changed:
                # Explicit child delete: SQLite enforces ON DELETE CASCADE only
                # when the foreign_keys pragma is on, which is not guaranteed.
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

    def __init__(self, dsn: str = "", wh: warehouse.Warehouse | None = None) -> None:
        self._dsn = dsn
        self._wh = wh
        self._pool: Any = None
        self._lock = threading.Lock()

    def _resolve_dsn(self) -> str:
        import os

        dsn = self._dsn or os.environ.get("QUANTLAB_DB_URL", "")
        if not dsn:
            raise RuntimeError(
                "no Postgres DSN for the experiment store: pass dsn=... or set "
                "QUANTLAB_DB_URL (there is deliberately no built-in default -- "
                "silently falling back to hardcoded credentials would look "
                "configured while pointing at whoever owns that database)"
            )
        return dsn

    def _ensure_pool(self):
        # Mirrors Warehouse._ensure_catalog_pool exactly; used only when no
        # warehouse was handed in, i.e. tests and tooling without an app.
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    try:
                        from psycopg_pool import ConnectionPool
                    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
                        raise RuntimeError(
                            "psycopg is not installed. Install the warehouse extras:\n"
                            "    pip install 'quantlab[store]'"
                        ) from exc
                    from quantlab.storage.pool import pool_config

                    config = pool_config()
                    self._pool = ConnectionPool(
                        self._resolve_dsn(),
                        min_size=0,
                        max_size=config.pg_max,
                        timeout=config.timeout,
                        check=ConnectionPool.check_connection,
                        open=False,
                    )
                    self._pool.open()
        return self._pool

    @contextmanager
    def _connect(self):
        """A catalog connection: the warehouse's pool when attached, else ours."""
        if self._wh is not None:
            with self._wh.catalog() as conn:
                yield conn
            return
        with self._ensure_pool().connection() as conn:
            yield conn

    def close(self) -> None:
        """Release this store's own pool. Idempotent.

        A borrowed warehouse pool is the warehouse's to close, not ours.
        """
        with self._lock:
            if self._pool is not None:
                self._pool.close()
                self._pool = None

    _COLUMNS = (
        "run_id, name, model_name, model_version, parameters, symbols, instrument_ids, "
        "ingest_run_ids, corporate_actions, dataset, start_date, end_date, status, "
        "error, created_at, "
        "signal_count, instruments_requested, instruments_with_data, instruments_full_warmup, "
        "owner_id, strategy, execution, execution_summary"
    )

    @staticmethod
    def _row_to_run(row: tuple) -> dict:
        (
            run_id, name, model_name, model_version, parameters, symbols, instrument_ids,
            ingest_run_ids, actions, dataset, start_date, end_date, status, error,
            created_at, signal_count, requested, with_data, full_warmup, owner_id,
            strategy, execution, execution_summary,
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
            "owner_id": owner_id,
            "strategy": strategy,
            "execution": execution,
            "execution_summary": execution_summary,
        }

    def save_run(self, result: Any) -> None:
        instrument_ids = getattr(result, "instrument_ids", None)
        by_symbol = (
            dict(zip(result.symbols, instrument_ids, strict=False)) if instrument_ids else {}
        )
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO experiment_runs ({self._COLUMNS}) "
                "VALUES (" + ", ".join(["%s"] * 23) + ")",
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
                    getattr(result, "owner_id", None),
                    _pg_json(getattr(result, "strategy", None)),
                    _pg_json(getattr(result, "execution", None)),
                    _pg_json(getattr(result, "execution_summary", None)),
                ),
            )
            conn.cursor().executemany(
                "INSERT INTO experiment_signals (run_id, instrument_id, symbol, date, kind, "
                "direction, trigger_values, data_window_end) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        result.id,
                        by_symbol.get(s.symbol),
                        s.symbol,
                        s.date,
                        getattr(s, "kind", "both"),
                        s.direction,
                        json.dumps(s.trigger_values, sort_keys=True),
                        s.data_window_end,
                    )
                    for s in result.signals
                ],
            )
            conn.commit()

    @staticmethod
    def _scope(owner_id: str | None, prefix: str = "WHERE") -> tuple[str, tuple]:
        """The ownership filter, or nothing in single-user mode."""
        if owner_id is None:
            return "", ()
        return f"{prefix} owner_id = %s", (owner_id,)

    def get_run(self, run_id: str, owner_id: str | None = None) -> dict | None:
        scope, params = self._scope(owner_id, "AND")
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs WHERE run_id = %s {scope}",
                (run_id, *params),
            ).fetchone()
        return self._row_to_run(row) if row else None

    def get_run_signals(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol, date, direction, trigger_values, data_window_end, kind "
                "FROM experiment_signals WHERE run_id = %s ORDER BY symbol, date",
                (run_id,),
            ).fetchall()
        return [
            {
                "symbol": symbol,
                "date": date.isoformat(),
                "direction": direction,
                "trigger_values": trigger_values,
                "data_window_end": data_window_end.isoformat(),
                "kind": kind or "both",
            }
            for symbol, date, direction, trigger_values, data_window_end, kind in rows
        ]

    def list_runs(self, saved_only: bool = False, owner_id: str | None = None) -> dict:
        clauses, params = [], []
        if saved_only:
            clauses.append("name IS NOT NULL")
        if owner_id is not None:
            clauses.append("owner_id = %s")
            params.append(owner_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs {where} "
                f"ORDER BY created_at DESC, run_id DESC",
                tuple(params),
            ).fetchall()
        return {"total": len(rows), "items": [self._row_to_run(row) for row in rows]}

    def set_run_name(self, run_id: str, name: str, owner_id: str | None = None) -> bool:
        scope, params = self._scope(owner_id, "AND")
        with self._connect() as conn:
            changed = conn.execute(
                f"UPDATE experiment_runs SET name = %s WHERE run_id = %s {scope}",
                (name, run_id, *params),
            ).rowcount
            conn.commit()
        return changed > 0

    def delete_run(self, run_id: str, owner_id: str | None = None) -> bool:
        scope, params = self._scope(owner_id, "AND")
        with self._connect() as conn:
            # experiment_signals cascades from the run's foreign key.
            changed = conn.execute(
                f"DELETE FROM experiment_runs WHERE run_id = %s {scope}",
                (run_id, *params),
            ).rowcount
            conn.commit()
        return changed > 0


def select_experiment_store(
    db_path: str | Path | None = None, wh: warehouse.Warehouse | None = None
) -> ExperimentStore:
    """Mirror ``select_backend``: the warehouse when configured, else the demo.

    ``wh`` lets the app hand over its already-pooled warehouse so experiment
    queries share the catalog pool instead of opening a second one.
    """
    from quantlab.storage import warehouse

    if warehouse.configured():
        return PostgresExperimentStore(wh=wh)
    return SqliteExperimentStore(db_path or "/data/quantlab.db")


__all__ = [
    "ExperimentStore",
    "PostgresExperimentStore",
    "SqliteExperimentStore",
    "select_experiment_store",
]

