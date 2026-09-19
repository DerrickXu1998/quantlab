"""The demo path must not acquire a database dependency (feature 006).

The zero-setup promise is that cloning the project and running it works with no
databases, no credentials and no network. A single module-scope `import psycopg`
would break that for everyone without Postgres installed, and nothing else in
the suite would notice — the drivers are present in this environment.

So these tests make them *absent* and check the demo path still stands up.
"""

from __future__ import annotations

import builtins
import sys

import pytest

from quantlab import seed
from quantlab.storage import backends, experiments

WAREHOUSE_DRIVERS = ("psycopg", "clickhouse_connect")


@pytest.fixture()
def drivers_unavailable(monkeypatch):
    """Make the warehouse drivers unimportable for the duration of a test."""
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in WAREHOUSE_DRIVERS:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    for module in list(sys.modules):
        if module.split(".")[0] in WAREHOUSE_DRIVERS:
            monkeypatch.delitem(sys.modules, module, raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded)
    # Nothing may point the app at a warehouse while we assert the fallback.
    monkeypatch.delenv("QUANTLAB_DB_URL", raising=False)
    monkeypatch.delenv("QUANTLAB_CH_URL", raising=False)
    return guarded


def test_the_app_starts_and_serves_with_no_warehouse_drivers(drivers_unavailable, tmp_path):
    db_path = tmp_path / "demo.db"
    seed.run(db_path)

    from fastapi.testclient import TestClient

    from quantlab.api.app import create_app

    with TestClient(create_app(str(db_path))) as client:
        health = client.get("/api/v1/health").json()
        assert health["dataset"] == "sqlite"
        assert health["seeded"] is True
        assert client.get("/api/v1/instruments").status_code == 200
        assert client.get("/api/v1/models").status_code == 200


def test_backend_selection_falls_back_without_drivers(drivers_unavailable, tmp_path):
    chosen = backends.select_backend(str(tmp_path / "demo.db"))
    assert chosen.name == "sqlite"


def test_experiment_store_selection_falls_back_without_drivers(drivers_unavailable, tmp_path):
    chosen = experiments.select_experiment_store(str(tmp_path / "demo.db"))
    assert chosen.name == "sqlite"


def test_a_full_run_completes_without_drivers(drivers_unavailable, tmp_path):
    """The whole workbench loop, not just startup."""
    db_path = tmp_path / "demo.db"
    seed.run(db_path)

    from quantlab.research.runner import run_experiment

    backend = backends.SqliteBackend(str(db_path))
    store = experiments.SqliteExperimentStore(str(db_path))
    symbols = [item["symbol"] for item in backend.list_instruments()["items"][:2]]

    result = run_experiment(
        backend,
        model_name="sma-crossover",
        overrides={},
        symbols=symbols,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    store.save_run(result)

    assert result.dataset == "sqlite"
    assert store.get_run(result.id) is not None
