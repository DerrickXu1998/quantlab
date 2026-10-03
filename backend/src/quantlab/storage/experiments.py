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
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
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


def _coverage(
    requested: int, with_data: int, full_warmup: int, facts: dict | None = None
) -> dict:
    return {
        "instruments_requested": requested,
        "instruments_with_data": with_data,
        "instruments_full_warmup": full_warmup,
        # Null on runs whose rules read no fundamentals, and on every run
        # recorded before fact coverage was kept.
        "facts": facts,
    }


def _fact_coverage(result: Any) -> dict | None:
    """The run's fact coverage as a plain dict, for either store's JSON column."""
    facts = getattr(result.coverage, "facts", None)
    return asdict(facts) if facts is not None else None


#: The queue's columns, read with every run after the original 24.
_QUEUE_COLUMNS = (
    "estimated_bars, started_at, finished_at, error_category, attempts, cancel_requested, "
    "headline"
)


def _queue_fields(values: tuple, iso, parse=lambda value: value) -> dict:
    estimated_bars, started_at, finished_at, error_category, attempts, cancel, headline = values
    return {
        # performance.metrics, stored with the performance: the run list's
        # figures. Null until the run completes (or, for a run from before the
        # queue, until its performance is first read).
        "metrics": parse(headline) if headline else None,
        "estimated_bars": estimated_bars,
        "started_at": iso(started_at),
        "finished_at": iso(finished_at),
        "error_category": error_category,
        "attempts": attempts or 0,
        "cancel_requested": bool(cancel),
    }


def _headline(performance: dict | None) -> dict | None:
    return (performance or {}).get("metrics") or None


def _now(offset_seconds: float = 0) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=offset_seconds)


def _stamp(moment: datetime) -> str:
    """SQLite's timestamp text. One fixed format, so text order is time order."""
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


#: The message a run gets when the worker running it died and it has had all
#: its attempts. A deploy restarts the worker; an OOM kill is the other cause.
WORKER_LOST = (
    "the worker stopped while running this backtest (a restart, or it ran out of "
    "memory) and it has been tried {attempts} times; narrow the selection or try again"
)


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
        "ingest_run_ids, corporate_actions, owner_id, strategy, execution, execution_summary, "
        "fact_coverage"
    )

    _READ = f"{_COLUMNS}, {_QUEUE_COLUMNS}"

    @staticmethod
    def _row_to_run(row: tuple) -> dict:
        (
            run_id, name, model_name, model_version, parameters, symbols, start_date,
            end_date, status, error, created_at, signal_count, requested, with_data,
            full_warmup, dataset, instrument_ids, ingest_run_ids, actions, owner_id,
            strategy, execution, execution_summary, fact_coverage,
        ) = row[:24]
        return {
            **_queue_fields(row[24:], lambda value: value, json.loads),
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
            "coverage": _coverage(
                requested,
                with_data,
                full_warmup,
                json.loads(fact_coverage) if fact_coverage else None,
            ),
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
                f"VALUES ({', '.join(['?'] * 24)})",
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
                    _json_or_none(_fact_coverage(result)),
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
                f"SELECT {self._READ} FROM experiment_runs WHERE id = ? {scope}",
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
                f"SELECT {self._READ} FROM experiment_runs {where} "
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

    # --- The run queue --------------------------------------------------------

    def enqueue_run(self, record: dict) -> None:
        """Insert a queued run: identity, request and selection, no results."""
        with db.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO experiment_runs (id, name, model_name, model_version, parameters, "
                "symbols, start_date, end_date, status, created_at, signal_count, "
                "instruments_requested, instruments_with_data, instruments_full_warmup, "
                "dataset, owner_id, strategy, execution, request, estimated_bars) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, 0, ?, 0, 0, ?, ?, ?, ?, ?, ?)",
                (
                    record["id"],
                    record.get("name"),
                    record["model_name"],
                    record["model_version"],
                    canonical_json(record["parameters"]),
                    canonical_json(record["symbols"]),
                    record["start_date"],
                    record["end_date"],
                    _stamp(_now()),
                    len(record["symbols"]),
                    record.get("dataset", "sqlite"),
                    record.get("owner_id"),
                    _json_or_none(record.get("strategy")),
                    _json_or_none(record.get("execution")),
                    canonical_json(record["request"]),
                    record.get("estimated_bars"),
                ),
            )
            conn.commit()

    def claim_next_run(
        self, worker: str, lease_seconds: float, max_bars: int | None = None
    ) -> dict | None:
        """Take the oldest queued run (within ``max_bars``) and mark it running.

        BEGIN IMMEDIATE takes SQLite's write lock before the read, so two
        workers cannot both pick the same row.
        """
        size = "AND COALESCE(estimated_bars, 0) <= ?" if max_bars is not None else ""
        conn = db.connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT id, request, attempts, owner_id FROM experiment_runs "
                f"WHERE status = 'queued' {size} ORDER BY created_at, id LIMIT 1",
                (max_bars,) if max_bars is not None else (),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            run_id, request, attempts, owner_id = row
            now = _now()
            conn.execute(
                "UPDATE experiment_runs SET status = 'running', started_at = ?, worker = ?, "
                "lease_until = ?, attempts = attempts + 1 WHERE id = ?",
                (_stamp(now), worker, _stamp(now + timedelta(seconds=lease_seconds)), run_id),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()
        return {
            "id": run_id,
            "request": json.loads(request) if request else None,
            "attempts": (attempts or 0) + 1,
            "owner_id": owner_id,
        }

    def renew_lease(self, run_id: str, worker: str, lease_seconds: float) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE experiment_runs SET lease_until = ? "
                "WHERE id = ? AND worker = ? AND status = 'running'",
                (_stamp(_now(lease_seconds)), run_id, worker),
            )
            conn.commit()

    def cancel_requested(self, run_id: str) -> bool:
        with db.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM experiment_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return bool(row and row[0])

    def finish_run(self, result: Any, performance: dict | None) -> bool:
        """Write a running run's results. False if it was cancelled meanwhile,
        in which case nothing is written."""
        with db.connect(self.db_path) as conn:
            changed = conn.execute(
                "UPDATE experiment_runs SET status = ?, error = NULL, signal_count = ?, "
                "instruments_requested = ?, instruments_with_data = ?, "
                "instruments_full_warmup = ?, model_name = ?, model_version = ?, "
                "parameters = ?, symbols = ?, dataset = ?, instrument_ids = ?, "
                "ingest_run_ids = ?, corporate_actions = ?, strategy = ?, execution = ?, "
                "execution_summary = ?, fact_coverage = ?, performance = ?, headline = ?, "
                "finished_at = ?, lease_until = NULL "
                "WHERE id = ? AND status = 'running' AND cancel_requested = 0",
                (
                    result.status,
                    result.signal_count,
                    result.coverage.instruments_requested,
                    result.coverage.instruments_with_data,
                    result.coverage.instruments_full_warmup,
                    result.model_name,
                    result.model_version,
                    canonical_json(result.parameters),
                    canonical_json(result.symbols),
                    getattr(result, "dataset", "sqlite"),
                    _json_or_none(getattr(result, "instrument_ids", None)),
                    _json_or_none(getattr(result, "ingest_run_ids", None)),
                    _json_or_none(getattr(result, "corporate_actions", None)),
                    _json_or_none(getattr(result, "strategy", None)),
                    _json_or_none(getattr(result, "execution", None)),
                    _json_or_none(getattr(result, "execution_summary", None)),
                    _json_or_none(_fact_coverage(result)),
                    canonical_json(performance) if performance is not None else None,
                    _json_or_none(_headline(performance)),
                    _stamp(_now()),
                    result.id,
                ),
            ).rowcount
            if changed:
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
        return changed > 0

    def fail_run(self, run_id: str, error: str, category: str) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE experiment_runs SET status = 'failed', error = ?, error_category = ?, "
                "finished_at = ?, lease_until = NULL "
                "WHERE id = ? AND status IN ('queued', 'running')",
                (error, category, _stamp(_now()), run_id),
            )
            conn.commit()

    def mark_cancelled(self, run_id: str) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE experiment_runs SET status = 'cancelled', finished_at = ?, "
                "lease_until = NULL WHERE id = ? AND status IN ('queued', 'running')",
                (_stamp(_now()), run_id),
            )
            conn.commit()

    def cancel_run(self, run_id: str, owner_id: str | None = None) -> str | None:
        """Cancel a queued run now, or ask a running one to stop.

        Returns the run's status afterwards ('cancelled', or 'running' while the
        worker winds it down), or None if there is no such cancellable run.
        """
        scope, params = self._scope(owner_id, "AND")
        with db.connect(self.db_path) as conn:
            if conn.execute(
                f"UPDATE experiment_runs SET status = 'cancelled', finished_at = ? "
                f"WHERE id = ? AND status = 'queued' {scope}",
                (_stamp(_now()), run_id, *params),
            ).rowcount:
                conn.commit()
                return "cancelled"
            if conn.execute(
                f"UPDATE experiment_runs SET cancel_requested = 1 "
                f"WHERE id = ? AND status = 'running' {scope}",
                (run_id, *params),
            ).rowcount:
                conn.commit()
                return "running"
        return None

    def recover_stale_runs(self, max_attempts: int) -> dict[str, int]:
        """Runs whose worker stopped renewing its lease: queue them again, or
        fail them once they have had ``max_attempts``."""
        now = _stamp(_now())
        with db.connect(self.db_path) as conn:
            cancelled = conn.execute(
                "UPDATE experiment_runs SET status = 'cancelled', finished_at = ?, "
                "lease_until = NULL WHERE status = 'running' AND lease_until < ? "
                "AND cancel_requested = 1",
                (now, now),
            ).rowcount
            stale = conn.execute(
                "SELECT id, attempts FROM experiment_runs "
                "WHERE status = 'running' AND lease_until < ?",
                (now,),
            ).fetchall()
            requeued = failed = 0
            for run_id, attempts in stale:
                if (attempts or 0) >= max_attempts:
                    conn.execute(
                        "UPDATE experiment_runs SET status = 'failed', error = ?, "
                        "error_category = 'worker', finished_at = ?, lease_until = NULL "
                        "WHERE id = ?",
                        (WORKER_LOST.format(attempts=attempts), now, run_id),
                    )
                    failed += 1
                else:
                    conn.execute(
                        "UPDATE experiment_runs SET status = 'queued', worker = NULL, "
                        "lease_until = NULL, started_at = NULL WHERE id = ?",
                        (run_id,),
                    )
                    requeued += 1
            conn.commit()
        return {"requeued": requeued, "failed": failed, "cancelled": cancelled}

    def queued_run_ids(self) -> list[str]:
        """Every queued run, first in line first -- across owners, since they
        share one worker."""
        with db.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id FROM experiment_runs WHERE status = 'queued' ORDER BY created_at, id"
            ).fetchall()
        return [row[0] for row in rows]

    def get_performance(self, run_id: str) -> dict | None:
        with db.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT performance FROM experiment_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def set_performance(self, run_id: str, performance: dict) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE experiment_runs SET performance = ?, headline = ? WHERE id = ?",
                (canonical_json(performance), _json_or_none(_headline(performance)), run_id),
            )
            conn.commit()


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
        "owner_id, strategy, execution, execution_summary, fact_coverage"
    )

    _READ = f"{_COLUMNS}, {_QUEUE_COLUMNS}"

    @staticmethod
    def _row_to_run(row: tuple) -> dict:
        (
            run_id, name, model_name, model_version, parameters, symbols, instrument_ids,
            ingest_run_ids, actions, dataset, start_date, end_date, status, error,
            created_at, signal_count, requested, with_data, full_warmup, owner_id,
            strategy, execution, execution_summary, fact_coverage,
        ) = row[:24]
        return {
            **_queue_fields(row[24:], lambda value: value.isoformat() if value else None),
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
            "coverage": _coverage(requested, with_data, full_warmup, fact_coverage),
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
                "VALUES (" + ", ".join(["%s"] * 24) + ")",
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
                    _pg_json(_fact_coverage(result)),
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
                f"SELECT {self._READ} FROM experiment_runs WHERE run_id = %s {scope}",
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
                f"SELECT {self._READ} FROM experiment_runs {where} "
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

    # --- The run queue --------------------------------------------------------

    def enqueue_run(self, record: dict) -> None:
        """Insert a queued run: identity, request and selection, no results."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO experiment_runs (run_id, name, model_name, model_version, "
                "parameters, symbols, start_date, end_date, status, created_at, signal_count, "
                "instruments_requested, instruments_with_data, instruments_full_warmup, "
                "dataset, owner_id, strategy, execution, request, estimated_bars) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'queued', clock_timestamp(), 0, "
                "%s, 0, 0, %s, %s, %s, %s, %s, %s)",
                (
                    record["id"],
                    record.get("name"),
                    record["model_name"],
                    record["model_version"],
                    json.dumps(record["parameters"], sort_keys=True),
                    json.dumps(record["symbols"]),
                    record["start_date"],
                    record["end_date"],
                    len(record["symbols"]),
                    record.get("dataset", "warehouse"),
                    record.get("owner_id"),
                    _pg_json(record.get("strategy")),
                    _pg_json(record.get("execution")),
                    json.dumps(record["request"], sort_keys=True),
                    record.get("estimated_bars"),
                ),
            )
            conn.commit()

    def claim_next_run(
        self, worker: str, lease_seconds: float, max_bars: int | None = None
    ) -> dict | None:
        """Take the oldest queued run (within ``max_bars``) and mark it running.

        SKIP LOCKED: two workers asking at once get two different runs, never
        the same one, and neither waits on the other.
        """
        size = "AND COALESCE(estimated_bars, 0) <= %(max_bars)s" if max_bars is not None else ""
        with self._connect() as conn:
            row = conn.execute(
                f"""
                UPDATE experiment_runs
                   SET status = 'running', started_at = now(), worker = %(worker)s,
                       lease_until = now() + make_interval(secs => %(lease)s),
                       attempts = attempts + 1
                 WHERE run_id = (
                       SELECT run_id FROM experiment_runs
                        WHERE status = 'queued' {size}
                        ORDER BY created_at, run_id
                        LIMIT 1
                          FOR UPDATE SKIP LOCKED)
             RETURNING run_id, request, attempts, owner_id
                """,
                {"worker": worker, "lease": lease_seconds, "max_bars": max_bars},
            ).fetchone()
            conn.commit()
        if row is None:
            return None
        run_id, request, attempts, owner_id = row
        return {"id": run_id, "request": request, "attempts": attempts, "owner_id": owner_id}

    def renew_lease(self, run_id: str, worker: str, lease_seconds: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE experiment_runs SET lease_until = now() + make_interval(secs => %s) "
                "WHERE run_id = %s AND worker = %s AND status = 'running'",
                (lease_seconds, run_id, worker),
            )
            conn.commit()

    def cancel_requested(self, run_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM experiment_runs WHERE run_id = %s", (run_id,)
            ).fetchone()
        return bool(row and row[0])

    def finish_run(self, result: Any, performance: dict | None) -> bool:
        """Write a running run's results. False if it was cancelled meanwhile,
        in which case nothing is written."""
        instrument_ids = getattr(result, "instrument_ids", None)
        by_symbol = (
            dict(zip(result.symbols, instrument_ids, strict=False)) if instrument_ids else {}
        )
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE experiment_runs SET status = %s, error = NULL, signal_count = %s, "
                "instruments_requested = %s, instruments_with_data = %s, "
                "instruments_full_warmup = %s, model_name = %s, model_version = %s, "
                "parameters = %s, symbols = %s, dataset = %s, instrument_ids = %s, "
                "ingest_run_ids = %s, corporate_actions = %s, strategy = %s, execution = %s, "
                "execution_summary = %s, fact_coverage = %s, performance = %s, headline = %s, "
                "finished_at = now(), lease_until = NULL "
                "WHERE run_id = %s AND status = 'running' AND NOT cancel_requested",
                (
                    result.status,
                    result.signal_count,
                    result.coverage.instruments_requested,
                    result.coverage.instruments_with_data,
                    result.coverage.instruments_full_warmup,
                    result.model_name,
                    result.model_version,
                    json.dumps(result.parameters, sort_keys=True),
                    json.dumps(result.symbols),
                    getattr(result, "dataset", "warehouse"),
                    json.dumps(instrument_ids) if instrument_ids else None,
                    json.dumps(getattr(result, "ingest_run_ids", None) or []) or None,
                    json.dumps(getattr(result, "corporate_actions", []) or []),
                    _pg_json(getattr(result, "strategy", None)),
                    _pg_json(getattr(result, "execution", None)),
                    _pg_json(getattr(result, "execution_summary", None)),
                    _pg_json(_fact_coverage(result)),
                    json.dumps(performance) if performance is not None else None,
                    _pg_json(_headline(performance)),
                    result.id,
                ),
            ).rowcount
            if changed:
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
        return changed > 0

    def fail_run(self, run_id: str, error: str, category: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE experiment_runs SET status = 'failed', error = %s, error_category = %s, "
                "finished_at = now(), lease_until = NULL "
                "WHERE run_id = %s AND status IN ('queued', 'running')",
                (error, category, run_id),
            )
            conn.commit()

    def mark_cancelled(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE experiment_runs SET status = 'cancelled', finished_at = now(), "
                "lease_until = NULL WHERE run_id = %s AND status IN ('queued', 'running')",
                (run_id,),
            )
            conn.commit()

    def cancel_run(self, run_id: str, owner_id: str | None = None) -> str | None:
        """Cancel a queued run now, or ask a running one to stop. Returns the
        status afterwards, or None if there is no such cancellable run."""
        scope, params = self._scope(owner_id, "AND")
        with self._connect() as conn:
            if conn.execute(
                f"UPDATE experiment_runs SET status = 'cancelled', finished_at = now() "
                f"WHERE run_id = %s AND status = 'queued' {scope}",
                (run_id, *params),
            ).rowcount:
                conn.commit()
                return "cancelled"
            if conn.execute(
                f"UPDATE experiment_runs SET cancel_requested = true "
                f"WHERE run_id = %s AND status = 'running' {scope}",
                (run_id, *params),
            ).rowcount:
                conn.commit()
                return "running"
            conn.commit()
        return None

    def recover_stale_runs(self, max_attempts: int) -> dict[str, int]:
        """Runs whose worker stopped renewing its lease: queue them again, or
        fail them once they have had ``max_attempts``."""
        with self._connect() as conn:
            cancelled = conn.execute(
                "UPDATE experiment_runs SET status = 'cancelled', finished_at = now(), "
                "lease_until = NULL WHERE status = 'running' AND lease_until < now() "
                "AND cancel_requested"
            ).rowcount
            failed = conn.execute(
                "UPDATE experiment_runs SET status = 'failed', error_category = 'worker', "
                "error = replace(%s, '{attempts}', attempts::text), "
                "finished_at = now(), lease_until = NULL "
                "WHERE status = 'running' AND lease_until < now() AND attempts >= %s",
                (WORKER_LOST, max_attempts),
            ).rowcount
            requeued = conn.execute(
                "UPDATE experiment_runs SET status = 'queued', worker = NULL, "
                "lease_until = NULL, started_at = NULL "
                "WHERE status = 'running' AND lease_until < now()"
            ).rowcount
            conn.commit()
        return {"requeued": requeued, "failed": failed, "cancelled": cancelled}

    def queued_run_ids(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id FROM experiment_runs WHERE status = 'queued' "
                "ORDER BY created_at, run_id"
            ).fetchall()
        return [row[0] for row in rows]

    def get_performance(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT performance FROM experiment_runs WHERE run_id = %s", (run_id,)
            ).fetchone()
        return row[0] if row and row[0] else None

    def set_performance(self, run_id: str, performance: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE experiment_runs SET performance = %s, headline = %s WHERE run_id = %s",
                (json.dumps(performance), _pg_json(_headline(performance)), run_id),
            )
            conn.commit()


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

