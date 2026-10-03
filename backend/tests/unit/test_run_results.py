"""A run's results are stored and read, never recomputed on view.

Runs recorded before results were stored get them computed once by the worker
(jobs.backfill_next), newest first; the API answers "being prepared" until then.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api.app import create_app
from quantlab.research import errors, jobs
from quantlab.storage.experiments import run_summary


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("results") / "quantlab.db"
    seed.run(path)
    return path


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.setenv("QUANTLAB_RUN_MODE", "queue")
    monkeypatch.setenv("QUANTLAB_RUN_WORKER", "off")
    with TestClient(create_app(str(db_path))) as test_client:
        # Each test starts with nothing left to backfill.
        app = test_client.app
        while jobs.backfill_next(app.state.backend, app.state.experiments):
            pass
        yield test_client


@pytest.fixture
def symbols(client):
    return [item["symbol"] for item in client.get("/api/v1/instruments").json()["items"][:2]]


def _body(symbols):
    return {
        "model_name": "sma-crossover",
        "symbols": symbols,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
    }


def _legacy_run(db_path, symbols, monkeypatch) -> str:
    """A completed run with no stored results, as every pre-queue run is."""
    monkeypatch.setenv("QUANTLAB_RUN_MODE", "inline")
    with TestClient(create_app(str(db_path))) as inline_client:
        run_id = inline_client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    monkeypatch.setenv("QUANTLAB_RUN_MODE", "queue")
    return run_id


def _backfill(client):
    app = client.app
    return jobs.backfill_next(app.state.backend, app.state.experiments)


def test_an_older_run_is_never_recomputed_on_view(db_path, client, symbols, monkeypatch):
    run_id = _legacy_run(db_path, symbols, monkeypatch)
    store = client.app.state.experiments

    response = client.get(f"/api/v1/runs/{run_id}/performance")

    assert response.status_code == 409
    assert "being prepared" in response.json()["detail"]
    assert store.get_performance(run_id) is None  # the request computed nothing


def test_the_worker_backfills_older_runs_and_the_list_shows_them(
    db_path, client, symbols, monkeypatch
):
    run_id = _legacy_run(db_path, symbols, monkeypatch)
    listed = {r["id"]: r for r in client.get("/api/v1/runs").json()["items"]}[run_id]
    assert listed["metrics"] is None and listed["summary"] is None

    assert _backfill(client) == run_id

    store = client.app.state.experiments
    stored = store.get_performance(run_id)
    assert client.get(f"/api/v1/runs/{run_id}/performance").json() == stored
    row = {r["id"]: r for r in client.get("/api/v1/runs").json()["items"]}[run_id]
    assert row["metrics"] == stored["metrics"]
    summary = row["summary"]
    bench = stored["benchmark"]
    assert summary["benchmark_return"] == pytest.approx(bench[-1]["value"] / bench[0]["value"] - 1)
    assert summary["excess_return"] == pytest.approx(
        stored["metrics"]["total_return"] - summary["benchmark_return"]
    )
    assert summary["equity_spark"][0] == 1.0
    assert 2 <= len(summary["equity_spark"]) <= 48
    assert _backfill(client) is None  # stored once, never again


def test_backfill_takes_the_newest_run_first(db_path, client, symbols, monkeypatch):
    older = _legacy_run(db_path, symbols, monkeypatch)
    newer = _legacy_run(db_path, symbols[:1], monkeypatch)
    # Pre-queue runs record created_at to the second; two made in one second
    # would tie. Real ones are minutes apart, so make this one an hour older.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE experiment_runs SET created_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (older,),
        )

    assert _backfill(client) == newer
    assert _backfill(client) == older


def test_new_runs_store_their_summary_when_they_complete(client, symbols):
    run_id = client.post("/api/v1/runs", json=_body(symbols)).json()["id"]
    app = client.app
    jobs.process_next(app.state.backend, app.state.experiments)

    row = {r["id"]: r for r in client.get("/api/v1/runs").json()["items"]}[run_id]
    assert row["summary"]["benchmark_return"] is not None
    assert row["summary"]["benchmark_spark"][0] == pytest.approx(1.0, abs=0.05)


def test_a_run_whose_results_cannot_be_computed_says_why_once(
    db_path, client, symbols, monkeypatch
):
    run_id = _legacy_run(db_path, symbols, monkeypatch)

    def broken(*args, **kwargs):
        raise errors.UnknownSymbolError(["GONE"])

    monkeypatch.setattr(jobs, "compute_run_performance", broken)
    assert _backfill(client) == run_id
    assert _backfill(client) is None  # recorded, and not picked again

    response = client.get(f"/api/v1/runs/{run_id}/performance")
    assert response.status_code == 422
    assert "GONE" in response.json()["detail"]
    row = {r["id"]: r for r in client.get("/api/v1/runs").json()["items"]}[run_id]
    assert "GONE" in row["results_error"]


def test_long_intraday_curves_are_stored_a_point_a_session():
    sessions = [f"2024-01-{d:02d}" for d in range(1, 29)]
    points = [
        {"date": f"{day}T{9 + k // 12:02d}:{(k % 12) * 5:02d}:00", "value": 100.0 + i}
        for i, (day, k) in enumerate((day, k) for day in sessions for k in range(100))
    ]
    assert len(points) > jobs.MAX_STORED_POINTS

    compact = jobs._compact({"equity": list(points), "benchmark": list(points)})

    assert len(compact["equity"]) == len(sessions)
    assert compact["equity"][0] == points[99]  # each session keeps its closing mark
    assert compact["equity"][-1] == points[-1]


def test_run_summary_compares_the_strategy_with_buy_and_hold():
    performance = {
        "metrics": {"total_return": 0.30},
        "equity": [{"date": f"d{i}", "value": 100.0 + i} for i in range(200)],
        "benchmark": [{"date": f"d{i}", "value": 100.0 + i / 2} for i in range(200)],
        "regression": {"alpha": 0.01, "beta": 0.8, "information_ratio": 0.5},
    }
    summary = run_summary(performance)

    assert summary["benchmark_return"] == pytest.approx(199.5 / 100 - 1)
    assert summary["excess_return"] == pytest.approx(0.30 - (199.5 / 100 - 1))
    assert (summary["alpha"], summary["beta"]) == (0.01, 0.8)
    assert len(summary["equity_spark"]) == 48
    assert summary["equity_spark"][-1] == pytest.approx(2.99)
    assert run_summary(None) is None


def test_a_strategy_reading_unloaded_macro_series_is_refused_at_submit(client, symbols):
    """S6's regime gate reads VIX.FRED and HYSPREAD.FRED. Where they are not
    loaded, Submit says so at once, with the fix, and queues nothing."""
    before = client.get("/api/v1/runs").json()["total"]
    body = {
        "strategy": {
            "name": "S6 regime gate",
            "components": [
                {"rule_name": "sma-crossover", "role": "entry", "parameters": {}},
                {
                    "rule_name": "macro-risk-off",
                    "role": "filter",
                    "parameters": {"use_hy_spread": True},
                },
            ],
        },
        "symbols": symbols,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
    }

    response = client.post("/api/v1/runs", json=body)

    assert response.status_code == 422, response.json()
    detail = response.json()["detail"]
    assert "VIX.FRED" in detail
    assert "ingest-macro --provider fred" in detail
    assert client.get("/api/v1/runs").json()["total"] == before
