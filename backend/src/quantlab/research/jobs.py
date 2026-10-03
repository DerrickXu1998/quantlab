"""Backtests in the background: queue a run, and a worker that executes it.

A run used to execute inside ``POST /runs``. Intraday runs outlived the
request -- the connection was dropped at 60 s while the server finished the run
-- so the result existed and the person who asked never saw it. Now:

1. the API resolves and checks the request (``runner.prepare_run``: everything
   that needs no bars) and stores it as a ``queued`` run;
2. a worker claims the oldest queued run, executes it, computes its
   performance once, and stores both;
3. the UI lists runs and their status, and opens a finished one instantly.

The worker has two lanes. The *main* lane takes any run, the largest included,
and holds the server-wide large-run slot while it runs one -- at most one large
run is in memory at a time, which is what the slot always meant. The *quick*
lane takes only runs under ``runner.LARGE_RUN_BARS``, so a one-ticker daily
test never waits behind a 5-minute universe.

Nothing here knows about HTTP. ``python -m quantlab.worker`` runs a Worker in
its own container; the API can also run one in-process (development, the
demo), and tests drive ``process_next`` directly.
"""

from __future__ import annotations

import math
import os
import socket
import threading
import uuid
from dataclasses import asdict
from typing import Any

from quantlab.execution import minutes
from quantlab.logging import get_logger
from quantlab.replay import engine as replay_engine
from quantlab.research import errors, performance, runner

logger = get_logger(__name__)

#: How long a claim lasts without renewal, and how often it is renewed. A
#: worker that dies stops renewing; after the lease lapses the run is queued
#: again (or failed, after MAX_ATTEMPTS).
LEASE_SECONDS = 90.0
RENEW_SECONDS = 20.0
#: A run is tried at most this many times. Twice: a deploy mid-run deserves a
#: retry; a run that kills the worker twice will kill it a third time.
MAX_ATTEMPTS = 2
#: Idle polling interval, seconds. A queued run starts within this.
POLL_SECONDS = 1.0
#: How long the main lane waits for the large-run slot. The slot is shared
#: with any other worker process; the queue already orders large runs, so a
#: wait here means another process holds it, and waiting is the right answer.
LARGE_SLOT_WAIT_SECONDS = 3600.0


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


def queued_record(
    prepared: runner.PreparedRun,
    *,
    dataset: str,
    owner_id: str | None,
    name: str | None = None,
) -> dict[str, Any]:
    """The row a submitted run starts as: who, what, and nothing measured yet."""
    spec = prepared.spec
    entry = next((c for c in spec.components if c.role == "entry"), spec.components[0])
    rule = entry.resolve(0)
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        # Populated for clients that predate strategies, as runner does.
        "model_name": rule.name,
        "model_version": rule.version,
        "parameters": entry.effective_parameters(0),
        "symbols": list(prepared.symbols),
        "start_date": prepared.start_date,
        "end_date": prepared.end_date,
        "dataset": dataset,
        "owner_id": owner_id,
        "strategy": spec.to_dict(),
        "execution": spec.execution.to_dict(),
        "request": prepared.request(),
        "estimated_bars": prepared.estimated_bars,
    }


#: Which failures need which kind of fix. The UI offers "Fix in editor" for
#: data and validation, and "Re-run" for the worker.
_CATEGORIES: tuple[tuple[type[Exception], str], ...] = (
    (errors.SelectionTooLargeError, "limit"),
    (errors.LargeRunBusyError, "limit"),
    (errors.UnknownSymbolError, "data"),
    (errors.NoFactCoverageError, "data"),
    (errors.DatasetUnsupportedError, "data"),
    (errors.UnknownModelError, "validation"),
    (errors.ParameterValidationError, "validation"),
    (errors.InvalidWindowError, "validation"),
    (errors.WindowTooShortError, "validation"),
)


def categorise(exc: BaseException) -> str:
    for kind, category in _CATEGORIES:
        if isinstance(exc, kind):
            return category
    return "worker"


def describe(exc: BaseException) -> str:
    """A failure as a sentence for the run list, never a traceback."""
    if isinstance(exc, MemoryError):
        return (
            "the backtest ran out of memory; narrow the selection (fewer symbols, a "
            "shorter window or a coarser bar frequency)"
        )
    if isinstance(exc, errors.ExperimentError):
        return str(exc)
    return f"the backtest stopped unexpectedly ({type(exc).__name__}: {exc})"


# ---------------------------------------------------------------------------
# Performance, computed once
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """Performance as strict JSON: NaN and infinities become null.

    A ratio over a flat series is NaN; Postgres JSONB refuses NaN outright, and
    a client parsing strict JSON would too.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


#: Points kept per stored curve. An intraday run marks equity on every bar
#: (570k points for a 5-minute universe-year); the stored curve keeps the last
#: point of each session past this, which is more than a chart can draw. The
#: metrics are computed from the full series before this ever runs.
MAX_STORED_POINTS = 2500


def _compact_curve(points: list[dict]) -> list[dict]:
    if len(points) <= MAX_STORED_POINTS:
        return points
    by_day: dict[str, dict] = {}
    for point in points:
        by_day[str(point.get("date", ""))[:10]] = point
    daily = list(by_day.values())
    if len(daily) <= MAX_STORED_POINTS:
        return daily
    step = (len(daily) - 1) / (MAX_STORED_POINTS - 1)
    return [daily[round(i * step)] for i in range(MAX_STORED_POINTS)]


def _compact(performance: dict) -> dict:
    """Performance as stored: curves at most MAX_STORED_POINTS long."""
    for key in ("equity", "benchmark"):
        if isinstance(performance.get(key), list):
            performance[key] = _compact_curve(performance[key])
    return performance


def compute_run_performance(backend, store, run: dict, bars: dict | None = None) -> dict:
    """research.performance for a stored run, as the API returns it.

    The one implementation shared by the worker (at completion) and the API
    (for runs recorded before performance was stored). ``bars``, when given,
    are the bars the run itself read from its warm-up start -- exactly what
    load_replay_inputs would read again.
    """
    if bars is None:
        signals, bars = replay_engine.load_replay_inputs(backend, store, run)
    else:
        signals = store.get_run_signals(run["id"])
    config = runner.execution_config_for(run)
    result = performance.compute_performance(
        run_id=run["id"],
        signals=signals,
        bars_by_symbol=bars,
        symbols=list(run["symbols"]),
        execution=config,
        window_start=run["start_date"],
        window_end=run["end_date"],
        corporate_actions=replay_engine.load_corporate_actions(backend, run, config),
        minute_source=minutes.source_for(backend, config),
    )
    return _compact(_jsonable(asdict(result)))


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class _Lease:
    """Renews a claimed run's lease in the background while it executes."""

    def __init__(self, store, run_id: str, worker: str) -> None:
        self._store, self._run_id, self._worker = store, run_id, worker
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._renew, name=f"lease-{run_id[:8]}", daemon=True)

    def _renew(self) -> None:
        while not self._stop.wait(RENEW_SECONDS):
            try:
                self._store.renew_lease(self._run_id, self._worker, LEASE_SECONDS)
            except Exception:  # noqa: BLE001 -- a missed renewal is retried
                logger.warning("run_lease_renew_failed", extra={"run_id": self._run_id})

    def __enter__(self) -> _Lease:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def process_next(
    backend,
    store,
    *,
    worker: str = "inline",
    max_bars: int | None = None,
    large_slot: bool = True,
) -> str | None:
    """Claim and run one queued run. Returns its id, or None if none waited.

    ``max_bars`` restricts the claim to small runs (the quick lane).
    ``large_slot`` takes the server-wide slot for a large run, so a run that
    exceeds LARGE_RUN_BARS is never in memory beside another one.
    """
    claimed = store.claim_next_run(worker, LEASE_SECONDS, max_bars=max_bars)
    if claimed is None:
        return None
    run_id = claimed["id"]
    logger.info(
        "run_started", extra={"run_id": run_id, "worker": worker, "attempt": claimed["attempts"]}
    )
    with _Lease(store, run_id, worker):
        _execute_claimed(backend, store, claimed, worker=worker, large_slot=large_slot)
    return run_id


def _execute_claimed(backend, store, claimed: dict, *, worker: str, large_slot: bool) -> None:
    run_id = claimed["id"]
    request = claimed.get("request") or {}
    try:
        # Prepared again rather than trusted: a symbol may have been removed
        # from the catalog, or a rule from the registry, while it waited.
        prepared = runner.prepare_run(
            backend,
            strategy=request.get("strategy"),
            symbols=request.get("symbols") or [],
            start_date=request.get("start_date", ""),
            end_date=request.get("end_date", ""),
        )

        def execute():
            return runner.execute_prepared(
                backend,
                prepared,
                owner_id=claimed.get("owner_id"),
                run_id=run_id,
                should_cancel=lambda: store.cancel_requested(run_id),
                keep_bars=True,
            )

        if prepared.large and large_slot:
            with backend.large_run_slot(LARGE_SLOT_WAIT_SECONDS) as acquired:
                if not acquired:
                    raise errors.LargeRunBusyError()
                result = execute()
        else:
            result = execute()

        # Performance from the run as it will be stored: signals as decided,
        # bars from the warm-up start. Computed here, once, so opening the run
        # is a read, never a second simulation.
        run_view = {
            **asdict_run(result),
            "id": run_id,
        }
        perf = compute_run_performance(backend, _SignalsOf(result), run_view, bars=result.bars)
        if store.finish_run(result, perf):
            logger.info("run_completed", extra={"run_id": run_id, "worker": worker})
        else:
            store.mark_cancelled(run_id)
            logger.info("run_cancelled", extra={"run_id": run_id, "worker": worker})
    except errors.RunCancelledError:
        store.mark_cancelled(run_id)
        logger.info("run_cancelled", extra={"run_id": run_id, "worker": worker})
    except Exception as exc:  # noqa: BLE001 -- every failure is recorded on the run
        category = categorise(exc)
        store.fail_run(run_id, describe(exc), category)
        log = logger.info if category != "worker" else logger.exception
        log("run_failed", extra={"run_id": run_id, "worker": worker, "category": category})


def asdict_run(result: runner.RunResult) -> dict:
    """The fields of a RunResult that load_replay_inputs and performance read."""
    return {
        "id": result.id,
        "symbols": list(result.symbols),
        "start_date": result.start_date,
        "end_date": result.end_date,
        "status": result.status,
        "dataset": result.dataset,
        "strategy": result.strategy,
        "execution": result.execution,
        "instrument_ids": result.instrument_ids,
    }


class _SignalsOf:
    """A read-only store view over a just-finished result, so performance can
    be computed before anything is written (load_replay_inputs asks the store
    for the run's signals)."""

    def __init__(self, result: runner.RunResult) -> None:
        self._signals = [
            {
                "symbol": s.symbol,
                "date": s.date,
                "direction": s.direction,
                "trigger_values": s.trigger_values,
                "data_window_end": s.data_window_end,
                "kind": getattr(s, "kind", "both"),
            }
            for s in result.signals
        ]

    def get_run_signals(self, run_id: str) -> list[dict]:
        return list(self._signals)


# ---------------------------------------------------------------------------
# Results for runs recorded before they were stored
# ---------------------------------------------------------------------------


def backfill_next(backend, store, *, skip: set[str] | None = None) -> str | None:
    """Compute and store one older run's results. Returns its id, or None.

    Runs recorded before the queue have no stored performance; the API no
    longer recomputes on view, so the worker does it once, newest first, when
    it has nothing queued. A run whose results cannot be computed records why
    (performance_error) and is not tried again.
    """
    run = store.next_run_without_results(exclude=sorted(skip or ()))
    if run is None:
        return None
    run_id = run["id"]
    try:
        config = runner.execution_config_for(run)
        estimate = runner.estimate_bars(
            len(run["symbols"]), run["start_date"], run["end_date"], config.bar_frequency
        )
        if estimate > runner.LARGE_RUN_BARS:
            with backend.large_run_slot(LARGE_SLOT_WAIT_SECONDS) as acquired:
                if not acquired:
                    raise errors.LargeRunBusyError()
                performance = compute_run_performance(backend, store, run)
        else:
            performance = compute_run_performance(backend, store, run)
        store.set_performance(run_id, performance)
        logger.info("run_results_backfilled", extra={"run_id": run_id})
    except errors.LargeRunBusyError:
        # Not this run's fault: leave it for the next idle moment.
        if skip is not None:
            skip.add(run_id)
    except Exception as exc:  # noqa: BLE001 -- recorded on the run, never retried in a loop
        store.set_performance_error(run_id, describe(exc))
        logger.exception("run_results_backfill_failed", extra={"run_id": run_id})
    return run_id


# ---------------------------------------------------------------------------
# The worker loop
# ---------------------------------------------------------------------------


def worker_name() -> str:
    return os.environ.get("QUANTLAB_WORKER_NAME") or f"{socket.gethostname()}:{os.getpid()}"


class Worker:
    """Two lanes polling the queue until stopped. See the module docstring."""

    def __init__(self, backend, store, *, name: str | None = None, quick_lane: bool = True) -> None:
        self.backend, self.store = backend, store
        self.name = name or worker_name()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lanes = [("main", None, True)]
        if quick_lane:
            self._lanes.append(("quick", runner.LARGE_RUN_BARS, False))

    def start(self) -> None:
        self._recover()
        for lane, max_bars, large_slot in self._lanes:
            thread = threading.Thread(
                target=self._loop,
                args=(f"{self.name}/{lane}", max_bars, large_slot),
                name=f"run-worker-{lane}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        logger.info("run_worker_started", extra={"worker": self.name, "lanes": len(self._lanes)})

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)

    def run_forever(self) -> None:
        self.start()
        try:
            while not self._stop.wait(LEASE_SECONDS):
                self._recover()
        finally:
            self.stop()

    def _recover(self) -> None:
        try:
            outcome = self.store.recover_stale_runs(MAX_ATTEMPTS)
        except Exception:  # noqa: BLE001 -- the next sweep tries again
            logger.exception("run_recover_failed", extra={"worker": self.name})
            return
        if any(outcome.values()):
            logger.warning("run_recovered", extra={"worker": self.name, **outcome})

    def _loop(self, name: str, max_bars: int | None, large_slot: bool) -> None:
        # Only the main lane backfills older runs, and only when nothing is
        # queued: a submitted run is never kept waiting behind history.
        backfills = large_slot
        skip: set[str] = set()
        while not self._stop.is_set():
            try:
                ran = process_next(
                    self.backend, self.store, worker=name, max_bars=max_bars, large_slot=large_slot
                )
                if ran is None and backfills:
                    ran = backfill_next(self.backend, self.store, skip=skip)
            except Exception:  # noqa: BLE001 -- a broken claim must not kill the lane
                logger.exception("run_worker_error", extra={"worker": name})
                ran = None
            if ran is None:
                self._stop.wait(POLL_SECONDS)
