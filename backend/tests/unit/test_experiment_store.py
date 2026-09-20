"""The ExperimentStore contract, exercised against every adapter (feature 006).

One suite, both adapters. If SQLite and Postgres can diverge in behaviour then
a saved experiment means something different depending on configuration, which
defeats the point of the seam.

The Postgres adapter skips when no catalog is reachable, so the demo path's
test run never requires a database.
"""

from __future__ import annotations

import os

import pytest

from quantlab.research.runner import RunCoverage, RunResult
from quantlab.signals.engine import ComputedSignal
from quantlab.storage import db, experiments, repository
from quantlab.synthetic.generator import generate_universe


def _make_result(run_id: str = "run-1", *, name=None, dataset="sqlite") -> RunResult:
    return RunResult(
        id=run_id,
        model_name="sma-crossover",
        model_version="1.0.0",
        parameters={"fast": 5, "slow": 12},
        symbols=["ZZTRND", "ZZMEAN"],
        start_date="2024-01-01",
        end_date="2024-12-31",
        status="completed",
        created_at="2026-09-19T12:00:00+00:00",
        signal_count=2,
        coverage=RunCoverage(
            instruments_requested=2, instruments_with_data=2, instruments_full_warmup=1
        ),
        signals=[
            ComputedSignal(
                symbol="ZZTRND",
                date="2024-03-15",
                rule_name="sma-crossover",
                rule_version="1.0.0",
                parameters={"fast": 5, "slow": 12},
                direction="bullish",
                trigger_values={"sma_fast": 101.2},
                data_window_end="2024-03-15",
            ),
            ComputedSignal(
                symbol="ZZMEAN",
                date="2024-04-02",
                rule_name="sma-crossover",
                rule_version="1.0.0",
                parameters={"fast": 5, "slow": 12},
                direction="bearish",
                trigger_values={"sma_fast": 88.4},
                data_window_end="2024-04-02",
            ),
        ],
        name=name,
        dataset=dataset,
    )


@pytest.fixture()
def sqlite_store(tmp_path):
    conn = db.connect(tmp_path / "experiments.db")
    db.bootstrap(conn)
    repository.upsert_instruments(conn)
    repository.insert_bars(conn, generate_universe())
    conn.commit()
    store = experiments.SqliteExperimentStore(str(tmp_path / "experiments.db"))
    yield store
    conn.close()


@pytest.fixture()
def postgres_store():
    """A Postgres store that leaves the catalog as it found it.

    Without this the suite passes exactly once per database: every test here
    uses a fixed run_id, so a second run collides on experiment_runs_pkey. The
    SQLite fixture gets isolation free from tmp_path; Postgres is shared and
    has to clean up after itself.

    Rows are identified by diffing against what existed before, rather than by
    a hardcoded list, so a test that invents a new id is still cleaned up.
    """
    if not os.environ.get("QUANTLAB_DB_URL"):
        pytest.skip("no catalog configured; the demo path must not need one")
    pytest.importorskip("psycopg")
    import psycopg

    dsn = os.environ["QUANTLAB_DB_URL"]

    def existing_ids() -> set[str]:
        with psycopg.connect(dsn) as conn:
            return {row[0] for row in conn.execute("SELECT run_id FROM experiment_runs")}

    def drop(ids: set[str]) -> None:
        if not ids:
            return
        with psycopg.connect(dsn) as conn:
            conn.execute("DELETE FROM experiment_runs WHERE run_id = ANY(%s)", (list(ids),))
            conn.commit()

    before = existing_ids()
    try:
        yield experiments.PostgresExperimentStore()
    finally:
        drop(existing_ids() - before)


@pytest.fixture(params=["sqlite", "postgres"])
def store(request):
    return request.getfixturevalue(f"{request.param}_store")


def test_round_trips_a_run_with_its_signals(store):
    result = _make_result()
    store.save_run(result)

    fetched = store.get_run(result.id)
    assert fetched is not None
    assert fetched["model_name"] == "sma-crossover"
    assert fetched["parameters"] == {"fast": 5, "slow": 12}
    assert fetched["signal_count"] == 2
    assert fetched["coverage"]["instruments_requested"] == 2

    signals = store.get_run_signals(result.id)
    assert len(signals) == 2
    for signal in signals:
        # Point-in-time proof survives the round trip (Constitution VII).
        assert signal["data_window_end"] <= signal["date"]


def test_unknown_run_is_absent_rather_than_an_error(store):
    assert store.get_run("does-not-exist") is None


def test_lists_runs_newest_first(store):
    store.save_run(_make_result("run-a"))
    store.save_run(_make_result("run-b"))

    listed = store.list_runs()
    ids = [item["id"] for item in listed["items"]]
    # Asserted as "contains, in this order" rather than "equals": the Postgres
    # catalog is shared and may already hold real runs. Demanding exclusive
    # ownership of the table is what made this suite pass only against an
    # empty database.
    assert {"run-a", "run-b"} <= set(ids)
    assert listed["total"] >= 2
    assert ids.index("run-b") < ids.index("run-a"), "newest first"


def test_saved_only_returns_named_runs(store):
    store.save_run(_make_result("unnamed"))
    store.save_run(_make_result("named"))
    store.set_run_name("named", "worth keeping")

    saved = store.list_runs(saved_only=True)
    ids = [item["id"] for item in saved["items"]]
    assert "named" in ids
    assert "unnamed" not in ids, "an unnamed run is not a saved experiment"
    assert next(i for i in saved["items"] if i["id"] == "named")["name"] == "worth keeping"


def test_naming_an_unknown_run_reports_failure(store):
    assert store.set_run_name("does-not-exist", "x") is False


def test_deleting_removes_the_run_and_its_signals_together(store):
    result = _make_result("doomed")
    store.save_run(result)

    assert store.delete_run("doomed") is True

    assert store.get_run("doomed") is None
    assert store.get_run_signals("doomed") == []
    # Deleting again is honest about finding nothing.
    assert store.delete_run("doomed") is False


def test_a_zero_signal_run_is_storable(store):
    """A model finding nothing is a result, and must persist as one."""
    empty = _make_result("quiet")
    empty = RunResult(**{**empty.__dict__, "signal_count": 0, "signals": []})
    store.save_run(empty)

    fetched = store.get_run("quiet")
    assert fetched["signal_count"] == 0
    assert store.get_run_signals("quiet") == []


def test_dataset_is_recorded(store):
    store.save_run(_make_result("tagged", dataset="sqlite"))
    assert store.get_run("tagged")["dataset"] == "sqlite"


def test_corporate_actions_survive_a_round_trip(store):
    """Persisted rather than only reported: reopening a saved run must still
    warn that its price series contains unadjusted discontinuities."""
    result = _make_result("with-split")
    split = {
        "instrument_id": 1,
        "symbol": "ZZTRND",
        "ex_date": "2024-08-31",
        "action_type": "split",
        "split_ratio": 4.0,
        "dividend": None,
    }
    result = RunResult(**{**result.__dict__, "corporate_actions": [split]})
    store.save_run(result)

    assert store.get_run("with-split")["corporate_actions"] == [split]


def test_a_run_without_actions_reports_an_empty_list_not_null(store):
    store.save_run(_make_result("clean"))
    assert store.get_run("clean")["corporate_actions"] == []
