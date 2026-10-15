"""Contract tests for the live market data endpoints (roadmap 4a).

No broker and no warehouse: the refusals run before either is touched, and
the one end-to-end stream below swaps in a fake backend, stubs the lease
storage, and hands the app a hub whose consumer is a fake. Error shapes are
driven by the authored OpenAPI document, as in test_live_replay_contract.py.
"""

from __future__ import annotations

import itertools
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api import routes
from quantlab.api.app import create_app
from quantlab.storage import live as live_store
from quantlab.streaming import live_hub


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

STREAM_URL = "/api/v1/live/stream"
SESSION_URL = "/api/v1/live/{symbol}/session"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "quantlab.db"
    seed.run(db_path)
    with TestClient(create_app(str(db_path))) as test_client:
        yield test_client


@pytest.fixture
def live_env(monkeypatch):
    monkeypatch.setenv("QUANTLAB_KAFKA_BROKERS", "127.0.0.1:9")
    monkeypatch.setenv(live_hub.TOPIC_ENV, "quantlab.live.ticks")


def test_unconfigured_live_bus_is_a_clean_503(client, monkeypatch):
    monkeypatch.setenv("QUANTLAB_KAFKA_BROKERS", "127.0.0.1:9")
    monkeypatch.delenv(live_hub.TOPIC_ENV, raising=False)

    response = client.get(STREAM_URL, params={"symbols": "ZZTRND"})

    assert response.status_code == 503
    assert ERROR_REQUIRED <= set(response.json())
    assert live_hub.TOPIC_ENV in response.json()["detail"]


def test_bad_symbol_lists_are_400(client, live_env):
    assert client.get(STREAM_URL, params={"symbols": " , "}).status_code == 400
    too_many = ",".join(f"S{i}.US" for i in range(routes._LIVE_MAX_SYMBOLS + 1))
    response = client.get(STREAM_URL, params={"symbols": too_many})
    assert response.status_code == 400
    assert ERROR_REQUIRED <= set(response.json())


def test_the_demo_dataset_has_no_live_feed(client, live_env):
    # The seeded SQLite demo has no warehouse: no leases, no live bars.
    stream = client.get(STREAM_URL, params={"symbols": "ZZTRND"})
    session = client.get(SESSION_URL.format(symbol="ZZTRND"))

    for response in (stream, session):
        assert response.status_code == 503
        assert ERROR_REQUIRED <= set(response.json())
        assert "warehouse" in response.json()["detail"]


# --- one stream end to end, against fakes -----------------------------------


class FakeWarehouseBackend:
    """Just enough backend for the live routes: two known symbols."""

    name = "warehouse"
    IDS = {"AAPL.US": 1, "MSFT.US": 2}

    def __init__(self) -> None:
        self.wh = object()

    def validate_symbols(self, symbols):
        return [s for s in symbols if s not in self.IDS]

    def instrument_ids(self, symbols):
        return {s: self.IDS[s] for s in symbols if s in self.IDS}


class TickingConsumer:
    """A topic that ticks AAPL and an unwatched symbol on every poll."""

    def __init__(self) -> None:
        self._n = itertools.count()

    def poll(self, timeout_ms: int):
        n = next(self._n)
        values = [
            {"event": "heartbeat", "connected": True, "market": "open"},
            {"event": "tick", "symbol": "AAPL.US", "ts": f"t{n}", "last": 100.0 + n},
            {"event": "tick", "symbol": "TSLA.US", "ts": f"t{n}", "last": 1.0},
        ]
        return {("quantlab.live.ticks", 0): [SimpleNamespace(value=v) for v in values]}

    def close(self, autocommit: bool = False) -> None:
        pass


@pytest.fixture
def live_app(tmp_path, live_env, monkeypatch):
    db_path = tmp_path / "quantlab.db"
    seed.run(db_path)
    app = create_app(str(db_path))
    app.state.backend = FakeWarehouseBackend()
    hub = live_hub.LiveHub("127.0.0.1:9", "quantlab.live.ticks", consumer_factory=TickingConsumer)
    hub.start()
    app.state.live_hub = hub

    leases: list[tuple] = []
    monkeypatch.setattr(
        live_store, "renew_market_leases", lambda wh, owner, ids: leases.append((owner, list(ids)))
    )
    monkeypatch.setattr(
        live_store,
        "line_statuses",
        lambda wh, owner, ids: {i: live_store.LineStatus("active") for i in ids},
    )
    monkeypatch.setattr(
        live_store,
        "session_bars",
        lambda wh, instrument_id: (
            "2026-10-15",
            [{"ts": "2026-10-15T13:30:00.000Z", "open": 1, "high": 2, "low": 0.5,
              "close": 1.5, "volume": 10, "kind": "backfill"}],
        ),
    )
    # Short enough that the stream ends by itself inside the test.
    monkeypatch.setattr(routes, "_LIVE_STREAM_SECONDS", 1.5)
    monkeypatch.setattr(routes, "_LIVE_HEARTBEAT_SECONDS", 0.2)
    yield app, leases
    hub.stop()


def _frames(response) -> list[dict]:
    return [json.loads(line[5:]) for line in response.iter_lines() if line.startswith("data:")]


def test_a_stream_leases_its_lines_and_forwards_only_its_symbols(live_app):
    app, leases = live_app
    with TestClient(app) as client:
        with client.stream("GET", STREAM_URL, params={"symbols": "AAPL.US"}) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            frames = _frames(response)

    events = {f["event"] for f in frames}
    assert {"status", "heartbeat", "tick"} <= events
    allowed = set(SPEC["components"]["schemas"]["LiveEvent"]["properties"]["event"]["enum"])
    assert events <= allowed

    assert all(f["symbol"] == "AAPL.US" for f in frames if f["event"] == "tick")
    # Status is sent once per change, not every heartbeat.
    statuses = [f for f in frames if f["event"] == "status"]
    assert statuses == [{"event": "status", "symbol": "AAPL.US", "status": "active", "detail": ""}]
    beats = [f for f in frames if f["event"] == "heartbeat"]
    assert beats and beats[-1]["collector"] == "up" and beats[-1]["market"] == "open"
    # Leased on open, for the caller, by instrument id.
    assert leases and leases[0][1] == [1]


def test_an_unknown_symbol_is_404_before_any_lease(live_app):
    app, leases = live_app
    with TestClient(app) as client:
        response = client.get(STREAM_URL, params={"symbols": "AAPL.US,NOPE.US"})
    assert response.status_code == 404
    assert "NOPE.US" in response.json()["detail"]
    assert leases == []


def test_the_session_endpoint_matches_the_contract(live_app):
    app, _ = live_app
    with TestClient(app) as client:
        response = client.get(SESSION_URL.format(symbol="AAPL.US"))
        missing = client.get(SESSION_URL.format(symbol="NOPE.US"))

    assert response.status_code == 200
    body = response.json()
    schema = SPEC["components"]["schemas"]["LiveSession"]
    assert set(schema["required"]) <= set(body)
    assert body["status"] in SPEC["components"]["schemas"]["LiveLineStatus"]["enum"]
    assert set(SPEC["components"]["schemas"]["LiveBar"]["required"]) <= set(body["bars"][0])
    assert missing.status_code == 404


def test_the_contract_documents_the_live_endpoints():
    stream = SPEC["paths"]["/live/stream"]["get"]
    assert stream["operationId"] == "streamLive"
    assert "text/event-stream" in stream["responses"]["200"]["content"]
    for status in ("400", "404", "429", "503"):
        ref = stream["responses"][status]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/Error"), status
    session = SPEC["paths"]["/live/{symbol}/session"]["get"]
    assert session["operationId"] == "getLiveSession"
    assert session["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/LiveSession"
    )
