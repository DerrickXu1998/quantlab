"""The warehouse schema: discoverable, ordered, and protected against edits.

Offline except the last test, which applies everything to a real warehouse
when QUANTLAB_DB_URL and QUANTLAB_CH_URL point at one (`make store-test`).
"""

from __future__ import annotations

import importlib
import os
import re

import pytest

from quantlab import store
from quantlab.cli import main

runner = importlib.import_module("quantlab.store.migrate")


def _versions(directory) -> list[str]:
    return [path.stem for path in runner.discover(directory)]


def test_every_migration_is_numbered_and_in_order():
    for directory in (store.MIGRATIONS_DIR, store.CH_MIGRATIONS_DIR):
        versions = _versions(directory)
        assert versions, directory
        numbers = [int(re.match(r"(\d{3})_", v).group(1)) for v in versions]
        assert numbers == sorted(set(numbers)), f"duplicate or unordered numbers in {directory}"


def test_the_catalog_and_bars_schemas_are_all_here():
    assert _versions(store.MIGRATIONS_DIR)[:9] == [
        "001_catalog",
        "002_signals",
        "003_experiments",
        "004_fundamentals",
        "005_strategies_and_identity",
        "006_custom_rules",
        "007_run_fact_coverage",
        "008_run_queue",
        "009_run_results_stored",
    ]
    # 100 and 101 were written in quantlab-data-pipeline and are owned here
    # now, byte for byte, so warehouses that already applied them agree.
    assert _versions(store.CH_MIGRATIONS_DIR) == [
        "001_bars",
        "002_bars_force_merge",
        "100_pipeline_frequency_views",
        "101_minute_type",
    ]


def test_an_applied_migration_that_changed_is_refused():
    assert runner._check_drift("001_x", "abc", {}) is True
    assert runner._check_drift("001_x", "abc", {"001_x": "abc"}) is False
    with pytest.raises(store.MigrationDrift):
        runner._check_drift("001_x", "abc", {"001_x": "different"})


def test_a_semicolon_in_a_comment_does_not_split_a_statement():
    sql = "-- one; two\nCREATE TABLE t (a Int8);\n-- three;\nALTER TABLE t ADD COLUMN b Int8;"
    assert runner._split_statements(sql) == [
        "CREATE TABLE t (a Int8)",
        "ALTER TABLE t ADD COLUMN b Int8",
    ]


def test_moved_commands_say_where_they_went(capsys):
    assert main(["ingest-macro", "--provider", "fred"]) == 2
    err = capsys.readouterr().err
    assert "quantlab-data-pipeline" in err
    assert 'make quantlab-data ARGS="ingest-macro --provider fred"' in err


@pytest.mark.skipif(
    not (os.environ.get("QUANTLAB_DB_URL") and os.environ.get("QUANTLAB_CH_URL")),
    reason="needs QUANTLAB_DB_URL and QUANTLAB_CH_URL (run `make store-test`)",
)
def test_migrations_apply_and_are_idempotent():
    with store.session() as conn, store.ch_session() as client:
        store.migrate_all(conn, client)
        assert store.migrate(conn) == []
        assert store.ch_migrate(client) == []
        assert store.current_version(conn) == _versions(store.MIGRATIONS_DIR)[-1]
        assert store.ch_current_version(client) == _versions(store.CH_MIGRATIONS_DIR)[-1]
