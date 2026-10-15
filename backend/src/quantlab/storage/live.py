"""Live market data: line leases and today's live bars.

Two tables, both written for the Market tab's live view (roadmap 4a):

- ``live_subscriptions`` (Postgres) -- a lease on one IBKR market-data line.
  The API renews a row while a stream watches the symbol; the live-ingest
  collector serves unexpired rows within the line budget and writes back what
  it managed (``status``). This module only ever writes the lease, never the
  status: the status is the collector's answer.
- ``live.bars_1m`` (ClickHouse) -- the session's 1-minute bars the collector
  stored. Provisional and short-lived: Tiingo's end-of-day load is the source
  of truth, so this is the only module that reads ``live.`` and nothing a
  backtest uses imports it (tests/unit/test_live_isolation.py holds that).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from quantlab.storage.warehouse import Warehouse

#: How long one renewal keeps a line. The stream renews well inside this, so a
#: closed tab frees its lines about this long after it went away.
LEASE_SECONDS = 120

#: What a symbol's line is called before the collector has looked at it.
PENDING = "pending"


@dataclass(frozen=True)
class LineStatus:
    status: str
    detail: str = ""


def renew_market_leases(wh: Warehouse, owner_id: str, instrument_ids: Sequence[int]) -> None:
    """Hold (or extend) a market line lease per instrument for ``owner_id``.

    An upsert that touches only the expiry: a renewal must never reset a
    status the collector already wrote back.
    """
    if not instrument_ids:
        return
    with wh.catalog() as conn:
        conn.cursor().executemany(
            """
            INSERT INTO live_subscriptions (instrument_id, consumer, owner_id, expires_at)
            VALUES (%s, 'market', %s, now() + make_interval(secs => %s))
            ON CONFLICT (instrument_id, consumer, owner_id)
            DO UPDATE SET expires_at = EXCLUDED.expires_at, updated_at = now()
            """,
            [(instrument_id, owner_id, LEASE_SECONDS) for instrument_id in instrument_ids],
        )


def line_statuses(
    wh: Warehouse, owner_id: str, instrument_ids: Sequence[int]
) -> dict[int, LineStatus]:
    """The collector's answer for each of this owner's market leases.

    An instrument with no row (not leased yet) reads as pending.
    """
    if not instrument_ids:
        return {}
    with wh.catalog() as conn:
        rows = conn.execute(
            """
            SELECT instrument_id, status, status_detail
              FROM live_subscriptions
             WHERE consumer = 'market' AND owner_id = %s AND instrument_id = ANY(%s)
            """,
            (owner_id, list(instrument_ids)),
        ).fetchall()
    found = {row[0]: LineStatus(row[1], row[2]) for row in rows}
    return {i: found.get(i, LineStatus(PENDING)) for i in instrument_ids}


def session_bars(wh: Warehouse, instrument_id: int) -> tuple[str | None, list[dict]]:
    """The most recent stored session's 1-minute bars, oldest first.

    ``(None, [])`` when the collector has stored nothing for the instrument --
    a symbol whose backfill is still pending, or one never subscribed.
    """
    with wh.bars() as client:
        latest = client.query(
            "SELECT max(session_date), count() FROM live.bars_1m WHERE instrument_id = %(id)s",
            parameters={"id": instrument_id},
        ).result_rows
        if not latest or not latest[0][1]:
            return None, []
        session = latest[0][0]
        rows = client.query(
            """
            SELECT ts, open, high, low, close, volume, kind
              FROM live.bars_1m FINAL
             WHERE instrument_id = %(id)s AND session_date = %(session)s
             ORDER BY ts ASC
            """,
            parameters={"id": instrument_id, "session": session},
        ).result_rows
    return session.isoformat(), [bar_dict(row) for row in rows]


def bar_dict(row: Sequence) -> dict:
    ts, open_, high, low, close, volume, kind = row
    return {
        "ts": _iso_utc(ts),
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": int(volume),
        "kind": str(kind),
    }


def _iso_utc(ts) -> str:
    # clickhouse-connect hands back naive datetimes in UTC for a 'UTC' column.
    text = ts.isoformat(timespec="milliseconds")
    return text if text.endswith(("Z", "+00:00")) else f"{text}Z"


def statuses_by_symbol(
    ids: Mapping[str, int], statuses: Mapping[int, LineStatus]
) -> dict[str, LineStatus]:
    return {symbol: statuses.get(i, LineStatus(PENDING)) for symbol, i in ids.items()}
