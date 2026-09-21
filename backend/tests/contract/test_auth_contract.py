"""Contract tests for the auth endpoints, driven by the authored OpenAPI doc.

Same hand-rolled approach as test_api_contract.py: the shapes asserted here
come from contracts/openapi.yaml, not from the implementation.
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
AUTH_PATHS = {p for p in SPEC["paths"] if p.startswith("/auth/")}
USER_REQUIRED = set(SPEC["components"]["schemas"]["User"]["required"])
USER_PUBLIC_REQUIRED = set(SPEC["components"]["schemas"]["UserPublic"]["required"])
CREDENTIALS = SPEC["components"]["schemas"]["AuthCredentials"]["properties"]
# The three operations the session requirement does not cover.
PUBLIC_OPERATIONS = {"getHealth", "login", "registerUser"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "quantlab.db"
    seed.run(db_path)
    with TestClient(create_app(str(db_path), auth_enabled=True)) as test_client:
        yield test_client


def test_contract_documents_auth():
    assert AUTH_PATHS == {"/auth/register", "/auth/login", "/auth/logout", "/auth/me"}
    cookie = SPEC["components"]["securitySchemes"]["sessionCookie"]
    assert cookie["type"] == "apiKey"
    assert cookie["in"] == "cookie"
    assert cookie["name"] == "quantlab_session"
    # Password bounds in the contract match what the API enforces.
    assert CREDENTIALS["password"]["minLength"] == 8


def test_every_operation_but_the_public_three_requires_the_session():
    secured, open_ = set(), set()
    for ops in SPEC["paths"].values():
        for method, op in ops.items():
            if method == "parameters":
                continue
            (open_ if op.get("security") == [] else secured).add(op["operationId"])
    assert open_ == PUBLIC_OPERATIONS


def test_register_login_me_roundtrip_matches_schema(client):
    registered = client.post(
        "/api/v1/auth/register", json={"username": "carol", "password": "long-enough-password"}
    )
    assert registered.status_code == 201
    assert USER_REQUIRED <= set(registered.json())

    login = client.post(
        "/api/v1/auth/login", json={"username": "carol", "password": "long-enough-password"}
    )
    assert login.status_code == 200
    assert USER_REQUIRED <= set(login.json())
    set_cookie = login.headers["set-cookie"]
    assert set_cookie.startswith("quantlab_session=")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert USER_PUBLIC_REQUIRED <= set(me.json())

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_protected_operations_401_without_a_cookie(client):
    # No login on this client: every secured operation must refuse.
    fresh = TestClient(client.app)
    for path, ops in SPEC["paths"].items():
        for method, op in ops.items():
            if method == "parameters" or op["operationId"] in PUBLIC_OPERATIONS:
                continue
            response = fresh.request(method.upper(), f"/api/v1{path}")
            assert response.status_code == 401, f"{method.upper()} {path}"
            assert isinstance(response.json()["detail"], str)
