"""API routes per contracts/openapi.yaml. Thin handlers only (Constitution I):
every handler is a storage call; zero analytics here.

Handlers do not know which dataset is behind them. ``app.state.backend`` is
either the real warehouse (ClickHouse bars + Postgres catalog) or the
synthetic SQLite demo, chosen once at startup.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from quantlab.api import schemas

router = APIRouter()

# Real tickers are not bare uppercase words: quantlab's canonical ids carry an
# exchange suffix (AAPL.US, HSBA.LON) and some venues use digits or hyphens
# (BRK-B.US, 0700.HK). The old ^[A-Z]{2,8}$ fitted only the synthetic universe.
SYMBOL_PATTERN = r"^[A-Z0-9][A-Z0-9._\-]{0,19}$"


def backend(request: Request):
    return request.app.state.backend


def require_seeded(request: Request) -> None:
    """Guard for data routes: 503 until there is data to serve (FR-003)."""
    has_data, _ = backend(request).health()
    if not has_data:
        raise HTTPException(status_code=503, detail="database is not seeded yet")


@router.get(
    "/health",
    response_model=schemas.Health,
    tags=["system"],
    operation_id="getHealth",
)
def get_health(request: Request) -> schemas.Health:
    has_data, signal_count = backend(request).health()
    return schemas.Health(seeded=has_data, signal_count=signal_count)


@router.get(
    "/instruments",
    response_model=schemas.InstrumentList,
    tags=["instruments"],
    operation_id="listInstruments",
    dependencies=[Depends(require_seeded)],
)
def list_instruments(request: Request) -> dict:
    return backend(request).list_instruments()


@router.get(
    "/instruments/{symbol}/prices",
    response_model=schemas.PriceBarList,
    tags=["instruments"],
    operation_id="getPrices",
    dependencies=[Depends(require_seeded)],
)
def get_prices(
    request: Request,
    symbol: Annotated[str, Path(pattern=SYMBOL_PATTERN)],
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    store = backend(request)
    if not store.instrument_exists(symbol):
        raise HTTPException(status_code=404, detail=f"unknown symbol: {symbol}")
    return store.get_prices(
        symbol,
        start_date.isoformat() if start_date else None,
        end_date.isoformat() if end_date else None,
    )


@router.get(
    "/signals",
    response_model=schemas.SignalList,
    tags=["signals"],
    operation_id="listSignals",
    dependencies=[Depends(require_seeded)],
)
def list_signals(
    request: Request,
    instrument: Annotated[str | None, Query(pattern=SYMBOL_PATTERN)] = None,
    signal_type: str | None = None,
    direction: Literal["bullish", "bearish"] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    sort: Literal["date_asc", "date_desc"] = "date_desc",
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")
    return backend(request).list_signals(
        instrument=instrument,
        signal_type=signal_type,
        direction=direction,
        start=start_date.isoformat() if start_date else None,
        end=end_date.isoformat() if end_date else None,
        sort=sort,
        limit=limit,
        offset=offset,
    )
