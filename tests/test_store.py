"""Store tests: pure validation logic, plus round-trips against live databases.

The database tests need both halves of the store and skip without them::

    make store-test          # runs them in the compose stack
    QUANTLAB_DB_URL=... QUANTLAB_CH_URL=... pytest tests/test_store.py

Each database test works in its own ClickHouse/Postgres state and cleans up
after itself, so they can run against the same stack the stack uses.
"""
from __future__ import annotations

import datetime as dt
import os
import uuid

import pandas as pd
import pytest

from quantlab.schema import Currency, Security
from quantlab.store import bars as bars_mod
from quantlab.store import catalog

# ---------------------------------------------------------------------------
# Pure logic -- no database required
# ---------------------------------------------------------------------------


def test_storage_currency_normalises_pence_to_pounds():
    """GBX is the London trap: stored values must be GBP (Constitution III)."""
    assert catalog.storage_currency(Currency.GBX) is Currency.GBP
    assert catalog.storage_currency(Currency.USD) is Currency.USD
    assert catalog.storage_currency(Currency.GBP) is Currency.GBP


def _frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def test_validate_accepts_a_well_formed_bar():
    accepted, rejected = bars_mod.validate(
        _frame([{"open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}])
    )
    assert len(accepted) == 1
    assert rejected.empty


def test_validate_rejects_ohlc_ordering_violation():
    """A high below the close is impossible and must not reach ClickHouse,
    which would happily store it -- there are no CHECK constraints there."""
    accepted, rejected = bars_mod.validate(
        _frame([{"open": 10, "high": 11, "low": 9, "close": 12, "volume": 100}])
    )
    assert accepted.empty
    assert rejected["reason"].tolist() == ["OHLC ordering violated"]


def test_validate_rejects_low_above_open():
    """The real failure seen in Yahoo's HSBA.LON history."""
    accepted, rejected = bars_mod.validate(
        _frame([{"open": 6.932, "high": 6.976, "low": 6.968, "close": 6.975, "volume": 1}])
    )
    assert accepted.empty
    assert rejected["reason"].tolist() == ["OHLC ordering violated"]


def test_validate_rejects_non_positive_and_missing_prices():
    accepted, rejected = bars_mod.validate(
        _frame(
            [
                {"open": 10, "high": 11, "low": 0, "close": 10.5, "volume": 100},
                {"open": None, "high": 11, "low": 9, "close": 10.5, "volume": 100},
                {"open": 10, "high": 11, "low": 9, "close": 10.5, "volume": -5},
            ]
        )
    )
    assert accepted.empty
    assert set(rejected["reason"]) == {
        "non-positive price",
        "missing OHLC value",
        "negative volume",
    }


def test_validate_keeps_good_bars_when_one_is_bad():
    """One bad tick from a free source must not cost the whole refresh."""
    accepted, rejected = bars_mod.validate(
        _frame(
            [
                {"open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
                {"open": 10, "high": 11, "low": 9, "close": 99, "volume": 100},
                {"open": 12, "high": 13, "low": 11, "close": 12.5, "volume": 200},
            ]
        )
    )
    assert len(accepted) == 2
    assert len(rejected) == 1


# ---------------------------------------------------------------------------
# Live database round-trips
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


@pytest.fixture
def unique_symbol():
    """A symbol no other test or real ingest will collide with."""
    return f"TST{uuid.uuid4().hex[:6].upper()}.US"


def _panel(symbol: str, rows: list[tuple[str, float, float, float, float, int]]):
    frame = pd.DataFrame(
        [
            {
                "date": pd.Timestamp(date),
                "symbol": symbol,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": v,
                "adj_close": c,
            }
            for date, o, h, lo, c, v in rows
        ]
    )
    return frame.set_index(["date", "symbol"]).sort_index()


@needs_store
def test_migrations_are_idempotent(store_conn, store_client):
    """Re-running migrate against a current database must be a no-op."""
    from quantlab import store

    assert store.migrate(store_conn) == []
    assert store.ch_migrate(store_client) == []
    assert store.current_version(store_conn) is not None
    assert store.ch_current_version(store_client) is not None


@needs_store
def test_ensure_instruments_does_not_blank_existing_identifiers(store_conn, unique_symbol):
    """A later ingest from a thinner source must not erase a richer one's data."""
    rich = Security(symbol=unique_symbol, name="Test Corp", isin="US0000000001",
                    exchange="XNYS", currency=Currency.USD, sector="Tech")
    ids = catalog.ensure_instruments(store_conn, {unique_symbol: rich})
    assert unique_symbol in ids

    thin = Security(symbol=unique_symbol, currency=Currency.USD)
    catalog.ensure_instruments(store_conn, {unique_symbol: thin})

    row = store_conn.execute(
        "SELECT name, isin, sector FROM instruments WHERE symbol = %s", (unique_symbol,)
    ).fetchone()
    assert row == ("Test Corp", "US0000000001", "Tech")


@needs_store
def test_gbx_instrument_records_both_currencies(store_conn):
    """Storage is GBP; the vendor quoted GBX. Both must be recorded so the
    100x pence bug stays detectable after the fact."""
    symbol = f"TST{uuid.uuid4().hex[:6].upper()}.LON"
    sec = Security(symbol=symbol, exchange="XLON", currency=Currency.GBX)
    catalog.ensure_instruments(store_conn, {symbol: sec}, {symbol: Currency.GBX})

    row = store_conn.execute(
        "SELECT currency, quote_currency FROM instruments WHERE symbol = %s", (symbol,)
    ).fetchone()
    assert row == ("GBP", "GBX")


@needs_store
def test_universe_members_are_append_only(store_conn, unique_symbol):
    """Deleting a snapshot member must be impossible -- it is the survivorship
    defence, and a snapshot you can edit is not a snapshot."""
    import psycopg

    sec = Security(symbol=unique_symbol, currency=Currency.USD)
    ids = catalog.ensure_instruments(store_conn, {unique_symbol: sec})
    universe = f"test-{uuid.uuid4().hex[:8]}"
    snapshot_id = catalog.snapshot_universe(
        store_conn, universe, [unique_symbol], ids, snapshot_date=dt.date(2026, 1, 1)
    )

    with pytest.raises(psycopg.errors.RaiseException):
        store_conn.execute(
            "DELETE FROM universe_members WHERE snapshot_id = %s", (snapshot_id,)
        )
    store_conn.rollback()


@needs_store
def test_resnapshotting_the_same_day_does_not_rewrite_history(store_conn, unique_symbol):
    sec = Security(symbol=unique_symbol, currency=Currency.USD)
    ids = catalog.ensure_instruments(store_conn, {unique_symbol: sec})
    universe = f"test-{uuid.uuid4().hex[:8]}"
    day = dt.date(2026, 2, 2)

    first = catalog.snapshot_universe(store_conn, universe, [unique_symbol], ids, snapshot_date=day)
    second = catalog.snapshot_universe(store_conn, universe, [], ids, snapshot_date=day)
    assert first == second

    count = store_conn.execute(
        "SELECT count(*) FROM universe_members WHERE snapshot_id = %s", (first,)
    ).fetchone()[0]
    assert count == 1


@needs_store
def test_bars_round_trip_and_reingest_is_idempotent(store_conn, store_client, unique_symbol):
    """The property ReplacingMergeTree does not give for free: writing the
    same range twice must read back once."""
    from quantlab import store

    sec = Security(symbol=unique_symbol, currency=Currency.USD)
    ids = catalog.ensure_instruments(store_conn, {unique_symbol: sec})
    currencies = {unique_symbol: Currency.USD}
    panel = _panel(
        unique_symbol,
        [
            ("2026-01-05", 10.0, 11.0, 9.5, 10.5, 1000),
            ("2026-01-06", 10.5, 12.0, 10.0, 11.5, 2000),
            ("2026-01-07", 11.5, 12.5, 11.0, 12.0, 1500),
        ],
    )

    run_one = catalog.start_run(store_conn, source="test", symbols_requested=1)
    store_conn.commit()
    first = bars_mod.write_bars(
        store_client, panel, run_id=run_one, ids=ids, currencies=currencies, source="test"
    )
    assert first.written == 3
    assert first.rejected_count == 0

    run_two = catalog.start_run(store_conn, source="test", symbols_requested=1)
    store_conn.commit()
    bars_mod.write_bars(
        store_client, panel, run_id=run_two, ids=ids, currencies=currencies, source="test"
    )

    readback = store.load_panel(store_conn, store_client, [unique_symbol])
    assert len(readback) == 3, "re-ingest must not duplicate rows on read"

    # The later run supersedes the earlier one.
    raw = bars_mod.load_bars(store_client, [ids[unique_symbol]])
    assert set(raw.columns) >= {"open", "high", "low", "close"}
    assert len(raw) == 3

    closes = readback["close"].tolist()
    assert closes == [10.5, 11.5, 12.0]

    _cleanup_bars(store_client, ids[unique_symbol])


@needs_store
def test_bad_ticks_are_quarantined_not_dropped(store_conn, store_client, unique_symbol):
    """A rejected bar must be recorded with a reason: no silent mutations."""
    sec = Security(symbol=unique_symbol, currency=Currency.USD)
    ids = catalog.ensure_instruments(store_conn, {unique_symbol: sec})
    panel = _panel(
        unique_symbol,
        [
            ("2026-03-02", 10.0, 11.0, 9.5, 10.5, 1000),
            ("2026-03-03", 10.0, 11.0, 9.5, 99.0, 1000),  # close above high
        ],
    )

    run_id = catalog.start_run(store_conn, source="test", symbols_requested=1)
    store_conn.commit()
    result = bars_mod.write_bars(
        store_client, panel, run_id=run_id,
        ids=ids, currencies={unique_symbol: Currency.USD}, source="test",
    )
    assert result.written == 1
    assert result.rejected_count == 1

    catalog.record_rejects(store_conn, run_id, result.rejected)
    store_conn.commit()

    rows = store_conn.execute(
        "SELECT reason FROM ingest_rejects WHERE run_id = %s", (run_id,)
    ).fetchall()
    assert [r[0] for r in rows] == ["OHLC ordering violated"]

    _cleanup_bars(store_client, ids[unique_symbol])


@needs_store
def test_point_in_time_universe_filters_the_panel(store_conn, store_client):
    """A snapshot restricts the panel to who was actually in the universe."""
    from quantlab import store

    kept = f"TST{uuid.uuid4().hex[:6].upper()}.US"
    excluded = f"TST{uuid.uuid4().hex[:6].upper()}.US"
    securities = {
        kept: Security(symbol=kept, currency=Currency.USD),
        excluded: Security(symbol=excluded, currency=Currency.USD),
    }
    ids = catalog.ensure_instruments(store_conn, securities)
    currencies = {s: Currency.USD for s in securities}

    run_id = catalog.start_run(store_conn, source="test", symbols_requested=2)
    universe = f"test-{uuid.uuid4().hex[:8]}"
    snapshot_id = catalog.snapshot_universe(
        store_conn, universe, [kept], ids, snapshot_date=dt.date(2026, 4, 1)
    )
    store_conn.commit()

    for symbol in (kept, excluded):
        bars_mod.write_bars(
            store_client,
            _panel(symbol, [("2026-04-02", 10.0, 11.0, 9.5, 10.5, 1000)]),
            run_id=run_id, ids=ids, currencies=currencies, source="test",
        )

    panel = store.load_panel(store_conn, store_client, universe_snapshot=snapshot_id)
    symbols_present = set(panel.index.get_level_values("symbol"))
    assert symbols_present == {kept}

    for symbol in (kept, excluded):
        _cleanup_bars(store_client, ids[symbol])


@needs_store
def test_seed_warehouse_round_trip_and_reseed_is_idempotent(store_conn, store_client):
    """Seeding writes bars the warehouse can serve, and re-seeding the same
    range must read back exactly the same rows (ReplacingMergeTree dedup)."""
    from quantlab import store
    from quantlab.synthetic import SyntheticSpec

    symbol = f"TST{uuid.uuid4().hex[:6].upper()}.US"
    spec = SyntheticSpec(symbol=symbol, name="Test Synthetic Co", profile="mixed")

    first = store.seed_warehouse(
        store_conn, store_client, [spec], start="2024-01-01", end="2024-12-31"
    )
    assert first.status == "ok"
    assert first.symbols_ok == 1
    assert first.rows_written > 200  # one year of weekdays

    panel = store.load_panel(store_conn, store_client, [symbol])
    assert len(panel) == first.rows_written

    second = store.seed_warehouse(
        store_conn, store_client, [spec], start="2024-01-01", end="2024-12-31"
    )
    panel_after = store.load_panel(store_conn, store_client, [symbol])
    assert len(panel_after) == first.rows_written, "re-seed must not duplicate rows on read"
    assert second.run_id > first.run_id, "each seed opens a fresh run for provenance"
    pd.testing.assert_frame_equal(panel_after, panel)

    row = store_conn.execute(
        "SELECT source, kind, status, params->>'synthetic' FROM ingest_runs WHERE run_id = %s",
        (first.run_id,),
    ).fetchone()
    assert row[:3] == ("synthetic", "prices", "ok")
    assert row[3] == "true"

    # seed_warehouse commits as it goes, so a fixture rollback cannot undo it;
    # remove the catalog rows explicitly alongside the bars.
    instrument_id = catalog.instrument_ids(store_conn, [symbol])[symbol]
    _cleanup_bars(store_client, instrument_id)
    store_conn.execute(
        "DELETE FROM ingest_runs WHERE run_id = ANY(%s)", ([first.run_id, second.run_id],)
    )
    store_conn.execute(
        "DELETE FROM instruments WHERE instrument_id = %s", (instrument_id,)
    )
    store_conn.commit()


def _cleanup_bars(client, instrument_id: int) -> None:
    """Remove a test instrument's bars. ClickHouse deletes are mutations and
    asynchronous, which is fine for cleanup but never for the write path."""
    client.command(
        f"ALTER TABLE {bars_mod.TABLE} DELETE WHERE instrument_id = %(iid)s",
        parameters={"iid": int(instrument_id)},
    )
