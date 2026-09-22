"""Seed pipeline tests: determinism (SC-002), rule coverage (SC-003),
point-in-time integrity (VII), full re-derivation (SC-005), and runtime < 30 s."""

from __future__ import annotations

import json
import time
from collections import Counter

from quantlab import config, seed
from quantlab.signals import engine
from quantlab.storage import db as dbmod
from quantlab.storage import repository


def test_seed_completes_under_30_seconds(tmp_path):
    started = time.monotonic()
    seed.run(tmp_path / "timed.db")
    assert time.monotonic() - started < 30.0


def test_double_seed_identical_ordered_dump(tmp_path):
    db1, db2 = tmp_path / "one.db", tmp_path / "two.db"
    seed.run(db1)
    seed.run(db2)
    with dbmod.connect(db1) as conn1, dbmod.connect(db2) as conn2:
        first_hash = dbmod.dump_hash(conn1)
        assert first_hash == dbmod.dump_hash(conn2)
    # Reseeding the SAME file is idempotent (interrupted-seed edge case).
    seed.run(db1)
    with dbmod.connect(db1) as conn1:
        assert dbmod.dump_hash(conn1) == first_hash


def test_every_signal_is_point_in_time(tmp_path):
    db_path = tmp_path / "pit.db"
    seed.run(db_path)
    with dbmod.connect(db_path) as conn:
        violations = conn.execute(
            "SELECT count(*) FROM signals WHERE data_window_end > date"
        ).fetchone()[0]
    assert violations == 0


def test_every_starter_rule_fires(tmp_path):
    db_path = tmp_path / "coverage.db"
    seed.run(db_path)
    with dbmod.connect(db_path) as conn:
        counts = dict(
            conn.execute("SELECT rule_name, count(*) FROM signals GROUP BY rule_name").fetchall()
        )
    for rule_name in ("sma-crossover", "rsi-threshold", "breakout-20d"):
        assert counts.get(rule_name, 0) >= 1, f"{rule_name} never fired"


def test_signals_rederive_from_stored_bars(tmp_path):
    """SC-005: recomputing every rule from stored price_bars reproduces signals exactly."""
    db_path = tmp_path / "rederive.db"
    seed.run(db_path)
    with dbmod.connect(db_path) as conn:
        bars_by_symbol = repository.load_all_bars(conn)
        recomputed = engine.compute_signals(bars_by_symbol)
        stored = conn.execute(
            """
            SELECT symbol, date, rule_name, rule_version, parameters, direction,
                   trigger_values, data_window_end
            FROM signals ORDER BY symbol, date, rule_name
            """
        ).fetchall()

    expected = [
        (
            s.symbol,
            s.date,
            s.rule_name,
            s.rule_version,
            dbmod.canonical_json(s.parameters),
            s.direction,
            dbmod.canonical_json(s.trigger_values),
            s.data_window_end,
        )
        for s in recomputed
    ]
    assert [tuple(row) for row in stored] == expected


def test_seed_marks_meta_seeded(tmp_path):
    db_path = tmp_path / "meta.db"
    seed.run(db_path)
    with dbmod.connect(db_path) as conn:
        assert dbmod.get_meta(conn, "seeded") == "1"
        counts = dbmod.table_counts(conn)
    assert counts["instruments"] == 12
    assert counts["price_bars"] == 12 * len(config.trading_calendar())
    assert counts["signals"] > 0
    rule_names = Counter()
    with dbmod.connect(db_path) as conn:
        for (params,) in conn.execute("SELECT parameters FROM signals"):
            json.loads(params)  # valid JSON
        for (name,) in conn.execute("SELECT DISTINCT rule_name FROM signals"):
            rule_names[name] += 1
    # Every rule that materialises is a tradeable one, and no filter is: a
    # filter describes a state and emits on every bar, so storing one would
    # bury the real signals under gate rows.
    from quantlab.signals.registry import list_rules, tradeable_rules

    assert set(rule_names) <= {rule.name for rule in tradeable_rules()}
    assert {"sma-crossover", "rsi-threshold", "breakout-20d"} <= set(rule_names)
    filters = {r.name for r in list_rules() if set(r.roles) == {"filter"}}
    assert filters and not (filters & set(rule_names))
