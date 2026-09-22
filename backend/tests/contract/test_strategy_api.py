"""The strategy, execution and identity surfaces, over real HTTP.

These are the tests that would have caught the whole library being unreachable:
every one of them goes through the app, not around it.

The suite runs with authentication *on*, because that is the configuration a
deployment uses and the one where isolation can actually be wrong. Single-user
mode gets its own test at the bottom rather than being the default everything
else quietly relies on.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api.app import create_app

# PBKDF2 at its real cost is a third of a second per login, which would make
# this suite take minutes. The floor in quantlab.auth.passwords stops this from
# silently weakening a deployment.
os.environ.setdefault("QUANTLAB_PBKDF2_ITERATIONS", "1000")

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="module")
def seeded_template(tmp_path_factory):
    """Seeded once. Seeding is deterministic but not instant."""
    path = tmp_path_factory.mktemp("seed") / "template.db"
    seed.run(path)
    return path


@pytest.fixture
def db_path(seeded_template, tmp_path):
    """A private copy per test.

    Accounts and runs are written by these tests, so sharing one file would
    make them order-dependent -- and a suite whose isolation tests depend on
    execution order is not testing isolation.
    """
    import shutil

    path = tmp_path / "quantlab.db"
    shutil.copyfile(seeded_template, path)
    return str(path)


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.setenv("QUANTLAB_AUTH_REQUIRED", "true")
    with TestClient(create_app(db_path)) as test_client:
        yield test_client


def register(client, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def token(client):
    return register(client, "alice@example.com")


@pytest.fixture
def window(client):
    """The seeded dataset's actual extent, so tests do not pin a hardcoded year."""
    bars = client.get("/api/v1/instruments/ZZTRND/prices").json()["items"]
    return bars[0]["date"], bars[-1]["date"]


# --- identity ---------------------------------------------------------------


def test_health_is_public_and_says_whether_auth_is_required(client):
    """The SPA must learn this before it can possibly hold a token."""
    body = client.get("/api/v1/health").json()
    assert body["auth_required"] is True
    assert body["seeded"] is True


def test_register_returns_a_session_and_login_returns_another(client):
    first = client.post(
        "/api/v1/auth/register", json={"email": "bob@example.com", "password": PASSWORD}
    )
    assert first.status_code == 201
    assert set(first.json()) == {"user", "token", "expires_at"}

    second = client.post(
        "/api/v1/auth/login", json={"email": "BOB@example.com", "password": PASSWORD}
    )
    assert second.status_code == 200
    assert second.json()["user"]["id"] == first.json()["user"]["id"]
    assert second.json()["token"] != first.json()["token"]


def test_a_weak_password_is_refused_with_a_reason(client):
    response = client.post(
        "/api/v1/auth/register", json={"email": "weak@example.com", "password": "short"}
    )
    assert response.status_code == 422
    assert "12 characters" in response.json()["detail"]


def test_a_duplicate_registration_is_a_conflict(client, token):
    response = client.post(
        "/api/v1/auth/register", json={"email": "alice@example.com", "password": PASSWORD}
    )
    assert response.status_code == 409


def test_login_does_not_reveal_whether_an_account_exists(client, token):
    """Both answers are identical, so the endpoint is not an enumeration oracle."""
    wrong = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "wrong-but-long-enough"},
    )
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-but-long-enough"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_me_requires_a_token_and_returns_the_caller(client, token):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers=auth("nonsense")).status_code == 401
    body = client.get("/api/v1/auth/me", headers=auth(token)).json()
    assert body["email"] == "alice@example.com"


def test_logout_revokes_only_the_session_that_used_it(client):
    first = register(client, "carol@example.com")
    second = client.post(
        "/api/v1/auth/login", json={"email": "carol@example.com", "password": PASSWORD}
    ).json()["token"]

    assert client.post("/api/v1/auth/logout", headers=auth(first)).status_code == 204
    assert client.get("/api/v1/auth/me", headers=auth(first)).status_code == 401
    # Revoking one session must not sign the user out of their other devices.
    assert client.get("/api/v1/auth/me", headers=auth(second)).status_code == 200


def test_security_headers_are_present(client):
    headers = client.get("/api/v1/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"


# --- the model catalogue ----------------------------------------------------


def test_the_catalogue_carries_the_metadata_a_builder_needs(client):
    body = client.get("/api/v1/models").json()
    assert body["total"] >= 13
    by_name = {item["name"]: item for item in body["items"]}

    assert by_name["rsi-threshold"]["category"] == "mean_reversion"
    assert "entry" in by_name["rsi-threshold"]["roles"]
    # A rule that reports a regime rather than an event must advertise itself
    # as a filter only, or a builder cannot stop a user wiring it as an entry.
    assert by_name["adx-trend-filter"]["roles"] == ["filter"]
    assert all(item["summary"] for item in body["items"])


def test_the_new_rules_are_all_served(client):
    names = {item["name"] for item in client.get("/api/v1/models").json()["items"]}
    assert {
        "macd-crossover",
        "ema-crossover",
        "bollinger-reversion",
        "stochastic-threshold",
        "zscore-reversion",
        "roc-momentum",
        "donchian-breakout",
        "volume-spike",
        "adx-trend-filter",
        "rsi-zone",
    } <= names


def test_templates_are_public_and_complete(client):
    body = client.get("/api/v1/strategy-templates").json()
    assert body["total"] == 4
    for item in body["items"]:
        assert item["components"], item["id"]
        assert item["execution"]["commission_bps"] > 0, "a starter must not teach free turnover"


# --- strategies -------------------------------------------------------------


def rsi_plus_adx() -> dict:
    """The strategy the whole feature exists for: RSI, gated by a trend filter."""
    return {
        "name": "RSI in a trend",
        "description": "",
        "components": [
            {"rule_name": "rsi-threshold", "role": "entry", "parameters": {"oversold": 30.0}},
            {"rule_name": "rsi-threshold", "role": "exit", "parameters": {"overbought": 70.0}},
            {"rule_name": "adx-trend-filter", "role": "filter", "parameters": {"threshold": 20.0}},
        ],
        "entry_logic": "any",
        "exit_logic": "any",
        "execution": {"stop_loss_pct": 0.05, "commission_bps": 5.0},
    }


def test_strategies_require_a_token(client):
    assert client.get("/api/v1/strategies").status_code == 401
    assert client.post("/api/v1/strategies", json=rsi_plus_adx()).status_code == 401


def test_a_strategy_round_trips_through_crud(client, token):
    created = client.post("/api/v1/strategies", json=rsi_plus_adx(), headers=auth(token))
    assert created.status_code == 201, created.text
    strategy_id = created.json()["id"]
    assert len(created.json()["components"]) == 3
    assert created.json()["execution"]["stop_loss_pct"] == 0.05

    fetched = client.get(f"/api/v1/strategies/{strategy_id}", headers=auth(token))
    assert fetched.json()["name"] == "RSI in a trend"

    renamed = dict(rsi_plus_adx(), name="Renamed")
    updated = client.put(
        f"/api/v1/strategies/{strategy_id}", json=renamed, headers=auth(token)
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"

    assert client.delete(
        f"/api/v1/strategies/{strategy_id}", headers=auth(token)
    ).status_code == 204
    assert client.get(
        f"/api/v1/strategies/{strategy_id}", headers=auth(token)
    ).status_code == 404


def test_a_filter_cannot_be_wired_as_an_entry(client, token):
    body = dict(
        rsi_plus_adx(),
        components=[{"rule_name": "adx-trend-filter", "role": "entry"}],
    )
    response = client.post("/api/v1/strategies", json=body, headers=auth(token))
    assert response.status_code == 422
    assert "cannot be used as an 'entry'" in response.json()["detail"]


def test_a_bad_parameter_names_the_component_and_the_field(client, token):
    body = dict(
        rsi_plus_adx(),
        components=[
            {"rule_name": "rsi-threshold", "role": "entry", "parameters": {"period": 9999}}
        ],
    )
    response = client.post("/api/v1/strategies", json=body, headers=auth(token))
    assert response.status_code == 422
    assert "components[0].parameters.period" in response.json()["detail"]


def test_a_strategy_with_no_exit_is_saved_but_warned_about(client, token):
    body = dict(
        rsi_plus_adx(),
        name="Entry only",
        components=[{"rule_name": "rsi-threshold", "role": "entry"}],
        execution={},
    )
    created = client.post("/api/v1/strategies", json=body, headers=auth(token))
    assert created.status_code == 201
    assert any("never closed" in w for w in created.json()["warnings"])


def test_one_user_cannot_see_or_delete_anothers_strategy(client, token):
    mine = client.post(
        "/api/v1/strategies", json=rsi_plus_adx(), headers=auth(token)
    ).json()["id"]
    intruder = register(client, "mallory@example.com")

    assert client.get("/api/v1/strategies", headers=auth(intruder)).json()["total"] == 0
    # 404 and not 403: a 403 confirms the row exists.
    assert client.get(
        f"/api/v1/strategies/{mine}", headers=auth(intruder)
    ).status_code == 404
    assert client.delete(
        f"/api/v1/strategies/{mine}", headers=auth(intruder)
    ).status_code == 404
    # And it really is still there afterwards.
    assert client.get(f"/api/v1/strategies/{mine}", headers=auth(token)).status_code == 200


# --- running ----------------------------------------------------------------


def run_body(window, **overrides) -> dict:
    start, end = window
    return {
        "symbols": ["ZZTRND", "ZZMEAN"],
        "start_date": start,
        "end_date": end,
        **overrides,
    }


def test_a_legacy_single_model_run_still_works_unchanged(client, token, window):
    response = client.post(
        "/api/v1/runs",
        json=run_body(window, model_name="rsi-threshold", parameters={}),
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["model_name"] == "rsi-threshold"
    assert body["signal_count"] > 0
    # It is promoted into a one-rule strategy, and says so.
    assert body["strategy"]["components"][0]["rule_name"] == "rsi-threshold"
    assert body["execution"]["position_sizing"] == "equal_weight"


def test_an_inline_strategy_runs_and_records_what_it_ran(client, token, window):
    response = client.post(
        "/api/v1/runs",
        json=run_body(window, strategy=rsi_plus_adx()),
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["strategy"]["components"]) == 3
    assert body["execution"]["stop_loss_pct"] == 0.05
    assert body["execution_summary"]["fills"] >= 0


def test_a_saved_strategy_can_be_run_by_id(client, token, window):
    strategy_id = client.post(
        "/api/v1/strategies", json=rsi_plus_adx(), headers=auth(token)
    ).json()["id"]
    response = client.post(
        "/api/v1/runs", json=run_body(window, strategy_id=strategy_id), headers=auth(token)
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["strategy"]["components"]) == 3


def test_running_another_users_strategy_by_id_is_a_404(client, token, window):
    strategy_id = client.post(
        "/api/v1/strategies", json=rsi_plus_adx(), headers=auth(token)
    ).json()["id"]
    intruder = register(client, "eve@example.com")
    response = client.post(
        "/api/v1/runs", json=run_body(window, strategy_id=strategy_id), headers=auth(intruder)
    )
    assert response.status_code == 404


def test_naming_two_sources_at_once_is_refused(client, token, window):
    response = client.post(
        "/api/v1/runs",
        json=run_body(window, model_name="rsi-threshold", strategy=rsi_plus_adx()),
        headers=auth(token),
    )
    assert response.status_code == 400


def test_naming_no_source_is_refused(client, token, window):
    response = client.post("/api/v1/runs", json=run_body(window), headers=auth(token))
    assert response.status_code == 400


def test_execution_criteria_change_the_result(client, token, window):
    """The whole point: the same signals, executed differently, differ."""
    plain = client.post(
        "/api/v1/runs",
        json=run_body(window, model_name="sma-crossover"),
        headers=auth(token),
    ).json()
    stopped = client.post(
        "/api/v1/runs",
        json=run_body(
            window,
            model_name="sma-crossover",
            execution={"stop_loss_pct": 0.05, "take_profit_pct": 0.10},
        ),
        headers=auth(token),
    ).json()

    assert plain["signal_count"] == stopped["signal_count"], "same signals"

    plain_perf = client.get(
        f"/api/v1/runs/{plain['id']}/performance", headers=auth(token)
    ).json()
    stopped_perf = client.get(
        f"/api/v1/runs/{stopped['id']}/performance", headers=auth(token)
    ).json()

    assert plain_perf["exit_reasons"].get("stop_loss", 0) == 0
    assert stopped_perf["exit_reasons"].get("stop_loss", 0) > 0
    assert plain_perf["metrics"]["total_return"] != stopped_perf["metrics"]["total_return"]


def test_an_invalid_execution_setting_is_refused_by_name(client, token, window):
    response = client.post(
        "/api/v1/runs",
        json=run_body(window, model_name="rsi-threshold", execution={"stop_loss_pct": 5.0}),
        headers=auth(token),
    )
    assert response.status_code == 422
    assert "stop_loss_pct" in response.json()["detail"]


def test_a_window_shorter_than_the_lookback_is_refused(client, token):
    """Counted in bars against calendar days, which is the unit mismatch this
    check used to get wrong: 60 calendar days hold about 43 sessions."""
    response = client.post(
        "/api/v1/runs",
        json={
            "symbols": ["ZZTRND"],
            "start_date": "2024-01-01",
            "end_date": "2024-02-20",
            "model_name": "sma-crossover",
        },
        headers=auth(token),
    )
    assert response.status_code == 422
    assert "lookback" in response.json()["detail"]


# --- performance ------------------------------------------------------------


def test_performance_reports_costs_and_exit_reasons(client, token, window):
    run = client.post(
        "/api/v1/runs",
        json=run_body(
            window,
            model_name="rsi-threshold",
            execution={"commission_bps": 10.0, "slippage_bps": 5.0, "stop_loss_pct": 0.07},
        ),
        headers=auth(token),
    ).json()

    body = client.get(f"/api/v1/runs/{run['id']}/performance", headers=auth(token)).json()
    assert body["costs"]["commission"] > 0
    assert body["costs"]["slippage"] > 0
    assert sum(body["exit_reasons"].values()) == len(body["trades"])
    for trade in body["trades"]:
        assert trade["side"] in ("long", "short")
        assert trade["qty"] > 0
        assert trade["exit_reason"]


def test_assumptions_describe_the_run_that_actually_happened(client, token, window):
    """They used to be a fixed tuple, so a run could charge costs and still
    claim it charged none."""
    charged = client.post(
        "/api/v1/runs",
        json=run_body(window, model_name="rsi-threshold", execution={"commission_bps": 10.0}),
        headers=auth(token),
    ).json()
    body = client.get(f"/api/v1/runs/{charged['id']}/performance", headers=auth(token)).json()
    assert not any("No transaction costs" in line for line in body["assumptions"])
    assert any("10 bps commission" in line for line in body["assumptions"])

    free = client.post(
        "/api/v1/runs", json=run_body(window, model_name="rsi-threshold"), headers=auth(token)
    ).json()
    free_body = client.get(
        f"/api/v1/runs/{free['id']}/performance", headers=auth(token)
    ).json()
    assert any("No transaction costs" in line for line in free_body["assumptions"])


def test_a_replay_reconciles_with_its_own_performance(client, token, window):
    """The two used to be separate implementations kept in step by hand."""
    run = client.post(
        "/api/v1/runs",
        json=run_body(
            window, model_name="rsi-threshold", execution={"stop_loss_pct": 0.06}
        ),
        headers=auth(token),
    ).json()

    summary = client.get(
        f"/api/v1/runs/{run['id']}/replay/summary", headers=auth(token)
    ).json()
    performance = client.get(
        f"/api/v1/runs/{run['id']}/performance", headers=auth(token)
    ).json()

    assert summary["total_return"] == pytest.approx(
        performance["metrics"]["total_return"], rel=1e-9
    )
    assert summary["trade_count"] == performance["metrics"]["trade_count"]
    assert summary["exit_reasons"] == performance["exit_reasons"]


def test_a_replay_stream_emits_stop_fills(client, token, window):
    """A protective exit is triggered by a session's high and low. The replay
    used to reduce every bar to its close before the simulator saw it, so a
    stop could never fire there even when the run's own performance had one."""
    run = client.post(
        "/api/v1/runs",
        json=run_body(window, model_name="sma-crossover", execution={"stop_loss_pct": 0.04}),
        headers=auth(token),
    ).json()

    with client.stream(
        "GET",
        f"/api/v1/runs/{run['id']}/replay/stream",
        headers=auth(token),
        params={"max_events": 200_000},
    ) as response:
        assert response.status_code == 200
        reasons = set()
        for line in response.iter_lines():
            if line.startswith("data: ") and '"event": "fill"' in line:
                import json

                reasons.add(json.loads(line[6:])["reason"])
    assert "stop_loss" in reasons


# --- run ownership ----------------------------------------------------------


def test_one_user_cannot_see_or_delete_anothers_run(client, token, window):
    mine = client.post(
        "/api/v1/runs", json=run_body(window, model_name="rsi-threshold"), headers=auth(token)
    ).json()["id"]
    intruder = register(client, "trudy@example.com")

    assert client.get("/api/v1/runs", headers=auth(intruder)).json()["total"] == 0
    assert client.get(f"/api/v1/runs/{mine}", headers=auth(intruder)).status_code == 404
    assert client.delete(f"/api/v1/runs/{mine}", headers=auth(intruder)).status_code == 404
    assert client.patch(
        f"/api/v1/runs/{mine}", json={"name": "stolen"}, headers=auth(intruder)
    ).status_code == 404
    assert client.get(
        f"/api/v1/runs/{mine}/performance", headers=auth(intruder)
    ).status_code == 404
    assert client.get(
        f"/api/v1/runs/{mine}/replay/summary", headers=auth(intruder)
    ).status_code == 404

    # Still intact for its owner, including its signals.
    detail = client.get(f"/api/v1/runs/{mine}", headers=auth(token))
    assert detail.status_code == 200
    assert detail.json()["signals"]


def test_runs_require_a_token(client, window):
    assert client.get("/api/v1/runs").status_code == 401
    assert client.post("/api/v1/runs", json=run_body(window)).status_code == 401


# --- single-user mode -------------------------------------------------------


def test_with_auth_disabled_the_api_needs_no_token(db_path, monkeypatch):  # noqa: D103
    """The local demo must still boot straight into the app, and must still
    write rows of the same shape a real deployment does."""
    monkeypatch.setenv("QUANTLAB_AUTH_REQUIRED", "false")
    with TestClient(create_app(db_path)) as anonymous:
        assert anonymous.get("/api/v1/health").json()["auth_required"] is False
        assert anonymous.get("/api/v1/auth/me").json()["id"] == "local"
        assert anonymous.get("/api/v1/runs").status_code == 200
        assert anonymous.get("/api/v1/strategies").status_code == 200

        created = anonymous.post("/api/v1/strategies", json=rsi_plus_adx())
        assert created.status_code == 201
