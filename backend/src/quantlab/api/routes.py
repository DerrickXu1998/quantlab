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
from quantlab.research import errors as research_errors
from quantlab.research import runner
from quantlab.signals import builtins as _builtins  # noqa: F401  (registers builtin rules)
from quantlab.signals import registry as signal_registry
from quantlab.storage import db, repository

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


# --- Model catalog and experiment runs (feature 005) -----------------------
#
# Still thin handlers: execution lives in quantlab.research.runner so it stays
# testable without HTTP (Constitution I). These map typed errors to statuses.


def _model_to_schema(rule) -> dict:
    return {
        "name": rule.name,
        "version": rule.version,
        "parameters": [
            {
                "name": spec.name,
                "type": spec.type,
                "default": spec.default,
                "minimum": spec.minimum,
                "maximum": spec.maximum,
                "choices": spec.choices,
                "description": spec.description,
            }
            for spec in rule.param_specs.values()
        ],
        "lookback_days": rule.lookback_days,
        "scale_class": rule.scale_class,
        "direction_semantics": rule.direction_semantics,
    }


@router.get(
    "/models",
    response_model=schemas.ModelList,
    tags=["models"],
    operation_id="listModels",
)
def list_models() -> dict:
    """Assembled from the registry at request time, so registering a model
    changes this response with no code change (Constitution II)."""
    rules = signal_registry.list_rules()
    return {"total": len(rules), "items": [_model_to_schema(rule) for rule in rules]}


def _is_registered(model_name: str, model_version: str) -> bool:
    try:
        signal_registry.get_rule(model_name, model_version)
    except KeyError:
        return False
    return True


def _run_response(run: dict) -> dict:
    run = dict(run)
    run["model_available"] = _is_registered(run["model_name"], run["model_version"])
    return run


@router.post(
    "/runs",
    response_model=schemas.Run,
    status_code=201,
    tags=["runs"],
    operation_id="createRun",
    dependencies=[Depends(require_seeded)],
)
def create_run(request: Request, body: schemas.RunRequest) -> dict:
    with db.connect(request.app.state.db_path) as conn:
        try:
            result = runner.run_experiment(
                conn,
                model_name=body.model_name,
                model_version=body.model_version,
                overrides=body.parameters,
                symbols=body.symbols,
                start_date=body.start_date,
                end_date=body.end_date,
            )
        except research_errors.UnknownModelError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except research_errors.UnknownSymbolError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except research_errors.ParameterValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (
            research_errors.InvalidWindowError,
            research_errors.WindowTooShortError,
            research_errors.SelectionTooLargeError,
        ) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        repository.save_run(conn, result)
        conn.commit()
        stored = repository.get_run(conn, result.id)
    return _run_response(stored)


@router.get(
    "/runs",
    response_model=schemas.RunList,
    tags=["runs"],
    operation_id="listRuns",
    dependencies=[Depends(require_seeded)],
)
def list_runs(request: Request, saved_only: bool = False) -> dict:
    with db.connect(request.app.state.db_path) as conn:
        result = repository.list_runs(conn, saved_only=saved_only)
    return {"total": result["total"], "items": [_run_response(r) for r in result["items"]]}


@router.get(
    "/runs/{run_id}",
    response_model=schemas.RunDetail,
    tags=["runs"],
    operation_id="getRun",
    dependencies=[Depends(require_seeded)],
)
def get_run(request: Request, run_id: str) -> dict:
    with db.connect(request.app.state.db_path) as conn:
        run = repository.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
        signals = repository.get_run_signals(conn, run_id)
    return {**_run_response(run), "signals": signals}


@router.patch(
    "/runs/{run_id}",
    response_model=schemas.Run,
    tags=["runs"],
    operation_id="saveRun",
    dependencies=[Depends(require_seeded)],
)
def save_run(request: Request, run_id: str, body: schemas.RunNameRequest) -> dict:
    with db.connect(request.app.state.db_path) as conn:
        if not repository.set_run_name(conn, run_id, body.name):
            raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
        conn.commit()
        run = repository.get_run(conn, run_id)
    return _run_response(run)


@router.delete(
    "/runs/{run_id}",
    status_code=204,
    tags=["runs"],
    operation_id="deleteRun",
    dependencies=[Depends(require_seeded)],
)
def delete_run(request: Request, run_id: str) -> None:
    with db.connect(request.app.state.db_path) as conn:
        if not repository.delete_run(conn, run_id):
            raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
        conn.commit()
