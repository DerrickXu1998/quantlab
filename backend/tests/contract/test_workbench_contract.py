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
        / "005-signal-research-workbench"
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
    run = client.post(
        "/api/v1/runs", json=_run_body(symbols, parameters={"fast": 7})
    ).json()
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
