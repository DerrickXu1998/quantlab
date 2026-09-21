"""Contract tests for the historical replay endpoints (feature: replay).

Same approach as test_workbench_contract.py: field requirements are driven by
the authored OpenAPI document rather than restated here, so the tests fail if
the document and the app drift apart.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api.app import create_app


def _resolve_contract_path() -> Path:
    candidates = []
    if override := os.environ.get("QUANTLAB_CONTRACT_PATH"):
        candidates.append(Path(override))
    backend_dir = Path(__file__).resolve().parents[2]
    candidates.append(
        backend_dir.parent
        / "quantlab_specs"
        / "specs"
        / "006-warehouse-experiments"
        / "contracts"
        / "openapi.yaml"
    )
    candidates.append(backend_dir / "contracts" / "openapi.yaml")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"openapi.yaml not found in any of: {candidates}")


SPEC = yaml.safe_load(_resolve_contract_path().read_text())
SCHEMAS = SPEC["components"]["schemas"]
SUMMARY_REQUIRED = set(SCHEMAS["ReplaySummary"]["required"])


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "quantlab.db"
    seed.run(db_path)
    with TestClient(create_app(str(db_path))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def run(client):
    symbols = [item["symbol"] for item in client.get("/api/v1/instruments").json()["items"][:3]]
    created = client.post(
        "/api/v1/runs",
        json={
            "model_name": "sma-crossover",
            "symbols": symbols,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    )
    assert created.status_code == 201
    return created.json()


def _frames(response) -> list[dict]:
    """Parse an SSE body into one JSON object per `data:` frame."""
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


# --- GET /runs/{run_id}/replay/summary ---------------------------------------


def test_summary_matches_the_contract(client, run):
    response = client.get(f"/api/v1/runs/{run['id']}/replay/summary")

    assert response.status_code == 200
    payload = response.json()
    assert SUMMARY_REQUIRED <= set(payload)
    assert payload["run_id"] == run["id"]
    assert payload["days"] > 0
    assert payload["initial_cash"] > 0
    assert payload["max_drawdown"] <= 0
    assert payload["winning_trades"] + payload["losing_trades"] <= payload["trade_count"]
    # The caveats travel with the numbers, as they do on the performance report.
    assert payload["assumptions"]
    assert all(isinstance(line, str) and line for line in payload["assumptions"])


def test_summary_reconciles_with_the_performance_endpoint(client, run):
    """The contract-level statement of the key invariant: replay and
    performance are the same measurement, observed differently."""
    summary = client.get(f"/api/v1/runs/{run['id']}/replay/summary").json()
    performance = client.get(f"/api/v1/runs/{run['id']}/performance").json()

    assert summary["total_return"] == pytest.approx(performance["metrics"]["total_return"])
    assert summary["max_drawdown"] == pytest.approx(performance["metrics"]["max_drawdown"])
    assert summary["trade_count"] == performance["metrics"]["trade_count"]
    assert summary["days"] == len(performance["equity"])


def test_summary_of_an_unknown_run_is_404(client):
    response = client.get("/api/v1/runs/does-not-exist/replay/summary")

    assert response.status_code == 404
    assert set(SCHEMAS["Error"]["required"]) <= set(response.json())


def test_replay_of_a_failed_run_is_409_rather_than_a_flat_book(client):
    from quantlab.research.runner import RunCoverage, RunResult

    broken = RunResult(
        id="broken-replay-run",
        model_name="sma-crossover",
        model_version="1.0.0",
        parameters={},
        symbols=["ZZTRND"],
        start_date="2024-01-01",
        end_date="2024-12-31",
        status="failed",
        created_at="2026-09-19T12:00:00+00:00",
        signal_count=0,
        coverage=RunCoverage(1, 0, 0),
        error="something broke",
    )
    client.app.state.experiments.save_run(broken)

    assert client.get("/api/v1/runs/broken-replay-run/replay/summary").status_code == 409
    assert client.get("/api/v1/runs/broken-replay-run/replay/stream").status_code == 409


# --- GET /runs/{run_id}/replay/stream ----------------------------------------


def test_stream_is_sse_and_ends_with_a_summary_frame(client, run):
    response = client.get(f"/api/v1/runs/{run['id']}/replay/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    frames = _frames(response)
    assert frames, "expected at least one frame"
    kinds = {frame["event"] for frame in frames}
    assert kinds <= {"bar", "signal", "fill", "equity", "summary"}
    assert {"bar", "equity", "summary"} <= kinds

    terminal = frames[-1]
    assert terminal["event"] == "summary"
    assert SUMMARY_REQUIRED <= set(terminal)

    # Chronology: dates never go backwards, and every stored signal fires.
    dated = [frame["date"] for frame in frames[:-1]]
    assert dated == sorted(dated)
    fired = {(frame["symbol"], frame["date"]) for frame in frames if frame["event"] == "signal"}
    assert len(fired) == run["signal_count"]


def test_stream_frames_carry_the_documented_fields(client, run):
    frames = _frames(client.get(f"/api/v1/runs/{run['id']}/replay/stream"))

    bars = [f for f in frames if f["event"] == "bar"]
    assert all(isinstance(f["closes"], dict) and f["closes"] for f in bars)

    equities = [f for f in frames if f["event"] == "equity"]
    assert all({"date", "equity", "cash", "positions", "realized_pnl"} <= set(f) for f in equities)
    # One equity frame per trading date, agreeing with the summary endpoint.
    summary = client.get(f"/api/v1/runs/{run['id']}/replay/summary").json()
    assert len(equities) == summary["days"]

    for fill in [f for f in frames if f["event"] == "fill"]:
        assert {"date", "symbol", "side", "qty", "price", "value", "realized_pnl"} <= set(fill)
        assert fill["side"] in ("buy", "sell")

    for signal in [f for f in frames if f["event"] == "signal"]:
        assert {"date", "symbol", "direction", "trigger_values", "data_window_end"} <= set(signal)
        assert signal["data_window_end"] <= signal["date"]  # Constitution VII


def test_stream_max_events_terminates_with_a_truncated_frame(client, run):
    response = client.get(f"/api/v1/runs/{run['id']}/replay/stream", params={"max_events": 5})

    frames = _frames(response)
    assert len(frames) == 6
    assert frames[-1]["event"] == "truncated"
    assert "detail" in frames[-1]


def test_stream_of_an_unknown_run_is_404(client):
    response = client.get("/api/v1/runs/does-not-exist/replay/stream")

    assert response.status_code == 404
    assert set(SCHEMAS["Error"]["required"]) <= set(response.json())


def test_the_contract_documents_the_event_stream():
    stream = SPEC["paths"]["/runs/{run_id}/replay/stream"]["get"]
    assert "text/event-stream" in stream["responses"]["200"]["content"]
    summary = SPEC["paths"]["/runs/{run_id}/replay/summary"]["get"]
    ref = summary["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/ReplaySummary")
