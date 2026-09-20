"""SC-005: every stored signal re-derives exactly from stored price_bars.

Seeds a fresh database, recomputes all registered rules from the persisted
price_bars alone, and asserts exact equality with the stored signals —
instrument, date, rule (name, version, parameters), direction, trigger
values, and data_window_end.
"""

from __future__ import annotations

from collections import Counter

from quantlab import seed
from quantlab.signals import engine
from quantlab.storage import db as dbmod
from quantlab.storage import repository


def _stored_signals(db_path):
    with dbmod.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT symbol, date, rule_name, rule_version, parameters, direction,
                   trigger_values, data_window_end
            FROM signals ORDER BY symbol, date, rule_name
            """
        ).fetchall()
    return [tuple(row) for row in rows]


def _recomputed_signals(db_path):
    with dbmod.connect(db_path) as conn:
        bars_by_symbol = repository.load_all_bars(conn)
    recomputed = engine.compute_signals(bars_by_symbol)
    return [
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


def test_signals_rederive_exactly_from_stored_bars(tmp_path):
    db_path = tmp_path / "rederive.db"
    seed.run(db_path)
    stored = _stored_signals(db_path)
    recomputed = _recomputed_signals(db_path)
    assert stored, "seed produced no signals"
    assert recomputed == stored


def test_rederivation_covers_every_rule_and_instrument(tmp_path):
    """The exact-equality check above could pass vacuously per rule; assert
    every stored (symbol, rule) pair appears in the recomputed set too."""
    db_path = tmp_path / "rederive_coverage.db"
    seed.run(db_path)
    stored = Counter((symbol, rule) for symbol, _, rule, *_ in _stored_signals(db_path))
    recomputed = Counter((symbol, rule) for symbol, _, rule, *_ in _recomputed_signals(db_path))
    assert stored == recomputed
    from quantlab.signals.registry import tradeable_rules

    assert {rule for _, rule in stored} <= {rule.name for rule in tradeable_rules()}
    assert {"sma-crossover", "rsi-threshold", "breakout-20d"} <= {
        rule for _, rule in stored
    }
