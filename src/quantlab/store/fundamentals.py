"""Fundamentals ingest: SEC EDGAR and Companies House into `fundamentals`.

Both providers reduce to the same long row (migration 004): who, which tag,
which unit, which period, what value, and when the market could first know it
(filed_at). Three jobs live here:

  * ``map_sec_tickers``        ticker -> CIK via ``company_tickers.json``,
                               written to ``instruments.cik`` plus a
                               ``symbol_map`` row (source='sec_edgar').
  * ``ingest_sec_fundamentals`` companyfacts per CIK-bound instrument,
                               flattened one row per XBRL fact.
  * ``ingest_ch_fundamentals`` filing history + iXBRL accounts per
                               ``instruments.company_number``.

All three are idempotent and resumable. The fundamentals identity includes the
filing (accession), so a re-pull of the same filing is an ON CONFLICT no-op;
``--only-missing`` (the default) skips instruments that already have rows for
the provider, so an interrupted run resumes where it stopped. Chunk commits
bound the blast radius of a crash to the instruments since the last commit --
the rows written so far are valid and never duplicate.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Mapping, Sequence

from ..providers.companies_house import UK_TAGS, parse_ixbrl_facts, parse_ixbrl_period_end
from ..providers.sec_edgar import CONCEPT_TAGS
from . import catalog
from .identifiers import MapReport
from .ingest import IngestReport

log = logging.getLogger(__name__)

SOURCE_SEC = "sec_edgar"
SOURCE_CH = "companies_house"

# tag -> canonical concept, first preference in CONCEPT_TAGS wins.
_SEC_CONCEPTS: dict[str, str] = {}
for _concept, _tags in CONCEPT_TAGS.items():
    for _tag in _tags:
        _SEC_CONCEPTS.setdefault(_tag, _concept)


def _as_date(value: Any) -> dt.date | None:
    if value in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _is_pseudo(meta: Mapping[str, Any] | None) -> bool:
    meta = meta or {}
    return bool(meta.get("synthetic") or meta.get("macro"))


# ---------------------------------------------------------------------------
# SEC EDGAR: companyfacts -> long rows
# ---------------------------------------------------------------------------


def flatten_companyfacts(blob: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One companyfacts payload -> fundamentals rows (minus instrument_id).

    Every (taxonomy, tag, unit, entry) becomes a row. Entries without an
    ``end``, ``filed`` or ``val`` cannot be placed in time or valued and are
    skipped. Restatements are kept: the same fact re-published by a later
    filing arrives with a new accession and filed_at, which is exactly the
    point-in-time history the table exists for.
    """
    rows: list[dict[str, Any]] = []
    for taxonomy, tags in (blob.get("facts") or {}).items():
        if not isinstance(tags, Mapping):
            continue
        for tag, node in tags.items():
            units = (node or {}).get("units") or {}
            for unit, entries in units.items():
                for entry in entries:
                    value, filed, end = entry.get("val"), entry.get("filed"), entry.get("end")
                    if value is None or not filed or not end:
                        continue
                    period_end, filed_at = _as_date(end), _as_date(filed)
                    if period_end is None or filed_at is None:
                        continue
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        continue
                    meta = {
                        k: entry[k]
                        for k in ("form", "fy", "fp", "frame")
                        if entry.get(k) is not None
                    }
                    rows.append(
                        {
                            "provider": SOURCE_SEC,
                            "taxonomy": str(taxonomy),
                            "tag": str(tag),
                            "concept": _SEC_CONCEPTS.get(tag, ""),
                            "unit": str(unit),
                            "period_start": _as_date(entry.get("start")),
                            "period_end": period_end,
                            "filed_at": filed_at,
                            "value": number,
                            "accession": str(entry.get("accn") or ""),
                            "meta": meta,
                        }
                    )
    return rows


def write_fundamentals(conn, rows: Sequence[Mapping[str, Any]], *, run_id: int) -> int:
    """Insert fundamentals rows, returning how many were actually new.

    Identity conflicts (a re-pulled filing) are no-ops, so the count is the
    honest "rows added" number, not the attempted number. Row-at-a-time on
    purpose: psycopg's executemany cannot report per-row conflict outcomes.
    """
    written = 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO fundamentals (
                    instrument_id, provider, taxonomy, tag, concept, unit,
                    period_start, period_end, filed_at, value, accession,
                    run_id, meta
                ) VALUES (
                    %(instrument_id)s, %(provider)s, %(taxonomy)s, %(tag)s,
                    %(concept)s, %(unit)s, %(period_start)s, %(period_end)s,
                    %(filed_at)s, %(value)s, %(accession)s, %(run_id)s,
                    %(meta)s::jsonb
                )
                ON CONFLICT (instrument_id, provider, taxonomy, tag, unit,
                             period_end, filed_at, accession) DO NOTHING
                """,
                {
                    "instrument_id": int(row["instrument_id"]),
                    "provider": row["provider"],
                    "taxonomy": row.get("taxonomy") or "",
                    "tag": row["tag"],
                    "concept": row.get("concept") or "",
                    "unit": row.get("unit") or "",
                    "period_start": row.get("period_start"),
                    "period_end": row["period_end"],
                    "filed_at": row["filed_at"],
                    "value": float(row["value"]),
                    "accession": row.get("accession") or "",
                    "run_id": run_id,
                    "meta": json.dumps(dict(row.get("meta") or {}), sort_keys=True, default=str),
                },
            )
            written += cur.rowcount
    return written


# ---------------------------------------------------------------------------
# SEC EDGAR: ticker -> CIK mapping
# ---------------------------------------------------------------------------


def ticker_variants(symbol: str) -> list[str]:
    """Ticker spellings to try against the SEC master, most likely first.

    SEC spells class shares with a dash (BRK-B); warehouse symbols inherited
    the Yahoo/Stooq dot convention (BRK.B). Case differs too -- the master is
    upper-case, catalog symbols are not guaranteed to be.
    """
    root = symbol.rsplit(".", 1)[0].upper()
    variants = [root]
    for swapped in (root.replace(".", "-"), root.replace("-", ".")):
        if swapped != root and swapped not in variants:
            variants.append(swapped)
    return variants


def _sec_map_candidates(
    conn, symbols: Sequence[str] | None = None, *, only_missing: bool
) -> list[str]:
    """Catalog .US symbols worth a CIK lookup: real equities only."""
    query = "SELECT symbol, cik, meta FROM instruments"
    params: list = []
    if symbols:
        query += " WHERE symbol = ANY(%s)"
        params.append(list(symbols))
    query += " ORDER BY symbol"
    rows = conn.execute(query, params).fetchall()
    out = []
    for symbol, cik, meta in rows:
        if not symbol.endswith(".US") or _is_pseudo(meta):
            continue
        if only_missing and cik:
            continue
        out.append(symbol)
    return out


def map_sec_tickers(
    conn,
    symbols: Sequence[str] | None = None,
    *,
    provider=None,
    limit: int | None = None,
    only_missing: bool = True,
) -> MapReport:
    """Match catalog .US instruments against SEC's ticker -> CIK master.

    Same commit discipline as ``map_identifiers``: the mapping itself is the
    resume state, and a binding never blanks an existing CIK. ``symbols``
    restricts the pass to an explicit list (tests; ad-hoc fixes).
    """
    if provider is None:
        from ..providers.sec_edgar import SecEdgarProvider

        provider = SecEdgarProvider()

    candidates = _sec_map_candidates(conn, symbols, only_missing=only_missing)
    if limit:
        candidates = candidates[:limit]
    report = MapReport(source=SOURCE_SEC, candidates=len(candidates))
    if not candidates:
        log.info("map-sec-tickers: nothing to do")
        return report

    master = provider.ticker_to_cik()  # one request, cached for a week
    mappings: dict[str, int] = {}
    for symbol in candidates:
        for variant in ticker_variants(symbol):
            if variant in master:
                mappings[symbol] = master[variant]
                break
    report.unresolved = [s for s in candidates if s not in mappings]

    ids = catalog.instrument_ids(conn, list(mappings))
    report.mapped = catalog.record_cik_mappings(conn, mappings, ids, source=SOURCE_SEC)
    conn.commit()

    log.info("map-sec-tickers: %d matched, %d unmatched", report.mapped, len(report.unresolved))
    return report


# ---------------------------------------------------------------------------
# SEC EDGAR: fundamentals ingest
# ---------------------------------------------------------------------------


def _fundamentals_candidates(
    conn, column: str, provider: str, *, only_missing: bool
) -> list[tuple[str, int, str]]:
    """(symbol, instrument_id, identifier) for instruments carrying `column`."""
    missing_clause = ""
    if only_missing:
        missing_clause = (
            "AND NOT EXISTS (SELECT 1 FROM fundamentals f"
            "  WHERE f.instrument_id = i.instrument_id AND f.provider = %(provider)s)"
        )
    rows = conn.execute(
        f"""
        SELECT i.symbol, i.instrument_id, i.{column}, i.meta
          FROM instruments i
         WHERE i.{column} <> '' {missing_clause}
         ORDER BY i.symbol
        """,
        {"provider": provider},
    ).fetchall()
    return [(s, iid, ident) for s, iid, ident, meta in rows if not _is_pseudo(meta)]


def ingest_sec_fundamentals(
    conn,
    *,
    provider=None,
    symbols: Sequence[str] | None = None,
    limit: int | None = None,
    only_missing: bool = True,
    chunk_size: int = 25,
) -> IngestReport:
    """Pull companyfacts for every CIK-bound instrument into `fundamentals`.

    One HTTP request per instrument (the shared client stays under SEC's
    10 req/s hard limit). Facts are flattened whole -- every taxonomy, tag and
    unit -- because canonical-concept resolution is a read-time concern.
    Commits every ``chunk_size`` instruments; ``--only-missing`` resumes.
    ``symbols`` restricts the pass to an explicit list (tests; ad-hoc fixes).
    """
    if provider is None:
        from ..providers.sec_edgar import SecEdgarProvider

        provider = SecEdgarProvider()

    candidates = _fundamentals_candidates(conn, "cik", SOURCE_SEC, only_missing=only_missing)
    if symbols:
        wanted = set(symbols)
        candidates = [c for c in candidates if c[0] in wanted]
    if limit:
        candidates = candidates[:limit]

    run_id = catalog.start_run(
        conn,
        source=SOURCE_SEC,
        kind="fundamentals",
        symbols_requested=len(candidates),
        params={"only_missing": only_missing},
    )
    conn.commit()

    written, ok = 0, 0
    missing: list[str] = []
    pending: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal written
        if pending:
            written += write_fundamentals(conn, pending, run_id=run_id)
            pending.clear()
        conn.commit()

    for i, (symbol, instrument_id, cik) in enumerate(candidates):
        try:
            blob = provider.companyfacts(int(cik))
        except Exception as exc:
            log.warning("sec_edgar: companyfacts for %s (CIK %s) failed: %s", symbol, cik, exc)
            missing.append(symbol)
            continue
        rows = flatten_companyfacts(blob)
        for row in rows:
            row["instrument_id"] = instrument_id
        pending.extend(rows)
        ok += 1
        if (i + 1) % chunk_size == 0:
            flush()
            log.info("sec_edgar: %d/%d instruments, %d rows so far", i + 1, len(candidates), written)
    flush()

    status = "failed" if candidates and not ok else ("partial" if missing else "ok")
    catalog.finish_run(
        conn,
        run_id,
        status=status,
        rows_written=written,
        symbols_ok=ok,
        error=f"{len(missing)} instruments failed" if missing else None,
    )
    conn.commit()

    return IngestReport(
        run_id=run_id,
        status=status,
        symbols_requested=len(candidates),
        symbols_ok=ok,
        rows_written=written,
        missing=missing,
        providers_used={SOURCE_SEC: ok},
    )


# ---------------------------------------------------------------------------
# Companies House: filing history + iXBRL accounts
# ---------------------------------------------------------------------------


def ingest_ch_fundamentals(
    conn,
    *,
    provider=None,
    symbols: Sequence[str] | None = None,
    limit: int | None = None,
    only_missing: bool = True,
    concepts: Sequence[str] | None = None,
    chunk_size: int = 10,
) -> IngestReport:
    """Parse filed accounts for every company_number-bound instrument.

    Per company: the filing history supplies the point-in-time anchor
    (``date`` -> filed_at) and the filing identity (``transaction_id`` ->
    accession); each accounts document is parsed for the UK_TAGS concepts.

    Two honest gaps in what the REST API gives us, both recorded in ``meta``:

      * ``period_end`` comes from the iXBRL document's
        ``EndDateForPeriodCoveredByReport``/``BalanceSheetDate`` tag; when the
        parser cannot find one the filing date is used and
        ``meta.period_end_assumed`` is set.
      * ``unit`` stays empty: the regex parser does not resolve unitRef to a
        currency. The values are in the company's presentation currency.
    """
    if provider is None:
        from ..providers.companies_house import CompaniesHouseProvider

        provider = CompaniesHouseProvider()
        # Fail before opening a run when the key is missing: with no bound
        # instruments there would otherwise be no API call to surface it.
        provider._require_key()
    concepts = list(concepts or UK_TAGS)

    candidates = _fundamentals_candidates(conn, "company_number", SOURCE_CH, only_missing=only_missing)
    if symbols:
        wanted = set(symbols)
        candidates = [c for c in candidates if c[0] in wanted]
    if limit:
        candidates = candidates[:limit]

    run_id = catalog.start_run(
        conn,
        source=SOURCE_CH,
        kind="fundamentals",
        symbols_requested=len(candidates),
        params={"only_missing": only_missing, "concepts": concepts},
    )
    conn.commit()

    written, ok = 0, 0
    missing: list[str] = []
    pending: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal written
        if pending:
            written += write_fundamentals(conn, pending, run_id=run_id)
            pending.clear()
        conn.commit()

    for i, (symbol, instrument_id, number) in enumerate(candidates):
        try:
            history = provider.filing_history(number, category="accounts")
        except Exception as exc:
            log.warning("companies_house: filing history for %s (%s) failed: %s", symbol, number, exc)
            missing.append(symbol)
            continue
        company_rows = 0
        for _, item in history.iterrows():
            doc = (item.get("links") or {}).get("document_metadata")
            filed_at = _as_date(item.get("date"))
            if not doc or filed_at is None:
                continue
            try:
                content = provider.client.get(
                    f"{doc}/content", ttl=-1, headers={"Accept": "application/xhtml+xml"}
                )
            except Exception as exc:
                log.debug("companies_house: document fetch failed for %s: %s", symbol, exc)
                continue
            text = content.decode("utf-8", errors="replace")
            facts = parse_ixbrl_facts(text, concepts)
            if not facts:
                continue
            period_end = parse_ixbrl_period_end(text)
            meta: dict[str, Any] = {"company_number": number}
            if period_end is None:
                # The statutory period end is in the iXBRL contexts, which the
                # regex parser does not resolve; the filing date is the least-
                # wrong placeholder and is flagged as assumed.
                period_end = filed_at
                meta["period_end_assumed"] = True
            accession = str(item.get("transaction_id") or doc.rsplit("/", 1)[-1])
            for concept, (tag, value) in facts.items():
                pending.append(
                    {
                        "instrument_id": instrument_id,
                        "provider": SOURCE_CH,
                        "taxonomy": "",
                        "tag": tag,
                        "concept": concept,
                        "unit": "",
                        "period_start": None,
                        "period_end": period_end,
                        "filed_at": filed_at,
                        "value": value,
                        "accession": accession,
                        "meta": meta,
                    }
                )
                company_rows += 1
        ok += 1
        if company_rows == 0:
            log.info("companies_house: no parseable accounts for %s (%s)", symbol, number)
        if (i + 1) % chunk_size == 0:
            flush()
            log.info("companies_house: %d/%d companies, %d rows so far", i + 1, len(candidates), written)
    flush()

    status = "failed" if candidates and not ok else ("partial" if missing else "ok")
    catalog.finish_run(
        conn,
        run_id,
        status=status,
        rows_written=written,
        symbols_ok=ok,
        error=f"{len(missing)} instruments failed" if missing else None,
    )
    conn.commit()

    return IngestReport(
        run_id=run_id,
        status=status,
        symbols_requested=len(candidates),
        symbols_ok=ok,
        rows_written=written,
        missing=missing,
        providers_used={SOURCE_CH: ok},
    )
