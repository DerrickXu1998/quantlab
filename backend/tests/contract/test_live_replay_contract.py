"""Contract tests for the live (Kafka-consumed) replay endpoint.

No broker is involved: the bus checks run before any connection, and the
503-when-unconfigured path is exactly what the contract promises. The error
shapes are driven by the authored OpenAPI document, as in
test_replay_contract.py.
"""

from __future__ import annotations

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
ERROR_REQUIRED = set(SPEC["components"]["schemas"]["Error"]["required"])

LIVE_URL = "/api/v1/replay/live/stream"
LIVE_QUERY = {"symbols": "ZZTRND,ZZMEAN", "start": "2024-01-01", "end": "2024-12-31"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "quantlab.db"
    seed.run(db_path)
    with TestClient(create_app(str(db_path))) as test_client:
        yield test_client


def test_unconfigured_bus_is_a_clean_503(client, monkeypatch):
    monkeypatch.delenv("QUANTLAB_KAFKA_BROKERS", raising=False)

    response = client.get(LIVE_URL, params=LIVE_QUERY)

    assert response.status_code == 503
    assert ERROR_REQUIRED <= set(response.json())
    assert "QUANTLAB_KAFKA_BROKERS" in response.json()["detail"]


def test_unknown_model_is_404_before_any_broker_contact(client, monkeypatch):
    # A broker string that would fail to connect: the model check must win.
    monkeypatch.setenv("QUANTLAB_KAFKA_BROKERS", "127.0.0.1:9")

    response = client.get(LIVE_URL, params={**LIVE_QUERY, "model": "no-such-model"})

    assert response.status_code == 404
    assert ERROR_REQUIRED <= set(response.json())


def test_bad_requests_are_400_and_bad_params_422(client, monkeypatch):
    monkeypatch.setenv("QUANTLAB_KAFKA_BROKERS", "127.0.0.1:9")

    assert client.get(LIVE_URL, params={**LIVE_QUERY, "symbols": ""}).status_code == 400
    assert (
        client.get(
            LIVE_URL, params={**LIVE_QUERY, "start": "2024-12-31", "end": "2024-01-01"}
        ).status_code
        == 400
    )
    assert client.get(LIVE_URL, params={**LIVE_QUERY, "params": "not-json"}).status_code == 400
    assert (
        client.get(LIVE_URL, params={**LIVE_QUERY, "params": '{"fast": 1}'}).status_code == 422
    )


def test_the_contract_documents_the_live_stream():
    path = SPEC["paths"]["/replay/live/stream"]["get"]
    assert path["operationId"] == "streamLiveReplay"
    assert "text/event-stream" in path["responses"]["200"]["content"]
    for status in ("400", "404", "422", "503"):
        ref = path["responses"][status]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/Error"), status
    required = {p["name"] for p in path["parameters"] if p.get("required")}
    assert {"symbols", "start", "end"} <= required
