"""Tiingo is the fallback fundamentals source: SEC wins per name and concept.

Tiingo's statement fields carry the same concepts as SEC's. A series built
from both would pick between two vendors' figures by filing date alone, so
``load_facts_for`` chooses one source per (name, concept): SEC wherever it has
filed that concept by the read date, Tiingo otherwise.
"""

from __future__ import annotations

import datetime as dt

from quantlab.storage import warehouse

IDS = {"BOTH.US": 1, "TIINGO.US": 2, "LATE.US": 3}

#: (instrument_id, concept, period_start, period_end, filed_at, value, tag, run_id, provider)
ROWS = [
    # BOTH.US: SEC and Tiingo each filed FY2023 net income; SEC must win.
    (1, "net_income", dt.date(2023, 1, 1), dt.date(2023, 12, 31), dt.date(2024, 2, 16),
     10.0e9, "NetIncomeLoss", 7, "sec_edgar"),
    (1, "net_income", dt.date(2023, 2, 20), dt.date(2024, 2, 19), dt.date(2024, 2, 19),
     11.0e9, "netinc", 9, "tiingo"),
    # ...but only Tiingo has equity for it: per concept, so Tiingo is used.
    (1, "equity", None, dt.date(2024, 2, 19), dt.date(2024, 2, 19), 40.0e9, "equity", 9, "tiingo"),
    # TIINGO.US: Tiingo only.
    (2, "net_income", dt.date(2023, 2, 20), dt.date(2024, 2, 19), dt.date(2024, 2, 19),
     3.0e9, "netinc", 9, "tiingo"),
    # LATE.US: SEC's filing lands after the read date, Tiingo's before it.
    (3, "net_income", dt.date(2023, 1, 1), dt.date(2023, 12, 31), dt.date(2024, 9, 1),
     5.0e9, "NetIncomeLoss", 7, "sec_edgar"),
    (3, "net_income", dt.date(2023, 2, 20), dt.date(2024, 2, 19), dt.date(2024, 2, 19),
     4.0e9, "netinc", 9, "tiingo"),
]


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _Catalog:
    def execute(self, sql, params=None):
        if "SELECT symbol, instrument_id FROM instruments" in sql:
            return _Cursor([(s, IDS[s]) for s in params[0] if s in IDS])
        if "FROM fundamentals" in sql:
            ids, concepts, end = set(params[0]), set(params[1]), params[2]
            return _Cursor(
                [r for r in ROWS if r[0] in ids and r[1] in concepts and r[4].isoformat() <= end]
            )
        raise AssertionError(sql)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Warehouse:
    def catalog(self):
        return _Catalog()


def _value(series, concept, on):
    fact = series.value(concept, on)
    return None if fact is None else fact.value


def _load(end="2024-06-30"):
    return warehouse.load_facts_for(
        _Warehouse(), list(IDS), ["net_income", "equity"], "2024-01-01", end
    )


def test_sec_wins_where_it_has_filed_the_concept():
    series = _load()["BOTH.US"]
    assert _value(series, "net_income", "2024-06-30") == 10.0e9  # SEC's, not Tiingo's 11bn


def test_the_choice_is_per_concept_not_per_name():
    series = _load()["BOTH.US"]
    assert _value(series, "equity", "2024-06-30") == 40.0e9  # only Tiingo filed equity


def test_tiingo_fills_a_name_sec_has_nothing_for():
    series = _load()["TIINGO.US"]
    assert _value(series, "net_income", "2024-06-30") == 3.0e9


def test_an_sec_filing_after_the_read_date_does_not_displace_tiingo():
    """The choice uses only what was filed by the read date: SEC's figure filed
    in September cannot reach back and remove Tiingo's from a June backtest."""
    assert _value(_load("2024-06-30")["LATE.US"], "net_income", "2024-06-30") == 4.0e9
    assert _value(_load("2024-12-31")["LATE.US"], "net_income", "2024-12-31") == 5.0e9
