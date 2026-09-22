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
from quantlab.research.runner import run_experiment
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
            symbols=[f"SYM{i:05d}" for i in range(6000)],
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
