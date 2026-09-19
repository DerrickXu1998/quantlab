"""Ingestion: providers in, system of record out.

There is no transaction spanning Postgres and ClickHouse, so the write order
is the consistency mechanism:

  1. Catalog: upsert instruments, snapshot the universe, open the run. COMMIT.
     The run_id now exists and is visible, and is the version ClickHouse will
     use to supersede earlier copies of the same bar.
  2. ClickHouse: insert the bars, tagged with that run_id.
  3. Catalog: record rejects, close the run with real counts. COMMIT.

A crash between 2 and 3 leaves the run row `running`, which is the honest
state: bars may be present but nothing has vouched for them. `catalog.stale_runs`
surfaces those, and re-running the same range is safe because
ReplacingMergeTree keeps the highest run_id.

A crash between 1 and 2 leaves an open run with no bars -- also safe, also
visible. What cannot happen is bars that no run vouches for.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import pandas as pd

from ..schema import Currency, Security
from . import bars as bars_mod
from . import catalog

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    """What a run did. Printed by the CLI, asserted on by the tests."""

    run_id: int
    status: str
    symbols_requested: int = 0
    symbols_ok: int = 0
    rows_written: int = 0
    rows_rejected: int = 0
    missing: list[str] = field(default_factory=list)
    reject_reasons: dict[str, int] = field(default_factory=dict)
    snapshot_id: int | None = None
    providers_used: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"run {self.run_id}: {self.status}",
            f"  symbols   {self.symbols_ok}/{self.symbols_requested}",
            f"  rows      {self.rows_written} written, {self.rows_rejected} rejected",
        ]
        if self.providers_used:
            used = ", ".join(f"{k}={v}" for k, v in sorted(self.providers_used.items()))
            lines.append(f"  providers {used}")
        if self.snapshot_id is not None:
            lines.append(f"  universe  snapshot {self.snapshot_id}")
        for reason, count in sorted(self.reject_reasons.items()):
            lines.append(f"  rejected  {count:>6}  {reason}")
        if self.missing:
            shown = ", ".join(self.missing[:10])
            more = f" (+{len(self.missing) - 10} more)" if len(self.missing) > 10 else ""
            lines.append(f"  missing   {shown}{more}")
        return "\n".join(lines)


def _securities_for(
    symbols: Sequence[str],
    known: Mapping[str, Security],
    currencies: Mapping[str, Currency],
) -> dict[str, Security]:
    """Fill in a Security for every symbol, inventing a minimal one if needed."""
    out: dict[str, Security] = {}
    for symbol in symbols:
        sec = known.get(symbol)
        if sec is None:
            suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
            is_uk = suffix in {"LON", "L", "UK", "LSE"}
            sec = Security(
                symbol=symbol,
                exchange="XLON" if is_uk else "XNYS",
                country="GB" if is_uk else "US",
                currency=currencies.get(symbol, Currency.GBX if is_uk else Currency.USD),
            )
        out[symbol] = sec
    return out


def ingest_prices(
    conn,
    client,
    symbols: Sequence[str] | None = None,
    *,
    start: str = "2015-01-01",
    end: str = "",
    frequency: str = "1d",
    providers: Sequence[str] = ("stooq",),
    provider_options: Mapping[str, Mapping[str, Any]] | None = None,
    universe: str = "",
    universe_params: Mapping[str, Any] | None = None,
    snapshot_date: dt.date | str | None = None,
    max_workers: int | None = None,
) -> IngestReport:
    """Fetch history for `symbols` (and/or a universe) and load it into the store.

    Idempotent: re-running the same range writes bars with a higher run_id,
    which supersede the earlier copies. Reads go through the FINAL view, so a
    re-ingest is never visible as duplicated rows.
    """
    from ..data import load

    panel, ctx = load(
        symbols=symbols,
        start=start,
        end=end,
        frequency=frequency,
        providers=providers,
        provider_options=provider_options,
        universe=universe,
        universe_params=universe_params,
        normalise_currency=True,
        max_workers=max_workers,
        return_context=True,
    )

    requested = sorted(
        set(panel.index.get_level_values("symbol").unique())
        | set(ctx.securities)
        | set(symbols or [])
    )
    missing = list(ctx.extras.get("missing", []))
    provider_used: dict[str, str] = dict(ctx.extras.get("provider_used", {}))
    securities = _securities_for(requested, ctx.securities, ctx.currencies)

    # -- step 1: catalog, committed before any bar is written ---------------
    ids = catalog.ensure_instruments(conn, securities, ctx.currencies)

    snapshot_id = None
    if universe:
        members = [s.symbol for s in ctx.securities.values()] or requested
        snapshot_id = catalog.snapshot_universe(
            conn, universe, members, ids, snapshot_date=snapshot_date, source=",".join(providers)
        )

    source_label = providers[0] if len(providers) == 1 else "multi"
    run_id = catalog.start_run(
        conn,
        source=source_label,
        kind="prices",
        requested_start=start or None,
        requested_end=end or None,
        frequency=frequency,
        symbols_requested=len(requested),
        snapshot_id=snapshot_id,
        params={
            "providers": list(providers),
            "universe": universe or None,
            "symbols": list(symbols) if symbols else None,
        },
    )

    for provider_name in set(provider_used.values()):
        try:
            from ..data import get_provider

            provider = get_provider(provider_name)
        except Exception:  # provider no longer constructible -- mapping is optional
            continue
        mapping = {
            symbol: provider.to_native(symbol)
            for symbol, used in provider_used.items()
            if used == provider_name and symbol in ids
        }
        catalog.map_vendor_symbols(conn, provider_name, mapping, ids)

    conn.commit()

    # -- step 2: bars ------------------------------------------------------
    try:
        result = bars_mod.write_bars(
            client,
            panel,
            run_id=run_id,
            ids=ids,
            currencies=ctx.currencies,
            source_by_symbol=provider_used,
            source=source_label,
            frequency=frequency,
        )
    except Exception as exc:
        catalog.finish_run(conn, run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        conn.commit()
        raise

    # -- step 3: close the run --------------------------------------------
    catalog.record_rejects(conn, run_id, result.rejected)

    if result.written == 0 and requested:
        status = "failed"
    elif missing or result.rejected_count:
        status = "partial"
    else:
        status = "ok"

    catalog.finish_run(
        conn,
        run_id,
        status=status,
        rows_written=result.written,
        rows_rejected=result.rejected_count,
        symbols_ok=result.symbols_ok,
        error=f"{len(missing)} symbols returned no data" if missing else None,
    )
    conn.commit()

    counts: dict[str, int] = {}
    for used in provider_used.values():
        counts[used] = counts.get(used, 0) + 1

    return IngestReport(
        run_id=run_id,
        status=status,
        symbols_requested=len(requested),
        symbols_ok=result.symbols_ok,
        rows_written=result.written,
        rows_rejected=result.rejected_count,
        missing=missing,
        reject_reasons=result.reasons,
        snapshot_id=snapshot_id,
        providers_used=counts,
    )


def ingest_corporate_actions(
    conn,
    symbols: Sequence[str],
    *,
    start: str = "",
    end: str = "",
    provider: str = "yahoo",
) -> IngestReport:
    """Pull dividends and splits into the catalog.

    Yahoo is the only free source of UK corporate actions and it breaks
    periodically (Constitution III) -- a symbol that fails is recorded as
    missing, never fatal.
    """
    from ..data import get_provider

    adapter = get_provider(provider)
    ids = catalog.instrument_ids(conn, list(symbols))

    run_id = catalog.start_run(
        conn,
        source=provider,
        kind="corporate_actions",
        requested_start=start or None,
        requested_end=end or None,
        symbols_requested=len(symbols),
        params={"symbols": list(symbols)},
    )

    frames: list[pd.DataFrame] = []
    missing: list[str] = []
    for symbol in symbols:
        if symbol not in ids:
            missing.append(symbol)
            continue
        try:
            actions = adapter.corporate_actions(symbol, start, end)
        except Exception as exc:
            log.warning("%s: corporate actions unavailable: %s", symbol, exc)
            missing.append(symbol)
            continue
        if actions is None or actions.empty:
            continue
        frames.append(_melt_actions(symbol, actions))

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    written = catalog.write_corporate_actions(
        conn, combined, run_id=run_id, ids=ids, source=provider
    )

    status = "partial" if missing else ("ok" if written else "partial")
    catalog.finish_run(
        conn,
        run_id,
        status=status,
        rows_written=written,
        symbols_ok=len(symbols) - len(missing),
        error=f"{len(missing)} symbols returned no actions" if missing else None,
    )
    return IngestReport(
        run_id=run_id,
        status=status,
        symbols_requested=len(symbols),
        symbols_ok=len(symbols) - len(missing),
        rows_written=written,
        missing=missing,
    )


def _melt_actions(symbol: str, actions: pd.DataFrame) -> pd.DataFrame:
    """Provider shape (date index, dividend, split_ratio) -> long action rows."""
    frame = actions.reset_index()
    date_col = frame.columns[0]
    rows: list[dict[str, Any]] = []
    for row in frame.itertuples():
        ex_date = getattr(row, date_col)
        dividend = getattr(row, "dividend", None)
        split = getattr(row, "split_ratio", None)
        if pd.notna(dividend) and float(dividend or 0) > 0:
            rows.append(
                {
                    "symbol": symbol,
                    "ex_date": ex_date,
                    "action_type": "dividend",
                    "dividend": float(dividend),
                    "split_ratio": None,
                    "currency": None,
                }
            )
        if pd.notna(split) and float(split or 0) > 0 and float(split) != 1.0:
            rows.append(
                {
                    "symbol": symbol,
                    "ex_date": ex_date,
                    "action_type": "split",
                    "dividend": None,
                    "split_ratio": float(split),
                    "currency": None,
                }
            )
    return pd.DataFrame(rows)
