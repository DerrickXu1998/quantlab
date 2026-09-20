"""Catalog writes: identity, provenance, universe history, corporate actions.

All Postgres. No function here commits -- the caller owns the transaction, so
a catalog update lands atomically or not at all.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Mapping, Sequence

import pandas as pd

from ..schema import Currency, Security

log = logging.getLogger(__name__)

# Currencies quoted in minor units, and what they normalise to.
_MAJOR_UNIT = {Currency.GBX: Currency.GBP}


def storage_currency(quote: Currency) -> Currency:
    """The currency values are stored in, given what the vendor quoted."""
    return _MAJOR_UNIT.get(quote, quote)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def ensure_instruments(
    conn,
    securities: Mapping[str, Security],
    quote_currencies: Mapping[str, Currency] | None = None,
) -> dict[str, int]:
    """Upsert instruments, returning symbol -> instrument_id.

    Reference fields are filled in only when the incoming record actually
    carries them: a later ingest from a thinner source must not blank out
    identifiers an earlier richer one supplied.
    """
    quote_currencies = quote_currencies or {}
    if not securities:
        return {}

    rows = []
    for symbol, sec in securities.items():
        quote = quote_currencies.get(symbol, sec.currency)
        rows.append(
            {
                "symbol": symbol,
                "name": sec.name or "",
                "exchange": sec.exchange or "",
                "country": sec.country or "",
                "currency": storage_currency(quote).value,
                "quote_currency": quote.value,
                "sector": sec.sector or "",
                "industry": sec.industry or "",
                "isin": sec.isin or "",
                "sedol": sec.sedol or "",
                "cik": sec.cik or "",
                "company_number": sec.company_number or "",
                "figi": sec.figi or "",
                "meta": json.dumps(dict(sec.meta or {}), sort_keys=True),
            }
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO instruments (
                symbol, name, exchange, country, currency, quote_currency,
                sector, industry, isin, sedol, cik, company_number, figi, meta
            ) VALUES (
                %(symbol)s, %(name)s, %(exchange)s, %(country)s, %(currency)s,
                %(quote_currency)s, %(sector)s, %(industry)s, %(isin)s, %(sedol)s,
                %(cik)s, %(company_number)s, %(figi)s, %(meta)s::jsonb
            )
            ON CONFLICT (symbol) DO UPDATE SET
                name           = COALESCE(NULLIF(EXCLUDED.name, ''),           instruments.name),
                exchange       = COALESCE(NULLIF(EXCLUDED.exchange, ''),       instruments.exchange),
                country        = COALESCE(NULLIF(EXCLUDED.country, ''),        instruments.country),
                currency       = EXCLUDED.currency,
                quote_currency = EXCLUDED.quote_currency,
                sector         = COALESCE(NULLIF(EXCLUDED.sector, ''),         instruments.sector),
                industry       = COALESCE(NULLIF(EXCLUDED.industry, ''),       instruments.industry),
                isin           = COALESCE(NULLIF(EXCLUDED.isin, ''),           instruments.isin),
                sedol          = COALESCE(NULLIF(EXCLUDED.sedol, ''),          instruments.sedol),
                cik            = COALESCE(NULLIF(EXCLUDED.cik, ''),            instruments.cik),
                company_number = COALESCE(NULLIF(EXCLUDED.company_number, ''), instruments.company_number),
                figi           = COALESCE(NULLIF(EXCLUDED.figi, ''),           instruments.figi)
            """,
            rows,
        )

    return instrument_ids(conn, list(securities))


def instrument_ids(conn, symbols: Sequence[str]) -> dict[str, int]:
    """symbol -> instrument_id for symbols already present."""
    if not symbols:
        return {}
    rows = conn.execute(
        "SELECT symbol, instrument_id FROM instruments WHERE symbol = ANY(%s)",
        (list(symbols),),
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def symbols_for_ids(conn, ids: Sequence[int]) -> dict[int, str]:
    """instrument_id -> symbol. Used to re-label ClickHouse results."""
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT instrument_id, symbol FROM instruments WHERE instrument_id = ANY(%s)",
        (list(ids),),
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def map_vendor_symbols(
    conn,
    source: str,
    mapping: Mapping[str, str],
    ids: Mapping[str, int],
) -> int:
    """Record which vendor ticker served which instrument.

    Existing mappings are left alone -- on a re-run that is the normal case,
    and the exclusion constraint would reject a duplicate anyway.
    """
    rows = [
        {"instrument_id": ids[symbol], "source": source, "vendor_symbol": vendor}
        for symbol, vendor in mapping.items()
        if symbol in ids
    ]
    if not rows:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO symbol_map (instrument_id, source, vendor_symbol)
            SELECT %(instrument_id)s, %(source)s, %(vendor_symbol)s
            WHERE NOT EXISTS (
                SELECT 1 FROM symbol_map m
                 WHERE m.source = %(source)s
                   AND m.vendor_symbol = %(vendor_symbol)s
                   AND m.instrument_id = %(instrument_id)s
            )
            """,
            rows,
        )
    return len(rows)


def record_figi_mappings(
    conn,
    mappings: Mapping[str, Mapping[str, Any]],
    ids: Mapping[str, int],
    *,
    source: str = "openfigi",
) -> int:
    """Record OpenFIGI mapping results for catalog instruments.

    ``mappings``: symbol -> the best entry OpenFIGI returned for it. The FIGI
    lands in the two places join paths already read -- the ``instruments.figi``
    column and a ``symbol_map`` row under ``source='openfigi'`` -- while the
    rest of the payload (composite FIGI, name, exchange code, market sector,
    security type) folds into ``meta['openfigi']``. As with
    ``ensure_instruments``, a mapping never blanks an existing FIGI.
    """
    import datetime as dt

    rows = []
    figi_by_symbol: dict[str, str] = {}
    for symbol, entry in mappings.items():
        if symbol not in ids:
            continue
        figi = str(entry.get("figi") or "")
        if figi:
            figi_by_symbol[symbol] = figi
        rows.append(
            {
                "symbol": symbol,
                "figi": figi,
                "meta": json.dumps(
                    {
                        source: {
                            "composite_figi": entry.get("compositeFIGI", ""),
                            "ticker": entry.get("ticker", ""),
                            "name": entry.get("name", ""),
                            "exch_code": entry.get("exchCode", ""),
                            "market_sector": entry.get("marketSector", ""),
                            "security_type": entry.get("securityType", ""),
                            "mapped_at": dt.date.today().isoformat(),
                        }
                    },
                    sort_keys=True,
                ),
            }
        )
    if not rows:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            UPDATE instruments SET
                figi = COALESCE(NULLIF(%(figi)s, ''), instruments.figi),
                meta = instruments.meta || %(meta)s::jsonb
            WHERE symbol = %(symbol)s
            """,
            rows,
        )
    map_vendor_symbols(conn, source, figi_by_symbol, ids)
    return len(rows)


def record_cik_mappings(
    conn,
    mappings: Mapping[str, int],
    ids: Mapping[str, int],
    *,
    source: str = "sec_edgar",
) -> int:
    """Record ticker -> CIK matches for catalog instruments.

    Mirrors ``record_figi_mappings``: the CIK lands in the two places join
    paths already read -- the ``instruments.cik`` column (zero-padded to the
    SEC's ten-digit form) and a ``symbol_map`` row under ``source='sec_edgar'``
    -- and a mapping never blanks an existing CIK.
    """
    rows = []
    cik_by_symbol: dict[str, str] = {}
    for symbol, cik in mappings.items():
        if symbol not in ids:
            continue
        padded = f"{int(cik):010d}"
        cik_by_symbol[symbol] = padded
        rows.append(
            {
                "symbol": symbol,
                "cik": padded,
                "meta": json.dumps(
                    {source: {"cik": int(cik), "mapped_at": dt.date.today().isoformat()}},
                    sort_keys=True,
                ),
            }
        )
    if not rows:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            UPDATE instruments SET
                cik = COALESCE(NULLIF(%(cik)s, ''), instruments.cik),
                meta = instruments.meta || %(meta)s::jsonb
            WHERE symbol = %(symbol)s
            """,
            rows,
        )
    map_vendor_symbols(conn, source, cik_by_symbol, ids)
    return len(rows)


def record_company_number_mappings(
    conn,
    mappings: Mapping[str, str],
    ids: Mapping[str, int],
    *,
    source: str = "companies_house",
    names: Mapping[str, str] | None = None,
) -> int:
    """Record symbol -> Companies House company-number matches.

    Mirrors ``record_cik_mappings``: the number lands in the two places join
    paths already read -- the ``instruments.company_number`` column and a
    ``symbol_map`` row under ``source='companies_house'`` -- and the matched
    CH title folds into ``meta['companies_house']``. Stricter than the CIK
    variant on purpose: an existing company_number is never overwritten, not
    just never blanked -- a wrong CH binding is worse than a missing one.
    """
    names = names or {}
    rows = []
    number_by_symbol: dict[str, str] = {}
    for symbol, number in mappings.items():
        if symbol not in ids or not str(number).strip():
            continue
        number_by_symbol[symbol] = str(number)
        rows.append(
            {
                "symbol": symbol,
                "company_number": str(number),
                "meta": json.dumps(
                    {
                        source: {
                            "company_number": str(number),
                            "company_name": str(names.get(symbol, "")),
                            "mapped_at": dt.date.today().isoformat(),
                        }
                    },
                    sort_keys=True,
                ),
            }
        )
    if not rows:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            UPDATE instruments SET
                company_number = COALESCE(NULLIF(instruments.company_number, ''),
                                          NULLIF(%(company_number)s, '')),
                meta = instruments.meta || %(meta)s::jsonb
            WHERE symbol = %(symbol)s
            """,
            rows,
        )
    map_vendor_symbols(conn, source, number_by_symbol, ids)
    return len(rows)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def start_run(
    conn,
    *,
    source: str,
    kind: str = "prices",
    requested_start: str | None = None,
    requested_end: str | None = None,
    frequency: str = "1d",
    symbols_requested: int = 0,
    snapshot_id: int | None = None,
    params: Mapping[str, Any] | None = None,
) -> int:
    """Open an ingest run and return its id.

    The id is also the ClickHouse ReplacingMergeTree version, so it must be
    allocated before any bar is written and must never be reused.
    """
    from .. import __version__ as version

    row = conn.execute(
        """
        INSERT INTO ingest_runs (
            source, kind, requested_start, requested_end, frequency,
            symbols_requested, snapshot_id, quantlab_version, params
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        RETURNING run_id
        """,
        (
            source,
            kind,
            requested_start or None,
            requested_end or None,
            frequency,
            symbols_requested,
            snapshot_id,
            str(version),
            json.dumps(dict(params or {}), sort_keys=True, default=str),
        ),
    ).fetchone()
    return int(row[0])


def finish_run(
    conn,
    run_id: int,
    *,
    status: str,
    rows_written: int = 0,
    rows_rejected: int = 0,
    symbols_ok: int = 0,
    error: str | None = None,
) -> None:
    """Close out an ingest run."""
    conn.execute(
        """
        UPDATE ingest_runs
           SET status = %s,
               finished_at = now(),
               rows_written = %s,
               rows_rejected = %s,
               symbols_ok = %s,
               error = %s
         WHERE run_id = %s
        """,
        (status, rows_written, rows_rejected, symbols_ok, error, run_id),
    )


def record_rejects(conn, run_id: int, rejected: pd.DataFrame) -> int:
    """Persist bars that failed validation, with the reason.

    ClickHouse will accept anything, so validation happens in the library and
    what it throws out is recorded here rather than dropped silently.
    """
    if rejected is None or rejected.empty:
        return 0

    payload_cols = [
        c for c in ("open", "high", "low", "close", "volume", "adj_close")
        if c in rejected.columns
    ]
    rows = []
    for row in rejected.itertuples():
        payload = {}
        for column in payload_cols:
            value = getattr(row, column, None)
            payload[column] = None if pd.isna(value) else float(value)
        rows.append(
            (
                run_id,
                int(row.instrument_id) if pd.notna(row.instrument_id) else None,
                str(row.symbol),
                getattr(row, "ts", None),
                str(row.reason),
                json.dumps(payload, sort_keys=True),
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO ingest_rejects (run_id, instrument_id, symbol, ts, reason, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
            rows,
        )
    return len(rows)


def stale_runs(conn, older_than_minutes: int = 60) -> pd.DataFrame:
    """Runs still marked 'running' well after they started.

    Because bars land in ClickHouse and provenance in Postgres, there is no
    cross-system transaction: a process killed mid-ingest leaves its run row
    open. These are the runs whose bar counts should not be trusted.
    """
    rows = conn.execute(
        """
        SELECT run_id, source, kind, started_at
          FROM ingest_runs
         WHERE status = 'running'
           AND started_at < now() - make_interval(mins => %s)
         ORDER BY started_at
        """,
        (older_than_minutes,),
    ).fetchall()
    return pd.DataFrame(rows, columns=["run_id", "source", "kind", "started_at"])


# ---------------------------------------------------------------------------
# Universe snapshots
# ---------------------------------------------------------------------------


def snapshot_universe(
    conn,
    universe: str,
    symbols: Sequence[str],
    ids: Mapping[str, int],
    *,
    snapshot_date: dt.date | str | None = None,
    source: str = "",
) -> int:
    """Record who was in the universe today. Append-only by construction.

    Re-snapshotting the same (universe, date) returns the existing snapshot
    untouched -- rewriting history is exactly what this table exists to prevent.
    """
    snapshot_date = snapshot_date or dt.date.today()
    if isinstance(snapshot_date, str):
        snapshot_date = dt.date.fromisoformat(snapshot_date)

    existing = conn.execute(
        "SELECT snapshot_id FROM universe_snapshots WHERE universe = %s AND snapshot_date = %s",
        (universe, snapshot_date),
    ).fetchone()
    if existing:
        log.info("universe snapshot %s@%s already exists, leaving it alone", universe, snapshot_date)
        return int(existing[0])

    members = [ids[s] for s in symbols if s in ids]
    row = conn.execute(
        """
        INSERT INTO universe_snapshots (universe, snapshot_date, source, member_count)
        VALUES (%s, %s, %s, %s)
        RETURNING snapshot_id
        """,
        (universe, snapshot_date, source, len(members)),
    ).fetchone()
    snapshot_id = int(row[0])

    if members:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO universe_members (snapshot_id, instrument_id) VALUES (%s, %s)",
                [(snapshot_id, iid) for iid in members],
            )
    return snapshot_id


def snapshot_members(conn, snapshot_id: int) -> list[int]:
    """instrument_ids belonging to a universe snapshot."""
    rows = conn.execute(
        "SELECT instrument_id FROM universe_members WHERE snapshot_id = %s ORDER BY instrument_id",
        (snapshot_id,),
    ).fetchall()
    return [row[0] for row in rows]


def real_equity_symbols(
    securities: Mapping[str, Security],
    *,
    with_bars: Sequence[str] | None = None,
) -> list[str]:
    """The real instruments eligible for a warehouse universe snapshot.

    Synthetic fixtures and macro pseudo-instruments are warehouse plumbing, not
    universe members: they are excluded by meta flag or by symbol convention
    (ZX*, *.BOE). ``with_bars``, when given, further restricts to symbols that
    actually have bars in the store.
    """
    wanted = set(with_bars) if with_bars is not None else None
    out = []
    for symbol, sec in securities.items():
        if wanted is not None and symbol not in wanted:
            continue
        meta = dict(sec.meta or {})
        if meta.get("synthetic") or meta.get("macro"):
            continue
        if symbol.startswith("ZX") or symbol.endswith(".BOE"):
            continue
        out.append(symbol)
    return sorted(out)


def latest_snapshot(conn, universe: str) -> int | None:
    """Most recent universe snapshot id, or None if that universe has none."""
    row = conn.execute(
        "SELECT snapshot_id FROM universe_snapshots WHERE universe = %s "
        "ORDER BY snapshot_date DESC LIMIT 1",
        (universe,),
    ).fetchone()
    return int(row[0]) if row else None


# ---------------------------------------------------------------------------
# Corporate actions
# ---------------------------------------------------------------------------


def write_corporate_actions(
    conn,
    actions: pd.DataFrame,
    *,
    run_id: int,
    ids: Mapping[str, int],
    source: str,
) -> int:
    """Load dividends and splits.

    Expects columns: symbol, ex_date, action_type, and one of dividend /
    split_ratio. Storing these from day one is what makes point-in-time
    adjustment possible later; vendor adj_close alone cannot be rewound.
    """
    if actions is None or actions.empty:
        return 0

    frame = actions[actions["symbol"].isin(ids)]
    if frame.empty:
        return 0

    rows = [
        (
            ids[row.symbol],
            pd.to_datetime(row.ex_date).date(),
            str(row.action_type),
            float(row.dividend) if pd.notna(getattr(row, "dividend", None)) else None,
            float(row.split_ratio) if pd.notna(getattr(row, "split_ratio", None)) else None,
            getattr(row, "currency", None),
            source,
            run_id,
        )
        for row in frame.itertuples()
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO corporate_actions (
                instrument_id, ex_date, action_type, dividend, split_ratio,
                currency, source, run_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (instrument_id, ex_date, action_type) DO UPDATE SET
                dividend    = EXCLUDED.dividend,
                split_ratio = EXCLUDED.split_ratio,
                currency    = EXCLUDED.currency,
                source      = EXCLUDED.source,
                run_id      = EXCLUDED.run_id,
                ingested_at = now()
            """,
            rows,
        )
    return len(rows)


def load_securities(conn, symbols: Sequence[str] | None = None) -> dict[str, Security]:
    """Reference data as Security objects, ready for a Context."""
    query = """
        SELECT symbol, name, exchange, country, currency, sector, industry,
               isin, sedol, cik, company_number, figi, active, meta
          FROM instruments
    """
    params: list = []
    if symbols:
        query += " WHERE symbol = ANY(%s)"
        params.append(list(symbols))
    query += " ORDER BY symbol"

    out: dict[str, Security] = {}
    for row in conn.execute(query, params).fetchall():
        (symbol, name, exchange, country, currency, sector, industry,
         isin, sedol, cik, company_number, figi, active, meta) = row
        out[symbol] = Security(
            symbol=symbol,
            name=name,
            exchange=exchange,
            country=country,
            currency=Currency(currency),
            sector=sector,
            industry=industry,
            isin=isin,
            sedol=sedol,
            cik=cik,
            company_number=company_number,
            figi=figi,
            active=active,
            meta=meta or {},
        )
    return out


def list_symbols(conn, *, exchange: str = "", active_only: bool = False) -> list[str]:
    """Every instrument known to the catalog, optionally filtered."""
    clauses, params = [], []
    if exchange:
        clauses.append("exchange = %s")
        params.append(exchange)
    if active_only:
        clauses.append("active")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT symbol FROM instruments {where} ORDER BY symbol", params
    ).fetchall()
    return [row[0] for row in rows]


def corporate_actions(
    conn,
    symbols: Sequence[str] | None = None,
    *,
    start: str | dt.date | None = None,
    end: str | dt.date | None = None,
) -> pd.DataFrame:
    """Dividends and splits, for building point-in-time adjustment factors."""
    clauses, params = ["TRUE"], []
    if symbols:
        clauses.append("i.symbol = ANY(%s)")
        params.append(list(symbols))
    if start:
        clauses.append("c.ex_date >= %s")
        params.append(pd.Timestamp(start).date())
    if end:
        clauses.append("c.ex_date <= %s")
        params.append(pd.Timestamp(end).date())

    rows = conn.execute(
        f"""
        SELECT i.symbol, c.ex_date, c.action_type, c.dividend, c.split_ratio, c.currency
          FROM corporate_actions c
          JOIN instruments i USING (instrument_id)
         WHERE {' AND '.join(clauses)}
         ORDER BY c.ex_date, i.symbol
        """,
        params,
    ).fetchall()
    return pd.DataFrame(
        rows,
        columns=["symbol", "ex_date", "action_type", "dividend", "split_ratio", "currency"],
    )


def run_history(conn, limit: int = 20) -> pd.DataFrame:
    """Recent ingest runs -- the audit trail for where any bar came from."""
    rows = conn.execute(
        """
        SELECT run_id, source, kind, status, started_at, finished_at,
               symbols_requested, symbols_ok, rows_written, rows_rejected, error
          FROM ingest_runs
         ORDER BY started_at DESC
         LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return pd.DataFrame(
        rows,
        columns=[
            "run_id", "source", "kind", "status", "started_at", "finished_at",
            "symbols_requested", "symbols_ok", "rows_written", "rows_rejected", "error",
        ],
    )
