"""Fundamentals ingest: SEC EDGAR and Companies House into `fundamentals`.

Both providers reduce to the same long row (migration 004): who, which tag,
which unit, which period, what value, and when the market could first know it
(filed_at). Three jobs live here:

  * ``map_sec_tickers``        ticker -> CIK via ``company_tickers.json``,
                               written to ``instruments.cik`` plus a
                               ``symbol_map`` row (source='sec_edgar').
  * ``ingest_sec_fundamentals`` companyfacts per CIK-bound instrument,
                               flattened one row per XBRL fact.
  * ``map_ch_companies``       .LON instrument name -> Companies House
                               company_number via ``/search/companies``,
                               written to ``instruments.company_number`` plus
                               a ``symbol_map`` row (source='companies_house').
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
import re
from dataclasses import dataclass, field
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
# Companies House: name -> company_number mapping
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES = ("PUBLIC LIMITED COMPANY", "PLC", "LIMITED", "LTD", "LLP", "LP")
_WEAK_TOKENS = {"HOLDINGS", "HOLDING", "GROUP"}


def ch_search_name(raw: str) -> str:
    """Best-effort Companies House search string for a vendor name.

    OpenFIGI names are Bloomberg-style and carry decorations Companies House
    never uses: a trailing "/THE" (the article moved to the end) and a "-DI"
    depositary-interest marker. Both are dropped; the legal-form suffix stays
    in the query because CH's own titles carry it ("SHELL PLC").
    """
    name = re.sub(r"\s+", " ", str(raw or "")).strip()
    name = re.sub(r"/THE$", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(r"-DI$", "", name, flags=re.IGNORECASE).strip()
    return name


def normalize_company_name(name: str, *, strip_weak: bool = False) -> str:
    """Comparison key for company names.

    Upper-cased, ampersands spelled out, punctuation removed (dots/commas/
    apostrophes deleted outright, so "P.L.C." collapses to "PLC"), a leading
    "THE" and trailing legal forms (PLC/LIMITED/LTD/LLP/LP) removed. With
    ``strip_weak`` the filler words HOLDINGS/GROUP go too -- the second-tier
    key, trusted only when a search returns a single active candidate.
    """
    text = str(name or "").upper().replace("&", " AND ")
    text = re.sub(r"[.,']+", "", text)
    tokens = re.sub(r"[^A-Z0-9 ]+", " ", text).split()
    if tokens and tokens[0] == "THE":
        tokens = tokens[1:]
    changed = True
    while changed:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            parts = suffix.split()
            if len(tokens) > len(parts) and tokens[-len(parts):] == parts:
                tokens = tokens[: -len(parts)]
                changed = True
    if strip_weak:
        tokens = [t for t in tokens if t not in _WEAK_TOKENS]
    return " ".join(tokens)


def match_ch_company(
    query: str, results: Sequence[Mapping[str, Any]]
) -> tuple[Mapping[str, Any] | None, str]:
    """Pick the Companies House entry for a cleaned query name, conservatively.

    Returns ``(item, how)`` with ``how`` "exact" or "weak" on a match, and
    ``(None, status)`` otherwise. Only active companies are eligible -- a
    dissolved namesake never satisfies the query. "exact" is one active result
    whose normalized title equals the normalized query; "weak" additionally
    drops HOLDINGS/GROUP and is accepted only when the search produced a
    single active candidate at all. Two plausible live candidates return
    "ambiguous": the instrument goes to the review list instead of guessing.
    """
    if not normalize_company_name(query):
        return None, "no-name"
    active = [
        r
        for r in results
        if str(r.get("company_status", "")).lower() == "active" and r.get("company_number")
    ]
    if not active:
        return None, "no-results" if not results else "no-active"

    key = normalize_company_name(query)
    exact = [r for r in active if normalize_company_name(str(r.get("title", ""))) == key]
    if len(exact) == 1:
        return exact[0], "exact"
    if len(exact) > 1:
        return None, "ambiguous"

    weak_key = normalize_company_name(query, strip_weak=True)
    weak = [
        r
        for r in active
        if normalize_company_name(str(r.get("title", "")), strip_weak=True) == weak_key
    ]
    if len(weak) == 1 and len(active) == 1:
        return weak[0], "weak"
    return None, "ambiguous" if weak else "no-match"


@dataclass
class ChMapReport(MapReport):
    """MapReport plus the review list and the titles actually bound."""

    source: str = SOURCE_CH
    ambiguous: list[str] = field(default_factory=list)
    matched_names: dict[str, str] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.candidates and not self.mapped:
            return "failed"
        return "partial" if (self.unresolved or self.ambiguous) else "ok"

    def summary(self) -> str:
        lines = [
            f"map-ch-companies: {self.status} (source {self.source})",
            f"  candidates {self.candidates}",
            f"  mapped     {self.mapped}",
        ]
        for symbol, title in list(self.matched_names.items())[:10]:
            lines.append(f"    {symbol} -> {title}")
        if len(self.matched_names) > 10:
            lines.append(f"    (+{len(self.matched_names) - 10} more)")
        if self.ambiguous:
            shown = ", ".join(self.ambiguous[:10])
            more = f" (+{len(self.ambiguous) - 10} more)" if len(self.ambiguous) > 10 else ""
            lines.append(f"  ambiguous (review list, nothing written) {shown}{more}")
        if self.unresolved:
            shown = ", ".join(self.unresolved[:10])
            more = f" (+{len(self.unresolved) - 10} more)" if len(self.unresolved) > 10 else ""
            lines.append(f"  unresolved {shown}{more}")
        return "\n".join(lines)


def _ch_map_candidates(
    conn, symbols: Sequence[str] | None = None, *, only_missing: bool
) -> list[tuple[str, str]]:
    """(symbol, search name) for .LON instruments: real equities only.

    The search string comes from the OpenFIGI name when present
    (map-identifiers ran first and its names are reliable), falling back to
    the instrument's own name. Neither means no API call: the symbol is
    reported as unresolved instead of sending a bare ticker to CH.
    """
    query = "SELECT symbol, name, company_number, meta FROM instruments"
    params: list = []
    if symbols:
        query += " WHERE symbol = ANY(%s)"
        params.append(list(symbols))
    query += " ORDER BY symbol"
    rows = conn.execute(query, params).fetchall()
    out = []
    for symbol, name, company_number, meta in rows:
        if not symbol.endswith(".LON") or _is_pseudo(meta):
            continue
        if only_missing and company_number:
            continue
        figi_name = ((meta or {}).get("openfigi") or {}).get("name") or ""
        out.append((symbol, ch_search_name(figi_name or name or "")))
    return out


def map_ch_companies(
    conn,
    symbols: Sequence[str] | None = None,
    *,
    provider=None,
    limit: int | None = None,
    only_missing: bool = True,
) -> ChMapReport:
    """Bind Companies House company numbers to catalog .LON instruments.

    One ``/search/companies`` call per candidate (600 req / 5 min budget; the
    HTTP cache makes a re-run free for 30 days). Only high-confidence matches
    are written -- see :func:`match_ch_company`; ambiguous multi-hits land in
    ``report.ambiguous`` for manual review and are never guessed. An existing
    ``company_number`` is never overwritten, so the mapping is the resume
    state. Commits once at the end, like :func:`map_sec_tickers`.
    """
    if provider is None:
        from ..providers.companies_house import CompaniesHouseProvider

        provider = CompaniesHouseProvider()
        # Fail before any searching when the key is missing.
        provider._require_key()

    candidates = _ch_map_candidates(conn, symbols, only_missing=only_missing)
    if limit:
        candidates = candidates[:limit]
    report = ChMapReport(candidates=len(candidates))
    if not candidates:
        log.info("map-ch-companies: nothing to do")
        return report

    mappings: dict[str, str] = {}
    names: dict[str, str] = {}
    for symbol, query in candidates:
        if not query:
            log.info("map-ch-companies: %s has no name to search with", symbol)
            report.unresolved.append(symbol)
            continue
        try:
            results = provider.search(query, limit=10)
        except Exception as exc:
            log.warning("map-ch-companies: search for %s (%r) failed: %s", symbol, query, exc)
            report.unresolved.append(symbol)
            continue
        item, how = match_ch_company(query, results)
        if item is None:
            (report.ambiguous if how == "ambiguous" else report.unresolved).append(symbol)
            log.info("map-ch-companies: %s (%r) -> %s", symbol, query, how)
            continue
        number, title = str(item["company_number"]), str(item.get("title") or "")
        mappings[symbol] = number
        names[symbol] = title
        report.matched_names[symbol] = title
        log.info("map-ch-companies: %s -> %s (%s, %s)", symbol, title, number, how)

    ids = catalog.instrument_ids(conn, list(mappings))
    report.mapped = catalog.record_company_number_mappings(
        conn, mappings, ids, source=SOURCE_CH, names=names
    )
    conn.commit()

    log.info(
        "map-ch-companies: %d matched, %d ambiguous, %d unmatched",
        report.mapped,
        len(report.ambiguous),
        len(report.unresolved),
    )
    return report


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
    PDF-only filings (most large PLCs file scanned accounts at CH) are skipped
    via the document metadata's resource list, never retried.

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
        pdf_only = 0
        for _, item in history.iterrows():
            links = item.get("links")
            doc = links.get("document_metadata") if isinstance(links, Mapping) else None
            filed_at = _as_date(item.get("date"))
            if not doc or filed_at is None:
                continue
            try:
                content = provider.xhtml_content(doc)
            except Exception as exc:
                log.debug("companies_house: document fetch failed for %s: %s", symbol, exc)
                continue
            if content is None:
                # PDF-only filing: most large PLCs file scanned accounts at
                # CH, so there is no iXBRL to parse. Not an error, just a gap.
                pdf_only += 1
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
            log.info(
                "companies_house: no parseable accounts for %s (%s): %d filings PDF-only",
                symbol, number, pdf_only,
            )
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
