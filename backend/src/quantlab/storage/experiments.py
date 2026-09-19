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
    """What the workbench is allowed to ask of experiment persistence."""

    name: str

    def save_run(self, result: Any) -> None: ...
    def get_run(self, run_id: str) -> dict | None: ...
    def get_run_signals(self, run_id: str) -> list[dict]: ...
    def list_runs(self, saved_only: bool = False) -> dict: ...
    def set_run_name(self, run_id: str, name: str) -> bool: ...
    def delete_run(self, run_id: str) -> bool: ...


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
        "ingest_run_ids"
    )

    @staticmethod
    def _row_to_run(row: tuple) -> dict:
        (
            run_id, name, model_name, model_version, parameters, symbols, start_date,
            end_date, status, error, created_at, signal_count, requested, with_data,
            full_warmup, dataset, instrument_ids, ingest_run_ids,
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
        }

    def save_run(self, result: Any) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT INTO experiment_runs ({self._COLUMNS}) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

    def get_run(self, run_id: str) -> dict | None:
        with db.connect(self.db_path) as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return self._row_to_run(row) if row else None

    def get_run_signals(self, run_id: str) -> list[dict]:
        with db.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT symbol, date, direction, trigger_values, data_window_end "
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
            }
            for symbol, date, direction, trigger_values, data_window_end in rows
        ]

    def list_runs(self, saved_only: bool = False) -> dict:
        where = "WHERE name IS NOT NULL" if saved_only else ""
        with db.connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs {where} "
                f"ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return {"total": len(rows), "items": [self._row_to_run(row) for row in rows]}

    def set_run_name(self, run_id: str, name: str) -> bool:
        with db.connect(self.db_path) as conn:
            changed = conn.execute(
                "UPDATE experiment_runs SET name = ? WHERE id = ?", (name, run_id)
            ).rowcount
            conn.commit()
        return changed > 0

    def delete_run(self, run_id: str) -> bool:
        with db.connect(self.db_path) as conn:
            # Explicit child delete: SQLite enforces ON DELETE CASCADE only when
            # the foreign_keys pragma is on, which is not guaranteed here.
            conn.execute("DELETE FROM experiment_signals WHERE run_id = ?", (run_id,))
            changed = conn.execute(
                "DELETE FROM experiment_runs WHERE id = ?", (run_id,)
            ).rowcount
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
        "ingest_run_ids, dataset, start_date, end_date, status, error, created_at, "
        "signal_count, instruments_requested, instruments_with_data, instruments_full_warmup"
    )

    @staticmethod
    def _row_to_run(row: tuple) -> dict:
        (
            run_id, name, model_name, model_version, parameters, symbols, instrument_ids,
            ingest_run_ids, dataset, start_date, end_date, status, error, created_at,
            signal_count, requested, with_data, full_warmup,
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
            "dataset": dataset,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "status": status,
            "error": error,
            "created_at": created_at.isoformat(),
            "signal_count": signal_count,
            "coverage": _coverage(requested, with_data, full_warmup),
        }

    def save_run(self, result: Any) -> None:
        instrument_ids = getattr(result, "instrument_ids", None)
        by_symbol = (
            dict(zip(result.symbols, instrument_ids, strict=False)) if instrument_ids else {}
        )
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO experiment_runs ({self._COLUMNS}) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    result.id,
                    result.name,
                    result.model_name,
                    result.model_version,
                    json.dumps(result.parameters, sort_keys=True),
                    json.dumps(result.symbols),
                    json.dumps(instrument_ids) if instrument_ids else None,
                    json.dumps(getattr(result, "ingest_run_ids", None) or []) or None,
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

    def get_run(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs WHERE run_id = %s", (run_id,)
            ).fetchone()
        return self._row_to_run(row) if row else None

    def get_run_signals(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol, date, direction, trigger_values, data_window_end "
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
            }
            for symbol, date, direction, trigger_values, data_window_end in rows
        ]

    def list_runs(self, saved_only: bool = False) -> dict:
        where = "WHERE name IS NOT NULL" if saved_only else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._COLUMNS} FROM experiment_runs {where} "
                f"ORDER BY created_at DESC, run_id DESC"
            ).fetchall()
        return {"total": len(rows), "items": [self._row_to_run(row) for row in rows]}

    def set_run_name(self, run_id: str, name: str) -> bool:
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE experiment_runs SET name = %s WHERE run_id = %s", (name, run_id)
            ).rowcount
            conn.commit()
        return changed > 0

    def delete_run(self, run_id: str) -> bool:
        with self._connect() as conn:
            # experiment_signals cascades from the run's foreign key.
            changed = conn.execute(
                "DELETE FROM experiment_runs WHERE run_id = %s", (run_id,)
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

