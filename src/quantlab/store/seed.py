"""Seed the warehouse with deterministic synthetic bars -- no network needed.

Uses the exact write path of a real ingest (`store.ingest.ingest_prices`
spells out why the order matters): instruments and the run row land in the
Postgres catalog and commit first, bars go to ClickHouse tagged with that
run_id, and the run closes with real counts. Re-running is safe:
ReplacingMergeTree(run_id) supersedes the earlier copy of every bar, and
reads through the FINAL view never see duplicates.
"""
from __future__ import annotations

import datetime as dt
from typing import Sequence

from ..schema import Currency, Security, concat_panel
from ..synthetic import (
    DEFAULT_END,
    DEFAULT_SEED,
    DEFAULT_START,
    SOURCE,
    SyntheticSpec,
    generate_bars,
)
from . import bars as bars_mod
from . import catalog
from .ingest import IngestReport


def _securities_for(specs: Sequence[SyntheticSpec]) -> dict[str, Security]:
    return {
        spec.symbol: Security(
            symbol=spec.symbol,
            name=spec.name,
            exchange="XNYS",
            country="US",
            currency=Currency.USD,
            sector="Synthetic",
            meta={"synthetic": True, "regime_profile": spec.profile},
        )
        for spec in specs
    }


def seed_warehouse(
    conn,
    client,
    specs: Sequence[SyntheticSpec],
    *,
    start: str | dt.date = DEFAULT_START,
    end: str | dt.date = DEFAULT_END,
    seed: str | None = None,
    frequency: str = "1d",
) -> IngestReport:
    """Generate bars for `specs` and load them into the store.

    Idempotent: re-seeding the same range writes bars with a higher run_id,
    which supersede the earlier copies. The generated bars are a pure function
    of (symbol, start, end, seed), so a re-run writes identical values.
    """
    securities = _securities_for(specs)
    currencies = {symbol: Currency.USD for symbol in securities}

    # -- step 1: catalog, committed before any bar is written ---------------
    ids = catalog.ensure_instruments(conn, securities, currencies)
    run_id = catalog.start_run(
        conn,
        source=SOURCE,
        kind="prices",
        requested_start=str(start) or None,
        requested_end=str(end) or None,
        frequency=frequency,
        symbols_requested=len(specs),
        params={
            "synthetic": True,
            "seed": seed or DEFAULT_SEED,
            "symbols": [spec.symbol for spec in specs],
        },
    )
    conn.commit()

    # -- step 2: bars ------------------------------------------------------
    panel = concat_panel(
        {
            spec.symbol: generate_bars(spec.symbol, start, end, seed=seed, profile=spec.profile)
            for spec in specs
        }
    )
    try:
        result = bars_mod.write_bars(
            client,
            panel,
            run_id=run_id,
            ids=ids,
            currencies=currencies,
            source=SOURCE,
            frequency=frequency,
        )
    except Exception as exc:
        catalog.finish_run(conn, run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        conn.commit()
        raise

    # -- step 3: close the run ---------------------------------------------
    catalog.record_rejects(conn, run_id, result.rejected)

    if result.written == 0 and specs:
        status = "failed"
    elif result.rejected_count:
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
    )
    conn.commit()

    return IngestReport(
        run_id=run_id,
        status=status,
        symbols_requested=len(specs),
        symbols_ok=result.symbols_ok,
        rows_written=result.written,
        rows_rejected=result.rejected_count,
        reject_reasons=result.reasons,
        providers_used={SOURCE: result.symbols_ok},
    )
