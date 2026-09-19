"""API routes per contracts/openapi.yaml. Thin handlers only (Constitution I):
every handler is a storage-repository call; zero analytics here.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path as FsPath
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from quantlab.api import schemas
from quantlab.storage import db, repository

router = APIRouter()

SYMBOL_PATTERN = r"^[A-Z]{2,8}$"


def require_seeded(request: Request) -> None:
    """Guard for data routes: 503 until the seed step has completed (FR-003)."""
    db_path = FsPath(request.app.state.db_path)
    if db_path.is_file():
        try:
            with db.connect(db_path) as conn:
                if repository.is_seeded(conn):
                    return
        except sqlite3.OperationalError:
            pass  # file exists but schema missing -> treat as unseeded
    raise HTTPException(status_code=503, detail="database is not seeded yet")


@router.get(
    "/health",
    response_model=schemas.Health,
    tags=["system"],
    operation_id="getHealth",
)
def get_health(request: Request) -> schemas.Health:
    db_path = FsPath(request.app.state.db_path)
    if db_path.is_file():
        try:
            with db.connect(db_path) as conn:
                if repository.is_seeded(conn):
                    return schemas.Health(seeded=True, signal_count=repository.signal_count(conn))
        except sqlite3.OperationalError:
            pass
    return schemas.Health(seeded=False, signal_count=0)


@router.get(
    "/instruments",
    response_model=schemas.InstrumentList,
    tags=["instruments"],
    operation_id="listInstruments",
    dependencies=[Depends(require_seeded)],
)
def list_instruments(request: Request) -> dict:
    with db.connect(request.app.state.db_path) as conn:
        return repository.list_instruments(conn)


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
    with db.connect(request.app.state.db_path) as conn:
        if not repository.instrument_exists(conn, symbol):
            raise HTTPException(status_code=404, detail=f"unknown symbol: {symbol}")
        return repository.get_prices(
            conn,
            symbol,
            start=start_date.isoformat() if start_date else None,
            end=end_date.isoformat() if end_date else None,
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
    with db.connect(request.app.state.db_path) as conn:
        return repository.list_signals(
            conn,
            instrument=instrument,
            signal_type=signal_type,
            direction=direction,
            start=start_date.isoformat() if start_date else None,
            end=end_date.isoformat() if end_date else None,
            sort=sort,
            limit=limit,
            offset=offset,
        )
