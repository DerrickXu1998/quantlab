"""The screen and the company page, against fakes rather than a warehouse.

Three properties are worth more than the rest, and each one is a way this
feature would otherwise lie:

**Nothing filed after the as-of date is ever used.** The fake below returns
*every* row it holds, including a filing dated two years after the screen --
deliberately, so that the guarantee is proved in the resolution itself and not
merely in a WHERE clause. A test whose fake pre-filters proves only that the
fake filters.

**Unknown is not zero.** A company with negative equity has no price-to-book,
and a division that produced one would hand it a large negative multiple that
sorts as the cheapest name on the page (docs/FUNDAMENTALS.md §5.5).

**The universe bounds the query.** ``fundamentals_pit_idx`` leads with
``instrument_id``, so an unbounded screen cannot use it: 6,700 ms of sequential
scan against 857 ms (docs/RESEARCH.md §2). If the instrument list ever stops
reaching the query, nothing fails -- it just gets eight times slower.
"""

from __future__ import annotations

import datetime as dt
from typing import get_args

import pytest

from quantlab.api import schemas
from quantlab.signals import registry as signal_registry
from quantlab.storage import warehouse

AS_OF = "2024-06-30"

#: One symbol per case: a name that has filed, a name whose equity is negative,
#: a name that has filed nothing, and a name outside the universe.
IDS = {"CAT.US": 1, "NEG.US": 2, "QUIET.US": 3, "OUT.US": 4}
NAMES = {
    "CAT.US": "Caterpillar",
    "NEG.US": "Negative Book",
    "QUIET.US": "Never Filed",
    "OUT.US": "Not A Member",
}
UNIVERSE_MEMBERS = ["CAT.US", "NEG.US", "QUIET.US"]

CLOSES = {1: 100.0, 2: 10.0, 3: 5.0, 4: 40.0}

#: (instrument_id, concept, period_start, period_end, filed_at, value, tag, run_id)
FUNDAMENTALS = [
    # The figure that was public on the as-of date: FY2023, filed 2024-02-16.
    (1, "net_income", dt.date(2023, 1, 1), dt.date(2023, 12, 31),
     dt.date(2024, 2, 16), 10_000_000_000.0, "NetIncomeLoss", 7),
    # FY2024, filed twenty months *after* the as-of date. Using it would make
    # the screen ten times cheaper and nothing in the row would say why.
    (1, "net_income", dt.date(2024, 1, 1), dt.date(2024, 12, 31),
     dt.date(2026, 2, 13), 99_000_000_000.0, "NetIncomeLoss", 9),
    (1, "shares_outstanding", None, dt.date(2024, 3, 31),
     dt.date(2024, 5, 1), 500_000_000.0, "CommonStockSharesOutstanding", 7),
    (1, "equity", None, dt.date(2024, 3, 31),
     dt.date(2024, 5, 1), 20_000_000_000.0, "StockholdersEquity", 7),
    # Negative book value, and a loss. Both denominators are degenerate.
    (2, "equity", None, dt.date(2024, 3, 31),
     dt.date(2024, 5, 1), -5_000_000_000.0, "StockholdersEquity", 7),
    (2, "net_income", dt.date(2023, 1, 1), dt.date(2023, 12, 31),
     dt.date(2024, 2, 16), -1_000_000_000.0, "NetIncomeLoss", 7),
    (2, "shares_outstanding", None, dt.date(2024, 3, 31),
     dt.date(2024, 5, 1), 100_000_000.0, "CommonStockSharesOutstanding", 7),
    # Outside the universe, and cheap enough to be conspicuous if it leaks in.
    (4, "net_income", dt.date(2023, 1, 1), dt.date(2023, 12, 31),
     dt.date(2024, 2, 16), 8_000_000_000.0, "NetIncomeLoss", 7),
    (4, "shares_outstanding", None, dt.date(2024, 3, 31),
     dt.date(2024, 5, 1), 10_000_000.0, "CommonStockSharesOutstanding", 7),
]


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Catalog:
    """A Postgres stand-in that answers by which relation the SQL names."""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _Cursor(self._rows_for(sql, params))

    def _rows_for(self, sql, params):
        if "FROM universe_snapshots" in sql and "snapshot_id, snapshot_date" in sql:
            return [(11, dt.date(2024, 6, 28))]
        if "FROM universe_members" in sql:
            return [(symbol, NAMES[symbol]) for symbol in UNIVERSE_MEMBERS]
        if "SELECT symbol, instrument_id FROM instruments" in sql:
            return [(s, IDS[s]) for s in params[0] if s in IDS]
        if "FROM instruments WHERE symbol = %s" in sql or "FROM instruments\n" in sql:
            symbol = params[0]
            if symbol not in IDS:
                return []
            return [(IDS[symbol], symbol, NAMES[symbol], "XNYS", "USD", "")]
        if "SELECT DISTINCT concept" in sql:
            return [
                (concept,)
                for concept in sorted(
                    {row[1] for row in FUNDAMENTALS if row[0] == params[0]}
                )
            ]
        if "FROM signals" in sql:
            return [("breakout-20d", 580, dt.date(2026, 9, 1), "bearish")]
        if "FROM fundamentals" in sql:
            # Deliberately *not* filtered by filed_at: the point-in-time
            # guarantee has to hold in the resolution, not in this fake.
            wanted_ids, concepts = set(params[0]), set(params[1])
            return [
                row for row in FUNDAMENTALS
                if row[0] in wanted_ids and row[1] in concepts
            ]
        raise AssertionError(f"unexpected catalog query: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Bars:
    def __init__(self):
        self.parameters: list[dict] = []

    def query(self, sql, parameters=None):
        self.parameters.append(parameters or {})

        class _Result:
            def __init__(self, rows):
                self.result_rows = rows

        if "argMaxIf" in sql:
            instrument_id = parameters["iid"]
            return _Result(
                [(650, dt.datetime(2020, 1, 2), dt.datetime(2026, 9, 18),
                  CLOSES[instrument_id], 400)]
            )
        ids = parameters["ids"]
        return _Result([(iid, CLOSES[iid]) for iid in ids])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Warehouse:
    def __init__(self):
        self._catalog = _Catalog()
        self.client = _Bars()

    def catalog(self):
        return self._catalog

    def bars(self):
        return self.client


@pytest.fixture()
def wh():
    return _Warehouse()


def _screen(wh, **kwargs):
    params = {
        "universe": "liquid-500-ftse-core",
        "as_of": AS_OF,
        "metrics": list(warehouse.SCREEN_METRICS),
    }
    params.update(kwargs)
    return warehouse.screen(wh, **params)


def _values(result, symbol):
    return next(row["values"] for row in result["rows"] if row["symbol"] == symbol)


# --- Point in time ----------------------------------------------------------


def test_a_figure_filed_after_the_as_of_date_is_never_used(wh):
    """The whole feature. FY2024 was filed 2026-02-13 and did not exist on the
    screen's date; using it would make the name look ten times cheaper."""
    result = _screen(wh)

    # 100.00 x 500M shares over FY2023's $10bn, not FY2024's $99bn.
    assert _values(result, "CAT.US")["pe"] == pytest.approx(5.0)


def test_the_fundamentals_query_is_bounded_by_the_as_of_date(wh):
    """Belt as well as braces: the resolution refuses a late filing anyway, but
    a query that drags every restatement back is also the slow one."""
    _screen(wh)

    fundamentals = [
        params for sql, params in wh._catalog.calls if "FROM fundamentals" in sql
    ]
    assert fundamentals, "expected the screen to read fundamentals"
    assert all(params[2] == AS_OF for params in fundamentals)


def test_the_company_page_resolves_the_same_figure_as_the_screen(wh):
    """One point-in-time implementation, so a company page cannot disagree with
    a backtest over the same name (docs/RESEARCH.md §2)."""
    overview = warehouse.company_overview(wh, "CAT.US", AS_OF)

    earnings = next(f for f in overview["facts"] if f["concept"] == "net_income")
    assert earnings["value"] == 10_000_000_000.0
    assert earnings["filed_at"] == "2024-02-16"
    assert earnings["days_stale"] == 135
    assert earnings["in_force"] is True


# --- Unknown is not zero ----------------------------------------------------


def test_negative_equity_has_no_price_to_book_rather_than_a_cheap_one(wh):
    result = _screen(wh)

    values = _values(result, "NEG.US")
    assert values["pb"] is None
    assert values["roe"] is None
    # A loss is not a low multiple either.
    assert values["pe"] is None


def test_negative_equity_does_not_pass_a_cheap_price_to_book_screen(wh):
    """The failure this guards: -5bn of equity divided into a 1bn market cap is
    -0.2, which passes `pb <= 1` and sorts to the top of the page."""
    result = _screen(wh, metrics=["pb"], constraints=[("pb", None, 3.0)])

    # CAT.US at 2.5 is the only name with a book value at all.
    assert [row["symbol"] for row in result["rows"]] == ["CAT.US"]
    assert result["excluded_unmeasured"] == 2
    assert result["excluded_by_constraint"] == 0


def test_a_name_with_nothing_filed_is_unmeasured_not_excluded(wh):
    result = _screen(wh, metrics=["pe"], constraints=[("pe", None, 20.0)])

    assert [row["symbol"] for row in result["rows"]] == ["CAT.US"]
    # NEG.US has a loss, QUIET.US has no filings: neither failed the test.
    assert result["excluded_unmeasured"] == 2
    assert result["excluded_by_constraint"] == 0


def test_failing_a_constraint_and_never_being_measured_are_counted_apart(wh):
    """"Few qualified" and "most were never measured" must be distinguishable;
    a single "excluded" count reads as the first whichever it was."""
    result = _screen(wh, metrics=["pe"], constraints=[("pe", None, 4.0)])

    assert result["rows"] == []
    assert result["excluded_by_constraint"] == 1  # CAT.US at 5.0 is too dear
    assert result["excluded_unmeasured"] == 2


def test_coverage_reports_what_could_be_measured_and_what_it_needed(wh):
    result = _screen(wh, metrics=["pe", "gross_margin"])

    coverage = {item["metric"]: item for item in result["coverage"]}
    assert coverage["pe"]["measured"] == 1
    assert coverage["pe"]["universe"] == 3
    assert coverage["pe"]["requires"] == ["net_income", "shares_outstanding"]
    # Nobody here has filed gross profit, which is a fact about the warehouse.
    assert coverage["gross_margin"]["measured"] == 0


# --- The universe bound -----------------------------------------------------


def test_the_screen_names_its_instruments_in_the_query(wh):
    _screen(wh)

    fundamentals = [
        params for sql, params in wh._catalog.calls if "FROM fundamentals" in sql
    ]
    assert fundamentals
    for params in fundamentals:
        assert params[0], "an unbounded screen cannot use fundamentals_pit_idx"
        assert set(params[0]) <= {IDS[s] for s in UNIVERSE_MEMBERS}


def test_a_name_outside_the_universe_is_never_screened(wh):
    result = _screen(wh)

    assert "OUT.US" not in {row["symbol"] for row in result["rows"]}
    assert result["universe_size"] == len(UNIVERSE_MEMBERS)


def test_the_snapshot_reports_the_date_it_was_captured_not_the_one_asked_for(wh):
    """Running over yesterday's members is fine; not saying so is not."""
    result = _screen(wh)

    assert result["as_of"] == AS_OF
    assert warehouse.resolve_universe(wh, "liquid-500-ftse-core", AS_OF).as_of == (
        "2024-06-28"
    )


def test_a_universe_with_no_snapshot_that_far_back_is_unresolved():
    class _Empty(_Catalog):
        def _rows_for(self, sql, params):
            if "FROM universe_snapshots" in sql:
                return []
            return super()._rows_for(sql, params)

    wh = _Warehouse()
    wh._catalog = _Empty()

    assert warehouse.resolve_universe(wh, "liquid-500-ftse-core", "2009-01-01") is None
    assert _screen(wh) is None


def test_the_universe_is_read_in_bounded_chunks(wh, monkeypatch):
    """Chunking is about memory, not about the query: the answer for a name
    must not depend on who else was in its chunk."""
    monkeypatch.setattr(warehouse, "SCREEN_CHUNK", 1)

    chunked = _screen(wh)

    assert len([1 for sql, _ in wh._catalog.calls if "FROM fundamentals" in sql]) == 3
    assert _values(chunked, "CAT.US")["pe"] == pytest.approx(5.0)


# --- Ranking ----------------------------------------------------------------


def test_unmeasured_names_sort_last_whichever_way_the_rest_are_ordered(wh):
    ascending = _screen(wh, metrics=["pe"], sort_by="pe")
    descending = _screen(wh, metrics=["pe"], sort_by="pe", descending=True)

    for result in (ascending, descending):
        symbols = [row["symbol"] for row in result["rows"]]
        assert symbols[0] == "CAT.US", "a null is not the cheapest name on the page"
        assert set(symbols[1:]) == {"NEG.US", "QUIET.US"}


def test_rows_are_ordered_by_symbol_when_nothing_is_sorted_on(wh):
    result = _screen(wh)

    symbols = [row["symbol"] for row in result["rows"]]
    assert symbols == sorted(symbols)


def test_the_limit_truncates_the_ranking_not_the_coverage(wh):
    result = _screen(wh, metrics=["pe"], limit=1)

    assert len(result["rows"]) == 1
    assert result["coverage"][0]["universe"] == 3


# --- The company page -------------------------------------------------------


def test_a_concept_never_filed_is_reported_apart_from_one_merely_absent(wh):
    """A name that has never filed gross profit and one whose gross profit is
    stale produce the same gap on the page and are not the same fact."""
    overview = warehouse.company_overview(wh, "CAT.US", AS_OF)

    assert set(overview["concepts_available"]) == {
        "net_income", "equity", "shares_outstanding"
    }
    assert "gross_profit" in overview["concepts_missing"]
    assert "net_income" not in overview["concepts_missing"]


def test_the_blank_sector_is_returned_blank(wh):
    """607 of 644 names have none. An invented one would be indistinguishable
    from a real one and would license a peer group that does not exist."""
    assert warehouse.company_overview(wh, "CAT.US", AS_OF)["sector"] == ""


def test_the_close_is_taken_on_or_before_the_as_of_date(wh):
    warehouse.company_overview(wh, "CAT.US", AS_OF)

    bounds = next(p for p in wh.client.parameters if "iid" in p)
    assert bounds["as_of"] == f"{AS_OF} 23:59:59"


def test_an_unknown_symbol_has_no_overview(wh):
    assert warehouse.company_overview(wh, "NOSUCH.US", AS_OF) is None


def test_signal_history_is_counted_per_rule(wh):
    overview = warehouse.company_overview(wh, "CAT.US", AS_OF)

    assert overview["signals"] == [
        {
            "rule_name": "breakout-20d",
            "count": 580,
            "last_date": "2026-09-01",
            "last_direction": "bearish",
        }
    ]
    assert overview["signal_total"] == 580


def test_signal_history_is_bounded_by_the_as_of_date(wh):
    """The one thing on the page that must not outrun the date.

    Asked for CAT on 2024-06-30 this returned accounts filed by 2024-05-01, a
    chart cut at 2024-06-30, and a last signal dated 2026-09-01 -- two years
    after the date the page claims to answer. A destination whose whole claim
    is that it shows what was knowable on a date cannot show a signal from
    after it, and the count is part of the claim: "580 signals" as of 2024 is
    a different fact from "580 signals" today.
    """
    warehouse.company_overview(wh, "CAT.US", AS_OF)

    signal_sql, params = next(
        call for call in wh._catalog.calls if "FROM signals" in call[0]
    )
    assert "s.date <= %s" in signal_sql
    assert params[-1] == AS_OF


# --- The metric vocabulary --------------------------------------------------


def test_the_request_vocabulary_and_the_arithmetic_name_the_same_metrics():
    """The schema validates the request; the warehouse computes the answer. A
    metric in one and not the other is either a 422 nobody can avoid or a
    column nobody can ask for."""
    assert set(get_args(schemas.ScreenMetric)) == set(warehouse.SCREEN_METRICS)


@pytest.mark.parametrize(
    ("metric", "rule_name"),
    [
        ("pe", "pe-filter"),
        ("pb", "pb-filter"),
        ("roe", "profitability-filter"),
        ("leverage", "leverage-filter"),
        ("current_ratio", "liquidity-filter"),
    ],
)
def test_a_metric_needs_exactly_what_its_rule_needs(metric, rule_name):
    """A screen that disagreed with the backtest about which concepts a ratio
    is made of would disagree about who is measurable, silently."""
    rule = signal_registry.get_rule(rule_name)

    assert set(warehouse.SCREEN_METRIC_CONCEPTS[metric]) == set(rule.requires_facts)
