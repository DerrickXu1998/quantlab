"""Daily bars as columns must change nothing but memory.

The warehouse now hands a daily backtest ``BarSeries`` (datetime64[D]) instead
of one object per bar. Every number a run reports has to be the same as on
rows: signals, trades, fills, equity, the summary, and the re-derived
performance. Checked across a split and a dividend, with stops and ATR sizing
switched on so the adjusted-price paths are exercised too.
"""

from __future__ import annotations

import numpy as np
import pytest

from quantlab.execution.bars import BarSeries
from quantlab.research import performance, runner
from quantlab.synthetic.generator import Bar

DAYS = np.busday_offset("2022-01-03", np.arange(700), roll="forward")


def _rows(seed):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, len(DAYS))))
    close[400:] /= 4  # a 4-for-1 split on DAYS[400], raw prices
    return [
        Bar(str(d), float(c * 0.995), float(c * 1.01), float(c * 0.99), float(c), 1_000 + i)
        for i, (d, c) in enumerate(zip(DAYS, close, strict=True))
    ]


ROWS = {"AAA": _rows(1), "BBB": _rows(2)}
ACTIONS = [
    {
        "symbol": "AAA",
        "ex_date": str(DAYS[400]),
        "action_type": "split",
        "split_ratio": 4.0,
        "dividend": None,
    },
    {
        "symbol": "BBB",
        "ex_date": str(DAYS[400]),
        "action_type": "split",
        "split_ratio": 4.0,
        "dividend": None,
    },
    {
        "symbol": "AAA",
        "ex_date": str(DAYS[250]),
        "action_type": "dividend",
        "split_ratio": None,
        "dividend": 1.25,
    },
]


def _columns(rows):
    return BarSeries(
        np.array([b.date for b in rows], dtype="datetime64[D]"),
        [b.open for b in rows],
        [b.high for b in rows],
        [b.low for b in rows],
        [b.close for b in rows],
        [b.volume for b in rows],
    )


class Store:
    name = "warehouse"

    def __init__(self, columnar):
        self.columnar = columnar

    def _window(self, start, end):
        return {s: [b for b in rows if start <= b.date <= end] for s, rows in ROWS.items()}

    def load_bars_for(self, symbols, start, end):
        return self._window(start, end)

    def validate_symbols(self, symbols):
        return [s for s in symbols if s not in ROWS]

    def corporate_actions(self, symbols, start, end):
        return [a for a in ACTIONS if start <= a["ex_date"] <= end]

    def load_facts_for(self, symbols, concepts, start, end):
        return {}

    def instrument_ids(self, symbols):
        return {}

    def ingest_run_ids(self, symbols, start, end):
        return []

    def earliest_bar_dates(self, symbols):
        return {s: str(DAYS[0]) for s in symbols}


class ColumnarStore(Store):
    def load_daily_columns(self, symbols, start, end):
        return {s: _columns(rows) for s, rows in self._window(start, end).items()}


EXECUTION = {
    "stop_loss_pct": 0.05,
    "trailing_stop_pct": 0.08,
    "atr_stop_multiple": 2.5,
    "position_sizing": "volatility_target",
    "sizing_value": 0.2,
    "max_position_pct": 0.5,
}


def _run(store):
    return runner.run_experiment(
        store,
        symbols=["AAA", "BBB"],
        start_date=str(DAYS[60]),
        end_date=str(DAYS[-1]),
        model_name="sma-crossover",
        overrides={"fast": 10, "slow": 30},
        execution=EXECUTION,
    )


@pytest.fixture(scope="module")
def both():
    return _run(Store(False)), _run(ColumnarStore(True))


def test_the_columnar_path_is_actually_taken():
    bars = runner.load_bars(
        ColumnarStore(True), ["AAA"], "2022-01-01", "2024-12-31", runner.ExecutionConfig()
    )
    assert isinstance(bars["AAA"], BarSeries)
    assert bars["AAA"][0].date == str(DAYS[0])  # a daily key, not a timestamp


def test_signals_are_identical(both):
    rows, columns = both
    assert [vars(s) for s in rows.signals] == [vars(s) for s in columns.signals]
    assert rows.signal_count > 0


def test_execution_is_identical(both):
    rows, columns = both
    assert rows.execution_summary == columns.execution_summary
    assert rows.corporate_actions == columns.corporate_actions


def test_rederived_performance_is_identical(both):
    rows, _ = both
    config = runner.execution_config_for({"execution": rows.execution})
    signals = [vars(s) for s in rows.signals]

    def perf(store):
        bars = runner.load_bars(store, rows.symbols, str(DAYS[0]), rows.end_date, config)
        from quantlab.execution import adjustments

        actions = adjustments.by_symbol(
            store.corporate_actions(rows.symbols, str(DAYS[0]), rows.end_date),
            config.price_adjustment,
            end=rows.end_date,
        )
        return performance.compute_performance(
            run_id="r",
            signals=signals,
            bars_by_symbol=bars,
            symbols=rows.symbols,
            execution=config,
            window_start=rows.start_date,
            window_end=rows.end_date,
            corporate_actions=actions,
        )

    a, b = perf(Store(False)), perf(ColumnarStore(True))
    assert a.equity == b.equity
    assert a.benchmark == b.benchmark
    assert a.trades == b.trades
    assert a.metrics == b.metrics


def test_replay_events_are_identical(both):
    from quantlab.replay import engine as replay_engine

    rows, _ = both
    run = {
        "id": "r",
        "symbols": rows.symbols,
        "start_date": rows.start_date,
        "end_date": rows.end_date,
        "execution": rows.execution,
        "strategy": rows.strategy,
    }
    config = runner.execution_config_for(run)
    signals = [vars(s) for s in rows.signals]

    def events(store):
        bars = runner.load_bars(store, rows.symbols, str(DAYS[0]), rows.end_date, config)
        return [
            replay_engine.to_dict(e)
            for e in replay_engine.replay_events(run, signals, bars, config=config)
        ]

    assert events(Store(False)) == events(ColumnarStore(True))


def test_studies_are_identical(both):
    from quantlab.research import studies

    rows, _ = both
    run = {"id": "r", "strategy": rows.strategy, "model_name": "sma-crossover"}
    a = studies.compute_studies(run=run, symbol="AAA", bars=ROWS["AAA"])
    b = studies.compute_studies(run=run, symbol="AAA", bars=_columns(ROWS["AAA"]))
    assert a == b and a.studies
