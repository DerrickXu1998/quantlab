"""storage.live against a real catalog and bar store.

Skipped unless QUANTLAB_DB_URL and QUANTLAB_CH_URL point at a migrated
warehouse (the demo path must not need one). Everything it writes is keyed to
one throwaway instrument and removed afterwards.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest

from quantlab.storage import live as live_store

SYMBOL = "ZZLIVETEST.US"


@pytest.fixture
def warehouse():
    if not (os.environ.get("QUANTLAB_DB_URL") and os.environ.get("QUANTLAB_CH_URL")):
        pytest.skip("no warehouse configured; the demo path must not need one")
    from quantlab.storage.warehouse import Warehouse

    wh = Warehouse.from_env()
    with wh.catalog() as conn:
        instrument_id = conn.execute(
            "INSERT INTO instruments (symbol, name, currency, quote_currency) "
            "VALUES (%s, 'live store test', 'USD', 'USD') "
            "ON CONFLICT (symbol) DO UPDATE SET name = EXCLUDED.name RETURNING instrument_id",
            (SYMBOL,),
        ).fetchone()[0]
    try:
        yield wh, instrument_id
    finally:
        with wh.bars() as client:
            client.command(
                "DELETE FROM live.bars_1m WHERE instrument_id = %(id)s",
                parameters={"id": instrument_id},
            )
        with wh.catalog() as conn:
            # Cascades to live_subscriptions.
            conn.execute("DELETE FROM instruments WHERE instrument_id = %s", (instrument_id,))


def test_a_renewal_extends_the_lease_and_keeps_the_collectors_answer(warehouse):
    wh, instrument_id = warehouse

    assert live_store.line_statuses(wh, "u1", [instrument_id]) == {
        instrument_id: live_store.LineStatus("pending")
    }
    live_store.renew_market_leases(wh, "u1", [instrument_id])
    with wh.catalog() as conn:
        first = conn.execute(
            "SELECT expires_at FROM live_subscriptions WHERE instrument_id = %s", (instrument_id,)
        ).fetchone()[0]
        # The collector's write-back.
        conn.execute(
            "UPDATE live_subscriptions SET status = 'over_budget', status_detail = 'no line' "
            "WHERE instrument_id = %s",
            (instrument_id,),
        )

    live_store.renew_market_leases(wh, "u1", [instrument_id])

    with wh.catalog() as conn:
        rows = conn.execute(
            "SELECT expires_at, status FROM live_subscriptions WHERE instrument_id = %s",
            (instrument_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] >= first
    assert rows[0][1] == "over_budget"
    assert live_store.line_statuses(wh, "u1", [instrument_id])[instrument_id] == (
        live_store.LineStatus("over_budget", "no line")
    )
    # Another owner's lease is its own row and its own answer.
    assert live_store.line_statuses(wh, "u2", [instrument_id])[instrument_id].status == "pending"


def test_session_bars_are_the_latest_session_deduplicated_in_order(warehouse):
    wh, instrument_id = warehouse
    assert live_store.session_bars(wh, "u1", instrument_id) == (None, [])

    def row(ts, close, kind, ingest, owner="u1"):
        return [owner, instrument_id, ts, ts.date(), close, close, close, close, 10, kind, ingest]

    early = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    m1 = datetime(2026, 10, 15, 13, 31, tzinfo=UTC)
    m0 = datetime(2026, 10, 15, 13, 30, tzinfo=UTC)
    with wh.bars() as client:
        client.insert(
            "live.bars_1m",
            [
                row(early, 1.0, "backfill", datetime(2026, 10, 14, 14, 0, tzinfo=UTC)),
                row(m1, 3.0, "rolled", datetime(2026, 10, 15, 13, 32, tzinfo=UTC)),
                row(m0, 2.0, "backfill", datetime(2026, 10, 15, 13, 40, tzinfo=UTC)),
                # A reconnect re-backfilled 13:31: the later write wins.
                row(m1, 3.5, "backfill", datetime(2026, 10, 15, 13, 40, tzinfo=UTC)),
                # Another user's login fetched this minute too: same key but
                # for the owner, so it neither replaces u1's nor is served to u1.
                row(m1, 99.0, "rolled", datetime(2026, 10, 15, 13, 50, tzinfo=UTC), owner="u2"),
                row(m1, 98.0, "rolled", datetime(2026, 10, 16, 13, 50, tzinfo=UTC), owner="u2"),
            ],
            column_names=[
                "owner_id", "instrument_id", "ts", "session_date", "open", "high", "low",
                "close", "volume", "kind", "ts_ingest",
            ],
        )

    session, bars = live_store.session_bars(wh, "u1", instrument_id)
    theirs = live_store.session_bars(wh, "u2", instrument_id)
    assert [b["close"] for b in theirs[1]] == [98.0]

    assert session == date(2026, 10, 15).isoformat()
    assert [(b["ts"], b["close"], b["kind"]) for b in bars] == [
        ("2026-10-15T13:30:00.000Z", 2.0, "backfill"),
        ("2026-10-15T13:31:00.000Z", 3.5, "backfill"),
    ]
