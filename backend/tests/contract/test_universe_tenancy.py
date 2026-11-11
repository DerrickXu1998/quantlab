"""Universes a user publishes are theirs: POST /universes and every read of one.

POST /universes used to take no caller at all, and wrote into the shared table
every screen reads -- append-only, so an anonymous snapshot under a name
everyone used could never be taken back. Now publishing needs a session, the
snapshot is owned by the caller, and the list, the members read and the screen
all resolve names as the caller.

The SQL behind it (shared universes plus the caller's own, never a mix) is the
warehouse's; this pins the HTTP half: who must be signed in, and that the
caller -- never a client-supplied owner -- is what reaches storage.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api.app import create_app

os.environ.setdefault("QUANTLAB_PBKDF2_ITERATIONS", "1000")

API = "/api/v1"
PASSWORD = "correct-horse-battery-staple"


class _Recording:
    """A warehouse-shaped backend that remembers who asked."""

    name = "warehouse"

    def __init__(self):
        self.published: list[tuple[str, str]] = []

    def health(self):
        return True, 0

    def ensure_default_universe(self):
        pass

    def publish_universe(self, name, symbols, snapshot_date=None, *, owner):
        self.published.append((name, owner))
        return {"name": name, "as_of": "2026-10-01", "size": len(symbols)}

    def list_universes(self, owner=None):
        items = [{"name": "all", "as_of": "2026-10-01", "size": 3}]
        items += [
            {"name": name, "as_of": "2026-10-01", "size": 1}
            for name, who in self.published
            if who == owner
        ]
        return {"total": len(items), "items": items}

    def universe_members(self, name, as_of, owner=None):
        if (name, owner) in self.published:
            return {"name": name, "as_of": "2026-10-01", "symbols": ["AAA.US"]}
        return None

    def screen(self, *, universe, owner=None, **_):
        return None  # the 404 detail is built from list_universes(owner)


@pytest.fixture
def stub():
    return _Recording()


@pytest.fixture
def client(stub, tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTLAB_AUTH_REQUIRED", "true")
    with TestClient(create_app(str(tmp_path / "quantlab.db"), backend=stub)) as c:
        yield c


def _register(client, email: str) -> dict:
    response = client.post(f"{API}/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


BODY = {"name": "my-tech", "symbols": ["AAA.US"]}


def test_publishing_a_universe_needs_a_session(client, stub):
    response = client.post(f"{API}/universes", json=BODY)

    assert response.status_code == 401
    assert stub.published == []


def test_reading_universes_needs_a_session(client):
    assert client.get(f"{API}/universes").status_code == 401
    assert client.get(f"{API}/universes/my-tech").status_code == 401
    assert client.get(f"{API}/screen", params={"universe": "my-tech"}).status_code == 401


def test_a_published_universe_is_the_publishers_alone(client, stub):
    alice = _register(client, "alice@example.com")
    bob = _register(client, "bob@example.com")

    assert client.post(f"{API}/universes", json=BODY, headers=alice).status_code == 201
    ((_, owner),) = stub.published
    assert owner == client.get(f"{API}/auth/me", headers=alice).json()["id"]

    alice_names = {i["name"] for i in client.get(f"{API}/universes", headers=alice).json()["items"]}
    bob_names = {i["name"] for i in client.get(f"{API}/universes", headers=bob).json()["items"]}
    assert alice_names == {"all", "my-tech"}
    assert bob_names == {"all"}

    assert client.get(f"{API}/universes/my-tech", headers=alice).status_code == 200
    # Somebody else's universe reads as absent, like their runs.
    assert client.get(f"{API}/universes/my-tech", headers=bob).status_code == 404

    # The screen's miss names the right failure for each caller.
    alice_miss = client.get(
        f"{API}/screen", params={"universe": "my-tech", "as_of": "2020-01-01"}, headers=alice
    ).json()["detail"]
    bob_miss = client.get(
        f"{API}/screen", params={"universe": "my-tech"}, headers=bob
    ).json()["detail"]
    assert "no snapshot on or before 2020-01-01" in alice_miss
    assert bob_miss == "unknown universe: my-tech"


def test_an_owner_in_the_body_is_not_how_ownership_is_decided(client, stub):
    alice = _register(client, "alice@example.com")
    response = client.post(
        f"{API}/universes", json={**BODY, "owner": "someone-else"}, headers=alice
    )

    assert response.status_code in (201, 422)
    assert all(owner != "someone-else" for _, owner in stub.published)


# --- the demo ------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "quantlab.db"
    seed.run(db_path)
    with TestClient(create_app(str(db_path))) as c:
        yield c


def test_the_demo_refuses_a_universe_with_a_reason_not_a_500(demo):
    """The synthetic dataset has no universe history. Saying so is a 422 the
    client can show; it used to escape as NotImplementedError, a bare 500."""
    response = demo.post(f"{API}/universes", json=BODY)

    assert response.status_code == 422
    assert "no universe history" in response.json()["detail"]
