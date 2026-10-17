"""Contract tests for the per-user settings API.

A seeded demo app (no warehouse needed: settings live beside the accounts in
the SQLite identity store), with the live gateway manager faked where the
IBKR credential upload needs one. Shapes are checked against the authored
OpenAPI document.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api import routes
from quantlab.api.app import create_app
from quantlab.streaming import live_manager


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
URL = "/api/v1/me/settings"
CREDENTIALS_URL = "/api/v1/me/settings/ibkr/credentials"
SECRET = "hunter2-never-stored"


@pytest.fixture
def app_and_db(tmp_path):
    db_path = tmp_path / "quantlab.db"
    seed.run(db_path)
    return create_app(str(db_path)), db_path


@pytest.fixture
def client(app_and_db):
    with TestClient(app_and_db[0]) as test_client:
        yield test_client


def _document_shape(body: dict) -> None:
    assert set(SCHEMAS["UserSettingsDocument"]["required"]) <= set(body)
    assert set(SCHEMAS["UserSettings"]["required"]) <= set(body["settings"])


def test_a_new_user_reads_the_defaults(client):
    body = client.get(URL).json()
    _document_shape(body)
    assert body["settings"] == {
        "appearance": {"theme": "dark"},
        "market": {"default_data": "historical", "lists": []},
        "ibkr": {"username": None, "trading_mode": "paper"},
    }
    assert body["updated_at"] is None
    # Sign-in is off in this suite: the built-in account shows no email.
    assert body["account"]["email"] is None and body["account"]["auth_required"] is False
    assert body["ibkr_connection"] is None  # live data not set up here


def test_a_merge_patch_changes_only_what_it_names(client):
    client.patch(URL, json={"appearance": {"theme": "light"}})
    lists = [{"name": "Tech", "symbols": ["AAPL.US", "MSFT.US", "AAPL.US"]}]
    body = client.patch(URL, json={"market": {"lists": lists}}).json()

    assert body["settings"]["appearance"]["theme"] == "light"  # kept
    assert body["settings"]["market"]["lists"] == [
        {"name": "Tech", "symbols": ["AAPL.US", "MSFT.US"]}
    ]
    assert body["settings"]["market"]["default_data"] == "historical"
    assert body["updated_at"]

    # null puts a key back to its default; the read agrees with the write.
    client.patch(URL, json={"appearance": {"theme": None}})
    assert client.get(URL).json()["settings"]["appearance"]["theme"] == "dark"


@pytest.mark.parametrize(
    "patch",
    [
        {"appearance": {"colour": "red"}},  # unknown key: a typo, not a setting
        {"appearance": {"theme": "neon"}},
        {"market": {"lists": [{"name": "A", "symbols": []}, {"name": "A", "symbols": []}]}},
        {"market": {"lists": [{"name": "A", "symbols": ["not a symbol"]}]}},
        {"ibkr": {"password": SECRET}},
    ],
)
def test_invalid_changes_are_refused_and_nothing_is_saved(client, patch):
    response = client.patch(URL, json=patch)
    assert response.status_code == 422
    assert SECRET not in response.text
    assert client.get(URL).json()["updated_at"] is None


def test_settings_belong_to_their_user(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTLAB_AUTH_REQUIRED", "true")
    db_path = tmp_path / "quantlab.db"
    seed.run(db_path)
    with TestClient(create_app(str(db_path))) as client:
        tokens = []
        for email in ("a@example.com", "b@example.com"):
            creds = {"email": email, "password": "correct horse battery staple 9!"}
            client.post("/api/v1/auth/register", json=creds)
            tokens.append(client.post("/api/v1/auth/login", json=creds).json()["token"])
        a, b = ({"Authorization": f"Bearer {t}"} for t in tokens)

        client.patch(URL, json={"appearance": {"theme": "light"}}, headers=a)
        assert client.get(URL, headers=a).json()["settings"]["appearance"]["theme"] == "light"
        assert client.get(URL, headers=b).json()["settings"]["appearance"]["theme"] == "dark"
        assert client.get(URL, headers=a).json()["account"]["email"] == "a@example.com"
        assert client.get(URL).status_code == 401


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setenv(live_manager.URL_ENV, "http://manager.test")
    monkeypatch.setenv(live_manager.TOKEN_ENV, "t")
    calls = []
    state = {"state": "none"}

    def status(user_id):
        return dict(state)

    def connect(user_id, username, password, mode):
        calls.append(("connect", user_id, username, password, mode))
        state.update(state="logging_in", ib_username=username, trading_mode=mode)
        return dict(state)

    def disconnect(user_id):
        calls.append(("disconnect", user_id))
        state.clear()
        state["state"] = "none"
        return dict(state)

    monkeypatch.setattr(live_manager, "status", status)
    monkeypatch.setattr(live_manager, "connect", connect)
    monkeypatch.setattr(live_manager, "disconnect", disconnect)
    return calls


def test_uploading_ibkr_credentials_connects_and_stores_no_password(app_and_db, manager):
    app, db_path = app_and_db
    with TestClient(app) as client:
        body = {"username": "my-ibkr", "password": SECRET, "trading_mode": "live"}
        response = client.put(CREDENTIALS_URL, json=body)
        assert response.status_code == 202
        document = response.json()
        _document_shape(document)
        assert SECRET not in response.text
        assert document["settings"]["ibkr"] == {"username": "my-ibkr", "trading_mode": "live"}
        assert document["ibkr_connection"]["state"] == "logging_in"

        read = client.get(URL)
        assert read.json()["ibkr_connection"]["ib_username"] == "my-ibkr"
        assert SECRET not in read.text

    # The password reached the user's gateway, and was written nowhere.
    assert ("connect", "local", "my-ibkr", SECRET, "live") in manager
    assert SECRET.encode() not in Path(db_path).read_bytes()
    for sidecar in Path(db_path).parent.glob(Path(db_path).name + "*"):
        assert SECRET.encode() not in sidecar.read_bytes()


def test_the_market_tab_connect_also_remembers_the_login(client, manager):
    client.post(
        "/api/v1/live/connection",
        json={"username": "from-market", "password": SECRET, "trading_mode": "paper"},
    )
    assert client.get(URL).json()["settings"]["ibkr"]["username"] == "from-market"


def test_disconnecting_keeps_the_username_unless_asked_to_forget(client, manager):
    client.put(CREDENTIALS_URL, json={"username": "my-ibkr", "password": SECRET})

    kept = client.delete(CREDENTIALS_URL).json()
    assert kept["settings"]["ibkr"]["username"] == "my-ibkr"
    assert kept["ibkr_connection"] == {"state": "none"}

    forgot = client.delete(CREDENTIALS_URL, params={"forget": "true"}).json()
    assert forgot["settings"]["ibkr"] == {"username": None, "trading_mode": "paper"}
    assert [c[0] for c in manager].count("disconnect") == 2


def test_credential_uploads_share_the_connection_rate_limit(client, manager):
    body = {"username": "u", "password": SECRET}
    for _ in range(routes._LIVE_CONNECT_ATTEMPTS):
        assert client.put(CREDENTIALS_URL, json=body).status_code == 202
    assert client.post("/api/v1/live/connection", json=body).status_code == 429


def test_credentials_need_live_data_to_be_set_up(client, monkeypatch):
    monkeypatch.delenv(live_manager.URL_ENV, raising=False)
    response = client.put(CREDENTIALS_URL, json={"username": "u", "password": SECRET})
    assert response.status_code == 503
    assert client.get(URL).json()["settings"]["ibkr"]["username"] is None


def test_the_contract_documents_the_settings_api():
    paths = SPEC["paths"]
    assert paths["/me/settings"]["get"]["operationId"] == "getUserSettings"
    assert paths["/me/settings"]["patch"]["operationId"] == "updateUserSettings"
    credentials = paths["/me/settings/ibkr/credentials"]
    assert credentials["put"]["operationId"] == "putIbkrCredentials"
    assert credentials["delete"]["operationId"] == "deleteIbkrCredentials"
    assert SCHEMAS["UserSettings"]["additionalProperties"] is False
