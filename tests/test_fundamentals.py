"""Credentialed ingest jobs: SEC EDGAR, Companies House, FRED.

Offline unit tests stub the provider's HTTP client (no network, no keys). The
``needs_store`` round-trips run against the live stack with stubbed providers
-- they exercise the catalog and the fundamentals table, not the APIs -- and
clean up every row they write::

    make store-test
"""
from __future__ import annotations

import datetime as dt
import os
import uuid

import pandas as pd
import pytest

from quantlab import store
from quantlab.config import settings
from quantlab.schema import Currency, DataUnavailable, ProviderError, Security
from quantlab.store.fundamentals import (
    flatten_companyfacts,
    map_sec_tickers,
    ticker_variants,
)

# A small but representative companyfacts payload: two taxonomies, two units,
# and a restatement (same period, new accession and filed date).
COMPANYFACTS_BLOB = {
    "cik": 320193,
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 383285000000,
                         "accn": "0000320193-24-000123", "fy": 2023, "fp": "FY",
                         "form": "10-K", "filed": "2024-02-01"},
                        # Restatement: same fact, republished by a later filing.
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 383300000000,
                         "accn": "0000320193-24-000200", "fy": 2024, "fp": "FY",
                         "form": "10-K/A", "filed": "2024-06-01"},
                        # Incomplete entries cannot be placed in time -- skipped.
                        {"start": "2023-01-01", "val": 1, "accn": "x", "filed": "2024-02-01"},
                        {"end": "2023-12-31", "val": 2, "accn": "x"},
                    ]
                }
            },
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [
                        {"end": "2024-01-15", "val": 15440000000,
                         "accn": "0000320193-24-000123", "form": "10-K", "filed": "2024-02-01"},
                    ]
                }
            },
        },
    },
}

# A minimal iXBRL accounts document: one period-end tag, two numeric concepts.
IXBRL_DOC = """
<html><body>
<ix:nonNumeric name="uk-bus:EndDateForPeriodCoveredByReport" contextRef="c1">2023-12-31</ix:nonNumeric>
<ix:nonFraction name="uk-gaap:TurnoverRevenue" contextRef="c1" unitRef="gbp" scale="6">1,234</ix:nonFraction>
<ix:nonFraction name="uk-gaap:ProfitLoss" contextRef="c1" unitRef="gbp" sign="-">55</ix:nonFraction>
</body></html>
"""

# ---------------------------------------------------------------------------
# SEC companyfacts flattening -- pure logic, no database
# ---------------------------------------------------------------------------


def test_flatten_companyfacts_keeps_taxonomies_units_and_restatements():
    rows = flatten_companyfacts(COMPANYFACTS_BLOB)

    assert len(rows) == 3, "two incomplete entries must be skipped"
    assert {r["taxonomy"] for r in rows} == {"us-gaap", "dei"}
    assert {r["unit"] for r in rows} == {"USD", "shares"}

    revenue = [r for r in rows if r["tag"] == "Revenues"]
    assert len(revenue) == 2, "the restatement is a second row, not an overwrite"
    assert {r["accession"] for r in revenue} == {
        "0000320193-24-000123", "0000320193-24-000200"
    }
    assert {r["filed_at"] for r in revenue} == {dt.date(2024, 2, 1), dt.date(2024, 6, 1)}
    assert all(r["period_end"] == dt.date(2023, 12, 31) for r in revenue)
    assert all(r["period_start"] == dt.date(2023, 1, 1) for r in revenue)
    assert all(r["concept"] == "revenue" for r in revenue)

    shares = next(r for r in rows if r["unit"] == "shares")
    assert shares["concept"] == "shares_outstanding"
    assert shares["period_start"] is None, "an instantaneous fact has no period start"
    assert shares["provider"] == "sec_edgar"


def test_flatten_companyfacts_tolerates_empty_and_malformed_blobs():
    assert flatten_companyfacts({}) == []
    assert flatten_companyfacts({"facts": {}}) == []
    assert flatten_companyfacts({"facts": {"us-gaap": {"Assets": {"units": {}}}}}) == []


# ---------------------------------------------------------------------------
# Ticker -> CIK matching
# ---------------------------------------------------------------------------


def test_ticker_variants_handles_case_and_class_shares():
    assert ticker_variants("AAPL.US") == ["AAPL"]
    assert ticker_variants("aapl.us") == ["AAPL"]
    # SEC spells class shares with a dash; the warehouse inherited the dot.
    assert ticker_variants("BRK.B.US") == ["BRK.B", "BRK-B"]
    assert ticker_variants("BF-B.US") == ["BF-B", "BF.B"]


def test_map_sec_tickers_matches_and_reports_unmatched(monkeypatch):
    from quantlab.store import fundamentals as fundamentals_mod

    class StubSec:
        def ticker_to_cik(self):
            return {"AAPL": 320193, "BRK-B": 1067983}

    rows = [
        ("AAPL.US", "", {}),
        ("BRK.B.US", "", {}),
        ("GONE.US", "", {}),
        ("DONE.US", "0000000001", {}),           # already mapped; --only-missing skips it
        ("GBPUSD.BOE", "", {"macro": True}),     # macro pseudo-instrument: never mapped
        ("VOD.LON", "", {}),                     # not a US line
    ]

    class FakeResult:
        def fetchall(self):
            return rows

    class FakeConn:
        def execute(self, query, params=None):
            return FakeResult()

        def commit(self):
            pass

    recorded: dict[str, int] = {}
    monkeypatch.setattr(
        fundamentals_mod.catalog, "instrument_ids",
        lambda conn, syms: {s: i for i, s in enumerate(syms)},
    )
    monkeypatch.setattr(
        fundamentals_mod.catalog, "record_cik_mappings",
        lambda conn, m, ids, source: recorded.update(m) or len(m),
    )

    report = map_sec_tickers(FakeConn(), provider=StubSec())

    assert report.candidates == 3
    assert recorded == {"AAPL.US": 320193, "BRK.B.US": 1067983}
    assert report.mapped == 2
    assert report.unresolved == ["GONE.US"]
    assert report.status == "partial"
    assert report.source == "sec_edgar"


# ---------------------------------------------------------------------------
# Missing-credential errors must be loud and specific
# ---------------------------------------------------------------------------


def test_fred_series_fails_clearly_without_a_key(monkeypatch):
    from quantlab.providers.fred import FredProvider

    monkeypatch.setattr(settings(), "fred_api_key", "")
    with pytest.raises(ProviderError, match="FRED_API_KEY"):
        FredProvider().series("DGS10", "2024-01-01")


def test_companies_house_fails_clearly_without_a_key(monkeypatch):
    from quantlab.providers.companies_house import CompaniesHouseProvider

    monkeypatch.setattr(settings(), "companies_house_key", "")
    with pytest.raises(ProviderError, match="COMPANIES_HOUSE_API_KEY"):
        CompaniesHouseProvider().filing_history("00000006")


def test_sec_provider_fails_clearly_without_a_contact_email(monkeypatch):
    from quantlab.providers.sec_edgar import SecEdgarProvider

    monkeypatch.setenv("SEC_USER_AGENT", "")
    monkeypatch.setattr(settings(), "user_agent", "quantlab/0.1 (research)")
    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        SecEdgarProvider()


# ---------------------------------------------------------------------------
# FRED series parsing and the macro bridge
# ---------------------------------------------------------------------------


def test_fred_series_parses_observations_and_dots():
    """FRED marks missing observations with a literal '.'; they become NaN."""
    from quantlab.providers.fred import FredProvider

    provider = FredProvider(api_key="test-key")
    seen: list[dict] = []

    def fake_get_json(url, *, params=None, **kw):
        seen.append(dict(params or {}))
        return {"observations": [
            {"date": "2024-01-02", "value": "4.01"},
            {"date": "2024-01-03", "value": "."},
            {"date": "2024-01-04", "value": "4.05"},
        ]}

    provider.client.get_json = fake_get_json
    series = provider.series("DGS10", "2024-01-01", "2024-12-31")

    assert series.dropna().tolist() == [4.01, 4.05]
    assert len(series) == 3 and pd.isna(series.iloc[1])
    assert seen[0]["series_id"] == "DGS10"
    assert seen[0]["api_key"] == "test-key"
    assert seen[0]["observation_start"] == "2024-01-01"


def test_fred_series_batch_skips_empty_series_but_propagates_key_errors():
    from quantlab.providers.fred import FredProvider

    provider = FredProvider(api_key="test-key")

    def fake_series(code, start, end=""):
        if code == "DEAD":
            raise DataUnavailable(f"fred: no observations for {code}")
        return pd.Series([4.01], index=pd.DatetimeIndex(["2024-01-02"], name="date"), name=code)

    provider.series = fake_series
    frame = provider.series_batch(["DGS10", "DEAD"], "2024-01-01")
    assert list(frame.columns) == ["DGS10"]

    def broken(code, start, end=""):
        raise ProviderError("FRED needs a free API key; set FRED_API_KEY")

    provider.series = broken
    with pytest.raises(ProviderError, match="FRED_API_KEY"):
        provider.series_batch(["DGS10"], "2024-01-01")


def test_parse_series_args_accepts_fred_defaults():
    from quantlab.store.macro import DEFAULT_MAPPING, FRED_MAPPING, parse_series_args

    assert parse_series_args(None) == DEFAULT_MAPPING
    assert parse_series_args(None, defaults=FRED_MAPPING) == FRED_MAPPING
    assert FRED_MAPPING["VIXCLS"] == "VIX.FRED"
    assert FRED_MAPPING["DGS10"] == "UST10Y.FRED"
    assert parse_series_args(["dgs10:UST10Y.FRED"], defaults=FRED_MAPPING) == {
        "DGS10": "UST10Y.FRED"
    }


def test_fred_series_convert_through_the_macro_bar_path():
    """A FRED point series becomes degenerate OHLC bars, same as BoE."""
    from quantlab.store.macro import series_to_bars

    series = pd.Series(
        [24.23, 23.5],
        index=pd.DatetimeIndex(["2026-03-11", "2026-03-12"], name="date"),
        name="VIXCLS",
    )
    bars = series_to_bars(series, symbol="VIX.FRED")
    assert bars["close"].tolist() == [24.23, 23.5]
    assert (bars["volume"] == 0).all()


# ---------------------------------------------------------------------------
# Companies House iXBRL parsing
# ---------------------------------------------------------------------------


def test_parse_ixbrl_facts_keeps_the_raw_tag():
    from quantlab.providers.companies_house import parse_ixbrl, parse_ixbrl_facts

    facts = parse_ixbrl_facts(IXBRL_DOC, ["revenue", "net_income"])
    assert facts["revenue"] == ("TurnoverRevenue", 1_234_000_000.0)  # scale=6 applied
    assert facts["net_income"] == ("ProfitLoss", -55.0)              # sign="-" applied
    # The plain wrapper still returns bare values.
    assert parse_ixbrl(IXBRL_DOC, ["revenue"]) == {"revenue": 1_234_000_000.0}


def test_parse_ixbrl_period_end():
    from quantlab.providers.companies_house import parse_ixbrl_period_end

    assert parse_ixbrl_period_end(IXBRL_DOC) == dt.date(2023, 12, 31)
    assert parse_ixbrl_period_end("<html><body>no tags here</body></html>") is None
    human = '<ix:nonNumeric name="bus:BalanceSheetDate">31 December 2023</ix:nonNumeric>'
    assert parse_ixbrl_period_end(human) == dt.date(2023, 12, 31)


# ---------------------------------------------------------------------------
# Live database round-trips (providers stubbed; the store is real)
# ---------------------------------------------------------------------------

needs_store = pytest.mark.skipif(
    not (os.environ.get("QUANTLAB_DB_URL") and os.environ.get("QUANTLAB_CH_URL")),
    reason="needs QUANTLAB_DB_URL and QUANTLAB_CH_URL (run `make store-test`)",
)


@pytest.fixture
def store_conn():
    from quantlab import store

    with store.session() as conn:
        yield conn


@pytest.fixture
def store_client():
    from quantlab import store

    with store.ch_session() as client:
        yield client


def _cleanup(conn, run_ids, instrument_id):
    """fundamentals references both instruments and ingest_runs; delete it first."""
    conn.execute("DELETE FROM fundamentals WHERE instrument_id = %s", (instrument_id,))
    conn.execute("DELETE FROM ingest_runs WHERE run_id = ANY(%s)", (list(run_ids),))
    conn.execute("DELETE FROM instruments WHERE instrument_id = %s", (instrument_id,))
    conn.commit()


@needs_store
def test_map_sec_tickers_round_trip(store_conn):
    symbol = f"ZU{uuid.uuid4().hex[:6].upper()}.US"
    ids = store.ensure_instruments(
        store_conn, {symbol: Security(symbol=symbol, country="US", currency=Currency.USD)}
    )
    store_conn.commit()
    instrument_id = ids[symbol]

    class StubSec:
        def ticker_to_cik(self):
            return {symbol.rsplit(".", 1)[0]: 320193}

    try:
        report = map_sec_tickers(store_conn, [symbol], provider=StubSec())
        assert report.mapped == 1 and report.unresolved == []

        row = store_conn.execute(
            "SELECT cik, meta->'sec_edgar'->>'cik' FROM instruments WHERE symbol = %s",
            (symbol,),
        ).fetchone()
        assert row == ("0000320193", "320193")
        binding = store_conn.execute(
            "SELECT vendor_symbol FROM symbol_map"
            " WHERE instrument_id = %s AND source = 'sec_edgar'",
            (instrument_id,),
        ).fetchone()
        assert binding == ("0000320193",)
    finally:
        # symbol_map cascades with the instrument.
        store_conn.execute("DELETE FROM instruments WHERE instrument_id = %s", (instrument_id,))
        store_conn.commit()


@needs_store
def test_sec_fundamentals_round_trip_is_idempotent_and_point_in_time(store_conn):
    from quantlab.store.fundamentals import ingest_sec_fundamentals

    symbol = f"ZT{uuid.uuid4().hex[:6].upper()}.US"
    ids = store.ensure_instruments(
        store_conn,
        {symbol: Security(symbol=symbol, country="US", currency=Currency.USD,
                          cik="0000320193")},
    )
    store_conn.commit()
    instrument_id = ids[symbol]

    class StubSec:
        def companyfacts(self, cik):
            assert cik == 320193
            return COMPANYFACTS_BLOB

    run_ids: list[int] = []
    try:
        first = ingest_sec_fundamentals(store_conn, provider=StubSec(), symbols=[symbol])
        run_ids.append(first.run_id)
        assert first.status == "ok"
        assert first.symbols_ok == 1
        assert first.rows_written == 3

        # Re-pulling the same filings adds nothing: identity includes accession.
        second = ingest_sec_fundamentals(
            store_conn, provider=StubSec(), symbols=[symbol], only_missing=False
        )
        run_ids.append(second.run_id)
        assert second.rows_written == 0

        # The default --only-missing sees the rows and skips the instrument.
        third = ingest_sec_fundamentals(store_conn, provider=StubSec(), symbols=[symbol])
        run_ids.append(third.run_id)
        assert third.symbols_requested == 0

        # The point-in-time read: before the restatement's filed date, only the
        # original 10-K facts are visible; restatements never edit history.
        pit = store_conn.execute(
            "SELECT tag, value FROM fundamentals"
            " WHERE instrument_id = %s AND filed_at <= '2024-02-01' ORDER BY tag",
            (instrument_id,),
        ).fetchall()
        assert len(pit) == 2
        assert dict(pit)["Revenues"] == 383285000000.0

        total = store_conn.execute(
            "SELECT count(*) FROM fundamentals WHERE instrument_id = %s", (instrument_id,)
        ).fetchone()
        assert total[0] == 3

        run = store_conn.execute(
            "SELECT source, kind, status FROM ingest_runs WHERE run_id = %s", (first.run_id,)
        ).fetchone()
        assert run == ("sec_edgar", "fundamentals", "ok")
    finally:
        _cleanup(store_conn, run_ids, instrument_id)


@needs_store
def test_ch_fundamentals_round_trip(store_conn):
    from types import SimpleNamespace

    from quantlab.store.fundamentals import ingest_ch_fundamentals

    symbol = f"ZV{uuid.uuid4().hex[:6].upper()}.LON"
    number = "00000006"
    ids = store.ensure_instruments(
        store_conn,
        {symbol: Security(symbol=symbol, country="GB", currency=Currency.GBX,
                          company_number=number)},
    )
    store_conn.commit()
    instrument_id = ids[symbol]

    class StubCH:
        def __init__(self):
            self.client = SimpleNamespace(get=lambda url, **kw: IXBRL_DOC.encode())

        def filing_history(self, company_number, category="accounts", limit=50):
            assert company_number == number
            return pd.DataFrame(
                [
                    {
                        "date": pd.Timestamp("2024-03-15"),
                        "transaction_id": "TXN-1",
                        "links": {"document_metadata": "https://documents/abc"},
                    }
                ]
            )

    run_ids: list[int] = []
    try:
        first = ingest_ch_fundamentals(store_conn, provider=StubCH(), symbols=[symbol])
        run_ids.append(first.run_id)
        assert first.status == "ok"
        assert first.rows_written == 2

        rows = store_conn.execute(
            "SELECT concept, tag, value, period_end::text, filed_at::text, accession, unit"
            " FROM fundamentals WHERE instrument_id = %s ORDER BY concept",
            (instrument_id,),
        ).fetchall()
        assert rows == [
            ("net_income", "ProfitLoss", -55.0, "2023-12-31", "2024-03-15", "TXN-1", ""),
            ("revenue", "TurnoverRevenue", 1234000000.0, "2023-12-31", "2024-03-15", "TXN-1", ""),
        ]

        second = ingest_ch_fundamentals(
            store_conn, provider=StubCH(), symbols=[symbol], only_missing=False
        )
        run_ids.append(second.run_id)
        assert second.rows_written == 0, "re-pull of the same filing must be a no-op"

        run = store_conn.execute(
            "SELECT source, kind FROM ingest_runs WHERE run_id = %s", (first.run_id,)
        ).fetchone()
        assert run == ("companies_house", "fundamentals")
    finally:
        _cleanup(store_conn, run_ids, instrument_id)


@needs_store
def test_ingest_fred_series_round_trip(store_conn, store_client):
    """FRED series land as pseudo-instrument bars, tagged source='fred'."""
    from quantlab import store
    from quantlab.store import bars as bars_mod
    from quantlab.store import catalog
    from quantlab.store.macro import ingest_macro_series

    code = f"T{uuid.uuid4().hex[:8].upper()}"
    symbol = f"TST{uuid.uuid4().hex[:6].upper()}.FRED"
    frame = pd.DataFrame(
        {code: [4.01, 4.05]},
        index=pd.DatetimeIndex(["2026-01-05", "2026-01-06"], name="date"),
    )

    class StubFred:
        def series_batch(self, codes, start, end=""):
            return frame[[c for c in codes if c in frame.columns]]

    run_id = None
    try:
        report = ingest_macro_series(
            store_conn,
            store_client,
            {code: symbol},
            "2026-01-01",
            "2026-01-31",
            source="fred",
            provider=StubFred(),
            names={code: "test series"},
            currencies={code: Currency.USD},
            country="US",
        )
        run_id = report.run_id
        assert report.status == "ok"
        assert report.rows_written == 2

        panel = store.load_panel(store_conn, store_client, [symbol])
        assert panel["close"].tolist() == [4.01, 4.05]

        row = store_conn.execute(
            "SELECT country, currency, meta->>'macro', meta->>'source'"
            " FROM instruments WHERE symbol = %s",
            (symbol,),
        ).fetchone()
        assert row == ("US", "USD", "true", "fred")
    finally:
        instrument_id = catalog.instrument_ids(store_conn, [symbol])[symbol]
        store_client.command(
            f"ALTER TABLE {bars_mod.TABLE} DELETE WHERE instrument_id = %(iid)s",
            parameters={"iid": int(instrument_id)},
        )
        if run_id is not None:
            store_conn.execute("DELETE FROM ingest_runs WHERE run_id = %s", (run_id,))
        store_conn.execute("DELETE FROM instruments WHERE instrument_id = %s", (instrument_id,))
        store_conn.commit()