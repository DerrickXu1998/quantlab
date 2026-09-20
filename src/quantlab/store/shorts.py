"""Short-selling ingest: FINRA daily short volume, FCA net short positions.

Both sources land in the ``fundamentals`` table (migration 004) as daily
metric series -- the table is filing-oriented, but a published daily file is
honestly modelled as one: ``period_end`` is the trade/position date the fact
describes, ``filed_at`` is when the market could first know it, and the
``accession`` is the publication identity (the FINRA file name, the FCA
holder's disclosure), which keeps re-runs idempotent via ON CONFLICT.

The two metrics are not the same thing and the tags say so:

  * FINRA rows are short *volume*: ``short_volume``, ``short_exempt_volume``
    and ``total_volume`` in shares, published same day by 18:00 ET, so
    ``filed_at`` is the trade date itself. 40-50% is normal -- read the
    z-score, not the level.
  * FCA rows are short *interest*: ``net_short_position_pct``, disclosed at
    the 0.2% threshold on a T+2 basis, so ``filed_at`` is the position date
    plus two business days. One row per (holder, issuer, date) -- sum over
    holders at read time for the issuer-level position.

Nothing here touches ClickHouse: short data is small, relational and wants
the fundamentals table's constraints, not bar-level cardinality.
"""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from ..schema import DataUnavailable, ProviderError
from . import catalog
from .fundamentals import _is_pseudo, normalize_company_name, write_fundamentals
from .ingest import IngestReport

log = logging.getLogger(__name__)

SOURCE_FINRA = "finra"
SOURCE_FCA = "fca"

_FINRA_TAGS = ("short_volume", "short_exempt_volume", "total_volume")


# ---------------------------------------------------------------------------
# FINRA: symbol bridge and row building (pure, DB-free)
# ---------------------------------------------------------------------------


def finra_ticker_index(rows: Sequence[tuple[str, int, Mapping[str, Any] | None]]) -> dict[str, int]:
    """FINRA ticker -> instrument_id for real catalog .US instruments.

    The file uses plain US tickers with the exchange's class-share spelling
    (``BRK/A``); the catalog inherited the dot and dash conventions
    (``BRK.B.US``, ``BF-B.US``). Slash variants are registered alongside the
    plain root, but a variant is never allowed to shadow another
    instrument's plain root.
    """
    index: dict[str, int] = {}
    for symbol, instrument_id, meta in rows:
        if not symbol.endswith(".US") or _is_pseudo(meta):
            continue
        index[symbol.rsplit(".", 1)[0].upper()] = instrument_id
    for symbol, instrument_id, meta in rows:
        if not symbol.endswith(".US") or _is_pseudo(meta):
            continue
        root = symbol.rsplit(".", 1)[0].upper()
        for variant in (root.replace(".", "/"), root.replace("-", "/")):
            index.setdefault(variant, instrument_id)
    return index


def finra_rows_for_day(
    records: Sequence[Mapping[str, Any]],
    index: Mapping[str, int],
    day: dt.date,
) -> tuple[list[dict[str, Any]], int]:
    """One day's parsed FINRA rows -> fundamentals rows for catalog symbols.

    Returns (rows, skipped): skipped counts symbols absent from the catalog,
    not an error -- the file covers every FINRA-reported symbol, the catalog
    only the ingested universe. ``filed_at`` is the trade date (published by
    18:00 ET that day) and the accession is the file name, so a re-pull of
    the same day is an ON CONFLICT no-op.
    """
    accession = f"CNMSshvol-{day.strftime('%Y%m%d')}"
    rows: list[dict[str, Any]] = []
    skipped = 0
    for rec in records:
        instrument_id = index.get(str(rec["symbol"]).upper())
        if instrument_id is None:
            skipped += 1
            continue
        meta = {"market": rec.get("market", "")}
        for tag in _FINRA_TAGS:
            rows.append(
                {
                    "instrument_id": instrument_id,
                    "provider": SOURCE_FINRA,
                    "taxonomy": "",
                    "tag": tag,
                    "concept": tag,
                    "unit": "shares",
                    "period_start": None,
                    "period_end": day,
                    "filed_at": day,
                    "value": float(rec[tag]),
                    "accession": accession,
                    "meta": meta,
                }
            )
    return rows, skipped


# ---------------------------------------------------------------------------
# FCA: name bridge and row building (pure, DB-free)
# ---------------------------------------------------------------------------


def fca_name_index(
    rows: Sequence[tuple[str, int, str]],
) -> dict[str, tuple[str, int]]:
    """Normalized issuer name -> (symbol, instrument_id), unambiguous only.

    Both the instrument's own name and its OpenFIGI name are registered as
    keys. A normalized name claimed by two different instruments is dropped
    entirely -- matching by name at all is already the weak link, so a
    collision means no match, like ``map_ch_companies``'s ambiguous tier.
    """
    claims: dict[str, set[tuple[str, int]]] = {}
    for symbol, instrument_id, name in rows:
        key = normalize_company_name(name)
        if key:
            claims.setdefault(key, set()).add((symbol, instrument_id))
    return {key: next(iter(hit)) for key, hit in claims.items() if len(hit) == 1}


def fca_rows(
    positions: pd.DataFrame,
    index: Mapping[str, tuple[str, int]],
) -> tuple[list[dict[str, Any]], int]:
    """Parsed FCA disclosures -> fundamentals rows for matched issuers.

    Returns (rows, unmatched_issuers). The disclosure identity is the
    holder: it goes in the accession, so several holders short the same
    issuer on the same date coexist and a re-pull is idempotent. ``filed_at``
    is the position date plus two business days, the FCA's T+2 publication
    basis. 0.0% rows (a position fell below the threshold) are kept.
    """
    rows: list[dict[str, Any]] = []
    unmatched: set[str] = set()
    for rec in positions.itertuples(index=False):
        key = normalize_company_name(str(rec.issuer_name))
        hit = index.get(key) if key else None
        if hit is None:
            unmatched.add(str(rec.issuer_name))
            continue
        _, instrument_id = hit
        position_date = pd.Timestamp(rec.position_date).date()
        filed_at = (pd.Timestamp(position_date) + pd.offsets.BDay(2)).date()
        rows.append(
            {
                "instrument_id": instrument_id,
                "provider": SOURCE_FCA,
                "taxonomy": "",
                "tag": "net_short_position_pct",
                "concept": "net_short_position",
                "unit": "pct",
                "period_start": None,
                "period_end": position_date,
                "filed_at": filed_at,
                "value": float(rec.net_short_pct),
                "accession": str(rec.holder),
                "meta": {
                    "holder": str(rec.holder),
                    "isin": str(rec.isin),
                    "issuer_name": str(rec.issuer_name),
                },
            }
        )
    return rows, len(unmatched)


# ---------------------------------------------------------------------------
# Catalog queries
# ---------------------------------------------------------------------------


def _finra_catalog_rows(conn) -> list[tuple[str, int, Mapping[str, Any]]]:
    rows = conn.execute(
        "SELECT symbol, instrument_id, meta FROM instruments WHERE symbol LIKE '%.US' ORDER BY symbol"
    ).fetchall()
    return [(s, i, m) for s, i, m in rows]


def _fca_catalog_rows(conn) -> list[tuple[str, int, str]]:
    """(symbol, instrument_id, best name) for real .LON instruments.

    Like ``_ch_map_candidates`` the OpenFIGI name is preferred (it is the
    reliable vendor name); the instrument's own name is registered as a
    second key by the index builder.
    """
    rows = conn.execute(
        "SELECT symbol, instrument_id, name, meta FROM instruments WHERE symbol LIKE '%.LON' ORDER BY symbol"
    ).fetchall()
    out: list[tuple[str, int, str]] = []
    for symbol, instrument_id, name, meta in rows:
        if _is_pseudo(meta):
            continue
        figi_name = ((meta or {}).get("openfigi") or {}).get("name") or ""
        names = [n for n in (figi_name, name or "") if n]
        for n in names:
            out.append((symbol, instrument_id, n))
    return out


# ---------------------------------------------------------------------------
# Ingest jobs
# ---------------------------------------------------------------------------


def ingest_finra_shorts(
    conn,
    *,
    provider=None,
    start: str | dt.date,
    end: str | dt.date | None = None,
    limit: int | None = None,
) -> IngestReport:
    """Load FINRA daily short volume into ``fundamentals`` for catalog .US names.

    One HTTP request per trading day in ``[start, end]`` (weekdays only;
    ``--limit`` keeps the most recent N). A day with no file -- a market
    holiday or a file not yet published -- is recorded in ``missing`` and is
    not an error. Commits per day bound the blast radius of a crash, and the
    accession makes re-runs of covered days no-ops.
    """
    if provider is None:
        from ..providers.finra import FinraProvider

        provider = FinraProvider()

    days = [d.date() for d in pd.bdate_range(pd.Timestamp(start), pd.Timestamp(end or start))]
    if limit:
        days = days[-limit:]

    run_id = catalog.start_run(
        conn,
        source=SOURCE_FINRA,
        kind="fundamentals",
        requested_start=str(days[0]) if days else None,
        requested_end=str(days[-1]) if days else None,
        symbols_requested=len(days),
        params={"limit": limit},
    )
    conn.commit()

    index = finra_ticker_index(_finra_catalog_rows(conn))
    written, ok, skipped = 0, 0, 0
    missing: list[str] = []
    for day in days:
        try:
            frame = provider.short_volume_day(day)
        except DataUnavailable:
            missing.append(str(day))
            continue
        except ProviderError as exc:
            log.warning("finra: %s failed unexpectedly: %s", day, exc)
            missing.append(str(day))
            continue
        rows, skip = finra_rows_for_day(frame.to_dict("records"), index, day)
        skipped += skip
        written += write_fundamentals(conn, rows, run_id=run_id)
        conn.commit()
        ok += 1
        log.info("finra: %s -> %d rows (%d symbols not in catalog)", day, len(rows), skip)

    status = "ok" if ok or not days else "failed"
    catalog.finish_run(
        conn,
        run_id,
        status=status,
        rows_written=written,
        symbols_ok=ok,
        error=f"no files retrieved; {len(missing)} days missing" if not ok and days else None,
    )
    conn.commit()

    return IngestReport(
        run_id=run_id,
        status=status,
        symbols_requested=len(days),
        symbols_ok=ok,
        rows_written=written,
        missing=missing,
        reject_reasons={"symbols_not_in_catalog": skipped} if skipped else {},
        providers_used={SOURCE_FINRA: ok},
    )


def ingest_fca_shorts(
    conn,
    *,
    provider=None,
    limit: int | None = None,
    chunk_size: int = 10_000,
) -> IngestReport:
    """Load FCA disclosed net short positions for catalog .LON names.

    The FCA file is one daily-refreshed workbook of the entire disclosure
    history since 2013, so a run is a single fetch and a full re-pull;
    idempotency comes from the row identity (holder in the accession).
    Issuers are bridged by conservative normalized-name matching (see
    :func:`fca_name_index`) -- issuers that match nothing, or match a name
    claimed by two instruments, are skipped and counted, never guessed.
    ``--limit`` caps the number of matched instruments written.
    """
    if provider is None:
        from ..providers.fca import FcaProvider

        provider = FcaProvider()

    run_id = catalog.start_run(
        conn,
        source=SOURCE_FCA,
        kind="fundamentals",
        params={"limit": limit},
    )
    conn.commit()

    positions = provider.net_short_positions()
    index = fca_name_index(_fca_catalog_rows(conn))
    rows, unmatched = fca_rows(positions, index)

    if limit:
        keep: set[int] = set()
        for row in rows:
            if len(keep) >= limit:
                break
            keep.add(row["instrument_id"])
        rows = [r for r in rows if r["instrument_id"] in keep]

    instruments_hit = {row["instrument_id"] for row in rows}
    written = 0
    for i in range(0, len(rows), chunk_size):
        written += write_fundamentals(conn, rows[i : i + chunk_size], run_id=run_id)
        conn.commit()
        log.info("fca: %d/%d rows staged, %d written", min(i + chunk_size, len(rows)), len(rows), written)

    status = "ok" if rows else "failed"
    catalog.finish_run(
        conn,
        run_id,
        status=status,
        rows_written=written,
        symbols_ok=len(instruments_hit),
        error="no disclosures matched the catalog" if not rows else None,
    )
    conn.commit()

    return IngestReport(
        run_id=run_id,
        status=status,
        symbols_requested=len(instruments_hit),
        symbols_ok=len(instruments_hit),
        rows_written=written,
        reject_reasons={"unmatched_issuers": unmatched} if unmatched else {},
        providers_used={SOURCE_FCA: len(instruments_hit)},
    )
