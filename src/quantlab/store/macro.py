"""Macro series as pseudo-instrument bars.

BoE IADB series (FX fixings, Bank Rate, gilt yields, money-supply growth) are
point series, not OHLCV -- but the warehouse, the feature engine and every
read path already speak bars. So each series becomes a synthetic instrument
(``GBPUSD.BOE`` and friends) whose bars are degenerate: open=high=low=close=
value, adj_close=value, volume=0. That is the smallest deviation the schema
allows -- `bars.validate` accepts volume 0 and equal OHLC -- and it is what
lets ``gbp_usd`` sit in ClickHouse next to the equity bars it converts.

One honest caveat: `bars.validate` insists on strictly positive prices, so a
series that goes non-positive (M4 growth did, post-GFC) has those days
quarantined into ingest_rejects rather than written. They are not dropped
silently; the run closes as "partial" and the rejects carry the reason.
"""
from __future__ import annotations

import datetime as dt
from typing import Mapping, Sequence

import pandas as pd

from ..providers.boe import COMMON_SERIES
from ..schema import Currency, Security, concat_panel, validate_bars
from . import bars as bars_mod
from . import catalog
from .ingest import IngestReport

SOURCE = "boe"

# The five COMMON_SERIES as pseudo-symbols. The suffix marks the origin, the
# root is what a signal would look up.
DEFAULT_MAPPING: dict[str, str] = {
    "XUDLUSS": "GBPUSD.BOE",
    "XUDLERS": "GBPEUR.BOE",
    "IUDBEDR": "BANKRATE.BOE",
    "IUDSNPY": "GILT10Y.BOE",
    "LPMVWYR": "M4GROWTH.BOE",
}

# Quote currency of the stored numbers: an FX fixing is stored in its quote
# currency, the UK rate series are percentages of GBP amounts. The Currency
# enum has no "percent", so GBP is the least-wrong 3-letter value (the
# instruments table enforces char_length = 3).
_CURRENCY: dict[str, Currency] = {
    "XUDLUSS": Currency.USD,
    "XUDLERS": Currency.EUR,
    "IUDBEDR": Currency.GBP,
    "IUDSNPY": Currency.GBP,
    "LPMVWYR": Currency.GBP,
}


def series_to_bars(series: pd.Series, *, symbol: str = "") -> pd.DataFrame:
    """One date-indexed macro series -> canonical bars.

    NaN observations are dropped (BoE series have gaps around holidays and
    methodology changes). The result passes `schema.validate_bars`; whether it
    survives `bars.validate` depends on the values being strictly positive.
    """
    values = pd.to_numeric(series, errors="coerce").dropna()
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": 0.0,
            "adj_close": values,
        }
    )
    return validate_bars(frame, symbol=symbol)


def _securities_for(mapping: Mapping[str, str]) -> dict[str, Security]:
    return {
        symbol: Security(
            symbol=symbol,
            name=COMMON_SERIES.get(code, code),
            exchange="",          # macro series trade on no exchange
            country="GB",
            currency=_CURRENCY.get(code, Currency.GBP),
            sector="Macro",
            meta={"macro": True, "series_code": code, "source": SOURCE},
        )
        for code, symbol in mapping.items()
    }


def ingest_macro_series(
    conn,
    client,
    mapping: Mapping[str, str],
    start: str | dt.date,
    end: str | dt.date = "",
    *,
    source: str = SOURCE,
    provider=None,
    frequency: str = "1d",
) -> IngestReport:
    """Fetch BoE series and load them as pseudo-instrument bars.

    Same write path and ordering as `seed_warehouse`: catalog rows and the run
    commit first, bars go to ClickHouse tagged with the run_id, the run closes
    with real counts. Re-running the same range is idempotent
    (ReplacingMergeTree supersedes the earlier copy).

    `provider` is injectable for tests; anything with the BoeProvider
    `series_batch(codes, start, end)` interface works.
    """
    if not mapping:
        raise ValueError("ingest_macro_series needs at least one series mapping")
    if provider is None:
        from ..providers.boe import BoeProvider

        provider = BoeProvider()

    securities = _securities_for(mapping)
    currencies = {symbol: sec.currency for symbol, sec in securities.items()}

    # -- step 1: catalog, committed before any bar is written ---------------
    ids = catalog.ensure_instruments(conn, securities, currencies)
    catalog.map_vendor_symbols(
        conn, source, {symbol: code for code, symbol in mapping.items()}, ids
    )
    run_id = catalog.start_run(
        conn,
        source=source,
        kind="prices",
        requested_start=str(start) or None,
        requested_end=str(end) or None,
        frequency=frequency,
        symbols_requested=len(mapping),
        params={"macro": True, "series": dict(mapping)},
    )
    conn.commit()

    # -- step 2: fetch and write --------------------------------------------
    try:
        frame = provider.series_batch(list(mapping), start, end)
        panel = concat_panel(
            {
                symbol: series_to_bars(frame[code], symbol=symbol)
                for code, symbol in mapping.items()
                if code in frame.columns
            }
        )
        missing = [symbol for code, symbol in mapping.items() if code not in frame.columns]
        result = bars_mod.write_bars(
            client,
            panel,
            run_id=run_id,
            ids=ids,
            currencies=currencies,
            source=source,
            frequency=frequency,
        )
    except Exception as exc:
        catalog.finish_run(conn, run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        conn.commit()
        raise

    # -- step 3: close the run ----------------------------------------------
    catalog.record_rejects(conn, run_id, result.rejected)

    if result.written == 0 and mapping:
        status = "failed"
    elif result.rejected_count or missing:
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
        symbols_requested=len(mapping),
        symbols_ok=result.symbols_ok,
        rows_written=result.written,
        rows_rejected=result.rejected_count,
        missing=missing,
        reject_reasons=result.reasons,
        providers_used={source: result.symbols_ok},
    )


def parse_series_args(pairs: Sequence[str] | None) -> dict[str, str]:
    """--series CODE:SYMBOL pairs -> {code: symbol}; empty means the defaults."""
    if not pairs:
        return dict(DEFAULT_MAPPING)
    out: dict[str, str] = {}
    for item in pairs:
        if ":" not in item:
            raise ValueError(f"--series expects CODE:SYMBOL, got {item!r}")
        code, symbol = item.split(":", 1)
        if not code.strip() or not symbol.strip():
            raise ValueError(f"--series expects CODE:SYMBOL, got {item!r}")
        out[code.strip().upper()] = symbol.strip()
    return out
