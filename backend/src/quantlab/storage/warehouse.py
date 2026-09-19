"""Read access to the real data warehouse: ClickHouse bars + Postgres catalog.

This is the API's half of the store. It deliberately does not import the
research library: the backend image's build context is ``backend/``, and the
API has no business carrying the provider stack. What it shares with the
ingest side is the schema, not the code.

No pandas here either -- the backend serves JSON, and raw rows are cheaper.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

DB_URL_ENV = "QUANTLAB_DB_URL"
CH_URL_ENV = "QUANTLAB_CH_URL"

# Read through the FINAL view, never the raw table: ReplacingMergeTree
# collapses re-ingested duplicates on its own schedule, so the raw table can
# legitimately hold two copies of a bar between merges.
BARS_VIEW = "price_bars_current"


def configured() -> bool:
    """True when both halves of the warehouse are configured."""
    return bool(os.environ.get(DB_URL_ENV) and os.environ.get(CH_URL_ENV))


def pg_dsn() -> str:
    return os.environ.get(DB_URL_ENV, "")


def ch_settings(url: str = "") -> dict[str, Any]:
    """clickhouse://user:pass@host:8123/db -> clickhouse_connect kwargs."""
    parsed = urlparse(url or os.environ.get(CH_URL_ENV, ""))
    secure = parsed.scheme in ("clickhouses", "https")
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or (8443 if secure else 8123),
        "username": parsed.username or "default",
        "password": parsed.password or "",
        "database": (parsed.path or "/default").lstrip("/") or "default",
        "secure": secure,
    }


@dataclass
class Warehouse:
    """A paired Postgres + ClickHouse connection.

    Connections are opened per request rather than pooled. At this traffic
    level that is the right trade: no stale-connection handling, no pool
    exhaustion, and a database restart cannot wedge the API.
    """

    dsn: str
    ch: dict[str, Any]

    @classmethod
    def from_env(cls) -> Warehouse:
        return cls(dsn=pg_dsn(), ch=ch_settings())

    def catalog(self):
        import psycopg

        return psycopg.connect(self.dsn)

    def bars(self):
        import clickhouse_connect

        return clickhouse_connect.get_client(**self.ch)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def health(wh: Warehouse) -> tuple[bool, int]:
    """(has_data, signal_count). 'Seeded' means at least one bar is present."""
    try:
        client = wh.bars()
    except Exception:
        return False, 0
    try:
        rows = client.query(f"SELECT count() FROM {BARS_VIEW}").result_rows
        bars = int(rows[0][0]) if rows else 0
    except Exception:
        return False, 0
    finally:
        client.close()

    if bars == 0:
        return False, 0

    try:
        with wh.catalog() as conn:
            signals = conn.execute("SELECT count(*) FROM signals").fetchone()[0]
    except Exception:
        signals = 0
    return True, int(signals)


def instrument_exists(wh: Warehouse, symbol: str) -> bool:
    with wh.catalog() as conn:
        row = conn.execute(
            "SELECT 1 FROM instruments WHERE symbol = %s", (symbol,)
        ).fetchone()
    return row is not None


def list_instruments(wh: Warehouse) -> dict:
    """Catalog identity joined to ClickHouse bar counts.

    The join happens here because neither store holds both halves: ClickHouse
    has no symbols, Postgres has no bars.
    """
    with wh.catalog() as conn:
        rows = conn.execute(
            """
            SELECT i.instrument_id, i.symbol, i.name, i.currency,
                   (SELECT count(*) FROM signals s WHERE s.instrument_id = i.instrument_id)
            FROM instruments i
            ORDER BY i.symbol
            """
        ).fetchall()

    if not rows:
        return {"total": 0, "items": []}

    client = wh.bars()
    try:
        counts_rows = client.query(
            f"SELECT instrument_id, count() FROM {BARS_VIEW} GROUP BY instrument_id"
        ).result_rows
    finally:
        client.close()
    bar_counts = {int(iid): int(n) for iid, n in counts_rows}

    items = [
        {
            "symbol": symbol,
            "name": name or symbol,
            "currency": currency,
            # Real instruments have no synthetic regime label. The field is
            # optional in the contract precisely so both datasets fit it.
            "regime_profile": None,
            "bar_count": bar_counts.get(int(instrument_id), 0),
            "signal_count": int(signal_count),
        }
        for instrument_id, symbol, name, currency, signal_count in rows
    ]
    return {"total": len(items), "items": items}


def get_prices(
    wh: Warehouse,
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    frequency: str = "1d",
) -> dict:
    with wh.catalog() as conn:
        row = conn.execute(
            "SELECT instrument_id FROM instruments WHERE symbol = %s", (symbol,)
        ).fetchone()
    if row is None:
        return {"total": 0, "items": []}
    instrument_id = int(row[0])

    clauses = ["instrument_id = %(iid)s", "frequency = %(frequency)s"]
    params: dict[str, Any] = {"iid": instrument_id, "frequency": frequency}
    if start:
        clauses.append("ts >= %(start)s")
        params["start"] = f"{start} 00:00:00"
    if end:
        clauses.append("ts <= %(end)s")
        params["end"] = f"{end} 23:59:59"

    client = wh.bars()
    try:
        rows = client.query(
            f"""
            SELECT ts, open, high, low, close, volume
              FROM {BARS_VIEW}
             WHERE {' AND '.join(clauses)}
             ORDER BY ts ASC
            """,
            parameters=params,
        ).result_rows
    finally:
        client.close()

    items = [
        {
            "symbol": symbol,
            "date": ts.date().isoformat(),
            "open": float(o),
            "high": float(h),
            "low": float(lo),
            "close": float(c),
            "volume": int(v),
        }
        for ts, o, h, lo, c, v in rows
    ]
    return {"total": len(items), "items": items}


def list_signals(
    wh: Warehouse,
    *,
    instrument: str | None = None,
    signal_type: str | None = None,
    direction: str | None = None,
    start: str | None = None,
    end: str | None = None,
    sort: str = "date_desc",
    limit: int = 200,
    offset: int = 0,
) -> dict:
    """Signals materialised from warehouse bars (see quantlab.signals.materialize)."""
    where: list[str] = []
    params: list[Any] = []
    if instrument is not None:
        where.append("i.symbol = %s")
        params.append(instrument)
    if signal_type is not None:
        where.append("r.rule_name = %s")
        params.append(signal_type)
    if direction is not None:
        where.append("s.direction = %s")
        params.append(direction)
    if start is not None:
        where.append("s.date >= %s")
        params.append(start)
    if end is not None:
        where.append("s.date <= %s")
        params.append(end)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    order = "ASC" if sort == "date_asc" else "DESC"

    with wh.catalog() as conn:
        total = conn.execute(
            f"""
            SELECT count(*)
              FROM signals s
              JOIN instruments  i USING (instrument_id)
              JOIN signal_rules r USING (rule_id)
            {where_sql}
            """,
            params,
        ).fetchone()[0]

        rows = conn.execute(
            f"""
            SELECT s.signal_id, i.symbol, s.date, r.rule_name, r.rule_version,
                   r.parameters, s.direction, s.trigger_values, s.data_window_end
              FROM signals s
              JOIN instruments  i USING (instrument_id)
              JOIN signal_rules r USING (rule_id)
            {where_sql}
             ORDER BY s.date {order}, i.symbol ASC, r.rule_name ASC
             LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        ).fetchall()

    items = [
        {
            "id": signal_id,
            "symbol": symbol,
            "date": date.isoformat(),
            "rule_name": rule_name,
            "rule_version": rule_version,
            "parameters": parameters,
            "direction": direction_value,
            "trigger_values": trigger_values,
            "data_window_end": window_end.isoformat(),
        }
        for (signal_id, symbol, date, rule_name, rule_version, parameters,
             direction_value, trigger_values, window_end) in rows
    ]
    return {"total": int(total), "items": items}


# ---------------------------------------------------------------------------
# Bars for signal computation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Bar:
    """Shape the signal rules expect: date plus OHLCV, ascending by date."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def iter_symbol_bars(
    wh: Warehouse, symbols: Sequence[str] | None = None, frequency: str = "1d"
) -> Iterator[tuple[str, int, list[Bar]]]:
    """Yield (symbol, instrument_id, bars) for signal materialisation."""
    query = "SELECT instrument_id, symbol FROM instruments"
    params: list[Any] = []
    if symbols:
        query += " WHERE symbol = ANY(%s)"
        params.append(list(symbols))
    query += " ORDER BY symbol"

    with wh.catalog() as conn:
        instruments = conn.execute(query, params).fetchall()

    if not instruments:
        return

    client = wh.bars()
    try:
        for instrument_id, symbol in instruments:
            rows = client.query(
                f"""
                SELECT ts, open, high, low, close, volume
                  FROM {BARS_VIEW}
                 WHERE instrument_id = %(iid)s AND frequency = %(frequency)s
                 ORDER BY ts ASC
                """,
                parameters={"iid": int(instrument_id), "frequency": frequency},
            ).result_rows
            bars = [
                Bar(
                    date=ts.date().isoformat(),
                    open=float(o),
                    high=float(h),
                    low=float(lo),
                    close=float(c),
                    volume=int(v),
                )
                for ts, o, h, lo, c, v in rows
            ]
            yield symbol, int(instrument_id), bars
    finally:
        client.close()


# ---------------------------------------------------------------------------
# What the experiment runner needs (feature 006)
# ---------------------------------------------------------------------------


def _instrument_ids(wh: Warehouse, symbols: list[str]) -> dict[str, int]:
    """Canonical symbol -> surrogate id.

    Resolution is by `instruments.symbol`, the canonical quantlab id, which is
    unique and stable. Vendor tickers -- the ones that get reused and
    reassigned -- live in `symbol_map` and are bound to a date range there,
    enforced by an exclusion constraint at ingest. The workbench never sees
    them, so no as-of resolution is needed on this path.
    """
    if not symbols:
        return {}
    with wh.catalog() as conn:
        rows = conn.execute(
            "SELECT symbol, instrument_id FROM instruments WHERE symbol = ANY(%s)",
            (list(symbols),),
        ).fetchall()
    return {symbol: int(instrument_id) for symbol, instrument_id in rows}


def load_bars_for(
    wh: Warehouse,
    symbols: list[str],
    start: str,
    end: str,
    frequency: str = "1d",
) -> dict[str, list[Bar]]:
    """Bars for several instruments across one window, keyed by symbol.

    Reads through the deduplicating view, never the raw table: collapsing
    happens at merge time on ClickHouse's own schedule, so a re-ingested range
    read straight from `price_bars` comes back doubled.
    """
    ids = _instrument_ids(wh, symbols)
    if not ids:
        return {}
    by_id = {instrument_id: symbol for symbol, instrument_id in ids.items()}

    client = wh.bars()
    try:
        rows = client.query(
            f"""
            SELECT instrument_id, ts, open, high, low, close, volume
              FROM {BARS_VIEW}
             WHERE instrument_id IN %(ids)s
               AND frequency = %(frequency)s
               AND ts >= %(start)s AND ts <= %(end)s
             ORDER BY instrument_id, ts ASC
            """,
            parameters={
                "ids": tuple(by_id),
                "frequency": frequency,
                "start": f"{start} 00:00:00",
                "end": f"{end} 23:59:59",
            },
        ).result_rows
    finally:
        client.close()

    out: dict[str, list[Bar]] = {}
    for instrument_id, ts, o, h, lo, c, v in rows:
        symbol = by_id[int(instrument_id)]
        out.setdefault(symbol, []).append(
            Bar(ts.date().isoformat(), float(o), float(h), float(lo), float(c), int(v))
        )
    return out


def earliest_bar_dates(
    wh: Warehouse, symbols: list[str], frequency: str = "1d"
) -> dict[str, str]:
    """First available bar per instrument, for warm-up coverage reporting."""
    ids = _instrument_ids(wh, symbols)
    if not ids:
        return {}
    by_id = {instrument_id: symbol for symbol, instrument_id in ids.items()}

    client = wh.bars()
    try:
        rows = client.query(
            f"""
            SELECT instrument_id, min(ts)
              FROM {BARS_VIEW}
             WHERE instrument_id IN %(ids)s AND frequency = %(frequency)s
             GROUP BY instrument_id
            """,
            parameters={"ids": tuple(by_id), "frequency": frequency},
        ).result_rows
    finally:
        client.close()

    return {by_id[int(iid)]: ts.date().isoformat() for iid, ts in rows}


def corporate_actions(wh: Warehouse, symbols: list[str], start: str, end: str) -> list[dict]:
    """Splits and dividends inside the window, for the selected instruments.

    Reported, never applied. Stored bars are unadjusted and the vendor's
    adjusted close is explicitly not authoritative, so a split inside a run's
    window makes the series jump in a way that is an artefact rather than a
    market move. Making it visible is what keeps a distorted result
    recognisable; rebuilding a point-in-time adjustment factor is its own
    feature.
    """
    ids = _instrument_ids(wh, symbols)
    if not ids:
        return []
    by_id = {instrument_id: symbol for symbol, instrument_id in ids.items()}

    with wh.catalog() as conn:
        rows = conn.execute(
            """
            SELECT instrument_id, ex_date, action_type, split_ratio, dividend
              FROM corporate_actions
             WHERE instrument_id = ANY(%s) AND ex_date >= %s AND ex_date <= %s
             ORDER BY ex_date, instrument_id
            """,
            (list(by_id), start, end),
        ).fetchall()

    return [
        {
            "instrument_id": int(instrument_id),
            "symbol": by_id[int(instrument_id)],
            "ex_date": ex_date.isoformat(),
            "action_type": action_type,
            "split_ratio": float(split_ratio) if split_ratio is not None else None,
            "dividend": float(dividend) if dividend is not None else None,
        }
        for instrument_id, ex_date, action_type, split_ratio, dividend in rows
    ]
