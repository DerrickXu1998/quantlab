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

import os
import socket
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from typing import Any

from quantlab.execution import ExecutionSimulator, minutes
from quantlab.execution.engine import mark_session, result_of
from quantlab.logging import get_logger
from quantlab.replay import engine as replay_engine
from quantlab.replay import recording as replay_recording
from quantlab.research import errors, performance, runner
from quantlab.storage import db

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
    (errors.MissingSeriesError, "data"),
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


#: Drivers whose connection-level errors are infrastructure, not the run: the
#: catalog (psycopg, its pool) and the bar store (ClickHouse). Matched by
#: module and by class name across the MRO, so the demo path imports none.
_DRIVERS = ("psycopg", "psycopg_pool", "clickhouse_connect", "urllib3", "httpx")
#: Driver errors that share a transient class but are permanent misconfiguration.
_PERMANENT_WORDS = (
    "authentication failed", "does not exist", "permission denied", "no such",
    "unknown database", "access denied",
)
#: Failures to reach a server at all (DNS, refused, reset): always an outage.
_CONNECT_NAMES = {
    "ConnectError", "ConnectTimeout", "NewConnectionError", "NameResolutionError",
    "MaxRetryError", "ProtocolError", "RemoteProtocolError",
}
_TRANSIENT_NAMES = {
    "OperationalError", "QueryCanceled", "AdminShutdown", "ConnectionTimeout",
    "PoolTimeout", "TooManyRequests", "StreamClosedError",
}


def transient(exc: BaseException) -> bool:
    """A failure of the infrastructure rather than of the run: worth retrying."""
    # Not every OSError: a missing file (FileNotFoundError) is permanent.
    if isinstance(exc, (TimeoutError, ConnectionError, socket.gaierror)):
        return True
    from quantlab.storage import warehouse  # lazy: the warehouse driver is optional

    if isinstance(exc, Exception) and warehouse.server_memory_exhausted(exc):
        # ClickHouse out of memory server-wide (beside other queries), after
        # its own retries: the run did nothing wrong.
        return True
    if isinstance(exc, sqlite3.OperationalError):
        # Contention, not a schema problem ("no such table" is permanent).
        return any(word in str(exc).lower() for word in ("locked", "busy", "disk i/o"))
    module = type(exc).__module__ or ""
    if not module.startswith(_DRIVERS):
        return False
    names = {klass.__name__ for klass in type(exc).__mro__}
    text = str(exc).lower()
    if names & _CONNECT_NAMES or ("InterfaceError" in names and "closed" in text):
        # Reaching the server failed: an outage, however it is worded -- a
        # DNS blip says "no such host", which is no misconfiguration. A
        # pooled connection found closed is the same outage.
        return True
    if any(word in text for word in _PERMANENT_WORDS):
        return False  # configuration, not an outage: retrying cannot help
    return times_out(exc) or any(cls.__name__ in _TRANSIENT_NAMES for cls in type(exc).__mro__)


def times_out(exc: BaseException) -> bool:
    """A statement or request cancelled for taking too long -- the one place a
    driver's timeout is recognised, for retry and refusal decisions alike."""
    if isinstance(exc, TimeoutError) or "statement timeout" in str(exc).lower():
        return True
    return any(
        "Timeout" in klass.__name__ or klass.__name__ == "QueryCanceled"
        for klass in type(exc).__mro__
    )


def retryable(exc: BaseException) -> bool:
    """Worth trying again later rather than storing as an output's fate: an
    infrastructure failure, or memory pressure beside another job."""
    return transient(exc) or isinstance(exc, MemoryError)


#: Rebuilds a run may run out of memory before that is its answer. Counted,
#: not timed: one that never fits must not be re-run every pass for hours.
MAX_MEMORY_RETRIES = 2
_memory_retries: dict[str, int] = {}
#: run id -> when its last rebuild failed retryably (the request cool-down).
_last_retryable: dict[str, float] = {}
#: Runs whose rebuilt outputs the store refused: not offered again.
_unrecordable: set[str] = set()
#: Guards the per-run bookkeeping above; request threads and the worker share it.
_bookkeeping = threading.Lock()


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


def compute_run_performance(backend, store, run: dict) -> dict:
    """research.performance for a stored run, as the API returns it -- for a
    run recorded before performance was stored, rebuilt on today's data, and
    marked so."""
    return _performance(run, *_run_inputs(backend, store, run), reconstructed=True)


def _performance(
    run, signals, bars, config, actions, minute_source, *, simulated=None,
    reconstructed: bool = False,
) -> dict:
    """The run's performance, as stored and served. ``reconstructed`` when
    built after the fact on the data as it then stood -- the one place that
    is stamped, for performance as for the replay (record)."""
    result = performance.compute_performance(
        simulated=simulated,
        run_id=run["id"],
        signals=signals,
        bars_by_symbol=bars,
        symbols=list(run["symbols"]),
        execution=config,
        window_start=run["start_date"],
        window_end=run["end_date"],
        corporate_actions=actions,
        minute_source=minute_source,
    )
    return {
        **_compact(replay_recording.strict_json(asdict(result))),
        "reconstructed": reconstructed,
    }


def _run_inputs(backend, store, run: dict):
    """What a stored run executes on: its signals, its bars from the warm-up
    start, its execution config, corporate actions and minute source."""
    signals, bars = replay_engine.load_replay_inputs(backend, store, run)
    config = runner.execution_config_for(run)
    actions = replay_engine.load_corporate_actions(backend, run, config)
    return signals, bars, config, actions, minutes.source_for(backend, config)


#: Walked bars kept in a recorded replay (sessions for a daily run, intraday
#: bars for an intraday one). Each is a bar frame (a close per symbol) and an
#: equity frame, so a long intraday run (570k bars in a 5-minute
#: universe-year) would otherwise store hundreds of MB that no viewer could
#: watch. Past this the record keeps every Nth walked bar, plus every one with
#: a signal or a fill (recording.record).
MAX_RECORDED_BAR_FRAMES = 5000


#: Closes kept across all bar frames: a bar frame carries one per symbol, so
#: a record's size grows with the selection, not only with its length.
MAX_RECORDED_CLOSES = 2_000_000


def _record_step(run: dict, config) -> tuple[int, int]:
    """``(every, bars_every)`` for recording.record.

    ``every`` thins an intraday window's walked bars (bar and equity frames
    together) to about MAX_RECORDED_BAR_FRAMES; a daily run keeps every equity
    mark. ``bars_every`` then thins only bar frames, so the closes stored stay
    under MAX_RECORDED_CLOSES however many symbols the run has. Warm-up is
    never recorded, so it does not count. Sized as runner sizes runs.
    """
    walked = runner.estimate_bars(1, run["start_date"], run["end_date"], config.bar_frequency)
    every = 1 if config.bar_frequency == "1d" else max(1, -(-walked // MAX_RECORDED_BAR_FRAMES))
    closes = -(-walked // every) * max(1, len(run["symbols"]))
    return every, max(1, -(-closes // MAX_RECORDED_CLOSES))


def _replay(
    run, signals, bars, config, actions, minute_source, *, reconstructed: bool = False,
    simulator=None, on_day=None,
) -> replay_recording.RecordedReplay:
    events = replay_engine.replay_events(
        run, signals, bars, config=config, corporate_actions=actions,
        minute_source=minute_source, simulator=simulator, on_day=on_day,
    )
    every, bars_every = _record_step(run, config)
    return replay_recording.record(
        events, reconstructed=reconstructed, every=every, bars_every=bars_every
    )


@dataclass(frozen=True)
class RunOutputs:
    """What a finished run stores beside its signals."""

    #: None when it could not be computed now; ``performance_error`` says why.
    performance: dict | None
    #: None when the replay could not be recorded; ``replay_error`` says why.
    replay: replay_recording.RecordedReplay | None
    replay_error: str | None = None
    performance_error: str | None = None


def _reason(exc: BaseException) -> str:
    """Why a run's output (performance, replay) could not be built, said of
    that output -- ``describe`` is for the run itself, and "the backtest
    stopped" would be false here. Never empty: '' would read as none."""
    if isinstance(exc, (MemoryError, errors.ExperimentError)):
        text = describe(exc)
    else:
        text = f"{type(exc).__name__}: {exc}"
    return text or type(exc).__name__


def is_large_run(run: dict) -> bool:
    """Whether a stored run needs the large-run slot, sized as PreparedRun
    sized it: from its warm-up start, since a rebuild loads those bars too."""
    config = runner.execution_config_for(run)
    estimate = runner.estimate_bars(
        len(run["symbols"]),
        replay_engine.warmup_start(run, config),
        run["end_date"],
        config.bar_frequency,
    )
    return runner.is_large(estimate)


def record_results(result: runner.RunResult) -> RunOutputs:
    """Performance and replay for a just-finished run, from the bars it read.

    Shared by the worker and inline mode. A replay that cannot be recorded is
    not the run's failure: the backtest and its performance stand, and the
    replay records why it is missing (served as a 422) rather than throwing
    the finished results away.
    """
    run = asdict_run(result)
    traded = result.traded_on
    if traded is None or result.bars is None:
        # Reading them now would record today's data, not the run's.
        raise ValueError("record_results needs a result executed with keep_bars=True")
    # Exactly what the run traded on -- nothing re-read, so nothing that
    # changed since (a restated split, re-ingested minutes) can leak in.
    inputs = (
        _signal_dicts(result),
        result.bars,
        traded["config"],
        traded["actions"],
        traded["minute_source"],
    )
    return _retry_transient(lambda: _outputs(run, inputs))


def rebuild_results(backend, store, run: dict, *, performance: bool = True) -> RunOutputs:
    """The outputs a run that predates them lacks, from one walk over the data
    as it is now; the replay is marked ``reconstructed``. ``performance``
    False when one is stored already: then it is not reduced at all."""
    return _outputs(
        run, _run_inputs(backend, store, run), reconstructed=True, performance=performance
    )


def _outputs(
    run: dict, inputs, *, reconstructed: bool = False, performance: bool = True
) -> RunOutputs:
    _, bars, config, actions, minute_source = inputs
    # One walk for both: the replay is recorded from it, and the performance
    # is reduced from the same simulator and its session curve.
    simulator = ExecutionSimulator(list(run["symbols"]), bars, config, actions, minute_source)
    curve: list = []
    try:
        replay = _replay(
            run, *inputs, reconstructed=reconstructed,
            simulator=simulator, on_day=lambda day: mark_session(curve, day),
        )
    except Exception as exc:  # noqa: BLE001 -- recorded on the replay, not the run
        if retryable(exc):
            raise  # retried by the caller, never stored as the replay's fate
        logger.exception("run_replay_record_failed", extra={"run_id": run["id"]})
        if not performance:
            return RunOutputs(None, None, _reason(exc))
        # The walk may have stopped part-way: simulate afresh for performance,
        # which may fail for the same reason -- then it says so too.
        try:
            return RunOutputs(
                _performance(run, *inputs, reconstructed=reconstructed), None, _reason(exc)
            )
        except Exception as again:  # noqa: BLE001
            if retryable(again):
                raise
            return RunOutputs(None, None, _reason(exc), _reason(again))
    if not performance:
        return RunOutputs(None, replay)
    try:
        perf = _performance(
            run, *inputs, simulated=result_of(simulator, curve), reconstructed=reconstructed
        )
    except Exception as exc:  # noqa: BLE001 -- keep the replay; store why performance failed
        if retryable(exc):
            raise
        # The exact record is in hand: keep it, and store why performance is
        # not (performance_error: served as a 422, not retried).
        logger.exception("run_performance_record_failed", extra={"run_id": run["id"]})
        return RunOutputs(None, replay, performance_error=_reason(exc))
    return RunOutputs(perf, replay)


def _retry_transient(fn, attempts: int = 3):
    """``fn()``, tried again after a transient failure (a timeout, a dropped
    connection): those say nothing about the run and usually pass."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts or not transient(exc):
                raise
            logger.warning("run_results_retry", extra={"error": type(exc).__name__})
            # Short: this can run inside the large-run slot holding the bars.
            time.sleep(0.5 * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


def keep_outputs(store, run_id: str, outputs: RunOutputs | None) -> None:
    """After a run's own transaction: write again whatever exact output it
    holds that the store did not keep.

    Each output is written in its own savepoint inside that transaction, so a
    blip (a lock, a dropped connection, a statement timeout) loses only that
    output, and the run still completes. Without this the record in hand
    would be gone, and the output rebuilt later from data as it then stands.
    A write the store refused for good already left its reason, and is not
    sent again.
    """
    if outputs is None or (outputs.performance is None and outputs.replay is None):
        return

    def resend() -> None:
        run = store.get_run(run_id) or {}
        missing = RunOutputs(
            outputs.performance
            if outputs.performance is not None
            and not run.get("results_error")
            and not store.has_performance(run_id)
            else None,
            outputs.replay
            if outputs.replay is not None and store.get_replay(run_id, events=False) is None
            else None,
        )
        if missing.performance is not None or missing.replay is not None:
            store.set_rebuilt(run_id, missing)

    try:
        # Reads included: the run is saved already, and nothing here may turn
        # that into a failed request or a failed run.
        _retry_transient(resend)
    except Exception:  # noqa: BLE001 -- the run stands; the backfill rebuilds it
        logger.exception("run_outputs_unrecorded", extra={"run_id": run_id})


def run_inline(
    backend, *, owner_id: str | None, **arguments
) -> tuple[runner.RunResult, RunOutputs | None]:
    """Run and record in the request, as the worker does at completion."""
    prepared = runner.prepare_run(backend, **arguments)
    return execute_and_record(
        backend, prepared, wait_seconds=runner.LARGE_RUN_WAIT_SECONDS, owner_id=owner_id
    )


def _without_bars(result: runner.RunResult) -> runner.RunResult:
    """The result as it leaves the large-run slot: its bars (and what they
    were read with) are let go there, never held beside the next large run."""
    return replace(result, bars=None, traded_on=None)


def execute_and_record(
    backend, prepared, *, wait_seconds: float, large_slot: bool = True, **execute
) -> tuple[runner.RunResult, RunOutputs | None]:
    """Execute a prepared run and record its performance and replay.

    The one path for the worker and inline mode. Recording happens inside the
    large-run slot, since the run's bars are still held. A recording failure
    never discards the finished backtest: the run is returned with no outputs
    and its performance is computed once later, like a run that predates
    stored results.
    """

    def run():
        result = runner.execute_prepared(backend, prepared, keep_bars=True, **execute)
        if result.status != "completed":
            return _without_bars(result), None
        cancelled = execute.get("should_cancel")
        if cancelled is not None and cancelled():
            # Cancelled as it finished: finish_run will discard it, so do not
            # walk it all again (holding the slot and its bars) to record it.
            return _without_bars(result), None
        try:
            return _without_bars(result), record_results(result)
        except Exception:  # noqa: BLE001 -- the run stands without its outputs
            # Retried already (record_results). Holding the bars for a later
            # retry would pin a finished run's memory indefinitely, so the
            # trade is: keep the backtest, and let its outputs be rebuilt once
            # later -- the replay then says ``reconstructed``. Failing the
            # finished run instead would break "slower, never failing".
            logger.exception("run_results_record_failed", extra={"run_id": result.id})
            return _without_bars(result), None

    return runner.in_large_slot(backend, prepared.large and large_slot, wait_seconds, run)


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

        # Performance and replay from the bars the run read: opening or
        # replaying it later is a read, never a re-simulation over data that
        # may since have changed.
        result, outputs = execute_and_record(
            backend,
            prepared,
            wait_seconds=LARGE_SLOT_WAIT_SECONDS,
            large_slot=large_slot,
            owner_id=claimed.get("owner_id"),
            run_id=run_id,
            should_cancel=lambda: store.cancel_requested(run_id),
        )
        if store.finish_run(result, outputs):
            keep_outputs(store, run_id, outputs)
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
        "model_name": result.model_name,
        "model_version": result.model_version,
        "parameters": result.parameters,
        "symbols": list(result.symbols),
        "start_date": result.start_date,
        "end_date": result.end_date,
        "status": result.status,
        "dataset": result.dataset,
        "strategy": result.strategy,
        "execution": result.execution,
        "instrument_ids": result.instrument_ids,
    }


def _signal_dicts(result: runner.RunResult) -> list[dict]:
    """A just-finished result's signals, as the store returns a run's."""
    return [
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


# ---------------------------------------------------------------------------
# Results for runs recorded before they were stored
# ---------------------------------------------------------------------------


def _forget(run_id: str, now: float) -> None:
    """Drop a settled run's bookkeeping -- and any other run's gone stale
    (deleted, or a client that never came back), so it stays bounded."""
    with _bookkeeping:
        _first_deferred.pop(run_id, None)
        _memory_retries.pop(run_id, None)
        _last_retryable.pop(run_id, None)
        old = [r for r, (_, last) in _first_deferred.items() if now - last > MAX_DEFER_SECONDS]
        for stale in old:
            _first_deferred.pop(stale, None)
            _memory_retries.pop(stale, None)
        # Every retryable failure stamps _last_retryable, so a stale one here
        # also covers a run that only ever ran out of memory.
        for stale in [r for r, t in _last_retryable.items() if now - t > MAX_DEFER_SECONDS]:
            _memory_retries.pop(stale, None)
            _last_retryable.pop(stale, None)


def _excluded(skip: set[str] | None) -> list[str]:
    with _bookkeeping:
        return sorted((skip or set()) | _unrecordable)


def backfill_next(backend, store, *, skip: set[str] | None = None) -> str | None:
    """Compute and store one older run's results. Returns its id, or None.

    Runs recorded before the queue have no stored performance; the API no
    longer recomputes on view, so the worker does it once, newest first, when
    it has nothing queued -- with its replay from the same walk if that is
    missing too. A run whose results cannot be computed records why
    (performance_error) and is not tried again.
    """
    return rebuild_old_run(
        backend, store, store.next_run_without_results(exclude=_excluded(skip)), skip,
        wait_seconds=0,  # history never waits on the slot ahead of the queue
    )


def backfill_next_replay(backend, store, *, skip: set[str] | None = None) -> str | None:
    """Reconstruct and store one older run's replay. Returns its id, or None.

    A run completed before replays were recorded has none. It is rebuilt once,
    by re-execution on the data as it stands now, and stored marked
    ``reconstructed``; from then on it is read like any recorded replay. A run
    whose replay cannot be rebuilt records why and is not tried again.
    """
    return rebuild_old_run(
        backend, store, store.next_run_without_replay(exclude=_excluded(skip)), skip,
        replay_missing=True,  # that is what the query selected on
        wait_seconds=0,  # a busy slot puts it off to a later pass (skip)
    )


#: How long a run's rebuild may keep failing transiently (timeouts, dropped
#: connections) before the failure is taken as its answer. Time, not tries:
#: a minute-long outage must not fail every pending run, and a run that times
#: out for good must not be re-executed forever without saying so.
MAX_DEFER_SECONDS = 6 * 3600
#: A run's transient failures further apart than this start a new outage.
OUTAGE_GAP_SECONDS = 3600
#: After a transient failure, a request does not rebuild the same run again
#: for this long; its client keeps getting "being prepared".
REQUEST_COOLDOWN_SECONDS = 30
#: run id -> (first, latest) transient failure of its current outage. Entries
#: leave on success or on a final failure, so it holds at most the runs
#: awaiting a rebuild.
_first_deferred: dict[str, tuple[float, float]] = {}


def rebuild_old_run(
    backend,
    store,
    run: dict | None,
    skip: set[str] | None = None,
    *,
    wait_seconds: float | None = None,
    from_request: bool = False,
    worker_present: bool = True,
    replay_missing: bool | None = None,
    perf_missing: bool | None = None,
) -> str | None:
    """Rebuild whatever a run that predates them is missing -- performance,
    replay or both -- from ONE walk over the data as it is now, and store it
    (or why it failed). Returns the run's id, or None if there was no run.

    Shared by the worker's backfill and the request paths, so an old run is
    never re-executed twice, nor its two outputs built from two snapshots.
    Inside the large-run slot when the run is large; ``wait_seconds`` bounds
    that wait (a request passes none). A busy slot, a transient failure or
    memory pressure leaves the run for later. A transient outage is timed
    (MAX_DEFER_SECONDS) from requests and the worker alike, so inline mode,
    with no worker, still reaches an answer; memory failures count only in
    the worker (a request may simply have landed beside another job). After
    any of these, requests leave the run alone for REQUEST_COOLDOWN_SECONDS.
    This bookkeeping is per process and resets on restart -- it bounds
    wasted work, it is not a server-wide cap.
    """
    if run is None:
        return None
    run_id = run["id"]
    now = time.monotonic()
    with _bookkeeping:
        cooling = now - _last_retryable.get(run_id, -1e18) < REQUEST_COOLDOWN_SECONDS
        refused = run_id in _unrecordable
    if from_request and (cooling or refused):
        # It just failed transiently: a client's next retry must not re-run
        # the whole thing against the same outage (nor even query for it).
        return run_id
    # Each read unless the caller has just made it.
    if perf_missing is None:
        perf_missing = not store.has_performance(run_id)
    perf_missing = perf_missing and not run.get("results_error")
    if replay_missing is None:
        replay_missing = store.get_replay(run_id, events=False) is None
    if not (perf_missing or replay_missing):
        return run_id  # finished meanwhile (by a request, or the worker)
    # Stored performance is never replaced, even when it predates this
    # build's metric rules: one stored before then may be the exact figures
    # the worker recorded at completion, and nothing marks which -- so a
    # rebuilt replay's summary may differ from it, and says it was rebuilt.

    def build() -> RunOutputs:
        if replay_missing:
            return rebuild_results(backend, store, run, performance=perf_missing)
        return RunOutputs(compute_run_performance(backend, store, run), None)

    try:
        wait = LARGE_SLOT_WAIT_SECONDS if wait_seconds is None else wait_seconds
        # Sized here, inside the try: a stored spec that cannot be read is
        # the run's answer, not a crash.
        built = runner.in_large_slot(backend, is_large_run(run), wait, build)
    except errors.LargeRunBusyError:
        if skip is not None:
            skip.add(run_id)
        return run_id
    except Exception as exc:  # noqa: BLE001 -- recorded on the run, never retried in a loop
        # Stamped when it failed, not when it began: a 40s timeout must not
        # start a 30s cool-down already over.
        failed_at = time.monotonic()
        if retryable(exc):
            with _bookkeeping:
                _last_retryable[run_id] = failed_at
        if isinstance(exc, MemoryError):
            # A request's attempt counts only where no worker will try again
            # (inline mode); otherwise it may just have met another job.
            counts = not from_request or not worker_present
            with _bookkeeping:
                tries = _memory_retries.get(run_id, 0) + (1 if counts else 0)
                _memory_retries[run_id] = tries
            if tries <= MAX_MEMORY_RETRIES:
                logger.warning("run_results_rebuild_out_of_memory", extra={"run_id": run_id})
                if skip is not None:
                    skip.add(run_id)
                return run_id
        elif retryable(exc):
            # A timeout, a dropped connection or memory pressure says nothing
            # about the run: leave it for later, not failed for good. Requests
            # share this clock, so an outage that outlasts it ends as an
            # answer even with no worker (inline mode).
            if _still_deferring(run_id, failed_at):
                logger.warning("run_results_rebuild_deferred", extra={"run_id": run_id})
                if skip is not None:
                    skip.add(run_id)
                return run_id
        logger.exception("run_results_rebuild_failed", extra={"run_id": run_id})
        built = RunOutputs(
            None,
            None,
            replay_error=_reason(exc) if replay_missing else None,
            performance_error=_reason(exc) if perf_missing else None,
        )
    try:
        # Both from one walk, written together; a store failure here is not
        # the run's, so it is never recorded as one.
        store.set_rebuilt(run_id, built)
    except Exception as exc:  # noqa: BLE001 -- the store's failure, never the run's
        _store_refused(
            store, run_id, exc, replay_missing=replay_missing, perf_missing=perf_missing
        )
        if skip is not None:
            skip.add(run_id)
        return run_id
    _forget(run_id, time.monotonic())
    logger.info("run_results_rebuilt", extra={"run_id": run_id})
    return run_id


def _store_refused(
    store, run_id: str, exc: Exception, *, replay_missing: bool, perf_missing: bool
) -> None:
    """The store would not keep a rebuild's outputs. A blip, or the store
    itself not ready (a deploy ahead of its migration, a revoked grant), is
    about the store, not the run: retried on the same outage clock as a
    failed rebuild (MAX_DEFER_SECONDS), never every minute forever. A write
    it will refuse again -- too large, a value it cannot hold -- is the run's
    answer at once, as is any of these past that clock: why, stored as each
    missing output's error -- a small row the store does keep, and one
    every process (the API, the worker) reads. Only if even that is refused
    is the run held back in memory, until restart."""
    failed_at = time.monotonic()
    with _bookkeeping:
        _last_retryable[run_id] = failed_at  # requests leave it alone meanwhile
    about_the_store = (retryable(exc) and not db.write_refused(exc)) or db.not_ready(exc)
    if about_the_store and _still_deferring(run_id, failed_at):
        logger.exception("run_results_rebuild_store_deferred", extra={"run_id": run_id})
        return
    with _bookkeeping:
        _first_deferred.pop(run_id, None)
    logger.exception("run_results_rebuild_unrecordable", extra={"run_id": run_id})
    reason = f"rebuilt, but the store would not keep it ({_reason(exc)})"
    try:
        store.set_rebuilt(run_id, RunOutputs(
            None,
            None,
            replay_error=reason if replay_missing else None,
            performance_error=reason if perf_missing else None,
        ))
    except Exception:  # noqa: BLE001 -- not even the reason: hold it back here
        logger.exception("run_results_refusal_unrecordable", extra={"run_id": run_id})
        with _bookkeeping:
            _unrecordable.add(run_id)


def _still_deferring(run_id: str, failed_at: float) -> bool:
    """One run's outage clock -- shared by failed rebuilds and refused writes:
    True (and the failure noted) while it is under MAX_DEFER_SECONDS;
    failures more than OUTAGE_GAP_SECONDS apart start a new outage."""
    with _bookkeeping:
        first, last = _first_deferred.get(run_id, (failed_at, failed_at))
        if failed_at - last > OUTAGE_GAP_SECONDS:
            first = failed_at  # separate blips, not one outage
        if failed_at - first < MAX_DEFER_SECONDS:
            _first_deferred[run_id] = (first, failed_at)
            return True
        return False


def refused(run_id: str) -> bool:
    """Whether the store would not keep this run's rebuilt outputs (until
    restart): its answer is final, not "being prepared"."""
    with _bookkeeping:
        return run_id in _unrecordable


# ---------------------------------------------------------------------------
# The worker loop
# ---------------------------------------------------------------------------


#: Pause before runs deferred in one pass over history are offered again.
RETRY_DEFERRED_SECONDS = 60


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
        last_cleared = time.monotonic()
        while not self._stop.is_set():
            try:
                ran = process_next(
                    self.backend, self.store, worker=name, max_bars=max_bars, large_slot=large_slot
                )
                # One skip set for both: a run put off by one backfill (a busy
                # slot, an outage) is not picked straight back up by the other.
                if ran is None and backfills:
                    ran = backfill_next(self.backend, self.store, skip=skip)
                if ran is None and backfills:
                    ran = backfill_next_replay(self.backend, self.store, skip=skip)
                if (
                    ran is None
                    and backfills
                    and time.monotonic() - last_cleared >= RETRY_DEFERRED_SECONDS
                ):
                    # A pass over history is done. Runs deferred in it (a busy
                    # slot, a timeout) are offered again -- after a pause, so
                    # an outage is not hammered -- rather than skipped for the
                    # life of the process.
                    skip.clear()
                    last_cleared = time.monotonic()
            except Exception:  # noqa: BLE001 -- a broken claim must not kill the lane
                logger.exception("run_worker_error", extra={"worker": name})
                ran = None
            if ran is None:
                self._stop.wait(POLL_SECONDS)
