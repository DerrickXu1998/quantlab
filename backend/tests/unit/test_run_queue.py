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
    assert client.get(f"/api/v1/runs/{run_id}/performance").json() == stored
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
    assert recomputed == store.get_performance(run_id)


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
