"""Backtests in the background (research.jobs): submit, queue, run, read.

Driven against the seeded demo with no background worker, so each test decides
exactly when the worker takes a step (``jobs.process_next``).
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api.app import create_app
from quantlab.research import errors, jobs, runner
from quantlab.storage import db


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("queue") / "quantlab.db"
    seed.run(path)
    return path


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.setenv("QUANTLAB_RUN_MODE", "queue")
    monkeypatch.setenv("QUANTLAB_RUN_WORKER", "off")
    with TestClient(create_app(str(db_path))) as test_client:
        yield test_client


@pytest.fixture
def symbols(client):
    return [item["symbol"] for item in client.get("/api/v1/instruments").json()["items"][:2]]


def _body(symbols, **overrides):
    body = {
        "model_name": "sma-crossover",
        "symbols": symbols,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
    }
    body.update(overrides)
    return body


def _step(client) -> str | None:
    """One worker step, as the background worker would take it."""
    app = client.app
    return jobs.process_next(app.state.backend, app.state.experiments, worker="test")


def _drain(client) -> None:
    while _step(client):
        pass


def test_submit_returns_a_queued_run_at_once(client, symbols):
    response = client.post("/api/v1/runs", json=_body(symbols))

    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "queued"
    assert run["queue_position"] >= 1
    assert run["signal_count"] == 0
    assert run["estimated_bars"] > 0
    assert run["started_at"] is None
    # The resolved strategy is recorded at submission, not at completion.
    assert run["strategy"]["components"][0]["rule_name"] == "sma-crossover"
    _drain(client)


def test_bad_requests_are_refused_before_queueing(client, symbols):
    before = client.get("/api/v1/runs").json()["total"]

    assert client.post("/api/v1/runs", json=_body(["NOPE"])).status_code == 404
    assert client.post("/api/v1/runs", json=_body(symbols, model_name="no-such")).status_code == 404
    short = _body(symbols, start_date="2024-12-20", end_date="2024-12-31")
    assert client.post("/api/v1/runs", json=short).status_code == 422

    assert client.get("/api/v1/runs").json()["total"] == before


def test_the_worker_completes_a_run_and_stores_its_performance(client, symbols):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    assert client.get(f"/api/v1/runs/{run_id}/performance").status_code == 409

    assert _step(client) == run_id

    run = client.get(f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "completed"
    assert run["started_at"] and run["finished_at"]
    assert run["queue_position"] is None
    assert run["signal_count"] == len(run["signals"])
    assert run["attempts"] == 1

    stored = client.app.state.experiments.get_performance(run_id)
    assert stored is not None
    served = client.get(f"/api/v1/runs/{run_id}/performance").json()
    assert served["reconstructed"] is False  # recorded at completion
    assert served == stored
    # The list carries the headline figures without loading the curves.
    listed = {r["id"]: r for r in client.get("/api/v1/runs").json()["items"]}
    assert listed[run_id]["metrics"] == stored["metrics"]


def test_stored_performance_matches_a_fresh_computation(client, symbols):
    """The worker computes performance from the bars the run read; reading
    them again from the store must give exactly the same figures."""
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _step(client)
    app = client.app
    store = app.state.experiments
    run = store.get_run(run_id)
    recomputed = jobs.compute_run_performance(app.state.backend, store, run)
    # The same figures; the recomputation alone says it was rebuilt.
    assert recomputed.pop("reconstructed") is True
    stored = store.get_performance(run_id)
    assert stored.pop("reconstructed") is False
    assert recomputed == stored


def test_inline_results_match_queued_results(db_path, client, symbols, monkeypatch):
    queued_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _step(client)
    queued = client.get(f"/api/v1/runs/{queued_id}").json()

    monkeypatch.setenv("QUANTLAB_RUN_MODE", "inline")
    with TestClient(create_app(str(db_path))) as inline_client:
        response = inline_client.post("/api/v1/runs", json=_body(symbols))
        assert response.status_code == 201
        inline = inline_client.get(f"/api/v1/runs/{response.json()['id']}").json()

    assert inline["signal_count"] == queued["signal_count"]
    assert inline["signals"] == queued["signals"]
    assert inline["execution_summary"] == queued["execution_summary"]


def test_runs_are_taken_in_submission_order(client, symbols):
    _drain(client)
    first = client.post("/api/v1/runs", json=_body(symbols)).json()
    second = client.post("/api/v1/runs", json=_body(symbols[:1])).json()
    assert (first["queue_position"], second["queue_position"]) == (1, 2)

    listed = {r["id"]: r for r in client.get("/api/v1/runs").json()["items"]}
    assert listed[second["id"]]["queue_position"] == 2

    assert _step(client) == first["id"]
    assert client.get(f"/api/v1/runs/{second['id']}").json()["queue_position"] == 1
    assert _step(client) == second["id"]


def test_cancel_a_queued_run(client, symbols):
    _drain(client)
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]

    response = client.post(f"/api/v1/runs/{run_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert _step(client) is None  # nothing left to run
    assert client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 409


def test_cancel_a_running_run_records_nothing(client, symbols):
    _drain(client)
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    store = client.app.state.experiments
    store.claim_next_run("elsewhere", 60)  # another worker has it

    response = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert response.json()["status"] == "running"
    assert response.json()["cancel_requested"] is True

    # The worker reaches a checkpoint and stops without writing results.
    claimed = {"id": run_id, "request": store.get_run(run_id) and _request_of(store, run_id)}
    jobs._execute_claimed(
        client.app.state.backend, store, claimed, worker="elsewhere", large_slot=False
    )
    run = client.get(f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "cancelled"
    assert run["signals"] == []
    assert store.get_performance(run_id) is None


def _request_of(store, run_id):
    with db.connect(store.db_path) as conn:
        (raw,) = conn.execute(
            "SELECT request FROM experiment_runs WHERE id = ?", (run_id,)
        ).fetchone()
    import json

    return json.loads(raw)


def test_a_failure_while_running_is_recorded_with_its_category(client, symbols, monkeypatch):
    _drain(client)
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]

    def no_filings(*args, **kwargs):
        raise errors.NoFactCoverageError(["Revenues"], 2, "2024-12-31")

    monkeypatch.setattr(runner, "execute_prepared", no_filings)
    _step(client)

    run = client.get(f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["error_category"] == "data"
    assert "Revenues" in run["error"]


def test_an_unexpected_crash_is_a_worker_failure(client, symbols, monkeypatch):
    _drain(client)
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]

    def boom(*args, **kwargs):
        raise MemoryError()

    monkeypatch.setattr(runner, "execute_prepared", boom)
    _step(client)

    run = client.get(f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["error_category"] == "worker"
    assert "memory" in run["error"]


def test_a_run_whose_worker_died_is_queued_again_then_failed(client, symbols):
    _drain(client)
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    store = client.app.state.experiments

    for attempt in range(1, jobs.MAX_ATTEMPTS + 1):
        assert store.claim_next_run("dead", lease_seconds=-1)["attempts"] == attempt
        outcome = store.recover_stale_runs(jobs.MAX_ATTEMPTS)
        if attempt < jobs.MAX_ATTEMPTS:
            assert outcome["requeued"] == 1
            assert store.get_run(run_id)["status"] == "queued"

    assert outcome["failed"] == 1
    run = store.get_run(run_id)
    assert run["status"] == "failed"
    assert run["error_category"] == "worker"


def test_the_quick_lane_skips_large_runs(client, symbols):
    _drain(client)
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    app = client.app

    took = jobs.process_next(app.state.backend, app.state.experiments, max_bars=1)

    assert took is None
    assert app.state.experiments.get_run(run_id)["status"] == "queued"
    _drain(client)


def test_legacy_runs_get_performance_computed_once_and_stored(db_path, symbols, monkeypatch):
    monkeypatch.setenv("QUANTLAB_RUN_MODE", "inline")
    with TestClient(create_app(str(db_path))) as inline_client:
        run_id = inline_client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
        store = inline_client.app.state.experiments
        # Inline runs now store theirs at completion; forget it, as if the run
        # had been recorded before results were stored.
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE experiment_runs SET performance = NULL, headline = NULL WHERE id = ?",
                (run_id,),
            )
        assert store.get_performance(run_id) is None

        first = inline_client.get(f"/api/v1/runs/{run_id}/performance").json()

        assert store.get_performance(run_id) == first


def test_an_old_demo_database_is_widened_without_losing_signals(tmp_path):
    """Files from before the queue constrain status to completed/failed. The
    rebuild that widens it must keep every run and every run's signals."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE instruments (symbol TEXT PRIMARY KEY);
        INSERT INTO instruments VALUES ('AAA');
        CREATE TABLE experiment_runs (
            id TEXT PRIMARY KEY, name TEXT,
            status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
            error TEXT, owner_id TEXT,
            CHECK ((status = 'failed') = (error IS NOT NULL))
        );
        CREATE TABLE experiment_signals (
            run_id TEXT NOT NULL REFERENCES experiment_runs (id) ON DELETE CASCADE,
            symbol TEXT NOT NULL REFERENCES instruments (symbol),
            date TEXT NOT NULL
        );
        INSERT INTO experiment_runs VALUES ('r1', 'kept', 'completed', NULL, 'u1');
        INSERT INTO experiment_signals VALUES ('r1', 'AAA', '2024-01-02');
        """
    )
    conn.commit()
    conn.close()

    conn = db.connect(path)
    applied = db.migrate(conn)
    conn.commit()

    assert "experiment_runs.status" in applied
    assert conn.execute("SELECT name, owner_id FROM experiment_runs").fetchall() == [("kept", "u1")]
    assert conn.execute("SELECT count(*) FROM experiment_signals").fetchone() == (1,)
    conn.execute("INSERT INTO experiment_runs (id, status) VALUES ('r2', 'queued')")
    assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert db.migrate(conn) == []  # idempotent


def test_the_in_process_worker_runs_a_submitted_run(db_path, monkeypatch):
    """The default development setup: the API starts its own worker and a
    submitted run completes without anyone driving the queue."""
    import time

    monkeypatch.setenv("QUANTLAB_RUN_MODE", "queue")
    monkeypatch.setenv("QUANTLAB_RUN_WORKER", "inprocess")
    with TestClient(create_app(str(db_path))) as live:
        symbols = [i["symbol"] for i in live.get("/api/v1/instruments").json()["items"][:1]]
        run_id = live.post("/api/v1/runs", json=_body(symbols)).json()["id"]
        deadline = time.monotonic() + 20
        status = "queued"
        while time.monotonic() < deadline and status in ("queued", "running"):
            time.sleep(0.2)
            status = live.get(f"/api/v1/runs/{run_id}").json()["status"]
        assert status == "completed"
        assert live.app.state.run_worker is not None


# --- replays are recorded at completion, never re-simulated on request --------


def test_the_worker_records_the_replay_as_the_run_completes(client, symbols):
    from quantlab.replay import recording

    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    stored = client.app.state.experiments.get_replay(run_id)
    assert stored is not None and stored["error"] is None
    assert stored["reconstructed"] is False
    frames = list(recording.frames(stored["events"]))
    assert frames[-1]["event"] == "summary"
    response = client.get(f"/api/v1/runs/{run_id}/replay/stream")
    assert response.headers["x-replay-source"] == "recorded"
    summary = client.get(f"/api/v1/runs/{run_id}/replay/summary").json()
    performance = client.get(f"/api/v1/runs/{run_id}/performance").json()
    assert summary["final_equity"] == pytest.approx(performance["equity"][-1]["value"])


def _inline(client, monkeypatch):
    """Inline mode from here on: no worker, so requests rebuild old runs."""
    monkeypatch.setattr(client.app.state, "run_mode", "inline", raising=False)


def _forget_replay(db_path, run_id):
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM experiment_replays WHERE run_id = ?", (run_id,))


def test_a_large_older_run_is_prepared_by_the_worker_not_in_the_request(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    monkeypatch.setattr(runner, "LARGE_RUN_BARS", 0)  # every run is large now

    pending = client.get(f"/api/v1/runs/{run_id}/replay/summary")
    assert pending.status_code == 409
    assert pending.headers["retry-after"] == "5"
    assert client.get(f"/api/v1/runs/{run_id}/replay/stream").status_code == 409

    app = client.app
    while jobs.backfill_next_replay(app.state.backend, app.state.experiments) is not None:
        pass
    summary = client.get(f"/api/v1/runs/{run_id}/replay/summary").json()
    assert summary["reconstructed"] is True
    assert (
        client.get(f"/api/v1/runs/{run_id}/replay/stream").headers["x-replay-source"]
        == "reconstructed"
    )


def test_with_a_worker_an_old_run_is_rebuilt_by_it_never_in_the_request(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)

    def must_not_run(*args, **kwargs):
        raise AssertionError("re-executed an old run in the API process")

    with monkeypatch.context() as patched:
        patched.setattr(jobs, "rebuild_results", must_not_run)
        assert client.get(f"/api/v1/runs/{run_id}/replay/summary").status_code == 409
    store = client.app.state.experiments
    assert jobs.backfill_next_replay(client.app.state.backend, store, skip=set()) == run_id
    assert client.get(f"/api/v1/runs/{run_id}/replay/summary").json()["reconstructed"] is True


def test_with_no_worker_an_old_run_is_rebuilt_once_in_the_request(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    _inline(client, monkeypatch)

    first = client.get(f"/api/v1/runs/{run_id}/replay/summary")
    assert first.status_code == 200 and first.json()["reconstructed"] is True
    assert client.get(f"/api/v1/runs/{run_id}/replay/summary").json() == first.json()


def test_a_transient_failure_defers_a_rebuild_rather_than_failing_it(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)

    def flaky(*args, **kwargs):
        raise TimeoutError("warehouse timed out")

    monkeypatch.setattr(jobs, "rebuild_results", flaky)
    app = client.app
    skip: set[str] = set()
    while jobs.backfill_next_replay(app.state.backend, app.state.experiments, skip=skip):
        pass
    assert run_id in skip
    assert app.state.experiments.get_replay(run_id) is None  # nothing stored: retried later


def test_a_replay_that_cannot_be_rebuilt_says_why_and_is_not_retried(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)

    def broken(*args, **kwargs):
        raise RuntimeError("bars for this window are gone")

    monkeypatch.setattr(jobs, "rebuild_results", broken)
    app = client.app
    seen = []
    while (ran := jobs.backfill_next_replay(app.state.backend, app.state.experiments)):
        seen.append(ran)
        assert len(seen) < 50, "a failed rebuild must not be retried"
    assert run_id in seen

    response = client.get(f"/api/v1/runs/{run_id}/replay/summary")
    assert response.status_code == 422
    assert "bars for this window are gone" in response.json()["detail"]
    assert app.state.experiments.next_run_without_replay() is None


def test_a_recorded_replay_is_never_overwritten_by_a_reconstruction(client, symbols):
    from quantlab.replay import recording

    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    store = client.app.state.experiments
    original = store.get_replay(run_id)
    imposter = recording.RecordedReplay(events=b"", summary={}, reconstructed=True)
    store.set_rebuilt(run_id, jobs.RunOutputs(None, imposter))
    assert store.get_replay(run_id) == original


def test_a_replay_that_cannot_be_recorded_does_not_fail_the_run(client, symbols, monkeypatch):
    from quantlab.replay import recording

    def broken(*args, **kwargs):
        raise RuntimeError("cannot encode this stream")

    monkeypatch.setattr(recording, "record", broken)
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)

    assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "completed"
    assert client.get(f"/api/v1/runs/{run_id}/performance").status_code == 200
    replay = client.get(f"/api/v1/runs/{run_id}/replay/summary")
    assert replay.status_code == 422
    assert "cannot encode this stream" in replay.json()["detail"]


def test_one_walk_records_the_same_performance_as_a_fresh_computation(client, symbols):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    app = client.app
    store = app.state.experiments
    fresh = jobs.compute_run_performance(app.state.backend, store, store.get_run(run_id))
    assert fresh.pop("reconstructed") is True
    stored = store.get_performance(run_id)
    assert stored.pop("reconstructed") is False
    assert stored == fresh


def test_an_inline_run_whose_results_fail_to_record_is_still_saved(
    db_path, symbols, monkeypatch
):
    monkeypatch.setenv("QUANTLAB_RUN_MODE", "inline")

    def broken(*args, **kwargs):
        raise RuntimeError("minute source unavailable")

    monkeypatch.setattr(jobs, "record_results", broken)
    with TestClient(create_app(str(db_path))) as inline_client:
        created = inline_client.post("/api/v1/runs", json=_body(symbols))
        assert created.status_code == 201
        run_id = created.json()["id"]
        monkeypatch.undo()
        monkeypatch.setenv("QUANTLAB_RUN_MODE", "inline")
        # Computed once on first view, as for a run recorded before results were.
        assert inline_client.get(f"/api/v1/runs/{run_id}/performance").status_code == 200


def test_what_counts_as_a_transient_failure():
    assert jobs.transient(TimeoutError("read timed out"))
    assert jobs.transient(ConnectionResetError())
    assert jobs.transient(sqlite3.OperationalError("database is locked"))
    assert not jobs.transient(sqlite3.OperationalError("no such table: price_bars"))
    assert not jobs.transient(FileNotFoundError("bars.parquet"))
    assert not jobs.transient(MemoryError())
    assert not jobs.transient(errors.UnknownSymbolError(["GONE"]))

    class OperationalError(Exception):
        pass

    OperationalError.__module__ = "clickhouse_connect.driver.exceptions"
    assert jobs.transient(OperationalError("connection dropped"))


def test_a_rebuild_that_keeps_timing_out_is_failed_only_after_hours(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)

    def always_times_out(*args, **kwargs):
        raise TimeoutError("statement timeout")

    monkeypatch.setattr(jobs, "rebuild_results", always_times_out)
    app = client.app
    clock = {"now": 1000.0}
    monkeypatch.setattr(jobs.time, "monotonic", lambda: clock["now"])
    # A short outage, retried many times: deferred, never failed.
    for _ in range(10):
        jobs.backfill_next_replay(app.state.backend, app.state.experiments, skip=set())
        clock["now"] += 60
    assert app.state.experiments.get_replay(run_id) is None
    # One blip hours later is a new outage, not the old one: still deferred.
    clock["now"] += jobs.MAX_DEFER_SECONDS
    jobs.backfill_next_replay(app.state.backend, app.state.experiments, skip=set())
    assert app.state.experiments.get_replay(run_id) is None
    # Failing on every pass for hours on end: that is the answer, and stored.
    while app.state.experiments.get_replay(run_id) is None:
        clock["now"] += jobs.OUTAGE_GAP_SECONDS / 2
        jobs.backfill_next_replay(app.state.backend, app.state.experiments, skip=set())
    stored = app.state.experiments.get_replay(run_id)
    assert "statement timeout" in stored["error"]


def test_a_requests_retries_never_fail_an_old_runs_replay(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    _inline(client, monkeypatch)

    def always_times_out(*args, **kwargs):
        raise TimeoutError("warehouse unreachable")

    monkeypatch.setattr(jobs, "rebuild_results", always_times_out)
    calls = {"n": 0}
    real = jobs.rebuild_old_run

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(jobs, "rebuild_old_run", counted)
    # A client retrying through a short outage: "being prepared", never a
    # stored failure -- and the cool-down keeps it from re-running each time.
    for _ in range(5):
        assert client.get(f"/api/v1/runs/{run_id}/replay/summary").status_code == 409
    assert client.app.state.experiments.get_replay(run_id) is None
    assert jobs._first_deferred[run_id]  # one outage, timed from the first failure


def test_a_rebuild_whose_performance_fails_says_why_and_keeps_the_replay(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE experiment_runs SET performance = NULL, headline = NULL WHERE id = ?",
            (run_id,),
        )

    def broken(*args, **kwargs):
        raise ValueError("benchmark has no first close")

    monkeypatch.setattr(jobs, "_performance", broken)
    app = client.app
    store = app.state.experiments
    jobs.rebuild_old_run(app.state.backend, store, store.get_run(run_id))
    assert store.get_replay(run_id, events=False)["error"] is None  # replay kept
    row = {r["id"]: r for r in client.get("/api/v1/runs").json()["items"]}[run_id]
    assert "benchmark has no first close" in row["results_error"]


def test_a_replay_row_needs_a_stream_or_a_reason(client, symbols):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    store = client.app.state.experiments
    with pytest.raises(ValueError, match="either"):
        with store._connect() as conn:
            store._insert_replay(conn, run_id, None, "")


def test_the_large_run_test_counts_the_warm_up_a_rebuild_loads(monkeypatch):
    run = {
        "id": "r", "symbols": ["A"], "start_date": "2024-06-01", "end_date": "2024-06-30",
        "model_name": "sma-crossover", "parameters": {"fast": 20, "slow": 200},
    }
    window = runner.estimate_bars(1, run["start_date"], run["end_date"], "1d")
    monkeypatch.setattr(runner, "LARGE_RUN_BARS", window)  # window alone is not large
    assert jobs.is_large_run(run)


def test_a_performance_failure_at_completion_is_stored_not_recomputed_later(
    client, symbols, monkeypatch
):
    def broken(*args, **kwargs):
        raise ValueError("benchmark has no first close")

    monkeypatch.setattr(jobs, "_performance", broken)
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    monkeypatch.undo()
    store = client.app.state.experiments
    assert store.get_replay(run_id, events=False)["error"] is None  # recorded
    response = client.get(f"/api/v1/runs/{run_id}/performance")
    assert response.status_code == 422
    assert "benchmark has no first close" in response.json()["detail"]
    # Not offered to the backfill: its answer is stored.
    assert run_id != (store.next_run_without_results() or {}).get("id")


def test_a_rebuild_with_nothing_missing_does_no_work(client, symbols, monkeypatch):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)

    def must_not_run(*args, **kwargs):
        raise AssertionError("re-executed a run that needed nothing")

    monkeypatch.setattr(jobs, "rebuild_results", must_not_run)
    monkeypatch.setattr(jobs, "compute_run_performance", must_not_run)
    store = client.app.state.experiments
    assert jobs.rebuild_old_run(client.app.state.backend, store, store.get_run(run_id)) == run_id


def test_memory_pressure_while_rebuilding_is_retried_not_stored(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)

    def out_of_memory(*args, **kwargs):
        raise MemoryError()

    monkeypatch.setattr(jobs, "rebuild_results", out_of_memory)
    app = client.app
    jobs.backfill_next_replay(app.state.backend, app.state.experiments, skip=set())
    assert app.state.experiments.get_replay(run_id) is None


def test_a_driver_misconfiguration_is_not_transient():
    class OperationalError(Exception):
        pass

    OperationalError.__module__ = "psycopg"
    assert jobs.transient(OperationalError("server closed the connection unexpectedly"))
    assert not jobs.transient(OperationalError('password authentication failed for "ql"'))
    assert not jobs.transient(OperationalError('database "quantlab" does not exist'))


def test_an_old_run_whose_spec_cannot_be_sized_says_why_not_500(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    _inline(client, monkeypatch)

    def unreadable(run):
        raise TypeError("'>' not supported between instances of 'int' and 'str'")

    monkeypatch.setattr(jobs, "is_large_run", unreadable)
    response = client.get(f"/api/v1/runs/{run_id}/replay/summary")
    assert response.status_code == 422
    assert "not supported" in response.json()["detail"]


def test_a_stream_never_started_still_frees_its_slot(client, symbols, monkeypatch):
    import gc

    from quantlab.api import routes

    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    dropped = []

    class Unsent:  # a response whose client left before it was sent
        def __init__(self, content, **kwargs):
            dropped.append(content)

    monkeypatch.setattr(routes, "StreamingResponse", Unsent)
    for _ in range(routes._STREAM_SLOTS_PER_USER + 1):
        # Answered, but the stream itself never runs: had its slot leaked,
        # the last of these would be refused (429).
        assert client.get(f"/api/v1/runs/{run_id}/replay/stream").status_code == 200
        assert dropped
        dropped.clear()
        gc.collect()
    assert not client.app.state._stream_slots._counts


def test_a_rebuild_the_store_refuses_is_not_re_walked_every_minute(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    app = client.app
    store = app.state.experiments
    walks = {"n": 0}
    real = jobs.rebuild_results

    def counted(backend, store, run, **kwargs):
        walks["n"] += run["id"] == run_id
        return real(backend, store, run, **kwargs)

    def refuses(*args, **kwargs):
        raise ValueError("unsupported Unicode escape sequence")

    monkeypatch.setattr(jobs, "rebuild_results", counted)
    monkeypatch.setattr(store, "set_rebuilt", refuses)
    monkeypatch.setattr(jobs, "_unrecordable", set())
    assert jobs.backfill_next_replay(app.state.backend, store, skip=set()) == run_id
    # The worker's skip set is cleared each minute: a fresh one, as then.
    assert jobs.backfill_next_replay(app.state.backend, store, skip=set()) != run_id
    assert walks["n"] == 1


def test_the_cool_down_starts_when_a_slow_rebuild_fails(client, symbols, db_path, monkeypatch):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    _inline(client, monkeypatch)
    clock = {"t": 1000.0}
    monkeypatch.setattr(jobs.time, "monotonic", lambda: clock["t"])

    def slow_timeout(*args, **kwargs):
        clock["t"] += 40  # longer than the cool-down itself
        raise TimeoutError("warehouse read timed out")

    monkeypatch.setattr(jobs, "rebuild_results", slow_timeout)
    assert client.get(f"/api/v1/runs/{run_id}/replay/summary").status_code == 409
    assert jobs._last_retryable[run_id] == 1040.0
    clock["t"] += 5  # the client's Retry-After

    def must_not_run(*args, **kwargs):
        raise AssertionError("re-ran inside the cool-down")

    monkeypatch.setattr(jobs, "rebuild_results", must_not_run)
    assert client.get(f"/api/v1/runs/{run_id}/replay/summary").status_code == 409


def test_a_summary_with_every_stream_slot_taken_is_being_prepared_not_429(
    client, symbols, db_path, monkeypatch
):
    from quantlab.api import routes

    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    _inline(client, monkeypatch)
    client.get("/api/v1/runs")  # creates the app's slot table
    slots = client.app.state._stream_slots = routes._StreamSlots()
    user = client.get("/api/v1/runs/" + run_id).json().get("owner_id") or "local"
    for _ in range(routes._STREAM_SLOTS_PER_USER):
        slots.acquire(user)
    response = client.get(f"/api/v1/runs/{run_id}/replay/summary")
    assert response.status_code == 409, response.json()


def test_a_refused_replay_write_never_fails_the_finished_backtest(client, symbols, monkeypatch):
    store = client.app.state.experiments

    real = type(store)._insert_replay

    def statement_timeout(conn, run_id, replay, error):
        if replay is not None:  # the blob is too big; a reason row is not
            raise ValueError("value too long for type bytea")
        return real(conn, run_id, replay, error)

    monkeypatch.setattr(type(store), "_insert_replay", staticmethod(statement_timeout))
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    monkeypatch.undo()
    run = store.get_run(run_id)
    assert run["status"] == "completed"  # the backtest stands...
    # ...and says why its exact record is missing, rather than being
    # re-simulated on later data and passed off as a reconstruction.
    assert "could not be stored" in store.get_replay(run_id)["error"]
    assert store.get_run_signals(run_id)


def test_any_number_of_excluded_runs_is_one_query_parameter(client, symbols):
    store = client.app.state.experiments
    excluded = [f"gone-{i}" for i in range(5000)]  # past SQLite's variable limit
    store.next_run_without_replay(exclude=excluded)
    store.next_run_without_results(exclude=excluded)


def test_a_run_cancelled_as_it_finishes_is_not_walked_again_to_record(
    client, symbols, monkeypatch
):
    def must_not_record(*args, **kwargs):
        raise AssertionError("recorded a cancelled run")

    cancelled = {"now": False}
    real = runner.execute_prepared

    def finishes_then_cancelled(*args, **kwargs):
        result = real(*args, **kwargs)
        cancelled["now"] = True  # the user's cancel lands as it completes
        return result

    monkeypatch.setattr(jobs, "record_results", must_not_record)
    monkeypatch.setattr(runner, "execute_prepared", finishes_then_cancelled)
    app = client.app
    prepared = runner.prepare_run(
        app.state.backend, model_name="sma-crossover", overrides={}, symbols=symbols,
        start_date="2024-01-01", end_date="2024-12-31",
    )
    result, outputs = jobs.execute_and_record(
        app.state.backend, prepared, wait_seconds=0, should_cancel=lambda: cancelled["now"]
    )
    assert result.status == "completed" and outputs is None


def test_a_refused_replay_keeps_the_runs_exact_performance(client, symbols, monkeypatch):
    store = client.app.state.experiments

    real = type(store)._insert_replay

    def statement_timeout(conn, run_id, replay, error):
        if replay is not None:  # the blob is too big; a reason row is not
            raise ValueError("value too long for type bytea")
        return real(conn, run_id, replay, error)

    monkeypatch.setattr(type(store), "_insert_replay", staticmethod(statement_timeout))
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    monkeypatch.undo()
    assert store.get_performance(run_id) is not None  # from the run's own bars
    assert "could not be stored" in store.get_replay(run_id)["error"]


def test_a_brief_store_failure_after_a_rebuild_is_retried_not_given_up(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    store = client.app.state.experiments

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "set_rebuilt", locked)
    monkeypatch.setattr(jobs, "_unrecordable", set())
    jobs.backfill_next_replay(client.app.state.backend, store, skip=set())
    assert run_id not in jobs._unrecordable  # offered again once the lock passes


def test_requests_leave_a_run_the_store_refused_alone(client, symbols, db_path, monkeypatch):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)

    def must_not_run(*args, **kwargs):
        raise AssertionError("re-ran a run whose outputs the store refuses")

    monkeypatch.setattr(jobs, "_unrecordable", {run_id})
    monkeypatch.setattr(jobs, "rebuild_results", must_not_run)
    # A final answer, not "being prepared": nothing is preparing it.
    response = client.get(f"/api/v1/runs/{run_id}/replay/summary")
    assert response.status_code == 422
    assert "could not be stored" in response.json()["detail"]


def test_the_bars_are_let_go_inside_the_large_run_slot(client, symbols):
    app = client.app
    prepared = runner.prepare_run(
        app.state.backend, model_name="sma-crossover", overrides={}, symbols=symbols,
        start_date="2024-01-01", end_date="2024-12-31",
    )
    result, outputs = jobs.execute_and_record(app.state.backend, prepared, wait_seconds=0)
    assert outputs is not None and result.bars is None and result.traded_on is None


def test_a_store_that_keeps_dropping_is_given_up_on_after_the_outage_clock(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    store = client.app.state.experiments
    clock = {"t": 0.0}
    monkeypatch.setattr(jobs.time, "monotonic", lambda: clock["t"])

    def dropped(*args, **kwargs):
        raise ConnectionError("server closed the connection unexpectedly")

    monkeypatch.setattr(store, "set_rebuilt", dropped)
    monkeypatch.setattr(jobs, "_unrecordable", set())
    monkeypatch.setattr(jobs, "_first_deferred", {})
    backend = client.app.state.backend
    jobs.backfill_next_replay(backend, store, skip=set())
    assert run_id not in jobs._unrecordable  # a blip: offered again
    for _ in range(int(jobs.MAX_DEFER_SECONDS // 1800) + 1):  # one pass every 30 min
        clock["t"] += 1800
        jobs.rebuild_old_run(backend, store, store.get_run(run_id), set())
    assert run_id in jobs._unrecordable  # not re-walked every minute forever


def test_a_write_too_big_for_the_store_is_final_at_once(client, symbols, db_path, monkeypatch):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    store = client.app.state.experiments

    class ProgramLimitExceeded(Exception):
        pass

    ProgramLimitExceeded.__module__ = "psycopg.errors"

    def too_big(*args, **kwargs):
        raise ProgramLimitExceeded("total size of jsonb object elements exceeds the maximum")

    monkeypatch.setattr(store, "set_rebuilt", too_big)
    monkeypatch.setattr(jobs, "_unrecordable", set())
    jobs.backfill_next_replay(client.app.state.backend, store, skip=set())
    assert run_id in jobs._unrecordable  # not re-walked every minute for 6 hours


def test_a_summary_with_a_figure_that_is_no_number_is_still_served():
    from quantlab.api import schemas

    summary = schemas.ReplaySummary(
        run_id="r", days=1, initial_cash=1.0, final_equity=None, total_return=None,
        max_drawdown=None, trade_count=0, winning_trades=0, losing_trades=0,
        assumptions=[], total_borrow=None, total_commission=None,
    )
    assert summary.total_borrow is None


def test_a_refused_rebuild_is_a_final_answer_in_every_process(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    store = client.app.state.experiments
    real = store.set_rebuilt
    calls = {"n": 0}

    def refuses_the_blob_once(run, outputs, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:  # the rebuilt record: too big
            raise ValueError("value too long for type bytea")
        return real(run, outputs, **kwargs)  # the reason: a small row, kept

    monkeypatch.setattr(store, "set_rebuilt", refuses_the_blob_once)
    monkeypatch.setattr(jobs, "_unrecordable", set())
    jobs.backfill_next_replay(client.app.state.backend, store, skip=set())
    assert run_id not in jobs._unrecordable  # nothing held only in this process
    # Another process (the API, beside an external worker) reads the stored answer.
    response = client.get(f"/api/v1/runs/{run_id}/replay/summary")
    assert response.status_code == 422
    assert "would not keep it" in response.json()["detail"]


def test_a_refused_performance_write_keeps_why_not_a_later_rebuild(
    client, symbols, monkeypatch
):
    store = client.app.state.experiments
    real = type(store)._write_performance

    def statement_timeout(conn, run_id, performance, *, where_unset=False):
        raise ValueError("value too long for type bytea")

    monkeypatch.setattr(type(store), "_write_performance", staticmethod(statement_timeout))
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    monkeypatch.setattr(type(store), "_write_performance", staticmethod(real))
    assert store.get_run(run_id)["status"] == "completed"
    assert store.get_replay(run_id)["error"] is None  # the exact replay is kept
    response = client.get(f"/api/v1/runs/{run_id}/performance")
    assert response.status_code == 422  # never silently rebuilt on later data
    assert "could not be stored" in response.json()["detail"]


def test_a_run_records_where_its_bars_began(client, symbols):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    run = client.app.state.experiments.get_run(run_id)
    assert run["execution_summary"]["loaded_from"] < run["start_date"]


def test_a_rebuilt_runs_performance_says_it_was_rebuilt(db_path, client, symbols, monkeypatch):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE experiment_runs SET performance = NULL, headline = NULL WHERE id = ?",
            (run_id,),
        )
    app = client.app
    assert jobs.backfill_next(app.state.backend, app.state.experiments) == run_id
    assert client.get(f"/api/v1/runs/{run_id}/performance").json()["reconstructed"] is True


def test_a_pool_that_is_briefly_full_is_a_blip_not_a_final_answer(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    store = client.app.state.experiments

    class PoolTimeout(Exception):
        pass

    PoolTimeout.__module__ = "psycopg_pool"

    def pool_full(*args, **kwargs):
        raise PoolTimeout("couldn't get a connection after 30.00 sec")

    monkeypatch.setattr(store, "set_rebuilt", pool_full)
    monkeypatch.setattr(jobs, "_unrecordable", set())
    monkeypatch.setattr(jobs, "_first_deferred", {})
    jobs.backfill_next_replay(client.app.state.backend, store, skip=set())
    monkeypatch.undo()
    assert store.get_replay(run_id) is None  # no stored failure: retried later
    assert run_id not in jobs._unrecordable


def test_a_rebuilds_two_outputs_commit_together(client, symbols, db_path, monkeypatch):
    from quantlab.replay.recording import RecordedReplay

    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    store = client.app.state.experiments
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE experiment_runs SET performance = NULL WHERE id = ?", (run_id,))
        conn.execute("DELETE FROM experiment_replays WHERE run_id = ?", (run_id,))

    def dies(*args, **kwargs):
        raise KeyboardInterrupt  # the process stops between the two writes

    monkeypatch.setattr(type(store), "_insert_replay", staticmethod(dies))
    outputs = jobs.RunOutputs({"metrics": {}}, RecordedReplay(events=b"x", summary={}))
    with pytest.raises(KeyboardInterrupt):
        store.set_rebuilt(run_id, outputs)
    monkeypatch.undo()
    assert store.get_performance(run_id) is None  # not committed on its own


def test_a_lock_blip_on_the_replay_at_completion_is_not_a_final_answer(
    client, symbols, monkeypatch
):
    store = client.app.state.experiments
    real = type(store)._insert_replay

    def lock_timeout(conn, run_id, replay, error):
        if replay is not None:
            raise TimeoutError("canceling statement due to lock timeout")
        return real(conn, run_id, replay, error)

    monkeypatch.setattr(type(store), "_insert_replay", staticmethod(lock_timeout))
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    assert store.get_run(run_id)["status"] == "completed"
    assert store.get_performance(run_id) is not None
    assert store.get_replay(run_id) is None  # unset: rebuilt later, not failed for good


@pytest.mark.parametrize(
    ("message", "refused"),
    [
        ("canceling statement due to statement timeout", False),  # an IO stall too
        ("value too long for type character varying(10)", True),
        ("canceling statement due to lock timeout", False),
        ("canceling statement due to user request", False),  # an operator, a shutdown
        ("deadlock detected", False),
        ("server closed the connection unexpectedly", False),
    ],
)
def test_only_a_write_the_store_will_refuse_again_is_final(message, refused):
    from quantlab.storage import db

    assert db.write_refused(RuntimeError(message)) is refused


def test_a_store_not_migrated_yet_never_fails_the_runs_it_touches(
    client, symbols, db_path, monkeypatch
):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    _forget_replay(db_path, run_id)
    store = client.app.state.experiments

    class UndefinedTable(Exception):
        pass

    UndefinedTable.__module__ = "psycopg.errors"

    def ahead_of_its_migration(*args, **kwargs):
        raise UndefinedTable('relation "experiment_replays" does not exist')

    monkeypatch.setattr(store, "set_rebuilt", ahead_of_its_migration)
    monkeypatch.setattr(jobs, "_unrecordable", set())
    monkeypatch.setattr(jobs, "_first_deferred", {})
    jobs.backfill_next_replay(client.app.state.backend, store, skip=set())
    monkeypatch.undo()
    assert store.get_replay(run_id) is None  # deferred: rebuilt once migrated
    assert run_id not in jobs._unrecordable


def test_a_blip_at_completion_keeps_the_exact_replay_in_hand(client, symbols, monkeypatch):
    store = client.app.state.experiments
    real = type(store)._insert_replay
    calls = {"n": 0}

    def locked_once(conn, run_id, replay, error):
        calls["n"] += 1
        if calls["n"] == 1:  # inside the run's own transaction
            raise sqlite3.OperationalError("database is locked")
        return real(conn, run_id, replay, error)

    monkeypatch.setattr(type(store), "_insert_replay", staticmethod(locked_once))
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    replay = store.get_replay(run_id, events=False)
    assert replay is not None and replay["error"] is None
    assert replay["reconstructed"] is False  # what the run did, not a rebuild


def test_a_dns_blip_is_an_outage_however_it_is_worded():
    class ConnectError(Exception):
        pass

    ConnectError.__module__ = "httpx"
    assert jobs.transient(ConnectError("[Errno 8] nodename nor servname provided, or not known"))
    assert jobs.transient(ConnectError("No such host is known"))


def test_a_runs_exact_performance_is_never_replaced_by_a_replay_rebuild(
    client, symbols, db_path
):
    import json

    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    store = client.app.state.experiments
    exact = store.get_performance(run_id)
    exact.pop("reconstructed")  # as a build before this one stored it
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE experiment_runs SET performance = ? WHERE id = ?",
            (json.dumps(exact), run_id),
        )
    _forget_replay(db_path, run_id)  # it predates recorded replays
    jobs.backfill_next_replay(client.app.state.backend, store, skip=set())
    assert store.get_performance(run_id) == exact  # still the recorded one
    assert store.get_replay(run_id, events=False)["summary"]["reconstructed"] is True



def test_a_closed_pooled_connection_is_an_outage():
    class InterfaceError(Exception):
        pass

    InterfaceError.__module__ = "psycopg"
    assert jobs.transient(InterfaceError("the connection is closed"))


class _Store:
    """Just enough of a store for keep_outputs: nothing stored yet."""

    def __init__(self):
        self.sent = []

    def get_run(self, run_id):
        return {"id": run_id}

    def has_performance(self, run_id):
        return False

    def get_replay(self, run_id, events=True):
        return None

    def set_rebuilt(self, run_id, outputs):
        self.sent.append(outputs)


def test_a_dropped_reason_is_sent_again_like_an_output():
    """Why performance could not be computed is the run's answer: lost to a
    blip, the backfill would re-simulate it on today's data instead."""
    store = _Store()
    jobs.keep_outputs(
        store, "r1", jobs.RunOutputs(None, None, replay_error="r", performance_error="p")
    )
    assert store.sent == [jobs.RunOutputs(None, None, replay_error="r", performance_error="p")]


def test_nothing_is_kept_for_a_run_deleted_meanwhile():
    class Gone(_Store):
        def get_run(self, run_id):
            return None

    store = Gone()
    jobs.keep_outputs(store, "r1", jobs.RunOutputs(None, None, replay_error="r"))
    assert store.sent == []


def test_a_stored_reason_is_never_overwritten_by_a_rebuild(client, symbols, db_path):
    """First writer wins for performance OR why there is none: the store
    holds that rule, so no caller has to remember it."""
    store = client.app.state.experiments
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    _drain(client)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE experiment_runs SET performance = NULL, headline = NULL, "
            "performance_error = 'recorded reason' WHERE id = ?",
            (run_id,),
        )
    store.set_rebuilt(run_id, jobs.RunOutputs({"rebuilt": True}, None))
    assert store.get_performance(run_id) is None
    assert store.get_run(run_id)["results_error"] == "recorded reason"
