"""Postgres (leases in, statuses out) and ClickHouse (today's minutes)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from quantlab_live.plan import Lease

NEW_YORK = ZoneInfo("America/New_York")

BAR_COLUMNS = [
    "owner_id",
    "instrument_id",
    "ts",
    "session_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "kind",
]


def bar_row(owner_id: str, instrument_id: int, start: datetime, bar: dict, kind: str) -> list:
    """One live.bars_1m row, belonging to the user whose login fetched it; the
    session is the New York date of the minute."""
    start = start.astimezone(UTC)
    return [
        owner_id,
        instrument_id,
        start.replace(tzinfo=None),
        start.astimezone(NEW_YORK).date(),
        float(bar["open"]),
        float(bar["high"]),
        float(bar["low"]),
        float(bar["close"]),
        int(bar["volume"]),
        kind,
    ]


class Store:
    """Short-lived connections: a poll every two seconds needs no pool."""

    def __init__(self, pg_dsn: str, ch: dict) -> None:
        self._dsn = pg_dsn
        self._ch = ch
        self._client = None

    def leases(self, owner_id: str) -> list[Lease]:
        """One user's unexpired leases: their own login serves only them."""
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                """
                SELECT s.subscription_id, s.instrument_id, i.symbol, s.consumer, s.requested_at
                  FROM live_subscriptions s
                  JOIN instruments i USING (instrument_id)
                 WHERE s.expires_at > now() AND s.owner_id = %s
                """,
                (owner_id,),
            ).fetchall()
        return [Lease(*row) for row in rows]

    def write_statuses(self, rows: Sequence[tuple[int, str, str, str | None]]) -> None:
        """(subscription_id, status, detail, ib_symbol); untouched when unchanged."""
        if not rows:
            return
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            conn.cursor().executemany(
                """
                UPDATE live_subscriptions
                   SET status = %s, status_detail = %s, ib_symbol = %s, updated_at = now()
                 WHERE subscription_id = %s
                   AND (status, status_detail, ib_symbol)
                       IS DISTINCT FROM (%s, %s, %s)
                """,
                [(s, d, ib, sid, s, d, ib) for sid, s, d, ib in rows],
            )

    def insert_bars(self, rows: Sequence[list]) -> None:
        if not rows:
            return
        if self._client is None:
            import clickhouse_connect

            self._client = clickhouse_connect.get_client(**self._ch)
        try:
            self._client.insert("live.bars_1m", list(rows), column_names=BAR_COLUMNS)
        except Exception:
            # A dropped connection: reconnect on the next write.
            self._client = None
            raise
