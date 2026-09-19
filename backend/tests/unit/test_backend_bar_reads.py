"""The bar-reading methods the runner needs from a StorageBackend (feature 006).

These three are what let the runner stop knowing which store it is talking to.
Tested here against the SQLite adapter; the warehouse adapter is covered
separately because it needs a ClickHouse client.
"""

from __future__ import annotations

import pytest

from quantlab.storage import backends, db, repository
from quantlab.synthetic.generator import generate_universe


@pytest.fixture()
def backend(tmp_path):
    path = tmp_path / "demo.db"
    conn = db.connect(path)
    db.bootstrap(conn)
    repository.upsert_instruments(conn)
    repository.insert_bars(conn, generate_universe())
    conn.commit()
    conn.close()
    return backends.SqliteBackend(str(path))


def _symbols(backend, count=2):
    return [item["symbol"] for item in backend.list_instruments()["items"][:count]]


def test_loads_bars_for_several_instruments_across_one_window(backend):
    symbols = _symbols(backend)

    bars = backend.load_bars_for(symbols, "2024-01-01", "2024-06-30")

    assert set(bars) <= set(symbols)
    assert bars, "expected bars in a window this wide"
    for symbol, series in bars.items():
        assert series, f"{symbol} returned no bars"
        for bar in series:
            assert "2024-01-01" <= bar.date <= "2024-06-30"
        # Ascending by date: the engine relies on it.
        assert [bar.date for bar in series] == sorted(bar.date for bar in series)


def test_load_bars_for_an_unknown_symbol_yields_nothing_rather_than_raising(backend):
    assert backend.load_bars_for(["NOSUCH"], "2024-01-01", "2024-06-30") == {}


def test_load_bars_for_no_symbols_is_empty(backend):
    assert backend.load_bars_for([], "2024-01-01", "2024-06-30") == {}


def test_earliest_bar_dates_reports_the_first_bar_per_instrument(backend):
    symbols = _symbols(backend, 3)

    earliest = backend.earliest_bar_dates(symbols)

    assert set(earliest) == set(symbols)
    for symbol, first in earliest.items():
        window = backend.load_bars_for([symbol], "1900-01-01", "2100-01-01")[symbol]
        assert first == min(bar.date for bar in window)


def test_corporate_actions_are_empty_on_the_demo(backend):
    """The synthetic dataset has none; the method must still answer rather than
    raise, so the runner does not branch on which store it is talking to."""
    assert backend.corporate_actions(_symbols(backend), "2024-01-01", "2024-12-31") == []


def test_backend_reports_its_dataset_name(backend):
    assert backend.name == "sqlite"
