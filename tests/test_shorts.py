"""Short-selling ingest: FINRA short volume, FCA net short positions.

Offline unit tests stub the provider's HTTP client (no network, no keys).
The ``needs_store`` round-trips run against the live stack with stubbed
providers -- they exercise the catalog and the fundamentals table, not the
APIs -- and clean up every row they write::

    make store-test
"""
from __future__ import annotations

import datetime as dt
import io
import os
import uuid

import pandas as pd
import pytest

from quantlab import store
from quantlab.schema import Currency, DataUnavailable, ProviderError, Security
from quantlab.store.shorts import (
    fca_name_index,
    fca_rows,
    finra_rows_for_day,
    finra_ticker_index,
    ingest_finra_shorts,
)

# A representative slice of a CNMSshvol file: header, a fractional-volume row,
# a slash-spelled class share, a malformed line and the record-count footer.
SHVOL_TEXT = """Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
20260918|A|633386.346426|17|915680.398509|B,Q,N
20260918|BRK/B|219565|0|362575|B,N
20260918|MSFT|1200000|500|3400000|Q,N
20260918|BROKEN|not-a-number|0|100|N
too|few|fields
12315
"""

FCA_COLUMNS = ["Position Holder", "Name of Share Issuer", "ISIN", "Net Short Position (%)", "Position Date"]

FCA_ROWS = [
    ("AlphaGen Capital Limited", "SHELL PLC", "GB00B03MLX29", 1.42, dt.date(2026, 9, 16)),
    ("Bronte Capital Management Pty Ltd", "SHELL PLC", "GB00B03MLX29", 0.0, dt.date(2026, 9, 16)),
    ("Citadel Advisors LLC", "Not In Catalog Ltd", "GB00XXXXXXXX", 0.5, dt.date(2026, 9, 16)),
    # Unplaceable rows: no ISIN, bad date, non-numeric percentage.
    ("Nobody", "SHELL PLC", "", 0.4, dt.date(2026, 9, 16)),
    ("Nobody", "SHELL PLC", "GB00B03MLX29", "n/a", dt.date(2026, 9, 16)),
    ("Nobody", "SHELL PLC", "GB00B03MLX29", 0.4, None),
]


def _fca_xlsx(rows, columns=FCA_COLUMNS) -> bytes:
    openpyxl = pytest.importorskip("openpyxl")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(columns)
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# FINRA file parsing -- pure logic, no database
# ---------------------------------------------------------------------------


def test_parse_shvol_skips_header_footer_and_malformed_lines():
    from quantlab.providers.finra import parse_shvol

    rows = parse_shvol(SHVOL_TEXT)
    assert len(rows) == 3, "header, footer, short line and non-numeric row must drop"
    by_symbol = {r["symbol"]: r for r in rows}

    a = by_symbol["A"]
    assert a["date"] == dt.date(2026, 9, 18)
    assert a["short_volume"] == pytest.approx(633386.346426)
    assert a["short_exempt_volume"] == 17.0
    assert a["total_volume"] == pytest.approx(915680.398509)
    assert a["market"] == "B,Q,N"

    # Class shares keep the vendor's slash spelling; the bridge maps it.
    assert "BRK/B" in by_symbol
    assert parse_shvol("") == []


def test_finra_missing_day_is_data_unavailable_not_an_error():
    from quantlab.providers.finra import FinraProvider

    provider = FinraProvider()

    def absent(url, **kw):
        raise ProviderError(f"finra: HTTP 403 on {url}: Forbidden")

    provider.client.get_text = absent
    with pytest.raises(DataUnavailable, match="no short volume file"):
        provider.short_volume_day("2026-09-19")  # a Saturday

    def broken(url, **kw):
        raise ProviderError(f"finra: HTTP 500 on {url}: boom")

    provider.client.get_text = broken
    with pytest.raises(ProviderError, match="HTTP 500"):
        provider.short_volume_day("2026-09-18")


# ---------------------------------------------------------------------------
# FINRA ticker bridge and row building
# ---------------------------------------------------------------------------


def test_finra_ticker_index_handles_class_shares_and_pseudo():
    rows = [
        ("AAPL.US", 1, {}),
        ("BRK.B.US", 2, {}),          # catalog dot; file spells BRK/B
        ("BF-B.US", 3, {}),           # catalog dash; file spells BF/B
        ("GBPUSD.BOE", 9, {"macro": True}),
        ("VOD.LON", 10, {}),
    ]
    index = finra_ticker_index(rows)
    assert index["AAPL"] == 1
    assert index["BRK/B"] == 2 and index["BRK.B"] == 2
    assert index["BF/B"] == 3
    assert "GBPUSD" not in index and "VOD" not in index


def test_finra_rows_for_day_maps_skips_and_tags():
    index = {"A": 1, "BRK/B": 2}
    from quantlab.providers.finra import parse_shvol

    records = parse_shvol(SHVOL_TEXT)
    rows, skipped = finra_rows_for_day(records, index, dt.date(2026, 9, 18))

    assert skipped == 1, "MSFT is not in the catalog and is skipped, not an error"
    assert len(rows) == 6, "three tags per matched symbol"
    tags = {(r["instrument_id"], r["tag"]) for r in rows}
    assert tags == {
        (1, "short_volume"), (1, "short_exempt_volume"), (1, "total_volume"),
        (2, "short_volume"), (2, "short_exempt_volume"), (2, "total_volume"),
    }
    row = next(r for r in rows if r["instrument_id"] == 1 and r["tag"] == "short_volume")
    assert row["provider"] == "finra"
    assert row["unit"] == "shares"
    assert row["value"] == pytest.approx(633386.346426)
    assert row["period_end"] == dt.date(2026, 9, 18)
    assert row["filed_at"] == dt.date(2026, 9, 18), "published same day by 18:00 ET"
    assert row["accession"] == "CNMSshvol-20260918"
    assert row["meta"] == {"market": "B,Q,N"}


def test_ingest_finra_shorts_records_missing_days_without_failing(monkeypatch):
    from quantlab.store import shorts as shorts_mod

    class StubFinra:
        def short_volume_day(self, day):
            day = pd.Timestamp(day).date()
            if day == dt.date(2026, 9, 18):
                return pd.DataFrame(
                    [
                        {"date": day, "symbol": "A", "short_volume": 10.0,
                         "short_exempt_volume": 1.0, "total_volume": 20.0, "market": "N"}
                    ]
                )
            raise DataUnavailable(f"finra: no short volume file for {day}")

    monkeypatch.setattr(shorts_mod, "_finra_catalog_rows", lambda conn: [("A.US", 1, {})])
    monkeypatch.setattr(shorts_mod.catalog, "start_run", lambda conn, **kw: 42)
    finished = {}
    monkeypatch.setattr(
        shorts_mod.catalog, "finish_run",
        lambda conn, run_id, **kw: finished.update(kw),
    )
    written = []
    monkeypatch.setattr(
        shorts_mod, "write_fundamentals",
        lambda conn, rows, *, run_id: written.extend(rows) or len(rows),
    )

    class FakeConn:
        def commit(self):
            pass

    report = ingest_finra_shorts(
        FakeConn(), provider=StubFinra(), start="2026-09-17", end="2026-09-18"
    )

    assert report.status == "ok"
    assert report.symbols_requested == 2 and report.symbols_ok == 1
    assert report.missing == ["2026-09-17"]
    assert report.rows_written == 3
    assert finished["status"] == "ok"
    assert {r["tag"] for r in written} == {"short_volume", "short_exempt_volume", "total_volume"}

    # Nothing fetched at all is a failed run.
    class EmptyFinra:
        def short_volume_day(self, day):
            raise DataUnavailable("finra: no short volume file")

    written.clear()
    report = ingest_finra_shorts(
        FakeConn(), provider=EmptyFinra(), start="2026-09-17", end="2026-09-18"
    )
    assert report.status == "failed"
    assert report.rows_written == 0


# ---------------------------------------------------------------------------
# FCA workbook parsing, name bridge and row building
# ---------------------------------------------------------------------------


def test_parse_positions_locates_columns_and_drops_unplaceable_rows():
    from quantlab.providers.fca import parse_positions

    frame = parse_positions(_fca_xlsx(FCA_ROWS))
    assert len(frame) == 3, "blank ISIN, NaN pct and missing date must drop"
    shell = frame[frame["issuer_name"] == "SHELL PLC"]
    assert len(shell) == 2
    assert set(shell["net_short_pct"]) == {1.42, 0.0}, "a closed (0%) disclosure is kept"
    assert set(shell["isin"]) == {"GB00B03MLX29"}
    assert shell["position_date"].iloc[0] == pd.Timestamp("2026-09-16")


def test_parse_positions_fails_clearly_when_columns_are_missing():
    from quantlab.providers.fca import parse_positions

    blob = _fca_xlsx([("x", 1.0)], columns=["Something", "Else"])
    with pytest.raises(ProviderError, match="could not locate"):
        parse_positions(blob)


def test_fca_name_index_accepts_unique_names_and_drops_collisions():
    rows = [
        ("SHEL.LON", 1, "SHELL PLC"),
        ("SHEL.LON", 1, "Shell plc"),            # same instrument, second key
        ("DUP1.LON", 2, "ACME HOLDINGS PLC"),
        ("DUP2.LON", 3, "ACME GROUP PLC"),       # both normalize to ACME (weak tokens stay)
        ("NONAME.LON", 4, ""),
    ]
    index = fca_name_index(rows)
    assert index["SHELL"] == ("SHEL.LON", 1)
    # DUP1/DUP2 only collide after HOLDINGS/GROUP stripping, which the
    # normalizer does not do -- so both survive under their full names.
    assert index["ACME HOLDINGS"] == ("DUP1.LON", 2)
    assert index["ACME GROUP"] == ("DUP2.LON", 3)
    assert len(index) == 3

    # A true collision: two instruments, identical normalized name.
    rows = [("A1.LON", 1, "FOO PLC"), ("A2.LON", 2, "FOO LIMITED")]
    assert fca_name_index(rows) == {}, "an ambiguous name matches nothing"


def test_fca_rows_identities_and_t2_filing_date():
    from quantlab.providers.fca import parse_positions

    frame = parse_positions(_fca_xlsx(FCA_ROWS))
    index = {"SHELL": ("SHEL.LON", 1)}
    rows, unmatched = fca_rows(frame, index)

    assert unmatched == 1, "Not In Catalog Ltd is counted, never guessed"
    assert len(rows) == 2, "one row per holder disclosure, 0% included"
    row = next(r for r in rows if r["meta"]["holder"] == "AlphaGen Capital Limited")
    assert row["provider"] == "fca"
    assert row["tag"] == "net_short_position_pct"
    assert row["unit"] == "pct"
    assert row["period_end"] == dt.date(2026, 9, 16)
    # 2026-09-16 is a Wednesday; T+2 publication lands Friday 2026-09-18.
    assert row["filed_at"] == dt.date(2026, 9, 18)
    assert row["accession"] == "AlphaGen Capital Limited", "the holder is the filing identity"
    assert row["meta"]["isin"] == "GB00B03MLX29"
    closed = next(r for r in rows if r["value"] == 0.0)
    assert closed["meta"]["holder"] == "Bronte Capital Management Pty Ltd"


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


def _cleanup(conn, run_ids, instrument_id):
    """fundamentals references both instruments and ingest_runs; delete it first."""
    conn.execute("DELETE FROM fundamentals WHERE instrument_id = %s", (instrument_id,))
    conn.execute("DELETE FROM ingest_runs WHERE run_id = ANY(%s)", (list(run_ids),))
    conn.execute("DELETE FROM instruments WHERE instrument_id = %s", (instrument_id,))
    conn.commit()


@needs_store
def test_finra_shorts_round_trip_is_idempotent(store_conn):
    root = f"ZQ{uuid.uuid4().hex[:6].upper()}"
    symbol = f"{root}.US"
    ids = store.ensure_instruments(
        store_conn, {symbol: Security(symbol=symbol, country="US", currency=Currency.USD)}
    )
    store_conn.commit()
    instrument_id = ids[symbol]
    day = dt.date(2026, 9, 18)

    class StubFinra:
        def short_volume_day(self, d):
            assert pd.Timestamp(d).date() == day
            return pd.DataFrame(
                [
                    {"date": day, "symbol": root, "short_volume": 450.0,
                     "short_exempt_volume": 5.0, "total_volume": 1000.0, "market": "B,Q,N"},
                    {"date": day, "symbol": "NOTHERE", "short_volume": 1.0,
                     "short_exempt_volume": 0.0, "total_volume": 2.0, "market": "N"},
                ]
            )

    run_ids: list[int] = []
    try:
        first = ingest_finra_shorts(store_conn, provider=StubFinra(), start=day, end=day)
        run_ids.append(first.run_id)
        assert first.status == "ok"
        assert first.rows_written == 3, "three tags; the unknown symbol is skipped"
        assert first.reject_reasons == {"symbols_not_in_catalog": 1}

        rows = store_conn.execute(
            "SELECT tag, value, period_end::text, filed_at::text, accession, unit"
            " FROM fundamentals WHERE instrument_id = %s AND provider = 'finra' ORDER BY tag",
            (instrument_id,),
        ).fetchall()
        assert rows == [
            ("short_exempt_volume", 5.0, "2026-09-18", "2026-09-18", "CNMSshvol-20260918", "shares"),
            ("short_volume", 450.0, "2026-09-18", "2026-09-18", "CNMSshvol-20260918", "shares"),
            ("total_volume", 1000.0, "2026-09-18", "2026-09-18", "CNMSshvol-20260918", "shares"),
        ]

        second = ingest_finra_shorts(store_conn, provider=StubFinra(), start=day, end=day)
        run_ids.append(second.run_id)
        assert second.rows_written == 0, "re-pull of the same day must be a no-op"

        run = store_conn.execute(
            "SELECT source, kind, status FROM ingest_runs WHERE run_id = %s", (first.run_id,)
        ).fetchone()
        assert run == ("finra", "fundamentals", "ok")
    finally:
        _cleanup(store_conn, run_ids, instrument_id)


@needs_store
def test_fca_shorts_round_trip_is_idempotent(store_conn):
    from quantlab.store.shorts import ingest_fca_shorts

    name = f"ZQX{uuid.uuid4().hex[:6].upper()} TEST"
    symbol = f"{name.split()[0]}.LON"
    ids = store.ensure_instruments(
        store_conn,
        {symbol: Security(symbol=symbol, name=f"{name} PLC", country="GB", currency=Currency.GBX)},
    )
    store_conn.commit()
    instrument_id = ids[symbol]

    class StubFca:
        def net_short_positions(self):
            return pd.DataFrame(
                [
                    {"holder": "Stub Capital LP", "issuer_name": f"{name} PLC",
                     "isin": "GB00TEST0001", "net_short_pct": 0.85,
                     "position_date": pd.Timestamp("2026-09-16")},
                    {"holder": "Other Fund LLC", "issuer_name": f"{name} PLC",
                     "isin": "GB00TEST0001", "net_short_pct": 0.0,
                     "position_date": pd.Timestamp("2026-09-16")},
                    {"holder": "Ghost Fund", "issuer_name": "NO SUCH ISSUER PLC",
                     "isin": "GB00TEST0002", "net_short_pct": 1.2,
                     "position_date": pd.Timestamp("2026-09-16")},
                ]
            )

    run_ids: list[int] = []
    try:
        first = ingest_fca_shorts(store_conn, provider=StubFca())
        run_ids.append(first.run_id)
        assert first.status == "ok"
        assert first.rows_written == 2, "two holder disclosures; the unmatched issuer is skipped"
        assert first.symbols_ok == 1

        rows = store_conn.execute(
            "SELECT accession, value, period_end::text, filed_at::text,"
            "       meta->>'isin', meta->>'holder'"
            " FROM fundamentals WHERE instrument_id = %s AND provider = 'fca' ORDER BY accession",
            (instrument_id,),
        ).fetchall()
        assert rows == [
            ("Other Fund LLC", 0.0, "2026-09-16", "2026-09-18", "GB00TEST0001", "Other Fund LLC"),
            ("Stub Capital LP", 0.85, "2026-09-16", "2026-09-18", "GB00TEST0001", "Stub Capital LP"),
        ]

        second = ingest_fca_shorts(store_conn, provider=StubFca())
        run_ids.append(second.run_id)
        assert second.rows_written == 0, "re-pull of the same disclosures must be a no-op"

        run = store_conn.execute(
            "SELECT source, kind, status FROM ingest_runs WHERE run_id = %s", (first.run_id,)
        ).fetchone()
        assert run == ("fca", "fundamentals", "ok")
    finally:
        _cleanup(store_conn, run_ids, instrument_id)
