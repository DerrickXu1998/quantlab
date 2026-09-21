"""Fundamentals reads and point-in-time transforms (feature 008).

Warehouse reads are driven against fakes rather than a live warehouse, so they
run everywhere. The property that matters most is the visibility axis: a fact
is knowable from ``filed_at`` onwards, never from the ``period_end`` it
describes -- as_of_series is where that rule lives, and the tests below pin it.
"""

from __future__ import annotations

import datetime as dt

import pytest

from quantlab import fundamentals
from quantlab.storage import warehouse
from quantlab.storage.backends import SqliteBackend


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeCatalog:
    """Serves each registered query shape in call order."""

    def __init__(self, rows_by_call):
        self._rows_by_call = list(rows_by_call)
        self.statements: list[str] = []
        self.params: list = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        self.params.append(params)
        return _FakeCursor(self._rows_by_call.pop(0) if self._rows_by_call else [])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeWarehouse:
    def __init__(self, catalog_rows_by_call):
        self._catalog = _FakeCatalog(catalog_rows_by_call)

    def catalog(self):
        return self._catalog


def _fact(value, filed_at, period_end="2023-12-31", holder=None, provider="sec_edgar"):
    return {
        "value": float(value),
        "period_start": None,
        "period_end": period_end,
        "filed_at": filed_at,
        "provider": provider,
        "unit": "USD",
        "holder": holder,
    }


# --- Per-instrument concept catalog -------------------------------------------


def test_concept_catalog_excludes_unmapped_raw_facts_and_marks_derived():
    wh = _FakeWarehouse(
        [
            # Stored groups (concept <> '' only).
            [("revenue", "sec_edgar", "USD", 120, dt.date(2020, 2, 5), dt.date(2026, 2, 4))],
            # Derived short_volume_ratio overlap query: 60 aligned dates.
            [(60, dt.date(2026, 8, 20), dt.date(2026, 9, 18), "short_volume_ratio", "finra")],
        ]
    )

    result = warehouse.list_fundamental_concepts(wh, "AAPL.US")

    assert result["symbol"] == "AAPL.US"
    assert result["total"] == 2
    stored, derived = result["items"]
    assert stored == {
        "concept": "revenue",
        "provider": "sec_edgar",
        "unit": "USD",
        "fact_count": 120,
        "first_filed": "2020-02-05",
        "last_filed": "2026-02-04",
        "derived": False,
    }
    assert derived["concept"] == "short_volume_ratio"
    assert derived["derived"] is True
    assert derived["unit"] == "ratio"
    assert derived["fact_count"] == 60


def test_concept_catalog_sql_excludes_empty_concepts():
    wh = _FakeWarehouse([[], []])

    warehouse.list_fundamental_concepts(wh, "AAPL.US")

    assert "f.concept <> ''" in wh._catalog.statements[0]


def test_no_derived_concept_without_both_inputs():
    stored = [("revenue", "sec_edgar", "USD", 3, dt.date(2020, 2, 5), dt.date(2021, 2, 5))]
    wh = _FakeWarehouse([stored, []])

    result = warehouse.list_fundamental_concepts(wh, "AAPL.US")

    assert [item["concept"] for item in result["items"]] == ["revenue"]


# --- Raw fact reads -------------------------------------------------------------


def test_facts_read_preserves_both_dates_and_holder():
    row = (3.95, None, dt.date(2018, 9, 24), dt.date(2018, 9, 26), "fca", "pct", "BNP PARIBAS SA")
    wh = _FakeWarehouse([[row]])

    (fact,) = warehouse.get_fundamental_facts(wh, "AAL.LON", "net_short_position")

    assert fact["value"] == 3.95
    assert fact["period_start"] is None
    assert fact["period_end"] == "2018-09-24"
    assert fact["filed_at"] == "2018-09-26"
    assert fact["holder"] == "BNP PARIBAS SA"


# --- as_of_series: the point-in-time rule ----------------------------------------


def test_latest_filing_wins_and_restatements_supersede():
    facts = [
        _fact(10.0, "2024-02-09"),
        _fact(10.5, "2024-03-01"),  # restatement of the same period
        _fact(11.0, "2025-02-07", period_end="2024-12-31"),
    ]

    points = fundamentals.as_of_series(facts)

    assert points == [
        {"date": "2024-02-09", "value": 10.0},
        {"date": "2024-03-01", "value": 10.5},
        {"date": "2025-02-07", "value": 11.0},
    ]


def test_a_windowed_series_opens_with_the_value_knowable_at_start():
    """Without the opening point, a 2024 read would start from the first 2024
    filing -- silently presenting February's knowledge as January's."""
    facts = [_fact(10.0, "2023-02-03", "2022-12-31"), _fact(11.0, "2024-02-09")]

    points = fundamentals.as_of_series(facts, start="2024-01-01", end="2024-12-31")

    assert points == [
        {"date": "2024-01-01", "value": 10.0},
        {"date": "2024-02-09", "value": 11.0},
    ]


def test_a_window_before_any_filing_is_empty():
    facts = [_fact(10.0, "2024-02-09")]
    assert fundamentals.as_of_series(facts, start="2023-01-01", end="2023-12-31") == []


def test_per_holder_filings_are_summed_across_holders_per_date():
    """FCA short positions: each holder's latest filing persists until they
    file again; the series is the sum across holders."""
    facts = [
        _fact(0.5, "2024-01-10", holder="A", provider="fca"),
        _fact(1.0, "2024-01-12", holder="B", provider="fca"),
        _fact(0.7, "2024-02-01", holder="A", provider="fca"),  # A re-files lower
    ]

    points = fundamentals.as_of_series(facts)

    assert points == [
        {"date": "2024-01-10", "value": 0.5},
        {"date": "2024-01-12", "value": 1.5},
        {"date": "2024-02-01", "value": 1.7},
    ]


# --- Derived ratio facts ----------------------------------------------------------


def test_ratio_facts_align_on_the_trade_date_and_skip_zero_denominators():
    numerator = [_fact(50.0, "2024-03-01", "2024-03-01", provider="finra"),
                 _fact(60.0, "2024-03-04", "2024-03-04", provider="finra"),
                 _fact(70.0, "2024-03-05", "2024-03-05", provider="finra")]
    denominator = [_fact(200.0, "2024-03-01", "2024-03-01", provider="finra"),
                   _fact(0.0, "2024-03-04", "2024-03-04", provider="finra")]
    # 2024-03-05 has no denominator row at all.

    facts = fundamentals.ratio_facts(numerator, denominator)

    assert [(f["filed_at"], f["value"]) for f in facts] == [("2024-03-01", 0.25)]
    assert facts[0]["unit"] == "ratio"


def test_fetch_facts_synthesizes_the_derived_ratio_from_its_inputs():
    class _Store:
        def get_fundamental_facts(self, symbol, concept, start=None):
            rows = {
                "short_volume": [_fact(50.0, "2024-03-01", "2024-03-01", provider="finra")],
                "total_volume": [_fact(200.0, "2024-03-01", "2024-03-01", provider="finra")],
            }
            return rows[concept]

    facts, provenance = fundamentals.fetch_facts(_Store(), "AAPL.US", "short_volume_ratio")

    assert facts[0]["value"] == pytest.approx(0.25)
    assert "short_volume / total_volume" in provenance


# --- yoy_growth ---------------------------------------------------------------------


def test_yoy_growth_uses_the_as_of_value_one_year_earlier():
    points = [
        {"date": "2023-02-03", "value": 10.0},
        {"date": "2024-02-09", "value": 12.0},
    ]

    growth = fundamentals.yoy_growth(points)

    # The 2024-02-09 base is the as-of value at 2024-02-09 minus a year: the
    # 2023 filing's 10.0, still the latest knowable a year on.
    assert growth == [{"date": "2024-02-09", "value": pytest.approx(0.2)}]


def test_yoy_growth_drops_points_without_a_base():
    points = [{"date": "2023-02-03", "value": 10.0}]
    assert fundamentals.yoy_growth(points) == []


# --- build_series: the payload contract ---------------------------------------------


def test_build_series_carries_point_in_time_flag_and_provenance():
    facts = [_fact(10.0, "2024-02-09")]

    result = fundamentals.build_series(
        "AAPL.US", "revenue", "raw", facts, "sec_edgar facts as filed"
    )

    assert result["point_in_time"] is True
    assert "sec_edgar facts as filed" in result["provenance"]
    assert result["transform"] == "raw"
    assert result["items"] == [{"date": "2024-02-09", "value": 10.0}]


def test_build_series_raw_facts_filters_on_filed_at():
    facts = [
        _fact(10.0, "2024-02-09"),
        _fact(11.0, "2025-02-07", period_end="2024-12-31"),
    ]

    result = fundamentals.build_series(
        "AAPL.US", "revenue", "raw_facts", facts, "sec_edgar facts as filed",
        start="2025-01-01", end="2025-12-31",
    )

    # The 2024 filing describes a 2023 period but was knowable in 2024 -- the
    # window is on filed_at, so it is out.
    assert [fact["filed_at"] for fact in result["items"]] == ["2025-02-07"]


def test_per_holder_provenance_says_so():
    facts = [_fact(0.5, "2024-01-10", holder="A", provider="fca")]
    result = fundamentals.build_series(
        "AAL.LON", "net_short_position", "raw", facts, "fca facts as filed"
    )
    assert "summed across holders" in result["provenance"]


# --- The demo dataset answers empty, never an error --------------------------------


def test_sqlite_demo_backend_has_no_fundamentals(tmp_path):
    store = SqliteBackend(tmp_path / "quantlab.db")

    catalog = store.list_fundamental_concepts("ZZTRND")
    assert catalog == {"symbol": "ZZTRND", "total": 0, "items": []}
    assert store.get_fundamental_facts("ZZTRND", "revenue") == []
    facts, _ = fundamentals.fetch_facts(store, "ZZTRND", "revenue")
    result = fundamentals.build_series("ZZTRND", "revenue", "raw", facts, "no stored facts")
    assert result["total"] == 0 and result["items"] == []
