"""API contract tests: responses validated against contracts/openapi.yaml.

Lightweight hand-rolled checks (required fields, enums, types, patterns) driven
by the authored OpenAPI document — no heavyweight openapi-validator dependency.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api.app import create_app


def _resolve_contract_path() -> Path:
    """Locate the authored OpenAPI contract.

    Order: QUANTLAB_CONTRACT_PATH env override -> the authored source of
    truth under quantlab_specs/specs/ (local dev) -> the copy bundled in
    backend/contracts/ (present inside the Docker image, whose build context
    is backend/ and so cannot reach quantlab_specs/).
    """
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


CONTRACT_PATH = _resolve_contract_path()
SPEC = yaml.safe_load(CONTRACT_PATH.read_text())
SCHEMAS = SPEC["components"]["schemas"]

DIRECTIONS = set(SCHEMAS["Direction"]["enum"])
REGIME_PROFILES = set(SCHEMAS["Instrument"]["properties"]["regime_profile"]["enum"])
SYMBOL_PATTERN = SPEC["paths"]["/instruments/{symbol}/prices"]["get"]["parameters"][0]["schema"][
    "pattern"
]
SIGNAL_REQUIRED = set(SCHEMAS["Signal"]["required"])
LIMIT_DEFAULT = SPEC["paths"]["/signals"]["get"]["parameters"][6]["schema"]["default"]
LIMIT_MAX = SPEC["paths"]["/signals"]["get"]["parameters"][6]["schema"]["maximum"]
SORT_ENUM = SPEC["paths"]["/signals"]["get"]["parameters"][5]["schema"]["enum"]
SORT_DEFAULT = SPEC["paths"]["/signals"]["get"]["parameters"][5]["schema"]["default"]


def check_instrument(item):
    assert set(SCHEMAS["Instrument"]["required"]) <= set(item)
    assert re.fullmatch(SYMBOL_PATTERN, item["symbol"])
    assert isinstance(item["name"], str) and item["name"]
    assert item["currency"] == "USD"
    assert item["regime_profile"] in REGIME_PROFILES


def check_price_bar(item):
    assert set(SCHEMAS["PriceBar"]["required"]) <= set(item)
    assert re.fullmatch(SYMBOL_PATTERN, item["symbol"])
    date.fromisoformat(item["date"])
    for field in ("open", "high", "low", "close"):
        assert isinstance(item[field], (int, float)) and item[field] > 0
    assert isinstance(item["volume"], int) and item["volume"] >= 0
    assert item["high"] >= max(item["open"], item["close"])
    assert item["low"] <= min(item["open"], item["close"])


def check_signal(item):
    assert SIGNAL_REQUIRED <= set(item)
    assert isinstance(item["id"], int)
    assert re.fullmatch(SYMBOL_PATTERN, item["symbol"])
    date.fromisoformat(item["date"])
    assert isinstance(item["rule_name"], str) and item["rule_name"]
    assert isinstance(item["rule_version"], str) and item["rule_version"]
    assert isinstance(item["parameters"], dict)
    assert item["direction"] in DIRECTIONS
    assert isinstance(item["trigger_values"], dict) and item["trigger_values"]
    date.fromisoformat(item["data_window_end"])
    assert item["data_window_end"] <= item["date"]  # Constitution VII


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "quantlab.db"
    seed.run(db_path)
    with TestClient(create_app(str(db_path))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def all_signals(client):
    """Fetch every signal by paging through the API (total > max limit)."""
    first = client.get("/api/v1/signals", params={"limit": LIMIT_MAX, "offset": 0}).json()
    total = first["total"]
    assert total > 0
    items = list(first["items"])
    while len(items) < total:
        page = client.get(
            "/api/v1/signals", params={"limit": LIMIT_MAX, "offset": len(items)}
        ).json()
        assert page["total"] == total
        assert page["items"], "page unexpectedly empty before reaching total"
        items.extend(page["items"])
    assert len(items) == total
    return {"total": total, "items": items}


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["seeded"] is True
    assert isinstance(body["signal_count"], int) and body["signal_count"] > 0


def test_list_instruments(client):
    body = client.get("/api/v1/instruments").json()
    assert body["total"] == 12 == len(body["items"])
    for item in body["items"]:
        check_instrument(item)
        assert item["bar_count"] >= 756
        assert item["signal_count"] >= 0


def test_get_prices_ascending(client):
    body = client.get("/api/v1/instruments/ZZTRND/prices").json()
    assert body["total"] == len(body["items"]) >= 756
    dates = [item["date"] for item in body["items"]]
    assert dates == sorted(dates)
    for item in body["items"][:50]:
        check_price_bar(item)


def test_get_prices_date_filter(client):
    body = client.get(
        "/api/v1/instruments/ZZTRND/prices",
        params={"start_date": "2024-01-01", "end_date": "2024-01-31"},
    ).json()
    assert body["total"] == len(body["items"]) > 0
    assert all("2024-01-01" <= item["date"] <= "2024-01-31" for item in body["items"])


def test_get_prices_unknown_symbol_404(client):
    response = client.get("/api/v1/instruments/ZZNOPE/prices")
    assert response.status_code == 404
    body = response.json()
    assert isinstance(body["detail"], str)


def test_signals_total_matches_health(client, all_signals):
    health = client.get("/api/v1/health").json()
    assert all_signals["total"] == health["signal_count"]
    for item in all_signals["items"][:100]:
        check_signal(item)


def test_signals_default_sort_is_date_desc(client):
    body = client.get("/api/v1/signals").json()
    assert SORT_DEFAULT == "date_desc"
    assert len(body["items"]) == min(LIMIT_DEFAULT, body["total"])
    dates = [item["date"] for item in body["items"]]
    assert dates == sorted(dates, reverse=True)


def test_signals_sort_date_asc(client):
    body = client.get("/api/v1/signals", params={"sort": "date_asc"}).json()
    dates = [item["date"] for item in body["items"]]
    assert dates == sorted(dates)
    assert set(SORT_ENUM) == {"date_asc", "date_desc"}


def test_signals_pagination_total_is_pre_pagination(client, all_signals):
    total = all_signals["total"]
    page1 = client.get("/api/v1/signals", params={"limit": 5, "offset": 0}).json()
    page2 = client.get("/api/v1/signals", params={"limit": 5, "offset": 5}).json()
    assert page1["total"] == page2["total"] == total
    assert len(page1["items"]) == 5
    assert [i["id"] for i in page1["items"]] != [i["id"] for i in page2["items"]]
    # combined pages match the unpaginated head
    combined = [i["id"] for i in page1["items"] + page2["items"]]
    assert combined == [i["id"] for i in all_signals["items"][:10]]


def test_signals_filter_by_instrument(client, all_signals):
    symbol = all_signals["items"][0]["symbol"]
    body = client.get("/api/v1/signals", params={"instrument": symbol, "limit": LIMIT_MAX}).json()
    assert body["total"] == len(body["items"]) > 0
    assert all(item["symbol"] == symbol for item in body["items"])
    expected = [i for i in all_signals["items"] if i["symbol"] == symbol]
    assert [i["id"] for i in body["items"]] == [i["id"] for i in expected]


def test_signals_filter_by_signal_type_and_direction(client, all_signals):
    for rule_name in ("sma-crossover", "rsi-threshold", "breakout-20d"):
        body = client.get(
            "/api/v1/signals", params={"signal_type": rule_name, "limit": LIMIT_MAX}
        ).json()
        assert body["total"] > 0
        assert all(item["rule_name"] == rule_name for item in body["items"])
    body = client.get("/api/v1/signals", params={"direction": "bearish", "limit": LIMIT_MAX}).json()
    assert body["total"] > 0
    assert all(item["direction"] == "bearish" for item in body["items"])


def test_signals_filter_by_date_range(client, all_signals):
    start, end = "2024-06-01", "2024-06-30"
    body = client.get(
        "/api/v1/signals", params={"start_date": start, "end_date": end, "limit": LIMIT_MAX}
    ).json()
    assert all(start <= item["date"] <= end for item in body["items"])
    expected = [i for i in all_signals["items"] if start <= i["date"] <= end]
    assert body["total"] == len(expected)


def test_signals_filter_combination_empty_result(client):
    body = client.get(
        "/api/v1/signals",
        params={"instrument": "ZZTRND", "start_date": "1900-01-01", "end_date": "1900-12-31"},
    ).json()
    assert body == {"total": 0, "items": []}


def test_signals_start_after_end_is_400(client):
    response = client.get(
        "/api/v1/signals", params={"start_date": "2025-01-01", "end_date": "2024-01-01"}
    )
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_signals_invalid_direction_rejected(client):
    response = client.get("/api/v1/signals", params={"direction": "sideways"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_unseeded_database_returns_503_except_health(tmp_path):
    empty_db = tmp_path / "empty.db"
    with TestClient(create_app(str(empty_db))) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "seeded": False, "signal_count": 0}
        for path in ("/api/v1/instruments", "/api/v1/instruments/ZZTRND/prices", "/api/v1/signals"):
            response = client.get(path)
            assert response.status_code == 503, path
            assert isinstance(response.json()["detail"], str)
