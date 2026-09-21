"""Contract tests for the fundamentals read endpoints (feature 008).

Same approach as test_api_contract.py: required fields and shapes are driven
by the authored OpenAPI document rather than restated here. The demo dataset
holds no fundamentals, so these assert the empty-but-valid contract shape; the
warehouse read and transform semantics live in tests/unit/test_fundamentals_reads.py.
"""

from __future__ import annotations

import os
import re
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
SYMBOL_PATTERN = SPEC["paths"]["/instruments/{symbol}/prices"]["get"]["parameters"][0]["schema"][
    "pattern"
]
SERIES_PATH = SPEC["paths"]["/instruments/{symbol}/fundamentals/series"]["get"]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "quantlab.db"
    seed.run(db_path)
    with TestClient(create_app(str(db_path))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def symbol(client):
    return client.get("/api/v1/instruments").json()["items"][0]["symbol"]


# --- Concept catalog -----------------------------------------------------------


def test_concept_catalog_matches_the_contract(client, symbol):
    response = client.get(f"/api/v1/instruments/{symbol}/fundamentals/concepts")

    assert response.status_code == 200
    payload = response.json()
    assert set(SCHEMAS["FundamentalConceptList"]["required"]) <= set(payload)
    assert payload["symbol"] == symbol
    # The demo dataset holds no fundamentals: empty, not an error.
    assert payload["total"] == 0
    assert payload["items"] == []


def test_concept_catalog_of_an_unknown_symbol_is_404(client):
    response = client.get("/api/v1/instruments/NOSUCH/fundamentals/concepts")

    assert response.status_code == 404
    assert set(SCHEMAS["Error"]["required"]) <= set(response.json())


# --- Series ---------------------------------------------------------------------


def test_series_matches_the_contract(client, symbol):
    response = client.get(
        f"/api/v1/instruments/{symbol}/fundamentals/series", params={"concept": "revenue"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(SCHEMAS["FundamentalSeries"]["required"]) <= set(payload)
    assert re.fullmatch(SYMBOL_PATTERN, payload["symbol"])
    assert payload["concept"] == "revenue"
    assert payload["transform"] == "raw"  # the documented default
    assert payload["point_in_time"] is True
    assert isinstance(payload["provenance"], str) and payload["provenance"]
    assert payload["total"] == 0
    assert payload["items"] == []


def test_series_requires_a_concept(client, symbol):
    assert client.get(f"/api/v1/instruments/{symbol}/fundamentals/series").status_code == 422


def test_series_rejects_an_unknown_transform(client, symbol):
    response = client.get(
        f"/api/v1/instruments/{symbol}/fundamentals/series",
        params={"concept": "revenue", "transform": "cagr"},
    )
    assert response.status_code == 422


def test_series_of_an_unknown_symbol_is_404(client):
    response = client.get(
        "/api/v1/instruments/NOSUCH/fundamentals/series", params={"concept": "revenue"}
    )
    assert response.status_code == 404


def test_series_start_after_end_is_400(client, symbol):
    response = client.get(
        f"/api/v1/instruments/{symbol}/fundamentals/series",
        params={"concept": "revenue", "start_date": "2024-12-31", "end_date": "2024-01-01"},
    )
    assert response.status_code == 400


def test_the_transforms_and_filters_are_the_documented_ones():
    """The engine's lag enforcement depends on this contract: every fact shape
    must carry filed_at (visibility anchor) and period_end (period described),
    and the transforms must be the three the doc enumerates."""
    params = {p["name"]: p for p in SERIES_PATH["parameters"]}
    assert params["concept"]["required"] is True
    assert params["transform"]["schema"]["enum"] == ["raw", "raw_facts", "yoy_growth"]
    assert params["transform"]["schema"]["default"] == "raw"
    assert {"start_date", "end_date"} <= set(params)

    fact_required = set(SCHEMAS["FundamentalFact"]["required"])
    assert {"filed_at", "period_end", "value"} <= fact_required
