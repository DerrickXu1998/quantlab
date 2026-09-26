"""Read access to the real data warehouse: ClickHouse bars + Postgres catalog.

This is the API's half of the store. It deliberately does not import the
research library: the backend image's build context is ``backend/``, and the
API has no business carrying the provider stack. What it shares with the
ingest side is the schema, not the code.

No pandas here either -- the backend serves JSON, and raw rows are cheaper.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

# The screen below derives its ratios with the fundamental rules' own helpers
# rather than a second copy of them. This module has no other business knowing
# about quantlab.signals, and the dependency is worth the exception: two
# implementations of "unknown is not zero" is one that stops being maintained.
from quantlab.signals import fundamental as fundamental_rules
from quantlab.storage import facts
from quantlab.storage.pool import ClientPool, pool_config

DB_URL_ENV = "QUANTLAB_DB_URL"
CH_URL_ENV = "QUANTLAB_CH_URL"
#: The ClickHouse password when the URL carries none (a managed service's
#: secret kept out of the address). Postgres has libpq's own PGPASSWORD.
CH_PASSWORD_ENV = "QUANTLAB_CH_PASSWORD"

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
    """clickhouse[s]://user:pass@host:port/db -> clickhouse_connect kwargs.

    `clickhouses://` (or `?secure=true`) is TLS, defaulting to 8443 -- what a
    managed ClickHouse Cloud service speaks.
    """
    parsed = urlparse(url or os.environ.get(CH_URL_ENV, ""))
    query = parse_qs(parsed.query)
    secure = parsed.scheme in ("clickhouses", "https") or query.get("secure", [""])[0].lower() in (
        "1",
        "true",
        "yes",
    )
    # Percent-decoded: a managed service's generated password routinely holds
    # `@`, `/` or `%`, which only survive a URL encoded -- and urlparse hands
    # them back still encoded. With no password in the URL at all, it comes
    # from QUANTLAB_CH_PASSWORD, so the secret can live apart from the address.
    password = unquote(parsed.password) if parsed.password else os.environ.get(CH_PASSWORD_ENV, "")
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or (8443 if secure else 8123),
        "username": unquote(parsed.username) if parsed.username else "default",
        "password": password,
        "database": (parsed.path or "/default").lstrip("/") or "default",
        "secure": secure,
    }


@dataclass
class Warehouse:
    """A paired Postgres + ClickHouse connection, both pooled.

    Connections were previously opened per request. That was the right trade
    for one long-lived process beside its databases, but it inverts on a
    platform running several instances: connection cost is paid per request
    (measured at 9.86 ms for Postgres and 6.76 ms for ClickHouse, against
    queries costing 0.16 ms and 0.98 ms), and total demand grows with instance
    count against a fixed database budget. See feature 007.

    Both pools are created lazily on first use, never at construction, so
    building a Warehouse still touches no network and the application starts
    with every database unreachable.
    """

    dsn: str
    ch: dict[str, Any]
    _catalog_pool: Any = field(default=None, init=False, repr=False, compare=False)
    _bars_pool: ClientPool | None = field(default=None, init=False, repr=False, compare=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    @classmethod
    def from_env(cls) -> Warehouse:
        return cls(dsn=pg_dsn(), ch=ch_settings())

    def _ensure_catalog_pool(self):
        # psycopg_pool rather than a hand-rolled one: its connection() context
        # manager commits on clean exit, rolls back on error, and resets session
        # state before returning the connection. Reimplementing that is how a
        # half-finished transaction leaks into somebody else's request.
        if self._catalog_pool is None:
            with self._lock:
                if self._catalog_pool is None:
                    from psycopg_pool import ConnectionPool

                    config = pool_config()
                    self._catalog_pool = ConnectionPool(
                        self.dsn,
                        min_size=0,
                        max_size=config.pg_max,
                        timeout=config.timeout,
                        # Discard a connection that died while parked -- an idle
                        # timeout, or a database restart -- rather than serve it.
                        check=ConnectionPool.check_connection,
                        open=False,
                    )
                    self._catalog_pool.open()
        return self._catalog_pool

    def _ensure_bars_pool(self) -> ClientPool:
        if self._bars_pool is None:
            with self._lock:
                if self._bars_pool is None:
                    import clickhouse_connect

                    config = pool_config()

                    def factory():
                        return clickhouse_connect.get_client(**self.ch)

                    self._bars_pool = ClientPool(
                        factory, max_size=config.ch_max, timeout=config.timeout
                    )
        return self._bars_pool

    @contextmanager
    def catalog(self) -> Iterator[Any]:
        """Check out a catalog connection; returned on every exit path."""
        with self._ensure_catalog_pool().connection() as conn:
            yield conn

    @contextmanager
    def bars(self) -> Iterator[Any]:
        """Check out a bar-store client; returned on every exit path.

        A pool of clients rather than one shared client: clickhouse_connect's
        Client carries no lock and mutable per-instance state, so sharing it
        across the API's handler threads would be a data race.
        """
        with self._ensure_bars_pool().acquire() as client:
            yield client

    def close(self) -> None:
        """Release both pools. Idempotent; used at shutdown and in tests."""
        with self._lock:
            if self._catalog_pool is not None:
                self._catalog_pool.close()
                self._catalog_pool = None
            if self._bars_pool is not None:
                self._bars_pool.close()
                self._bars_pool = None


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def health(wh: Warehouse) -> tuple[bool, int]:
    """(has_data, signal_count). 'Seeded' means at least one bar is present."""
    try:
        with wh.bars() as client:
            rows = client.query(f"SELECT count() FROM {BARS_VIEW}").result_rows
            bars = int(rows[0][0]) if rows else 0
    except Exception:
        return False, 0

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


def validate_symbols(wh: Warehouse, symbols: Sequence[str]) -> list[str]:
    """The requested symbols the catalog does not know, in request order.

    One indexed lookup against ``instruments``. Run creation used to answer
    this through :func:`list_instruments`, which joins the whole catalog to a
    full GROUP BY over the bar store -- several seconds of ClickHouse work to
    check a handful of tickers, paid on every run request.
    """
    wanted = list(symbols)
    if not wanted:
        return []
    with wh.catalog() as conn:
        rows = conn.execute(
            "SELECT symbol FROM instruments WHERE symbol = ANY(%s)", (wanted,)
        ).fetchall()
    known = {row[0] for row in rows}
    return [symbol for symbol in wanted if symbol not in known]


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

    with wh.bars() as client:
        counts_rows = client.query(
            f"SELECT instrument_id, count() FROM {BARS_VIEW} GROUP BY instrument_id"
        ).result_rows
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

    with wh.bars() as client:
        rows = client.query(
            f"""
            SELECT ts, open, high, low, close, volume
              FROM {BARS_VIEW}
             WHERE {' AND '.join(clauses)}
             ORDER BY ts ASC
            """,
            parameters=params,
        ).result_rows

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
    """Yield (symbol, instrument_id, bars) for signal materialisation.

    One bar-store query for the whole selection -- the load_bars_for pattern --
    rather than one per instrument: over the full catalog that is the
    difference between one round trip and several hundred.
    """
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

    with wh.bars() as client:
        rows = client.query(
            f"""
            SELECT instrument_id, ts, open, high, low, close, volume
              FROM {BARS_VIEW}
             WHERE instrument_id IN %(ids)s AND frequency = %(frequency)s
             ORDER BY instrument_id, ts ASC
            """,
            parameters={
                "ids": tuple(int(instrument_id) for instrument_id, _ in instruments),
                "frequency": frequency,
            },
        ).result_rows

    grouped: dict[int, list[Bar]] = {}
    for instrument_id, ts, o, h, lo, c, v in rows:
        grouped.setdefault(int(instrument_id), []).append(
            Bar(
                date=ts.date().isoformat(),
                open=float(o),
                high=float(h),
                low=float(lo),
                close=float(c),
                volume=int(v),
            )
        )

    for instrument_id, symbol in instruments:
        # Every catalogued instrument is yielded, with an empty list when it
        # has no bars -- the materialiser depends on seeing it either way.
        yield symbol, int(instrument_id), grouped.get(int(instrument_id), [])


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

    with wh.bars() as client:
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

    with wh.bars() as client:
        rows = client.query(
            f"""
            SELECT instrument_id, min(ts)
              FROM {BARS_VIEW}
             WHERE instrument_id IN %(ids)s AND frequency = %(frequency)s
             GROUP BY instrument_id
            """,
            parameters={"ids": tuple(by_id), "frequency": frequency},
        ).result_rows

    return {by_id[int(iid)]: ts.date().isoformat() for iid, ts in rows}


def ingest_run_ids(
    wh: Warehouse, symbols: list[str], start: str, end: str, frequency: str = "1d"
) -> list[int]:
    """The ingest runs behind the bars in this window.

    Every bar carries run_id, which doubles as the ReplacingMergeTree version:
    a re-ingest writes rows with a higher run_id that supersede the earlier
    copies. Recording these is what makes a re-ingest distinguishable from the
    original run, in the case where every input the researcher chose is
    identical but the underlying data changed.
    """
    ids = _instrument_ids(wh, symbols)
    if not ids:
        return []

    with wh.bars() as client:
        rows = client.query(
            f"""
            SELECT DISTINCT run_id
              FROM {BARS_VIEW}
             WHERE instrument_id IN %(ids)s
               AND frequency = %(frequency)s
               AND ts >= %(start)s AND ts <= %(end)s
             ORDER BY run_id
            """,
            parameters={
                "ids": tuple(ids.values()),
                "frequency": frequency,
                "start": f"{start} 00:00:00",
                "end": f"{end} 23:59:59",
            },
        ).result_rows
    return [int(run_id) for (run_id,) in rows]


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


# ---------------------------------------------------------------------------
# Point-in-time fundamentals (docs/FUNDAMENTALS.md)
# ---------------------------------------------------------------------------


def load_facts_for(
    wh: Warehouse,
    symbols: list[str],
    concepts: list[str],
    start: str,
    end: str,
) -> dict[str, facts.FactSeries]:
    """Point-in-time fundamentals for a run, keyed by symbol.

    One query for the whole run, not one per symbol per rule: a strategy with
    three fundamental components over forty names would otherwise issue a
    hundred and twenty round trips to answer a question the index can answer
    once. Measured on the live warehouse, forty instruments across ten concepts
    is 31,844 rows in 78 ms via ``fundamentals_pit_idx``, whose three columns
    are exactly the three predicates below.

    **There is deliberately no lower bound on ``filed_at``.** ``start`` is the
    warm-up start, and the figure in force on that morning was filed before it
    -- often a year before. Bounding the scan by ``start`` would blank the
    first year of every window, and blank in the direction that hides itself:
    the gates would read shut rather than wrong, so nothing would look broken.
    ``start`` is used only to report which names were already covered when the
    window opened.

    The ``filed_at <= end`` bound is not an optimisation. It is the rule: a run
    ending in 2020 must not see a restatement filed in 2024, even though the
    series is only ever read at dates inside the window.
    """
    ids = _instrument_ids(wh, symbols)
    if not ids or not concepts:
        return {}
    by_id = {instrument_id: symbol for symbol, instrument_id in ids.items()}

    with wh.catalog() as conn:
        rows = conn.execute(
            """
            SELECT instrument_id, concept, period_start, period_end, filed_at,
                   value, tag, run_id
              FROM fundamentals
             WHERE instrument_id = ANY(%s)
               AND concept = ANY(%s)
               AND filed_at <= %s
             ORDER BY instrument_id, concept, filed_at, period_end,
                      period_start NULLS LAST, tag, value
            """,
            (list(by_id), sorted(set(concepts)), end),
        ).fetchall()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        instrument_id, concept, period_start, period_end, filed_at, value, tag, run_id = row
        grouped.setdefault(by_id[int(instrument_id)], []).append(
            {
                "concept": concept,
                "period_start": period_start,
                "period_end": period_end,
                "filed_at": filed_at,
                "value": value,
                "tag": tag,
                "run_id": run_id,
            }
        )
    return {symbol: facts.build_series(items) for symbol, items in grouped.items()}


def facts_as_of(
    wh: Warehouse, symbol: str, as_of: str, concepts: list[str] | None = None
) -> list[dict[str, Any]]:
    """What was knowable about one instrument on one date.

    The inspector's query (docs/FUNDAMENTALS.md §6). Built through the same
    :func:`load_facts_for` path rather than a second hand-written SQL rule, so
    the screen that exists to make the point-in-time rule believable cannot
    disagree with the rule the backtest actually ran.
    """
    wanted = sorted(concepts or facts.KNOWN_CONCEPTS)
    series = load_facts_for(wh, [symbol], wanted, as_of, as_of)
    found = series.get(symbol)
    if found is None:
        return []
    # ``as_of`` returns exactly the row the rule selects for each concept, so
    # every row here is in force. Saying so explicitly saves the inspector from
    # re-deriving a selection the server has already made.
    return [
        {**fact.to_dict(as_of), "in_force": True}
        for fact in found.as_of(as_of, concepts=wanted)
    ]


# ---------------------------------------------------------------------------
# Coverage, stated before anything is run (docs/RESEARCH.md §2)
# ---------------------------------------------------------------------------


def fundamentals_coverage(wh: Warehouse) -> dict[str, Any]:
    """Which instruments and concepts have any filings at all.

    Measured on the live warehouse: 644 catalogued instruments, 580 with some
    fundamentals, and per-concept coverage varying more than two to one --
    ``net_income`` on 468 names against ``gross_profit`` on 237. Averaging that
    away is how a gross-margin screen over 237 names reads as "few companies
    qualified" when the truth is "most were never measured"
    (docs/FUNDAMENTALS.md §5.1).

    Counted rather than hardcoded: those are the figures the warehouse held on
    2026-09-21, and an ingest changes them.

    One grouped scan rather than one per concept -- 5.7M rows in, 7,049 out at
    1.06 s measured -- with the per-concept rollup done here in arithmetic. The
    caller reads this once and holds it: it is a property of the warehouse, not
    of whatever is being edited.
    """
    with wh.catalog() as conn:
        instruments = [
            symbol
            for (symbol,) in conn.execute(
                "SELECT symbol FROM instruments ORDER BY symbol"
            ).fetchall()
        ]
        rows = conn.execute(
            """
            SELECT f.concept, i.symbol, min(f.filed_at), max(f.filed_at)
              FROM fundamentals f
              JOIN instruments  i USING (instrument_id)
             -- 88.8% of the table carries an empty concept: the ingest kept the
             -- raw XBRL tag and never mapped it. Counting those rows would
             -- claim coverage for something no rule can read (RESEARCH.md §2).
             WHERE f.concept <> ''
             GROUP BY f.concept, i.symbol
            """
        ).fetchall()

    by_concept: dict[str, dict[str, Any]] = {}
    with_facts: set[str] = set()
    for concept, symbol, first_filed, last_filed in rows:
        with_facts.add(symbol)
        entry = by_concept.setdefault(
            concept, {"symbols": [], "first": None, "last": None}
        )
        entry["symbols"].append(symbol)
        first, last = _iso_date(first_filed), _iso_date(last_filed)
        if entry["first"] is None or (first is not None and first < entry["first"]):
            entry["first"] = first
        if entry["last"] is None or (last is not None and last > entry["last"]):
            entry["last"] = last

    concepts = [
        {
            "concept": concept,
            "instruments": len(entry["symbols"]),
            "first_filed": entry["first"],
            "last_filed": entry["last"],
            # Enumerated, so a coverage warning can name the concept a strategy
            # is missing instead of falling back to "this name has no
            # fundamentals at all", which is a different and usually false claim.
            "symbols": sorted(entry["symbols"]),
        }
        for concept, entry in sorted(by_concept.items())
    ]
    return {
        "instruments_total": len(instruments),
        "instruments_with_facts": len(with_facts),
        "concepts": concepts,
        "symbols_with_facts": sorted(with_facts),
        "symbols_without_facts": [s for s in instruments if s not in with_facts],
    }


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    return value[:10] if isinstance(value, str) else value.isoformat()[:10]


# ---------------------------------------------------------------------------
# Universes (docs/RESEARCH.md §2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniverseSnapshot:
    """One dated membership list, and the date it was actually captured.

    ``as_of`` is the snapshot's own date, never the date that was asked for. A
    screen run on 2026-09-21 against a list captured on 2026-09-20 is running
    over yesterday's members, and reporting which is the difference between a
    reconstructed universe and today's survivors wearing a historical label.
    """

    universe: str
    as_of: str
    #: symbol -> display name. Carried together because a screen needs both and
    #: the membership join already has them in hand.
    members: dict[str, str] = field(default_factory=dict)

    @property
    def symbols(self) -> list[str]:
        return sorted(self.members)


def list_universes(wh: Warehouse) -> dict[str, Any]:
    """Every snapshot of every universe, newest first.

    One row per *snapshot* rather than per universe: membership is dated, and
    collapsing the dates would offer a list the caller cannot actually ask for.
    ``size`` is counted from ``universe_members`` rather than read from
    ``member_count``, which is a number written at ingest rather than the rows
    themselves.
    """
    with wh.catalog() as conn:
        rows = conn.execute(
            """
            SELECT s.universe, s.snapshot_date, count(m.instrument_id)
              FROM universe_snapshots s
              LEFT JOIN universe_members m USING (snapshot_id)
             GROUP BY s.universe, s.snapshot_date
             ORDER BY s.universe ASC, s.snapshot_date DESC
            """
        ).fetchall()
    items = [
        {"name": universe, "as_of": snapshot_date.isoformat(), "size": int(size)}
        for universe, snapshot_date, size in rows
    ]
    return {"total": len(items), "items": items}


def resolve_universe(wh: Warehouse, universe: str, as_of: str) -> UniverseSnapshot | None:
    """The membership of ``universe`` as it stood on ``as_of``, or None.

    The newest snapshot captured on or before the date, which is the rule the
    fundamentals follow and for the same reason: screening a past date against
    today's membership is survivorship bias, and it flatters the result rather
    than breaking it, so nothing announces it.

    None means no snapshot reaches that far back. The caller distinguishes "no
    such universe" from "no such date" because those need different answers,
    and neither is an empty result.
    """
    with wh.catalog() as conn:
        row = conn.execute(
            """
            SELECT snapshot_id, snapshot_date
              FROM universe_snapshots
             WHERE universe = %s AND snapshot_date <= %s
             ORDER BY snapshot_date DESC
             LIMIT 1
            """,
            (universe, as_of),
        ).fetchone()
        if row is None:
            return None
        snapshot_id, snapshot_date = row
        members = conn.execute(
            """
            SELECT i.symbol, i.name
              FROM universe_members m
              JOIN instruments i USING (instrument_id)
             WHERE m.snapshot_id = %s
            """,
            (snapshot_id,),
        ).fetchall()
    return UniverseSnapshot(
        universe=universe,
        as_of=snapshot_date.isoformat(),
        members={symbol: name or symbol for symbol, name in members},
    )


# ---------------------------------------------------------------------------
# One company (docs/RESEARCH.md §1c)
# ---------------------------------------------------------------------------


def company_overview(wh: Warehouse, symbol: str, as_of: str) -> dict[str, Any] | None:
    """Everything filed about one name, composed rather than newly sourced.

    The object the destination was missing: identity, the price bounds, the
    accounts as they stood on ``as_of``, which concepts this name has never
    filed, and which rules have fired on it. None when the symbol is not in the
    catalogue.

    The facts come through :func:`facts_as_of`, which comes through
    :func:`load_facts_for` -- the same path the backtest takes. A company page
    built on a second point-in-time query would eventually disagree with a run
    over the same name, and the disagreement would be invisible.
    """
    with wh.catalog() as conn:
        row = conn.execute(
            """
            SELECT instrument_id, symbol, name, exchange, currency, sector
              FROM instruments WHERE symbol = %s
            """,
            (symbol,),
        ).fetchone()
        if row is None:
            return None
        instrument_id, symbol, name, exchange, currency, sector = row

        # Every concept this name has *ever* filed, unbounded by as_of. A hole
        # in coverage and a figure that is merely stale are different facts
        # about a company, and only the first is permanent -- so the second
        # must not be reported as the first.
        filed = {
            concept
            for (concept,) in conn.execute(
                """
                SELECT DISTINCT concept FROM fundamentals
                 WHERE instrument_id = %s AND concept <> ''
                """,
                (int(instrument_id),),
            ).fetchall()
        }
        # Bounded by as_of, like the bars and the facts beside it.
        #
        # Without the bound this read is the one incoherent thing on the page:
        # asked for CAT on 2024-06-30 it returned accounts filed by 2024-05-01,
        # a chart cut at 2024-06-30, and a last signal dated 2026-09-01. A
        # destination whose whole claim is that it shows what was knowable on a
        # date cannot show a signal from two years after it. The count moves
        # with the date for the same reason -- "580 signals" as of 2024 is not
        # the same fact as "580 signals" today.
        signal_rows = conn.execute(
            """
            SELECT r.rule_name, count(*), max(s.date),
                   (array_agg(s.direction ORDER BY s.date DESC, s.signal_id DESC))[1]
              FROM signals s
              JOIN signal_rules r USING (rule_id)
             WHERE s.instrument_id = %s
               AND s.date <= %s
             GROUP BY r.rule_name
             ORDER BY count(*) DESC, r.rule_name ASC
            """,
            (int(instrument_id), as_of),
        ).fetchall()

    bounds = _bar_bounds(wh, int(instrument_id), as_of)
    company_facts = facts_as_of(wh, symbol, as_of)
    signals = [
        {
            "rule_name": rule_name,
            "count": int(count),
            "last_date": last_date.isoformat(),
            "last_direction": last_direction,
        }
        for rule_name, count, last_date, last_direction in signal_rows
    ]
    return {
        "symbol": symbol,
        "name": name or symbol,
        "exchange": exchange,
        "currency": currency,
        # Blank on 607 of 644 names. Passed through as filed rather than
        # guessed: an invented sector would be indistinguishable from a real
        # one and would license a peer comparison the catalogue cannot support
        # (docs/RESEARCH.md §2).
        "sector": sector,
        "as_of": as_of,
        **bounds,
        "facts": company_facts,
        "concepts_available": [fact["concept"] for fact in company_facts],
        "concepts_missing": sorted(facts.KNOWN_CONCEPTS - filed),
        "signals": signals,
        "signal_total": sum(item["count"] for item in signals),
    }


def _bar_bounds(
    wh: Warehouse, instrument_id: int, as_of: str, frequency: str = "1d"
) -> dict[str, Any]:
    """First bar, last bar, and the close that was quoted on ``as_of``.

    The bounds describe the whole series, because that is what the price panel
    can draw. The close is taken on or before the as-of date, because it sits
    beside accounts resolved to that same date -- a price from after it would
    make the one number on the page that is not point-in-time the one every
    ratio is built from.
    """
    with wh.bars() as client:
        rows = client.query(
            f"""
            SELECT count(), min(ts), max(ts),
                   argMaxIf(close, ts, ts <= %(as_of)s),
                   countIf(ts <= %(as_of)s)
              FROM {BARS_VIEW}
             WHERE instrument_id = %(iid)s AND frequency = %(frequency)s
            """,
            parameters={
                "iid": instrument_id,
                "frequency": frequency,
                "as_of": f"{as_of} 23:59:59",
            },
        ).result_rows
    # An aggregate over no rows still answers: min(ts) comes back as the epoch
    # rather than as null, so the row count is what says whether there is a
    # series at all.
    if not rows or not int(rows[0][0]):
        return {"first_bar": None, "last_bar": None, "last_close": None}
    _, first_ts, last_ts, close, quoted = rows[0]
    return {
        "first_bar": first_ts.date().isoformat(),
        "last_bar": last_ts.date().isoformat(),
        # argMaxIf over an empty selection returns 0.0, which would read as a
        # free company rather than as one that had not yet listed.
        "last_close": float(close) if int(quoted) else None,
    }


# ---------------------------------------------------------------------------
# The screen (docs/RESEARCH.md §4)
# ---------------------------------------------------------------------------
#
# A screen is a cross-section of the same ratios the fundamental rules gate on,
# read on one date instead of on every bar. The arithmetic is therefore the
# rules' own, imported rather than written again: a screen calling a name cheap
# while a backtest's pe-filter holds its gate shut is the failure this whole
# feature exists to avoid, and it would be entirely silent.

#: metric -> the filed concepts it cannot be computed without.
#:
#: These are the ``requires_facts`` of the rules the metrics mirror: `pe` needs
#: what `pe-filter` needs, `roe` what `profitability-filter` needs, and so on.
#: A price is not listed because it is not a filed concept -- it comes from the
#: bars, and a name with no bar simply has no market cap.
SCREEN_METRIC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "pe": ("net_income", "shares_outstanding"),
    "pb": ("equity", "shares_outstanding"),
    "roe": ("net_income", "equity"),
    "leverage": ("long_term_debt", "equity"),
    "net_margin": ("net_income", "revenue"),
    "gross_margin": ("gross_profit", "revenue"),
    "current_ratio": ("current_assets", "current_liabilities"),
}

#: The canonical order metrics are reported in, whatever order they were asked
#: for -- so two screens of the same metrics produce the same columns.
SCREEN_METRICS: tuple[str, ...] = tuple(SCREEN_METRIC_CONCEPTS)

#: How many names' facts are resolved at once.
#:
#: The whole 598-name universe across eight concepts is 348,102 rows in 857 ms
#: against ``fundamentals_pit_idx`` -- the query is fine. What is not fine is
#: holding every restatement of every period for 598 names in memory at once
#: just to read one date out of each. Chunking bounds that without touching the
#: point-in-time path: each chunk is still resolved by ``load_facts_for``, and
#: the answer for a name does not depend on who else was in its chunk.
SCREEN_CHUNK = 150


def _screen_values(
    metrics: Sequence[str],
    series: facts.FactSeries | None,
    close: float | None,
    as_of: str,
    max_stale_days: int,
) -> dict[str, float | None]:
    """Every requested ratio for one name, with None meaning *unknown*.

    None is load-bearing in both directions. A missing filing is not a zero,
    and a non-positive denominator is not an extreme ratio: a company with
    negative equity has no price-to-book, and dividing anyway would hand it a
    large negative multiple that sorts as the cheapest name on the screen
    (docs/FUNDAMENTALS.md §5.5). Both refusals live in ``_ratio``, which is the
    rules' own.
    """
    ratio = fundamental_rules._ratio

    def value(concept: str) -> float | None:
        return fundamental_rules._value(series, concept, as_of, max_stale_days)

    cap: float | None = None
    if series is not None and close is not None:
        # A one-bar list because `_market_cap` reads only `bars[i].close`.
        # Calling it rather than multiplying here is the point: the screen's
        # market cap is the rule's market cap, its guard against a
        # non-positive share count included.
        cap = fundamental_rules._market_cap(
            [Bar(as_of, close, close, close, close, 0)], 0, series, as_of, max_stale_days
        )

    computed: dict[str, float | None] = {
        "pe": ratio(cap, value("net_income")),
        "pb": ratio(cap, value("equity")),
        "roe": ratio(value("net_income"), value("equity")),
        "leverage": ratio(value("long_term_debt"), value("equity")),
        "net_margin": ratio(value("net_income"), value("revenue")),
        "gross_margin": ratio(value("gross_profit"), value("revenue")),
        "current_ratio": ratio(value("current_assets"), value("current_liabilities")),
    }
    # Six places is past any of these ratios' meaningful precision and keeps
    # float64 repr noise out of the payload (docs/RESEARCH.md §1e).
    return {
        metric: None if computed[metric] is None else round(computed[metric], 6)
        for metric in metrics
        if metric in computed
    }


def _last_closes(
    wh: Warehouse, symbols: list[str], as_of: str, frequency: str = "1d"
) -> dict[str, float]:
    """The close each name last traded at on or before ``as_of``.

    Bounded by the as-of date for the same reason the facts are: a screen whose
    accounts are point-in-time and whose prices are current is a look-ahead in
    the one input every valuation ratio divides by.
    """
    ids = _instrument_ids(wh, symbols)
    if not ids:
        return {}
    by_id = {instrument_id: symbol for symbol, instrument_id in ids.items()}
    with wh.bars() as client:
        rows = client.query(
            f"""
            SELECT instrument_id, argMax(close, ts)
              FROM {BARS_VIEW}
             WHERE instrument_id IN %(ids)s
               AND frequency = %(frequency)s
               AND ts <= %(as_of)s
             GROUP BY instrument_id
            """,
            parameters={
                "ids": tuple(by_id),
                "frequency": frequency,
                "as_of": f"{as_of} 23:59:59",
            },
        ).result_rows
    return {by_id[int(iid)]: float(close) for iid, close in rows}


def screen(
    wh: Warehouse,
    *,
    universe: str,
    as_of: str,
    metrics: Sequence[str],
    constraints: Sequence[tuple[str, float | None, float | None]] = (),
    sort_by: str | None = None,
    descending: bool = False,
    limit: int = 100,
    max_stale_days: int = fundamental_rules.DEFAULT_MAX_STALE_DAYS,
) -> dict[str, Any] | None:
    """Rank a named universe by filed ratios, as of a date. None if unresolved.

    ``universe`` is not a convenience. ``fundamentals_pit_idx`` is
    ``(instrument_id, concept, filed_at)`` and leads with the instrument, so a
    screen that names none of them cannot use it: measured, an unbounded eight
    concept scan is 6,700 ms of parallel sequential scan against 857 ms of
    index scan once the instruments are named (docs/RESEARCH.md §2). Research
    also happens *within* a list, so the constraint and the product agree.

    The two exclusion counters are the point of the response. "Failed the
    filter" and "was never measured" look identical in a short result table,
    and one of them is a statement about companies while the other is a
    statement about the warehouse.
    """
    snapshot = resolve_universe(wh, universe, as_of)
    if snapshot is None:
        return None

    wanted = [metric for metric in SCREEN_METRICS if metric in set(metrics)]
    concepts = sorted({c for metric in wanted for c in SCREEN_METRIC_CONCEPTS[metric]})
    symbols = snapshot.symbols
    closes = _last_closes(wh, symbols, as_of)

    values: dict[str, dict[str, float | None]] = {}
    for start in range(0, len(symbols), SCREEN_CHUNK):
        chunk = symbols[start : start + SCREEN_CHUNK]
        series_by_symbol = load_facts_for(wh, chunk, concepts, as_of, as_of)
        for symbol in chunk:
            values[symbol] = _screen_values(
                wanted, series_by_symbol.get(symbol), closes.get(symbol), as_of,
                max_stale_days,
            )

    kept: list[str] = []
    excluded_by_constraint = 0
    excluded_unmeasured = 0
    for symbol in symbols:
        row = values[symbol]
        # Unmeasured is checked first and counted separately: a name with no
        # filed equity has not failed a leverage test, it was never given one.
        if any(row.get(metric) is None for metric, _, _ in constraints):
            excluded_unmeasured += 1
        elif any(
            (low is not None and row[metric] < low)
            or (high is not None and row[metric] > high)
            for metric, low, high in constraints
        ):
            excluded_by_constraint += 1
        else:
            kept.append(symbol)

    ordered = _rank(kept, values, sort_by, descending)
    return {
        "as_of": as_of,
        "universe": snapshot.universe,
        "universe_size": len(symbols),
        "rows": [
            {"symbol": symbol, "name": snapshot.members[symbol], "values": values[symbol]}
            for symbol in ordered[:limit]
        ],
        "coverage": [
            {
                "metric": metric,
                "measured": sum(1 for row in values.values() if row.get(metric) is not None),
                "universe": len(symbols),
                "requires": list(SCREEN_METRIC_CONCEPTS[metric]),
            }
            for metric in wanted
        ],
        "sort_by": sort_by,
        "excluded_by_constraint": excluded_by_constraint,
        "excluded_unmeasured": excluded_unmeasured,
    }


def _rank(
    symbols: list[str],
    values: dict[str, dict[str, float | None]],
    sort_by: str | None,
    descending: bool,
) -> list[str]:
    """Order the survivors, unmeasured names last and ties broken by symbol.

    An unmeasured name never sorts to the top of a ranking in either
    direction: a null is not a very small number, and putting it first on an
    ascending P/E screen would present the names nothing is known about as the
    cheapest ones on the page.
    """
    if sort_by is None:
        return sorted(symbols)
    measured = [s for s in symbols if values[s].get(sort_by) is not None]
    unmeasured = [s for s in symbols if values[s].get(sort_by) is None]
    sign = -1.0 if descending else 1.0
    # The symbol tiebreak stays ascending either way, so the same screen always
    # answers in the same order (Constitution VI).
    measured.sort(key=lambda s: (sign * values[s][sort_by], s))
    return measured + sorted(unmeasured)
