"""Authentication (feature 007): hashing, sessions, the guard, and per-user
run isolation.

Everything here runs the app with ``auth_enabled=True`` explicitly — the
suite-wide default is off (see tests/conftest.py), and these are the tests
that turn it on.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api import auth
from quantlab.api.app import create_app
from quantlab.storage import experiments
from quantlab.storage.auth import SESSION_TTL, SqliteAuthStore, utcnow


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    """Keep PBKDF2 correct but cheap here; the production work factor is
    asserted by name in test_default_iteration_count."""
    monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 1_000)


def _credentials(username: str, password: str = "correct horse battery") -> dict:
    return {"username": username, "password": password}


@pytest.fixture()
def client(tmp_path):
    """An auth-enabled app on a fresh, unseeded database."""
    with TestClient(create_app(str(tmp_path / "auth.db"), auth_enabled=True)) as c:
        yield c


# --- Password hashing ----------------------------------------------------------


def test_default_iteration_count():
    assert auth.DEFAULT_PBKDF2_ITERATIONS == 600_000


def test_password_hash_roundtrip():
    stored = auth.hash_password("s3cret-passphrase")
    assert stored.startswith("pbkdf2_sha256$1000$")  # the fixture's work factor
    assert auth.verify_password("s3cret-passphrase", stored)


def test_wrong_password_is_rejected():
    stored = auth.hash_password("s3cret-passphrase")
    assert not auth.verify_password("s3cret-passphrasf", stored)
    assert not auth.verify_password("", stored)


def test_same_password_hashes_differently_per_user():
    assert auth.hash_password("same-password") != auth.hash_password("same-password")


def test_malformed_stored_hash_is_rejected():
    assert not auth.verify_password("whatever", "not-a-hash")
    assert not auth.verify_password("whatever", "bcrypt$1000$aa$bb")


# --- Session store ---------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    return SqliteAuthStore(tmp_path / "auth.db")


def _user(store: SqliteAuthStore, username: str = "alice", is_admin: bool = True) -> dict:
    return store.create_user(username, auth.hash_password("password-123"), is_admin)


def test_username_is_unique_case_insensitively(store):
    import sqlite3

    _user(store, "Alice")
    assert store.get_user_by_username("ALICE")["username"] == "Alice"
    with pytest.raises(sqlite3.IntegrityError):
        _user(store, "alice")
    assert store.count_users() == 1


def test_session_create_and_lookup(store):
    user = _user(store)
    token = auth.new_session_token()
    store.create_session(user["id"], auth.hash_token(token), utcnow())

    found = store.get_session_user(auth.hash_token(token), utcnow())
    assert found["id"] == user["id"]
    assert found["username"] == "alice"
    assert found["is_admin"] is True


def test_unknown_session_token(store):
    assert store.get_session_user(auth.hash_token("no-such-token"), utcnow()) is None


def test_expired_session_is_rejected(store):
    user = _user(store)
    token = auth.new_session_token()
    now = utcnow()
    store.create_session(user["id"], auth.hash_token(token), now)

    beyond = now + SESSION_TTL + timedelta(seconds=1)
    assert store.get_session_user(auth.hash_token(token), beyond) is None


def test_session_expiry_rolls_forward_on_use(store):
    user = _user(store)
    token = auth.new_session_token()
    now = utcnow()
    store.create_session(user["id"], auth.hash_token(token), now)

    # A lookup one day before expiry renews the session for another full TTL.
    almost = now + SESSION_TTL - timedelta(days=1)
    assert store.get_session_user(auth.hash_token(token), almost) is not None
    later = almost + SESSION_TTL - timedelta(days=1)
    assert store.get_session_user(auth.hash_token(token), later) is not None


def test_delete_session_revokes_it(store):
    user = _user(store)
    token = auth.new_session_token()
    store.create_session(user["id"], auth.hash_token(token), utcnow())

    assert store.delete_session(auth.hash_token(token)) is True
    assert store.get_session_user(auth.hash_token(token), utcnow()) is None
    assert store.delete_session(auth.hash_token(token)) is False


# --- Register / login / logout ---------------------------------------------------


def test_first_register_is_public_and_creates_the_admin(client):
    response = client.post("/api/v1/auth/register", json=_credentials("alice"))
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert body["is_admin"] is True
    assert "password" not in body and "password_hash" not in body


def test_register_closes_after_the_first_user(client):
    client.post("/api/v1/auth/register", json=_credentials("alice"))
    response = client.post("/api/v1/auth/register", json=_credentials("bob"))
    assert response.status_code == 401


def test_admin_registers_further_users_as_non_admin(client):
    client.post("/api/v1/auth/register", json=_credentials("alice"))
    client.post("/api/v1/auth/login", json=_credentials("alice"))

    response = client.post("/api/v1/auth/register", json=_credentials("bob"))
    assert response.status_code == 201
    assert response.json()["is_admin"] is False


def test_non_admin_cannot_register_users(client):
    client.post("/api/v1/auth/register", json=_credentials("alice"))
    client.post("/api/v1/auth/login", json=_credentials("alice"))
    client.post("/api/v1/auth/register", json=_credentials("bob"))
    client.post("/api/v1/auth/logout")

    client.post("/api/v1/auth/login", json=_credentials("bob"))
    response = client.post("/api/v1/auth/register", json=_credentials("carol"))
    assert response.status_code == 403


def test_register_rejects_duplicate_username_case_insensitively(client):
    client.post("/api/v1/auth/register", json=_credentials("alice"))
    client.post("/api/v1/auth/login", json=_credentials("alice"))
    response = client.post("/api/v1/auth/register", json=_credentials("ALICE"))
    assert response.status_code == 409


def test_register_validates_password_length(client):
    response = client.post("/api/v1/auth/register", json=_credentials("alice", "short"))
    assert response.status_code == 422


def test_login_sets_an_http_only_session_cookie(client):
    client.post("/api/v1/auth/register", json=_credentials("alice"))
    response = client.post("/api/v1/auth/login", json=_credentials("alice"))
    assert response.status_code == 200
    assert response.json()["is_admin"] is True
    cookie = response.headers["set-cookie"]
    assert f"{auth.SESSION_COOKIE}=" in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    # Local dev is plain http: Secure only behind QUANTLAB_AUTH_COOKIE_SECURE.
    assert "secure" not in cookie.lower()


def test_login_rejects_wrong_password_and_unknown_user(client):
    client.post("/api/v1/auth/register", json=_credentials("alice"))
    wrong = client.post("/api/v1/auth/login", json=_credentials("alice", "wrong-password"))
    assert wrong.status_code == 401
    unknown = client.post("/api/v1/auth/login", json=_credentials("nobody"))
    assert unknown.status_code == 401
    # Same message either way: no user enumeration.
    assert wrong.json() == unknown.json()


def test_login_rate_limit_trips(tmp_path):
    app = create_app(str(tmp_path / "auth.db"), auth_enabled=True)
    app.state.login_limiter = auth.LoginRateLimiter(max_attempts=3, window_seconds=60)
    with TestClient(app) as c:
        c.post("/api/v1/auth/register", json=_credentials("alice"))
        for _ in range(3):
            response = c.post("/api/v1/auth/login", json=_credentials("alice", "nope-nope"))
            assert response.status_code == 401
        response = c.post("/api/v1/auth/login", json=_credentials("alice", "nope-nope"))
        assert response.status_code == 429
        # The limit applies before credentials are even checked.
        response = c.post("/api/v1/auth/login", json=_credentials("alice"))
        assert response.status_code == 429


def test_me_returns_the_authenticated_user(client):
    client.post("/api/v1/auth/register", json=_credentials("alice"))
    client.post("/api/v1/auth/login", json=_credentials("alice"))
    body = client.get("/api/v1/auth/me").json()
    assert body["username"] == "alice"
    assert set(body) == {"id", "username"}


def test_logout_revokes_the_session(client):
    client.post("/api/v1/auth/register", json=_credentials("alice"))
    client.post("/api/v1/auth/login", json=_credentials("alice"))
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


# --- The guard ---------------------------------------------------------------------


def test_protected_route_401s_without_a_session(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/models").status_code == 401
    assert client.get("/api/v1/runs").status_code == 401
    assert client.post("/api/v1/auth/logout").status_code == 401


def test_protected_route_passes_with_a_session(client):
    client.post("/api/v1/auth/register", json=_credentials("alice"))
    client.post("/api/v1/auth/login", json=_credentials("alice"))
    assert client.get("/api/v1/models").status_code == 200


def test_health_stays_public(client):
    assert client.get("/api/v1/health").status_code == 200


def test_auth_off_leaves_everything_open(tmp_path):
    with TestClient(create_app(str(tmp_path / "open.db"), auth_enabled=False)) as c:
        assert c.get("/api/v1/models").status_code == 200
        assert c.get("/api/v1/runs").status_code in (200, 503)  # require_seeded only
        # ...and the auth surface does not exist.
        assert c.post("/api/v1/auth/login", json=_credentials("alice")).status_code == 404
        assert c.post("/api/v1/auth/register", json=_credentials("alice")).status_code == 404
        assert c.get("/api/v1/auth/me").status_code == 404


# --- Per-user run isolation ---------------------------------------------------------


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("auth-isolation") / "quantlab.db"
    seed.run(path)
    return str(path)


def _fake_run(run_id: str) -> SimpleNamespace:
    """The smallest object SqliteExperimentStore.save_run will accept."""
    return SimpleNamespace(
        id=run_id,
        name=None,
        model_name="sma-crossover",
        model_version="1.0.0",
        parameters={"fast": 5, "slow": 12},
        symbols=["ZZTRND"],
        start_date="2024-01-01",
        end_date="2024-12-31",
        status="completed",
        error=None,
        created_at="2025-01-02T00:00:00+00:00",
        signal_count=0,
        coverage=SimpleNamespace(
            instruments_requested=1, instruments_with_data=1, instruments_full_warmup=1
        ),
        signals=[],
    )


def _login_client(db_path: str, username: str) -> TestClient:
    c = TestClient(create_app(db_path, auth_enabled=True))
    response = c.post("/api/v1/auth/login", json=_credentials(username))
    assert response.status_code == 200
    return c


@pytest.fixture()
def two_users(seeded_db, tmp_path):
    """(alice's client, bob's client, store) on a fresh copy of the seeded db."""
    import shutil

    db_path = str(tmp_path / "isolation.db")
    shutil.copy(seeded_db, db_path)
    with TestClient(create_app(db_path, auth_enabled=True)) as admin:
        assert admin.post("/api/v1/auth/register", json=_credentials("alice")).status_code == 201
        # Register does not log in: alice must log in before she can add bob.
        assert admin.post("/api/v1/auth/login", json=_credentials("alice")).status_code == 200
        assert admin.post("/api/v1/auth/register", json=_credentials("bob")).status_code == 201
    alice = _login_client(db_path, "alice")
    bob = _login_client(db_path, "bob")
    yield alice, bob, db_path
    alice.close()
    bob.close()


def test_users_cannot_see_or_touch_each_others_runs(two_users):
    alice, bob, _ = two_users
    created = alice.post(
        "/api/v1/runs",
        json={
            "model_name": "sma-crossover",
            "parameters": {"fast": 5, "slow": 12},
            "symbols": ["ZZTRND"],
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    )
    assert created.status_code == 201
    run_id = created.json()["id"]

    # Alice sees her run everywhere.
    assert run_id in {r["id"] for r in alice.get("/api/v1/runs").json()["items"]}
    assert alice.get(f"/api/v1/runs/{run_id}").status_code == 200
    assert alice.get(f"/api/v1/runs/{run_id}/performance").status_code == 200
    assert alice.patch(f"/api/v1/runs/{run_id}", json={"name": "mine"}).status_code == 200

    # Bob gets 404 for every one of those — the run id might as well not exist.
    assert run_id not in {r["id"] for r in bob.get("/api/v1/runs").json()["items"]}
    assert bob.get(f"/api/v1/runs/{run_id}").status_code == 404
    assert bob.get(f"/api/v1/runs/{run_id}/performance").status_code == 404
    assert bob.patch(f"/api/v1/runs/{run_id}", json={"name": "stolen"}).status_code == 404
    assert bob.delete(f"/api/v1/runs/{run_id}").status_code == 404

    # And Alice's run is intact afterwards.
    assert alice.get(f"/api/v1/runs/{run_id}").json()["name"] == "mine"
    assert alice.delete(f"/api/v1/runs/{run_id}").status_code == 204


def test_pre_auth_runs_stay_visible_to_everyone(two_users):
    alice, bob, db_path = two_users
    store = experiments.SqliteExperimentStore(db_path)
    store.save_run(_fake_run("legacy-run"), user_id=None)

    for c in (alice, bob):
        assert "legacy-run" in {r["id"] for r in c.get("/api/v1/runs").json()["items"]}
        assert c.get("/api/v1/runs/legacy-run").status_code == 200


def test_scoping_matches_between_stores(tmp_path):
    """Store-level: scoped reads see own + NULL-owned runs, never others'."""
    from quantlab.storage import db

    conn = db.connect(tmp_path / "s.db")
    db.bootstrap(conn)
    conn.close()
    store = experiments.SqliteExperimentStore(tmp_path / "s.db")
    store.save_run(_fake_run("a1"), user_id=1)
    store.save_run(_fake_run("b1"), user_id=2)
    store.save_run(_fake_run("legacy"), user_id=None)

    alice_ids = {r["id"] for r in store.list_runs(user_id=1)["items"]}
    assert alice_ids == {"a1", "legacy"}
    assert store.get_run("b1", user_id=1) is None
    assert store.get_run_signals("b1", user_id=1) == []
    assert store.set_run_name("b1", "nope", user_id=1) is False
    assert store.delete_run("b1", user_id=1) is False
    assert store.get_run("b1") is not None  # unscoped still sees it

    # Unscoped (auth off) behaves exactly as before.
    assert {r["id"] for r in store.list_runs()["items"]} == {"a1", "b1", "legacy"}
