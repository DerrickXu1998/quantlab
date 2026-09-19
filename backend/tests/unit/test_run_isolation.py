"""Experiment output must never reach the seeded signal set (feature 005).

The existing `signals` table is keyed on
(symbol, date, rule_name, rule_version, parameters), so experiment output would
insert into it *cleanly* and then appear in the Signal Viewer — mixing
exploratory runs into the curated seeded set with nothing to indicate it. This
is the regression guard on an existing screen.
"""

from __future__ import annotations

import pytest

from quantlab.research.runner import run_experiment
from quantlab.storage import backends, db, experiments, repository
from quantlab.synthetic.generator import generate_universe


@pytest.fixture()
def seeded(tmp_path):
    """Yields (backend, store, conn): the two seams the runner now takes, plus
    a raw connection for asserting directly on the seeded tables."""
    path = tmp_path / "test.db"
    conn = db.connect(path)
    db.bootstrap(conn)
    repository.upsert_instruments(conn)
    bars = generate_universe()
    repository.insert_bars(conn, bars)

    from quantlab.signals.engine import compute_signals
    from quantlab.signals.registry import list_rules

    repository.mirror_rules(conn, list_rules())
    repository.insert_signals(conn, compute_signals(bars))
    conn.commit()
    yield backends.SqliteBackend(str(path)), experiments.SqliteExperimentStore(str(path)), conn
    conn.close()


def _seeded_signal_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]


def test_running_an_experiment_does_not_touch_the_seeded_signals_table(seeded):
    backend, store, conn = seeded
    before = _seeded_signal_count(conn)
    assert before > 0, "fixture should have seeded signals"

    symbols = [item["symbol"] for item in backend.list_instruments()["items"][:3]]
    result = run_experiment(
        backend,
        model_name="sma-crossover",
        overrides={"fast": 5, "slow": 12},
        symbols=symbols,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    store.save_run(result)

    assert _seeded_signal_count(conn) == before


def test_experiment_signals_land_in_their_own_table(seeded):
    backend, store, conn = seeded
    symbols = [item["symbol"] for item in backend.list_instruments()["items"][:3]]
    result = run_experiment(
        backend,
        model_name="sma-crossover",
        overrides={"fast": 5, "slow": 12},
        symbols=symbols,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    store.save_run(result)

    stored = conn.execute(
        "SELECT COUNT(*) FROM experiment_signals WHERE run_id = ?", (result.id,)
    ).fetchone()[0]
    assert stored == result.signal_count


def test_existing_signals_query_is_unaffected_by_runs(seeded):
    backend, store, conn = seeded
    before = repository.list_signals(conn, limit=50, offset=0)["total"]

    symbols = [item["symbol"] for item in backend.list_instruments()["items"][:3]]
    result = run_experiment(
        backend,
        model_name="sma-crossover",
        overrides={"fast": 5, "slow": 12},
        symbols=symbols,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    store.save_run(result)

    assert repository.list_signals(conn, limit=50, offset=0)["total"] == before


def test_deleting_a_run_removes_its_signals(seeded):
    backend, store, conn = seeded
    symbols = [item["symbol"] for item in backend.list_instruments()["items"][:3]]
    result = run_experiment(
        backend,
        model_name="sma-crossover",
        overrides={"fast": 5, "slow": 12},
        symbols=symbols,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    store.save_run(result)

    store.delete_run(result.id)

    remaining = conn.execute(
        "SELECT COUNT(*) FROM experiment_signals WHERE run_id = ?", (result.id,)
    ).fetchone()[0]
    assert remaining == 0
    assert store.get_run(result.id) is None
    # And the seeded set is still untouched.
    assert _seeded_signal_count(conn) > 0
