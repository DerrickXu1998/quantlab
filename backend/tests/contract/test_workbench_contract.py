"""Contract tests for the model catalog and experiment runs (feature 005).

Same approach as test_api_contract.py: required fields, enums and types are
driven by the authored OpenAPI document rather than restated here, so the tests
fail if the document and the app drift apart (Constitution V).
"""

from __future__ import annotations

import os
from datetime import date
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
PARAM_TYPES = set(SCHEMAS["ParamSpec"]["properties"]["type"]["enum"])
SCALE_CLASSES = set(SCHEMAS["Model"]["properties"]["scale_class"]["enum"])
RUN_STATUSES = set(SCHEMAS["Run"]["properties"]["status"]["enum"])
DIRECTIONS = set(SCHEMAS["Direction"]["enum"])


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "quantlab.db"
    seed.run(db_path)
    with TestClient(create_app(str(db_path))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def symbols(client):
    return [item["symbol"] for item in client.get("/api/v1/instruments").json()["items"][:2]]


def _run_body(symbols, **overrides):
    body = {
        "model_name": "sma-crossover",
        "symbols": symbols,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
    }
    body.update(overrides)
    return body


# --- GET /models -----------------------------------------------------------


def test_models_match_the_contract(client):
    payload = client.get("/api/v1/models").json()
    assert set(SCHEMAS["ModelList"]["required"]) <= set(payload)
    assert payload["total"] == len(payload["items"]) > 0

    for model in payload["items"]:
        assert set(SCHEMAS["Model"]["required"]) <= set(model)
        assert model["scale_class"] in SCALE_CLASSES
        assert isinstance(model["lookback_days"], int) and model["lookback_days"] >= 1
        for spec in model["parameters"]:
            assert set(SCHEMAS["ParamSpec"]["required"]) <= set(spec)
            assert spec["type"] in PARAM_TYPES


def test_catalog_reports_every_registered_rule(client):
    from quantlab.signals.registry import list_rules

    names = {m["name"] for m in client.get("/api/v1/models").json()["items"]}
    assert names == {rule.name for rule in list_rules()}


def test_catalog_publishes_bounds_so_a_form_can_be_generated(client):
    models = {m["name"]: m for m in client.get("/api/v1/models").json()["items"]}
    fast = next(p for p in models["sma-crossover"]["parameters"] if p["name"] == "fast")
    assert fast["type"] == "int"
    assert fast["minimum"] is not None and fast["maximum"] is not None
    assert fast["default"] == 20


# --- POST /runs ------------------------------------------------------------


def test_create_run_matches_the_contract(client, symbols):
    response = client.post("/api/v1/runs", json=_run_body(symbols))
    assert response.status_code == 201
    run = response.json()

    assert set(SCHEMAS["Run"]["required"]) <= set(run)
    assert run["status"] in RUN_STATUSES
    assert run["model_name"] == "sma-crossover"
    assert isinstance(run["signal_count"], int) and run["signal_count"] >= 0
    coverage = run["coverage"]
    assert set(SCHEMAS["RunCoverage"]["required"]) <= set(coverage)
    assert coverage["instruments_requested"] == len(symbols)


def test_effective_parameters_are_recorded_not_the_bare_defaults(client, symbols):
    run = client.post("/api/v1/runs", json=_run_body(symbols, parameters={"fast": 7})).json()
    # Overrides merged over declared defaults — the provenance must describe
    # what actually executed (Constitution VI).
    assert run["parameters"] == {"fast": 7, "slow": 50}


def test_unknown_model_is_404(client, symbols):
    response = client.post("/api/v1/runs", json=_run_body(symbols, model_name="nope"))
    assert response.status_code == 404


def test_unknown_symbol_is_404(client):
    response = client.post("/api/v1/runs", json=_run_body(["NOSUCH"]))
    assert response.status_code == 404


def test_out_of_range_parameter_is_422_naming_the_parameter(client, symbols):
    response = client.post("/api/v1/runs", json=_run_body(symbols, parameters={"fast": -5}))
    assert response.status_code == 422
    assert "fast" in str(response.json()["detail"])


def test_window_shorter_than_lookback_is_422(client, symbols):
    response = client.post(
        "/api/v1/runs",
        json=_run_body(symbols, start_date="2024-06-01", end_date="2024-06-10"),
    )
    assert response.status_code == 422
    assert "lookback" in str(response.json()["detail"]).lower()


def test_start_after_end_is_422(client, symbols):
    response = client.post(
        "/api/v1/runs",
        json=_run_body(symbols, start_date="2024-12-31", end_date="2024-01-01"),
    )
    assert response.status_code == 422


# --- GET /runs/{id} --------------------------------------------------------


def test_run_detail_returns_in_window_signals_with_point_in_time_proof(client, symbols):
    created = client.post("/api/v1/runs", json=_run_body(symbols)).json()
    detail = client.get(f"/api/v1/runs/{created['id']}").json()

    assert set(SCHEMAS["RunDetail"]["allOf"][1]["required"]) <= set(detail)
    assert len(detail["signals"]) == detail["signal_count"]
    for signal in detail["signals"]:
        assert set(SCHEMAS["ExperimentSignal"]["required"]) <= set(signal)
        assert signal["direction"] in DIRECTIONS
        date.fromisoformat(signal["date"])
        assert detail["start_date"] <= signal["date"] <= detail["end_date"]
        assert signal["data_window_end"] <= signal["date"]  # Constitution VII


def test_unknown_run_is_404(client):
    assert client.get("/api/v1/runs/does-not-exist").status_code == 404


def test_running_does_not_change_the_seeded_signal_set(client, symbols):
    """The regression guard on the Signal Viewer, at the API level."""
    before = client.get("/api/v1/signals", params={"limit": 1}).json()["total"]
    client.post("/api/v1/runs", json=_run_body(symbols, parameters={"fast": 9}))
    after = client.get("/api/v1/signals", params={"limit": 1}).json()["total"]
    assert after == before


# --- GET /runs/{run_id}/performance ----------------------------------------


def test_performance_matches_the_contract(client, symbols):
    run = client.post("/api/v1/runs", json=_run_body(symbols)).json()

    payload = client.get(f"/api/v1/runs/{run['id']}/performance").json()

    assert set(SCHEMAS["RunPerformance"]["required"]) <= set(payload)
    assert payload["run_id"] == run["id"]
    assert payload["initial_capital"] > 0

    for point in payload["equity"] + payload["benchmark"]:
        assert set(SCHEMAS["EquityPoint"]["required"]) <= set(point)
    for trade in payload["trades"]:
        assert set(SCHEMAS["Trade"]["required"]) <= set(trade)
        assert isinstance(trade["open"], bool)
        # An open position has no realised exit date; a closed one does.
        assert (trade["exit_date"] is None) is trade["open"]

    metrics = payload["metrics"]
    assert set(SCHEMAS["PerformanceMetrics"]["required"]) <= set(metrics)
    # Reported as a negative fraction, and a curve cannot rise into a drawdown.
    assert metrics["max_drawdown"] <= 0
    assert metrics["winning_trades"] + metrics["losing_trades"] <= metrics["trade_count"]


def test_performance_is_measured_over_the_reported_window_only(client, symbols):
    """Warm-up bars are inputs to the signals, not part of the period measured."""
    run = client.post("/api/v1/runs", json=_run_body(symbols)).json()

    payload = client.get(f"/api/v1/runs/{run['id']}/performance").json()

    for point in payload["equity"]:
        assert run["start_date"] <= point["date"] <= run["end_date"]


def test_performance_ships_its_own_caveats(client, symbols):
    """These figures are not tradeable. The disclosure travels in the payload
    so it cannot be dropped by a change to the UI."""
    run = client.post("/api/v1/runs", json=_run_body(symbols)).json()

    payload = client.get(f"/api/v1/runs/{run['id']}/performance").json()

    assert payload["assumptions"]
    assert all(isinstance(line, str) and line for line in payload["assumptions"])


def test_performance_of_an_unknown_run_is_404(client):
    response = client.get("/api/v1/runs/does-not-exist/performance")

    assert response.status_code == 404
    assert set(SCHEMAS["Error"]["required"]) <= set(response.json())


def test_the_frontend_is_not_asked_to_compute_any_of_this():
    """Constitution V, made checkable: the contract must carry the derived
    figures, not just the raw material the browser would otherwise reduce."""
    properties = SCHEMAS["PerformanceMetrics"]["properties"]

    assert {"sharpe_ratio", "max_drawdown", "win_rate", "total_return"} <= set(properties)
    assert SCHEMAS["RunPerformance"]["properties"]["equity"]["type"] == "array"


def test_performance_of_a_failed_run_is_409_rather_than_a_zeroed_body(client):
    """A failed run has no performance. Returning zeros would render as a flat
    book -- exactly the empty-vs-failed ambiguity the UI already guards."""
    from quantlab.research.runner import RunCoverage, RunResult

    broken = RunResult(
        id="broken-run",
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

    response = client.get("/api/v1/runs/broken-run/performance")

    assert response.status_code == 409
    assert set(SCHEMAS["Error"]["required"]) <= set(response.json())


# --- Execution criteria on runs ----------------------------------------------


def test_execution_criteria_are_recorded_and_echoed(client, symbols):
    """The criteria are provenance: the run record must carry the effective
    set (defaults merged over what was asked), or it is not reproducible."""
    run = client.post(
        "/api/v1/runs",
        json=_run_body(symbols, execution={"transaction_cost_bps": 10, "stop_loss_pct": 0.1}),
    ).json()

    execution = run["execution"]
    assert execution["transaction_cost_bps"] == 10
    assert execution["stop_loss_pct"] == 0.1
    # Defaults filled in: the recorded set is the effective set.
    assert execution["entry_price"] == "same_close"
    assert execution["position_sizing"] == "equal_weight"

    fetched = client.get(f"/api/v1/runs/{run['id']}").json()
    assert fetched["execution"] == execution


def test_a_run_without_execution_records_none(client, symbols):
    run = client.post("/api/v1/runs", json=_run_body(symbols)).json()
    assert run["execution"] is None


def test_invalid_execution_criteria_are_422(client, symbols):
    bad_values = client.post(
        "/api/v1/runs", json=_run_body(symbols, execution={"stop_loss_pct": 1.5})
    )
    assert bad_values.status_code == 422

    unknown_key = client.post(
        "/api/v1/runs", json=_run_body(symbols, execution={"slippage_bps": 5})
    )
    assert unknown_key.status_code == 422

    bad_enum = client.post(
        "/api/v1/runs", json=_run_body(symbols, execution={"entry_price": "yesterday"})
    )
    assert bad_enum.status_code == 422


def test_performance_honours_the_recorded_execution(client, symbols):
    """A run recorded with costs reports a performance whose assumptions say
    so; the same run without them says it charged nothing."""
    plain = client.post("/api/v1/runs", json=_run_body(symbols)).json()
    charged = client.post(
        "/api/v1/runs", json=_run_body(symbols, execution={"transaction_cost_bps": 50})
    ).json()
    stopped = client.post(
        "/api/v1/runs", json=_run_body(symbols, execution={"stop_loss_pct": 0.2})
    ).json()

    plain_assumptions = " ".join(
        client.get(f"/api/v1/runs/{plain['id']}/performance").json()["assumptions"]
    )
    charged_assumptions = " ".join(
        client.get(f"/api/v1/runs/{charged['id']}/performance").json()["assumptions"]
    )
    stopped_assumptions = " ".join(
        client.get(f"/api/v1/runs/{stopped['id']}/performance").json()["assumptions"]
    )

    assert "No transaction costs" in plain_assumptions
    assert "50 bps" in charged_assumptions
    assert "Stop-loss" in stopped_assumptions

    # Same signals, same fills, plus a 50 bps charge per fill: the charged run
    # can only do worse. (Stops are excluded from this comparison: cutting a
    # loser early can legitimately improve a run.)
    if charged["signal_count"] > 0:
        charged_metrics = client.get(f"/api/v1/runs/{charged['id']}/performance").json()
        plain_metrics = client.get(f"/api/v1/runs/{plain['id']}/performance").json()
        assert (
            charged_metrics["metrics"]["total_return"] <= plain_metrics["metrics"]["total_return"]
        )
