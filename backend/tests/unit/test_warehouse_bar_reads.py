"""Warehouse bar reads for the experiment runner (feature 006).

Driven against fakes rather than a live warehouse, so these run everywhere. The
property that matters most is which relation is read: `price_bars` collapses
duplicates at merge time on ClickHouse's own schedule, so a re-ingested range
read from the raw table comes back doubled. Reads must go through
`price_bars_current`, which applies FINAL.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pytest

from quantlab.storage import warehouse


@dataclass
class _Result:
    result_rows: list


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.queries: list[str] = []
        self.closed = False
        self.released = 0

    fail = False

    def query(self, sql, parameters=None):
        self.queries.append(sql)
        self.parameters = parameters
        if self.fail:
            raise RuntimeError("bar store query failed")
        return _Result(self._rows)

    def close(self):
        self.closed = True

    # Warehouse.bars() is a context manager since feature 007 -- the client is
    # checked out of a pool and returned on every exit path, rather than
    # constructed and closed per request.
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.released += 1
        return False


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeCatalog:
    def __init__(self, rows):
        self._rows = rows
        self.statements: list[str] = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        return _FakeCursor(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeWarehouse:
    def __init__(self, catalog_rows, bar_rows):
        self._catalog = _FakeCatalog(catalog_rows)
        self.client = _FakeClient(bar_rows)

    def catalog(self):
        return self._catalog

    def bars(self):
        return self.client


def _ts(day: int) -> dt.datetime:
    return dt.datetime(2024, 3, day, tzinfo=dt.UTC)


@pytest.fixture()
def wh():
    return _FakeWarehouse(
        catalog_rows=[("AAPL.US", 1), ("MSFT.US", 2)],
        bar_rows=[
            (1, _ts(1), 10.0, 11.0, 9.0, 10.5, 100),
            (1, _ts(2), 10.5, 12.0, 10.0, 11.5, 120),
            (2, _ts(1), 50.0, 51.0, 49.0, 50.5, 200),
        ],
    )


def test_reads_through_the_deduplicating_view_not_the_raw_table(wh):
    warehouse.load_bars_for(wh, ["AAPL.US", "MSFT.US"], "2024-03-01", "2024-03-31")

    sql = wh.client.queries[0]
    assert "price_bars_current" in sql
    # Reading the raw table would double a re-ingested range.
    assert "FROM price_bars\n" not in sql and "FROM price_bars " not in sql


def test_returns_bars_keyed_by_symbol_ascending_by_date(wh):
    bars = warehouse.load_bars_for(wh, ["AAPL.US", "MSFT.US"], "2024-03-01", "2024-03-31")

    assert set(bars) == {"AAPL.US", "MSFT.US"}
    assert [bar.date for bar in bars["AAPL.US"]] == ["2024-03-01", "2024-03-02"]
    assert bars["MSFT.US"][0].close == 50.5


def test_window_is_passed_as_a_full_day_range(wh):
    warehouse.load_bars_for(wh, ["AAPL.US"], "2024-03-01", "2024-03-31")

    params = wh.client.parameters
    # ts is a timestamp, so an end of "2024-03-31" must include that whole day.
    assert params["start"].startswith("2024-03-01")
    assert params["end"] == "2024-03-31 23:59:59"


def test_unknown_symbols_yield_nothing_rather_than_querying_bars():
    wh = _FakeWarehouse(catalog_rows=[], bar_rows=[])

    assert warehouse.load_bars_for(wh, ["NOSUCH"], "2024-01-01", "2024-12-31") == {}
    assert wh.client.queries == [], "should not reach the bar store for unknown symbols"


def test_the_client_is_released_even_though_rows_were_returned(wh):
    """Was: asserted the client is *closed* after a read. Since feature 007 it
    is checked out of a pool and *returned* -- closing it is precisely the
    behaviour that was removed. The invariant that matters is unchanged: a read
    must not leak the client, however the read ends."""
    warehouse.load_bars_for(wh, ["AAPL.US"], "2024-03-01", "2024-03-31")

    assert wh.client.released == 1
    assert not wh.client.closed, "a pooled client is returned for reuse, not closed"


def test_the_client_is_released_when_a_read_fails(wh):
    """The exit path that leaks a connection is the one nobody tests."""
    wh.client.fail = True

    with pytest.raises(RuntimeError):
        warehouse.load_bars_for(wh, ["AAPL.US"], "2024-03-01", "2024-03-31")

    assert wh.client.released == 1


def test_earliest_bar_dates_maps_back_to_symbols():
    wh = _FakeWarehouse(
        catalog_rows=[("AAPL.US", 1), ("MSFT.US", 2)],
        bar_rows=[(1, _ts(1)), (2, _ts(5))],
    )

    assert warehouse.earliest_bar_dates(wh, ["AAPL.US", "MSFT.US"]) == {
        "AAPL.US": "2024-03-01",
        "MSFT.US": "2024-03-05",
    }


def test_corporate_actions_shape_is_reported_not_applied():
    """Splits are surfaced so an unadjusted discontinuity is recognisable.
    Prices are never adjusted here — that is a separate feature."""

    class _TwoStepCatalog(_FakeCatalog):
        def __init__(self):
            super().__init__([])
            self._calls = 0

        def execute(self, sql, params=None):
            self._calls += 1
            if self._calls == 1:
                return _FakeCursor([("AAPL.US", 1)])
            return _FakeCursor([(1, dt.date(2020, 8, 31), "split", 4.0, None)])

    wh = _FakeWarehouse(catalog_rows=[], bar_rows=[])
    wh._catalog = _TwoStepCatalog()

    actions = warehouse.corporate_actions(wh, ["AAPL.US"], "2020-01-01", "2020-12-31")

    assert actions == [
        {
            "instrument_id": 1,
            "symbol": "AAPL.US",
            "ex_date": "2020-08-31",
            "action_type": "split",
            "split_ratio": 4.0,
            "dividend": None,
        }
    ]


def test_ingest_provenance_distinguishes_a_re_ingest():
    """The case that matters: identical configuration, different data.

    Every input the researcher chose is the same; only the ingest behind the
    bars changed. If this were not recorded the two runs would look
    reproducible when they are not.
    """
    before = _FakeWarehouse(catalog_rows=[("AAPL.US", 1)], bar_rows=[(7,)])
    after = _FakeWarehouse(catalog_rows=[("AAPL.US", 1)], bar_rows=[(9,)])

    first = warehouse.ingest_run_ids(before, ["AAPL.US"], "2024-01-01", "2024-12-31")
    second = warehouse.ingest_run_ids(after, ["AAPL.US"], "2024-01-01", "2024-12-31")

    assert first == [7]
    assert second == [9]
    assert first != second


def test_ingest_provenance_reads_the_deduplicating_view():
    """A re-ingest supersedes earlier rows only after a merge, so the raw table
    would report both the old and new run ids."""
    wh = _FakeWarehouse(catalog_rows=[("AAPL.US", 1)], bar_rows=[(7,)])

    warehouse.ingest_run_ids(wh, ["AAPL.US"], "2024-01-01", "2024-12-31")

    assert "price_bars_current" in wh.client.queries[0]


def test_no_known_symbols_means_no_ingest_lineage():
    wh = _FakeWarehouse(catalog_rows=[], bar_rows=[])
    assert warehouse.ingest_run_ids(wh, ["NOSUCH"], "2024-01-01", "2024-12-31") == []
    assert wh.client.queries == []


# --- universe-sized selections are read in batches ---------------------------
#
# One FINAL query over a whole universe exceeded the self-hosted ClickHouse's
# per-query memory cap; the reads now go BAR_QUERY_CHUNK instruments at a time.
# These pin that the batching is invisible: same answers, just more queries.


class _IdAwareClient(_FakeClient):
    """Answers each query only for the ids it asked about, as ClickHouse would."""

    def __init__(self, rows_by_id):
        super().__init__([])
        self._rows_by_id = rows_by_id
        self.batches: list[tuple] = []

    def query(self, sql, parameters=None):
        self.queries.append(sql)
        ids = tuple((parameters or {}).get("ids", ()))
        self.batches.append(ids)
        if "DISTINCT run_id" in sql:
            # Overlapping run ids across batches: the union must dedupe them.
            runs = sorted({r for i in ids for r in self._rows_by_id[i]["runs"]})
            return _Result([(r,) for r in runs])
        if "min(ts)" in sql:
            return _Result([(i, self._rows_by_id[i]["bars"][0][1]) for i in ids])
        if "argMax(close" in sql:
            return _Result([(i, self._rows_by_id[i]["bars"][-1][5]) for i in ids])
        return _Result([row for i in ids for row in self._rows_by_id[i]["bars"]])


def _universe(n=60):
    symbols = [f"S{i:03d}.US" for i in range(1, n + 1)]
    rows_by_id = {
        i: {
            "bars": [(i, _ts(d), 1.0, 2.0, 0.5, float(i * 10 + d), 100) for d in (1, 2)],
            "runs": {7, 7 + i % 3},
        }
        for i in range(1, n + 1)
    }
    # Catalogue rows deliberately out of id order: batching must still sort.
    catalog = [(s, i) for i, s in reversed(list(enumerate(symbols, start=1)))]
    wh = _FakeWarehouse(catalog_rows=catalog, bar_rows=[])
    wh.client = _IdAwareClient(rows_by_id)
    return wh, symbols


def test_a_universe_is_read_in_batches_and_reassembled_exactly():
    wh, symbols = _universe(60)

    bars = warehouse.load_bars_for(wh, symbols, "2024-03-01", "2024-03-31")

    assert [len(b) for b in wh.client.batches] == [25, 25, 10]
    assert all(len(set(b)) == len(b) for b in wh.client.batches)
    assert sorted(i for b in wh.client.batches for i in b) == list(range(1, 61))
    assert set(bars) == set(symbols)
    assert [bar.close for bar in bars["S042.US"]] == [421.0, 422.0]


def test_a_small_selection_is_still_one_query(wh):
    warehouse.load_bars_for(wh, ["AAPL.US", "MSFT.US"], "2024-03-01", "2024-03-31")
    assert len(wh.client.queries) == 1


def test_per_instrument_aggregates_merge_across_batches():
    wh, symbols = _universe(60)

    first = warehouse.earliest_bar_dates(wh, symbols)
    last = warehouse._last_closes(wh, symbols, "2024-03-31")
    runs = warehouse.ingest_run_ids(wh, symbols, "2024-03-01", "2024-03-31")

    assert len(first) == 60 and first["S060.US"] == "2024-03-01"
    assert len(last) == 60 and last["S060.US"] == 602.0
    # Distinct per batch, deduplicated and ordered across batches.
    assert runs == [7, 8, 9]


def test_catalogue_materialisation_reads_in_batches_too():
    wh, symbols = _universe(60)
    # This path reads the catalogue as (instrument_id, symbol), not (symbol, id).
    wh._catalog = _FakeCatalog([(i, s) for s, i in wh._catalog._rows])

    yielded = list(warehouse.iter_symbol_bars(wh, symbols))

    assert len(wh.client.queries) == 3
    assert len(yielded) == 60
    by_symbol = {symbol: bars for symbol, _, bars in yielded}
    assert [bar.close for bar in by_symbol["S001.US"]] == [11.0, 12.0]
