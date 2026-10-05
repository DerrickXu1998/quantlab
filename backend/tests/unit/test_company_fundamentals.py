"""Tiingo's fundamentals for one company, against a fake catalog.

The fake returns every row it holds, including a release and a trading day
dated after the as-of date, so that "nothing after as_of" is proved in the
resolution rather than in a WHERE clause the fake would only be echoing.
"""

from __future__ import annotations

import datetime as dt

import pytest

from quantlab.storage import warehouse

AS_OF = "2025-11-15"

PROFILE = {
    "name": "Apple Inc",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "sicCode": 3571,
    "permaTicker": "US000000000038",
    "reportingCurrency": "usd",
    "isADR": False,
    "isActive": True,
    "fetched_at": "2026-10-05",
}

#: (filed_at, concept, value)
DAILY = [
    (dt.date(2025, 11, 13), "pe_ratio", 36.1),
    (dt.date(2025, 11, 13), "market_cap", 4.0e12),
    (dt.date(2025, 11, 14), "pe_ratio", 36.4),
    # After the as-of date.
    (dt.date(2025, 11, 17), "pe_ratio", 99.0),
]

#: (taxonomy, tag, unit, filed_at, value, fiscal_year, fiscal_quarter)
STATEMENTS = [
    # One release date, two reports: the fourth quarter and the annual.
    ("tiingo-incomeStatement", "revenue", "$", dt.date(2025, 10, 31), 102e9, 2025, 4),
    ("tiingo-incomeStatement", "revenue", "$", dt.date(2025, 10, 31), 416e9, 2025, 0),
    ("tiingo-incomeStatement", "revenue", "$", dt.date(2025, 8, 1), 94e9, 2025, 3),
    ("tiingo-balanceSheet", "equity", "$", dt.date(2025, 10, 31), 73.7e9, 2025, 4),
    ("tiingo-balanceSheet", "equity", "$", dt.date(2025, 8, 1), 65.8e9, 2025, 3),
    ("tiingo-overview", "roe", "%", dt.date(2025, 10, 31), 1.64, 2025, 4),
    # Only in the quarter: the grid shows a blank for the others.
    ("tiingo-cashFlow", "capex", "$", dt.date(2025, 8, 1), -3.4e9, 2025, 3),
    # Filed after the as-of date: the next quarter must not appear.
    ("tiingo-incomeStatement", "revenue", "$", dt.date(2026, 1, 30), 140e9, 2026, 1),
]


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Catalog:
    def __init__(self, known=True):
        self.known = known
        self.calls: list[tuple[str, object]] = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "SELECT instrument_id, meta FROM instruments" in sql:
            return _Cursor([(2, {"tiingo": PROFILE})] if self.known else [])
        if "company: Tiingo daily metrics" in sql:
            return _Cursor(DAILY)
        if "company: Tiingo statements" in sql:
            return _Cursor(STATEMENTS)
        raise AssertionError(f"unexpected query: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Warehouse:
    def __init__(self, known=True):
        self._catalog = _Catalog(known)

    def catalog(self):
        return self._catalog


@pytest.fixture()
def result():
    return warehouse.company_fundamentals(_Warehouse(), "AAPL.US", AS_OF)


def test_an_unknown_symbol_is_none():
    assert warehouse.company_fundamentals(_Warehouse(known=False), "NOPE.US", AS_OF) is None


def test_the_profile_is_tiingos_meta_snapshot(result):
    profile = result["profile"]
    assert profile["name"] == "Apple Inc"
    assert profile["sic_code"] == 3571
    assert profile["perma_ticker"] == "US000000000038"
    assert profile["reporting_currency"] == "usd"
    assert profile["is_adr"] is False
    # Fields Tiingo did not send are absent, not invented.
    assert profile["company_website"] is None


def test_daily_metrics_stop_at_the_as_of_date(result):
    assert [day["date"] for day in result["daily"]] == ["2025-11-13", "2025-11-14"]
    assert result["daily"][0]["market_cap"] == 4.0e12
    assert result["daily"][1]["market_cap"] is None  # not published that day
    assert all(day["pe_ratio"] != 99.0 for day in result["daily"])


def test_releases_are_newest_first_and_never_after_the_as_of_date(result):
    labels = [release["label"] for release in result["releases"]]
    # The quarter before the annual report it was filed with, then Q3.
    assert labels == ["FY2025 Q4", "FY2025", "FY2025 Q3"]
    assert result["releases"][0]["filed_at"] == "2025-10-31"
    assert "FY2026 Q1" not in labels


def test_the_grid_reads_income_balance_cash_flow_then_overview(result):
    assert [line["statement"] for line in result["lines"]] == [
        "incomeStatement", "balanceSheet", "cashFlow", "overview",
    ]


def test_each_line_is_labelled_from_tiingos_definitions_with_blanks_kept(result):
    lines = {line["code"]: line for line in result["lines"]}

    revenue = lines["revenue"]
    assert revenue["label"] == "Revenue"
    assert revenue["units"] == "$"
    assert revenue["values"] == [102e9, 416e9, 94e9]

    capex = lines["capex"]
    assert capex["label"] == "Capital Expenditure"
    assert capex["values"] == [None, None, -3.4e9]

    roe = lines["roe"]
    assert roe["units"] == "%"
    assert roe["description"].startswith("Return on Shareholder")


def test_the_release_count_is_bounded():
    limited = warehouse.company_fundamentals(_Warehouse(), "AAPL.US", AS_OF, releases=1)

    assert [release["label"] for release in limited["releases"]] == ["FY2025 Q4"]
    lines = {line["code"]: line for line in limited["lines"]}
    # A field with nothing in the shown releases is left out, not shown blank.
    assert "capex" not in lines
    assert lines["revenue"]["values"] == [102e9]


def test_both_reads_are_bounded_by_instrument_and_date():
    store = _Warehouse()
    warehouse.company_fundamentals(store, "AAPL.US", AS_OF, start="2025-01-01")

    daily = next(p for sql, p in store._catalog.calls if "Tiingo daily metrics" in sql)
    assert daily[0] == 2 and daily[2] == AS_OF and daily[3] == "2025-01-01"
    statements = next(p for sql, p in store._catalog.calls if "Tiingo statements" in sql)
    assert statements == (2, AS_OF)
