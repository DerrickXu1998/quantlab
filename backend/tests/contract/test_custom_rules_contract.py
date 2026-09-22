"""Contract tests for custom signal rules and the template catalog (008, M2).

Driven by the authored OpenAPI document like the other contract files. The
demo dataset runs them end-to-end: custom rules are storage + signal compute,
neither of which needs the warehouse.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api.app import create_app

pytestmark = pytest.mark.skip(
    reason=(
        "Custom rules have no API surface on this base. A strategy component "
        "resolves through the global registry by name (strategy/spec.py "
        "resolve()), and a rule built at runtime from a template has no "
        "registry entry -- how one gets there is a design decision, not a "
        "merge conflict. The store, the templates and the schema landed; the "
        "routes and the runner path did not. These tests are the "
        "specification for that work, so they are kept rather than deleted."
    )
)


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

RSI_EXIT_70 = {
    "input": {"source": "indicator", "indicator": "rsi", "params": {"period": 14}},
    "comparator": "exits_zone",
    "threshold": 70,
    "bullish_on": "above",
}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "quantlab.db"
    seed.run(db_path)
    with TestClient(create_app(str(db_path))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def symbols(client):
    return [item["symbol"] for item in client.get("/api/v1/instruments").json()["items"][:2]]


def _create_rule(client, name="RSI exit", config=None):
    return client.post(
        "/api/v1/rules",
        json={"name": name, "template": "indicator-threshold", "config": config or RSI_EXIT_70},
    )


# --- Template catalog ----------------------------------------------------------


def test_signal_templates_match_the_contract(client):
    response = client.get("/api/v1/signal-templates")

    assert response.status_code == 200
    payload = response.json()
    assert set(SCHEMAS["SignalTemplateList"]["required"]) <= set(payload)
    assert payload["total"] == len(payload["items"]) == 3
    ids = {item["id"] for item in payload["items"]}
    assert ids == {"indicator-threshold", "indicator-crossover", "fundamental-condition"}
    by_id = {item["id"]: item for item in payload["items"]}
    for item in payload["items"]:
        assert set(SCHEMAS["SignalTemplate"]["required"]) <= set(item)
        assert item["config_fields"]
    # Bars-only templates run on every dataset, including the demo.
    assert by_id["indicator-threshold"]["available_on_dataset"] is True
    assert by_id["indicator-crossover"]["available_on_dataset"] is True
    # The fundamental template reads filings the demo does not have.
    assert by_id["fundamental-condition"]["inputs"] == "bars+fundamentals"
    assert by_id["fundamental-condition"]["available_on_dataset"] is False


def test_template_catalog_matches_the_template_registry(client):
    from quantlab.signals import templates

    payload = client.get("/api/v1/signal-templates").json()
    assert {t.id for t in templates.list_templates()} == {i["id"] for i in payload["items"]}


# --- CRUD -----------------------------------------------------------------------


def test_rule_crud_roundtrip_matches_the_contract(client):
    created = _create_rule(client)
    assert created.status_code == 201
    rule = created.json()
    assert set(SCHEMAS["CustomRule"]["required"]) <= set(rule)
    assert rule["template"] == "indicator-threshold"
    assert rule["config"] == RSI_EXIT_70
    assert rule["slug"] == "rsi-exit"
    assert rule["lookback_days"] == 16  # rsi(14) -> 16, the builtin's own lookback

    listed = client.get("/api/v1/rules").json()
    assert set(SCHEMAS["CustomRuleList"]["required"]) <= set(listed)
    assert any(item["rule_id"] == rule["rule_id"] for item in listed["items"])

    fetched = client.get(f"/api/v1/rules/{rule['rule_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["rule_id"] == rule["rule_id"]

    patched = client.patch(
        f"/api/v1/rules/{rule['rule_id']}", json={"config": {**RSI_EXIT_70, "threshold": 65}}
    )
    assert patched.status_code == 200
    assert patched.json()["config"]["threshold"] == 65

    assert client.delete(f"/api/v1/rules/{rule['rule_id']}").status_code == 204
    assert client.get(f"/api/v1/rules/{rule['rule_id']}").status_code == 404


def test_unknown_template_is_404(client):
    response = client.post(
        "/api/v1/rules", json={"name": "x", "template": "nope", "config": {}}
    )
    assert response.status_code == 404


def test_invalid_config_is_422_naming_the_field(client):
    response = client.post(
        "/api/v1/rules",
        json={
            "name": "bad",
            "template": "indicator-threshold",
            "config": {**RSI_EXIT_70, "comparator": "touches"},
        },
    )
    assert response.status_code == 422
    assert "comparator" in response.json()["detail"]


def test_empty_patch_is_422_and_an_unknown_rule_is_404(client):
    rule = _create_rule(client, name="to patch").json()
    assert client.patch(f"/api/v1/rules/{rule['rule_id']}", json={}).status_code == 422
    assert client.get("/api/v1/rules/nope").status_code == 404
    assert client.delete("/api/v1/rules/nope").status_code == 404


# --- Runs integration --------------------------------------------------------------


def test_run_with_custom_rule_records_the_definition_snapshot(client, symbols):
    rule = _create_rule(client).json()
    response = client.post(
        "/api/v1/runs",
        json={
            "custom_rule_id": rule["rule_id"],
            "symbols": symbols,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    )

    assert response.status_code == 201
    run = response.json()
    assert set(SCHEMAS["Run"]["required"]) <= set(run)
    snapshot = run["custom_rule"]
    assert snapshot["rule_id"] == rule["rule_id"]
    assert snapshot["template"] == "indicator-threshold"
    assert snapshot["config"] == RSI_EXIT_70
    assert snapshot["lookback_days"] == 16
    assert run["model_name"] == rule["slug"]
    assert run["parameters"] == {}  # a custom rule's config is fixed
    assert run["model_available"] is True


def test_both_model_selectors_is_422_and_neither_is_422(client, symbols):
    rule = _create_rule(client).json()
    body = {"symbols": symbols, "start_date": "2024-01-01", "end_date": "2024-12-31"}

    both = client.post(
        "/api/v1/runs",
        json={**body, "model_name": "sma-crossover", "custom_rule_id": rule["rule_id"]},
    )
    assert both.status_code == 422

    neither = client.post("/api/v1/runs", json=body)
    assert neither.status_code == 422


def test_unknown_custom_rule_is_404(client, symbols):
    response = client.post(
        "/api/v1/runs",
        json={
            "custom_rule_id": "nope",
            "symbols": symbols,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    )
    assert response.status_code == 404


def test_deleting_a_rule_keeps_its_runs_readable_with_model_unavailable(client, symbols):
    rule = _create_rule(client, name="disposable").json()
    run = client.post(
        "/api/v1/runs",
        json={
            "custom_rule_id": rule["rule_id"],
            "symbols": symbols,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    ).json()

    client.delete(f"/api/v1/rules/{rule['rule_id']}")

    fetched = client.get(f"/api/v1/runs/{run['id']}").json()
    # The run stays readable from its snapshot; only re-runnability is gone.
    assert fetched["model_available"] is False
    assert fetched["custom_rule"]["config"] == RSI_EXIT_70


def test_models_catalog_lists_custom_rules_with_their_origin(client):
    rule = _create_rule(client, name="catalog check").json()

    payload = client.get("/api/v1/models").json()
    origins = {item["name"]: item["origin"] for item in payload["items"]}
    assert origins["sma-crossover"] == "builtin"
    assert origins["catalog-check"] == "custom"
    # The module-scope client is shared, so other tests' rules exist too --
    # select ours by name rather than by first-custom.
    custom = next(item for item in payload["items"] if item["name"] == "catalog-check")
    assert custom["custom_rule_id"] == rule["rule_id"]
    assert custom["template"] == "indicator-threshold"
    assert custom["parameters"] == []
    assert custom["lookback_days"] == 16


# --- fundamental-condition (M3) ---------------------------------------------------

FUNDAMENTAL_CONFIG = {
    "concept": "revenue",
    "transform": "yoy_growth",
    "comparator": "crosses_above",
    "threshold": 0.0,
    "bullish_on": "above",
}


def test_fundamental_rule_creation_works_on_the_demo_but_running_it_is_422(client, symbols):
    """Creating the rule is fine -- validation is dataset-independent. Running
    it is what needs filings, and the demo holds none."""
    rule = client.post(
        "/api/v1/rules",
        json={
            "name": "Revenue growth",
            "template": "fundamental-condition",
            "config": FUNDAMENTAL_CONFIG,
        },
    )
    assert rule.status_code == 201

    response = client.post(
        "/api/v1/runs",
        json={
            "custom_rule_id": rule.json()["rule_id"],
            "symbols": symbols,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    )
    assert response.status_code == 422
    assert "fundamentals" in response.json()["detail"]
    assert "sqlite" in response.json()["detail"]
