"""OpenFIGI identifier mappings for the catalog.

The "week one" job from docs/DATA_SOURCES.md: give every real instrument its
OpenFIGI identifiers so price sources, short-interest filings and fundamentals
can be joined on something stable later. The mapping response is written to
the catalog rather than a new table:

  * ``instruments.figi``            the (exchange-level) FIGI
  * ``symbol_map``                  source='openfigi', vendor_symbol=FIGI
  * ``instruments.meta['openfigi']`` composite FIGI, name, exchange code,
                                    market sector, security type, mapped_at

Synthetic (``meta.synthetic``) and macro (``meta.macro``) pseudo-instruments
are never submitted -- OpenFIGI cannot resolve them and every job costs
against the keyless 25 req/min budget. The run is resumable: by default only
instruments still lacking a FIGI are mapped, so re-running after an
interruption picks up where the last one stopped.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from . import catalog

log = logging.getLogger(__name__)

SOURCE = "openfigi"


_UK_SUFFIXES = {"LON", "L", "UK"}


def job_for_symbol(symbol: str) -> dict[str, str]:
    """Canonical symbol -> one OpenFIGI TICKER mapping job."""
    root = symbol.rsplit(".", 1)[0] if "." in symbol else symbol
    suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else "US"
    exch = "LN" if suffix in _UK_SUFFIXES else "US"
    return {"idType": "TICKER", "idValue": root, "exchCode": exch}


def fallback_job_for_symbol(symbol: str) -> dict[str, str] | None:
    """A second-chance job for UK symbols the bare ticker did not resolve.

    Bloomberg spells an LSE ticker with a trailing slash when the bare ticker
    is taken by a US line (BP/ on LN vs BP on US), and class-share dots become
    slashes (BT.A -> BT/A). Only UK symbols get a fallback; there is no
    equivalent convention to exploit for US names.
    """
    if "." not in symbol:
        return None
    root, suffix = symbol.rsplit(".", 1)
    if suffix.upper() not in _UK_SUFFIXES:
        return None
    id_value = root.replace(".", "/") if "." in root else root + "/"
    return {"idType": "TICKER", "idValue": id_value, "exchCode": "LN"}


def candidate_rows(conn, symbols: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """symbol/figi/meta for catalog instruments, optionally restricted."""
    query = "SELECT symbol, figi, meta FROM instruments"
    params: list = []
    if symbols:
        query += " WHERE symbol = ANY(%s)"
        params.append(list(symbols))
    query += " ORDER BY symbol"
    rows = conn.execute(query, params).fetchall()
    return [{"symbol": r[0], "figi": r[1], "meta": r[2] or {}} for r in rows]


def select_candidates(
    rows: Sequence[Mapping[str, Any]], *, only_missing: bool = True
) -> list[str]:
    """Filter catalog rows down to instruments worth a mapping job.

    Synthetic and macro pseudo-instruments are always excluded -- they exist
    only inside quantlab. With ``only_missing`` (the default), instruments
    that already carry a FIGI are skipped too, which is what makes a re-run
    after an interruption resume instead of start over.
    """
    out = []
    for row in rows:
        meta = row.get("meta") or {}
        if meta.get("synthetic") or meta.get("macro"):
            continue
        if only_missing and row.get("figi"):
            continue
        out.append(row["symbol"])
    return out


@dataclass
class MapReport:
    """What a mapping pass did. Printed by the CLI, asserted on by the tests."""

    source: str = SOURCE
    candidates: int = 0
    mapped: int = 0
    unresolved: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.candidates and not self.mapped:
            return "failed"
        return "partial" if self.unresolved else "ok"

    def summary(self) -> str:
        lines = [
            f"map-identifiers: {self.status} (source {self.source})",
            f"  candidates {self.candidates}",
            f"  mapped     {self.mapped}",
        ]
        if self.unresolved:
            shown = ", ".join(self.unresolved[:10])
            more = f" (+{len(self.unresolved) - 10} more)" if len(self.unresolved) > 10 else ""
            lines.append(f"  unresolved {shown}{more}")
        return "\n".join(lines)


def map_identifiers(
    conn,
    symbols: Sequence[str] | None = None,
    *,
    provider=None,
    limit: int | None = None,
    only_missing: bool = True,
) -> MapReport:
    """Map catalog instruments to OpenFIGI identifiers and record the results.

    ``symbols`` restricts the pass to an explicit list (tests; ad-hoc fixes);
    the default is every eligible instrument in the catalog. ``provider`` is
    injectable for tests -- anything with the OpenFigiProvider
    ``map_identifiers(jobs)`` interface works. Commits like the other
    store-level ingest functions: the mapping itself is the resume state.
    """
    if provider is None:
        from ..providers.openfigi import OpenFigiProvider

        provider = OpenFigiProvider()

    candidates = select_candidates(candidate_rows(conn, symbols), only_missing=only_missing)
    if limit:
        candidates = candidates[:limit]
    report = MapReport(candidates=len(candidates))
    if not candidates:
        log.info("map-identifiers: nothing to do")
        return report

    def submit(symbols: Sequence[str], jobs: Sequence[dict[str, str]]) -> list[list[dict[str, Any]]]:
        """Run jobs in provider-sized chunks. A failed chunk (transient 429,
        network reset) costs its jobs instead of the whole run: the HTTP cache
        holds the chunks that succeeded, and --only-missing resumes the rest
        next run."""
        responses: list[list[dict[str, Any]]] = []
        per_request = provider.jobs_per_request
        for i in range(0, len(jobs), per_request):
            try:
                responses.extend(provider.map_identifiers(jobs[i : i + per_request]))
            except Exception as exc:
                log.warning("map-identifiers: chunk failed, will retry next run: %s", exc)
                responses.extend([[] for _ in jobs[i : i + per_request]])
        return responses

    def best_per_symbol(
        symbols: Sequence[str], responses: Sequence[list[dict[str, Any]]]
    ) -> dict[str, Mapping[str, Any]]:
        out = {}
        for symbol, data in zip(symbols, responses):
            entry = data[0] if data else {}
            if entry.get("figi"):
                out[symbol] = entry
        return out

    jobs = [job_for_symbol(symbol) for symbol in candidates]
    log.info(
        "map-identifiers: %d instruments, %d request(s) of <=%d jobs",
        len(candidates),
        -(-len(jobs) // provider.jobs_per_request),
        provider.jobs_per_request,
    )
    best = best_per_symbol(candidates, submit(candidates, jobs))

    # Fallback pass for unresolved UK lines: Bloomberg's slash tickers.
    fallback = [s for s in candidates if s not in best]
    fallback_jobs = {s: fallback_job_for_symbol(s) for s in fallback}
    fallback = [s for s in fallback if fallback_jobs[s]]
    if fallback:
        log.info("map-identifiers: %d UK fallback job(s) with slash tickers", len(fallback))
        best.update(best_per_symbol(fallback, submit(fallback, [fallback_jobs[s] for s in fallback])))

    report.unresolved = [s for s in candidates if s not in best]

    ids = catalog.instrument_ids(conn, list(best))
    report.mapped = catalog.record_figi_mappings(conn, best, ids, source=SOURCE)
    conn.commit()

    log.info("map-identifiers: %d mapped, %d unresolved", report.mapped, len(report.unresolved))
    return report
