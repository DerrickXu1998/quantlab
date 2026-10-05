"""Experiment runner behaviour (features 005 and 006).

Feature 006 changed what the runner is handed: a StorageBackend and an
ExperimentStore rather than a sqlite3 connection. Every guarantee below is
unchanged -- that is the point of the seam. If one of these breaks, the
refactor changed behaviour, not just plumbing.

The warm-up window is the highest-risk behaviour in this feature: get it wrong
and results look entirely plausible while being quietly misleading, because the
first ~lookback_days of any window silently emit nothing.
"""

from __future__ import annotations

import pytest

from quantlab.research import errors
from quantlab.research.runner import MAX_SELECTION_INSTRUMENT_DAYS, run_experiment
from quantlab.storage import backends, db, repository
from quantlab.synthetic.generator import generate_universe


@pytest.fixture()
def conn(tmp_path):
    """Named `conn` for continuity with the feature-005 suite; it is now the
    storage seam the runner is handed."""
    path = tmp_path / "test.db"
    connection = db.connect(path)
    db.bootstrap(connection)
    repository.upsert_instruments(connection)
    repository.insert_bars(connection, generate_universe())
    connection.commit()
    connection.close()
    return backends.SqliteBackend(str(path))


def _symbols(backend):
    return sorted(item["symbol"] for item in backend.list_instruments()["items"][:2])


# --- (a) warm-up window -----------------------------------------------------


def test_reported_signals_are_confined_to_the_requested_window(conn):
    symbols = _symbols(conn)
    result = run_experiment(
        conn,
        model_name="sma-crossover",
        overrides={},
        symbols=symbols,
        start_date="2024-06-01",
        end_date="2024-12-31",
    )

    assert result.signals, "expected signals in a window this long"
    for signal in result.signals:
        assert "2024-06-01" <= signal.date <= "2024-12-31"


def test_warmup_history_is_loaded_so_the_window_does_not_cold_start(conn):
    """The decisive test. sma-crossover declares lookback_days=51. If only
    in-window bars were loaded, the first ~51 trading days could not emit, and a
    short window would understate the model. Signals must be able to appear in
    the first weeks of the window when prior history exists."""
    symbols = _symbols(conn)
    start, end = "2024-06-01", "2024-08-31"

    result = run_experiment(
        conn,
        model_name="sma-crossover",
        overrides={},
        symbols=symbols,
        start_date=start,
        end_date=end,
    )

    assert result.coverage.instruments_full_warmup > 0, (
        "instruments with history before the window start must be reported as "
        "having full warm-up"
    )
    # Compare against a run over the same window with a much longer history
    # available: the in-window signals must agree, proving the short window was
    # not cold-started.
    long_run = run_experiment(
        conn,
        model_name="sma-crossover",
        overrides={},
        symbols=symbols,
        start_date="2023-01-01",
        end_date=end,
    )
    in_window = [s for s in long_run.signals if start <= s.date <= end]
    assert [(s.symbol, s.date) for s in result.signals] == [
        (s.symbol, s.date) for s in in_window
    ], "a short window must produce the same in-window signals as a long one"


# --- (b) window shorter than the model's lookback ---------------------------


def test_window_shorter_than_lookback_is_rejected_before_executing(conn):
    """Must be an explained rejection, never a completed run with zero signals —
    the two are indistinguishable to a researcher otherwise."""
    with pytest.raises(errors.WindowTooShortError) as excinfo:
        run_experiment(
            conn,
            model_name="sma-crossover",
            overrides={},
            symbols=_symbols(conn),
            start_date="2024-06-01",
            end_date="2024-06-10",
        )
    assert "lookback" in str(excinfo.value).lower()


# --- (c) determinism --------------------------------------------------------


def test_identical_configurations_produce_identical_results(conn):
    kwargs = dict(
        model_name="sma-crossover",
        overrides={"fast": 10, "slow": 30},
        symbols=_symbols(conn),
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    first = run_experiment(conn, **kwargs)
    second = run_experiment(conn, **kwargs)

    assert [(s.symbol, s.date, s.direction) for s in first.signals] == [
        (s.symbol, s.date, s.direction) for s in second.signals
    ]
    assert first.signal_count == second.signal_count


# --- (d) zero signals is a result, not a failure ----------------------------


def test_zero_signal_run_completes_with_coverage(conn):
    """A model that fires nothing is information. It must complete."""
    result = run_experiment(
        conn,
        model_name="rsi-threshold",
        # RSI is bounded to [0, 100], so these thresholds cannot be crossed.
        # A principled way to guarantee silence rather than hoping for it.
        overrides={"overbought": 100, "oversold": 0},
        symbols=_symbols(conn),
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    assert result.signal_count == 0
    assert result.signals == []
    assert result.coverage.instruments_requested == len(_symbols(conn))


# --- coverage and validation ------------------------------------------------


def test_coverage_reports_the_denominator(conn):
    symbols = _symbols(conn)
    result = run_experiment(
        conn,
        model_name="sma-crossover",
        overrides={},
        symbols=symbols,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    assert result.coverage.instruments_requested == len(symbols)
    assert 0 <= result.coverage.instruments_with_data <= len(symbols)
    assert 0 <= result.coverage.instruments_full_warmup <= result.coverage.instruments_with_data


def test_out_of_range_parameter_is_rejected_naming_the_parameter(conn):
    with pytest.raises(errors.ParameterValidationError) as excinfo:
        run_experiment(
            conn,
            model_name="sma-crossover",
            overrides={"fast": -5},
            symbols=_symbols(conn),
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
    assert excinfo.value.parameter == "fast"


def test_unknown_model_is_rejected(conn):
    with pytest.raises(errors.UnknownModelError):
        run_experiment(
            conn,
            model_name="does-not-exist",
            overrides={},
            symbols=_symbols(conn),
            start_date="2024-01-01",
            end_date="2024-12-31",
        )


def test_unknown_symbol_is_rejected(conn):
    with pytest.raises(errors.UnknownSymbolError):
        run_experiment(
            conn,
            model_name="sma-crossover",
            overrides={},
            symbols=["NOT-A-SYMBOL"],
            start_date="2024-01-01",
            end_date="2024-12-31",
        )


def test_start_after_end_is_rejected(conn):
    with pytest.raises(errors.InvalidWindowError):
        run_experiment(
            conn,
            model_name="sma-crossover",
            overrides={},
            symbols=_symbols(conn),
            start_date="2024-12-31",
            end_date="2024-01-01",
        )


def test_duplicate_symbols_are_deduplicated(conn):
    """Asking for the same instrument twice must not double the work or the
    coverage denominator."""
    symbols = _symbols(conn)
    result = run_experiment(
        conn,
        model_name="sma-crossover",
        overrides={},
        symbols=symbols * 3,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    assert result.coverage.instruments_requested == len(symbols)
    assert result.symbols == sorted(set(symbols))


def test_oversized_selection_is_rejected_up_front(conn):
    """The size guard runs before symbol validation: it is the cheaper check,
    and an obviously oversized request should not pay for a universe lookup."""
    with pytest.raises(errors.SelectionTooLargeError):
        run_experiment(
            conn,
            model_name="sma-crossover",
            overrides={},
            # One more symbol-year than the limit allows, whatever it is set to.
            symbols=[f"SYM{i:05d}" for i in range(MAX_SELECTION_INSTRUMENT_DAYS // 366 + 1)],
            start_date="2024-01-01",
            end_date="2024-12-31",
        )


# --- fundamental coverage ---------------------------------------------------
#
# A fundamental gate with no facts holds shut and says nothing. These pin the
# two halves of making that visible: a run that could never fire is refused,
# and one that could partly fire says which names it could not read.


def _annual_revenue(first_year: int, last_year: int):
    from quantlab.storage.facts import build_series

    rows = []
    for k, year in enumerate(range(first_year, last_year + 1)):
        rows.append(
            {
                "concept": "revenue",
                "value": 1.0e9 * (1.2**k),
                "period_start": f"{year}-01-01",
                "period_end": f"{year}-12-31",
                "filed_at": f"{year + 1}-03-01",
            }
        )
    return build_series(rows)


class _FactsBackend:
    """The demo's bars with a warehouse's name and some filings: exactly the
    store the fallback hides, and exactly the one these tests need."""

    name = "warehouse"

    def __init__(self, inner, facts, fundamentals_start=None):
        self._inner = inner
        self._facts = facts
        self._fundamentals_start = fundamentals_start
        self.fundamentals_start_calls = 0

    def __getattr__(self, attr):
        return getattr(self._inner, attr)

    def load_facts_for(self, symbols, concepts, start, end):
        return {s: self._facts[s] for s in symbols if s in self._facts}

    def fundamentals_start(self, symbols, concepts, end):
        self.fundamentals_start_calls += 1
        return self._fundamentals_start


def test_a_fundamental_run_on_the_demo_is_refused_naming_the_dataset(conn):
    """The demo has no filings. An empty run would look like a model that never fired."""
    with pytest.raises(errors.DatasetUnsupportedError, match="synthetic demo"):
        run_experiment(
            conn,
            model_name="revenue-growth",
            symbols=_symbols(conn),
            start_date="2024-01-01",
            end_date="2024-12-31",
        )


def test_a_fundamental_run_where_no_name_has_filed_is_refused(conn):
    backend = _FactsBackend(conn, facts={})
    with pytest.raises(errors.NoFactCoverageError, match="revenue on or before 2024-12-31"):
        run_experiment(
            backend,
            model_name="revenue-growth",
            symbols=_symbols(conn),
            start_date="2024-01-01",
            end_date="2024-12-31",
        )


def test_partial_fact_coverage_is_reported_and_persisted(conn):
    from quantlab.storage.experiments import SqliteExperimentStore

    covered, uncovered = _symbols(conn)
    backend = _FactsBackend(conn, facts={covered: _annual_revenue(2018, 2023)})

    result = run_experiment(
        backend,
        model_name="revenue-growth",
        symbols=[covered, uncovered],
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    facts = result.coverage.facts
    assert facts is not None
    assert facts.concepts == ["revenue"]
    assert facts.instruments_with_facts == 1
    assert facts.missing_by_concept == {"revenue": 1}
    assert facts.instruments_missing_facts == [uncovered]

    store = SqliteExperimentStore(conn.db_path)
    store.save_run(result)
    stored = store.get_run(result.id, None)
    assert stored["coverage"]["facts"] == {
        "concepts": ["revenue"],
        "instruments_with_facts": 1,
        "missing_by_concept": {"revenue": 1},
        "instruments_missing_facts": [uncovered],
        # The demo-backed fake knows no fundamentals start, so nothing moved.
        "fundamentals_start": None,
        "requested_start_date": None,
    }


# --- fundamentals bound the window ------------------------------------------
#
# Before the first filing every fundamental gate holds shut, so those years
# are a flat line against a moving benchmark: not a result, a data gap. A run
# that reads fundamentals starts where they do (constitution, Principle III).


def test_a_fundamental_run_starts_where_its_fundamentals_do(conn):
    from quantlab.research.runner import prepare_run

    backend = _FactsBackend(conn, facts={}, fundamentals_start="2024-03-01")
    prepared = prepare_run(
        backend,
        model_name="revenue-growth",
        symbols=_symbols(conn),
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    assert prepared.start_date == "2024-03-01"
    assert prepared.requested_start_date == "2024-01-01"
    assert prepared.fundamentals_start == "2024-03-01"
    # The worker re-prepares from the request, so it must carry what was asked
    # for: re-limiting the limited start would lose the original.
    assert prepared.request()["start_date"] == "2024-01-01"
    again = prepare_run(backend, **prepared.request())
    assert (again.start_date, again.requested_start_date) == ("2024-03-01", "2024-01-01")


def test_a_start_inside_fundamental_coverage_is_left_alone(conn):
    from quantlab.research.runner import prepare_run

    backend = _FactsBackend(conn, facts={}, fundamentals_start="2023-10-05")
    prepared = prepare_run(
        backend,
        model_name="revenue-growth",
        symbols=_symbols(conn),
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    assert prepared.start_date == "2024-01-01"
    assert prepared.requested_start_date is None
    assert prepared.fundamentals_start == "2023-10-05"


def test_a_bars_only_run_never_asks_where_fundamentals_start(conn):
    from quantlab.research.runner import prepare_run

    backend = _FactsBackend(conn, facts={}, fundamentals_start="2024-03-01")
    prepared = prepare_run(
        backend,
        model_name="sma-crossover",
        symbols=_symbols(conn),
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    assert prepared.start_date == "2024-01-01"
    assert prepared.fundamentals_start is None
    assert backend.fundamentals_start_calls == 0


def test_a_limited_run_records_both_dates_in_its_fact_coverage(conn):
    from quantlab.storage.experiments import SqliteExperimentStore

    covered, uncovered = _symbols(conn)
    backend = _FactsBackend(
        conn, facts={covered: _annual_revenue(2018, 2023)}, fundamentals_start="2024-03-01"
    )
    result = run_experiment(
        backend,
        model_name="revenue-growth",
        symbols=[covered, uncovered],
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    assert result.start_date == "2024-03-01"
    assert result.coverage.facts.fundamentals_start == "2024-03-01"
    assert result.coverage.facts.requested_start_date == "2024-01-01"

    store = SqliteExperimentStore(conn.db_path)
    store.save_run(result)
    stored = store.get_run(result.id, None)
    assert stored["start_date"] == "2024-03-01"
    assert stored["coverage"]["facts"]["requested_start_date"] == "2024-01-01"


def test_the_demo_has_no_fundamentals_start():
    """Unknown, not "today": the demo's refusal stays the one that names it."""
    start = backends.SqliteBackend.fundamentals_start(None, ["AAA"], ["revenue"], "2024-12-31")
    assert start is None


def test_a_run_without_fundamental_rules_reports_no_fact_coverage(conn):
    result = run_experiment(
        conn,
        model_name="sma-crossover",
        symbols=_symbols(conn),
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    assert result.coverage.facts is None


def test_a_name_missing_one_of_two_concepts_counts_as_missing():
    """pe-filter reads net_income and shares_outstanding; half a P/E is none."""
    from quantlab.research.runner import _fact_coverage
    from quantlab.storage.facts import build_series

    only_income = build_series(
        [
            {"concept": "net_income", "value": 1.0, "period_start": "2023-01-01",
             "period_end": "2023-12-31", "filed_at": "2024-03-01"},
        ]
    )
    coverage = _fact_coverage(
        ["AAA", "BBB"], ["net_income", "shares_outstanding"], {"AAA": only_income}
    )

    assert coverage.instruments_with_facts == 0
    assert coverage.missing_by_concept == {"net_income": 1, "shares_outstanding": 2}
    assert coverage.instruments_missing_facts == ["AAA", "BBB"]
