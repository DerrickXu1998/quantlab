"""API routes per contracts/openapi.yaml. Thin handlers only (Constitution I):
every handler is a storage call; zero analytics here.

Handlers do not know which dataset is behind them. ``app.state.backend`` is
either the real warehouse (ClickHouse bars + Postgres catalog) or the
synthetic SQLite demo, chosen once at startup.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse

from quantlab import auth as auth_lib
from quantlab.api import schemas, security
from quantlab.api.security import CurrentUser, owner_scope
from quantlab.replay import engine as replay_engine
from quantlab.research import errors as research_errors
from quantlab.research import performance, runner
from quantlab.signals import registry as signal_registry
from quantlab.strategy import StrategySpec, StrategyValidationError, templates
from quantlab.streaming import bus as streaming_bus
from quantlab.streaming import live as streaming_live

router = APIRouter()

# Real tickers are not bare uppercase words: quantlab's canonical ids carry an
# exchange suffix (AAPL.US, HSBA.LON) and some venues use digits or hyphens
# (BRK-B.US, 0700.HK). The old ^[A-Z]{2,8}$ fitted only the synthetic universe.
SYMBOL_PATTERN = r"^[A-Z0-9][A-Z0-9._\-]{0,19}$"


def backend(request: Request):
    return request.app.state.backend


def experiments(request: Request):
    """Where runs are kept. A separate seam from the dataset: on the
    warehouse these are different database systems."""
    return request.app.state.experiments


def strategies_store(request: Request):
    """Where saved strategies are kept. Every method takes an owner."""
    return request.app.state.strategies


def auth_service(request: Request):
    return request.app.state.auth


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
    active = backend(request)
    has_data, signal_count = active.health()
    return schemas.Health(
        dataset=active.name,
        seeded=has_data,
        signal_count=signal_count,
        # Unauthenticated on purpose: the SPA has to know whether to show a
        # sign-in gate before it can possibly have a token.
        auth_required=auth_lib.auth_required(),
    )


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
        "category": rule.category,
        "summary": rule.summary,
        "roles": list(rule.roles),
        "requires_facts": list(rule.requires_facts),
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


def _run_response(run: dict, dataset: str = "sqlite") -> dict:
    run = dict(run)
    run.pop("owner_id", None)  # internal; the caller is the owner by construction
    run["model_available"] = _is_registered(run["model_name"], run["model_version"])
    run.setdefault("dataset", dataset)
    # A run recorded against a different dataset stays readable but cannot be
    # reproduced as recorded.
    run["re_runnable"] = run["dataset"] == dataset
    return run


def _resolve_request_strategy(request: Request, body: schemas.RunRequest, user) -> dict | None:
    """The strategy a run request names, whichever way it names it.

    Exactly one of the three forms is accepted. Silently preferring one when
    two are given would run something other than what the caller wrote.
    """
    given = [
        name
        for name, value in (
            ("model_name", body.model_name),
            ("strategy_id", body.strategy_id),
            ("strategy", body.strategy),
        )
        if value
    ]
    if len(given) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"give exactly one of model_name, strategy_id or strategy; got {given}",
        )
    if not given:
        raise HTTPException(
            status_code=400,
            detail="a run needs one of model_name, strategy_id or strategy",
        )

    if body.strategy_id:
        saved = strategies_store(request).get(owner_scope(user) or user.id, body.strategy_id)
        if saved is None:
            # Another user's strategy reads as absent, never as forbidden.
            raise HTTPException(
                status_code=404, detail=f"unknown strategy: {body.strategy_id}"
            )
        return saved
    if body.strategy is not None:
        return body.strategy.model_dump()
    return None


@router.post(
    "/runs",
    response_model=schemas.Run,
    status_code=201,
    tags=["runs"],
    operation_id="createRun",
    dependencies=[Depends(require_seeded)],
)
def create_run(request: Request, body: schemas.RunRequest, user: CurrentUser) -> dict:
    active = backend(request)
    store = experiments(request)
    spec = _resolve_request_strategy(request, body, user)
    try:
        result = runner.run_experiment(
            active,
            strategy=spec,
            model_name=body.model_name,
            model_version=body.model_version,
            overrides=body.parameters,
            execution=body.execution.model_dump() if body.execution else None,
            symbols=body.symbols,
            start_date=body.start_date,
            end_date=body.end_date,
            owner_id=user.id,
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

    store.save_run(result)
    stored = store.get_run(result.id, owner_scope(user))
    return _run_response(stored, active.name)


@router.get(
    "/runs",
    response_model=schemas.RunList,
    tags=["runs"],
    operation_id="listRuns",
    dependencies=[Depends(require_seeded)],
)
def list_runs(request: Request, user: CurrentUser, saved_only: bool = False) -> dict:
    result = experiments(request).list_runs(
        saved_only=saved_only, owner_id=owner_scope(user)
    )
    active = backend(request).name
    return {"total": result["total"], "items": [_run_response(r, active) for r in result["items"]]}


@router.get(
    "/runs/{run_id}",
    response_model=schemas.RunDetail,
    tags=["runs"],
    operation_id="getRun",
    dependencies=[Depends(require_seeded)],
)
def get_run(request: Request, run_id: str, user: CurrentUser) -> dict:
    store = experiments(request)
    run = store.get_run(run_id, owner_scope(user))
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    signals = store.get_run_signals(run_id)
    return {**_run_response(run, backend(request).name), "signals": signals}

@router.get(
    "/runs/{run_id}/performance",
    response_model=schemas.RunPerformance,
    tags=["runs"],
    operation_id="getRunPerformance",
    dependencies=[Depends(require_seeded)],
)
def get_run_performance(request: Request, run_id: str, user: CurrentUser) -> dict:
    """Still a thin handler: the analytics live in research.performance, which
    is where the frontend cannot reach them (Constitution V)."""
    store = experiments(request)
    run = store.get_run(run_id, owner_scope(user))
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    # A failed run has no performance. Zeroed figures would read as a flat
    # book rather than as an absent result -- the same distinction the UI
    # already draws between an empty run and a failed one.
    if run["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"run {run_id} failed; it has no performance")

    symbols = list(run["symbols"])
    # Bars are loaded from the warm-up start, not the window start: a stop set
    # from an ATR on the first session of the window needs the sessions behind
    # it. Nothing can happen in the warm-up -- no signal is dated there.
    signals, bars = replay_engine.load_replay_inputs(backend(request), store, run)
    result = performance.compute_performance(
        run_id=run_id,
        signals=signals,
        bars_by_symbol=bars,
        symbols=symbols,
        execution=runner.execution_config_for(run),
        window_start=run["start_date"],
        window_end=run["end_date"],
    )
    return asdict(result)


@router.patch(
    "/runs/{run_id}",
    response_model=schemas.Run,
    tags=["runs"],
    operation_id="saveRun",
    dependencies=[Depends(require_seeded)],
)
def save_run(
    request: Request, run_id: str, body: schemas.RunNameRequest, user: CurrentUser
) -> dict:
    store = experiments(request)
    if not store.set_run_name(run_id, body.name, owner_scope(user)):
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    run = store.get_run(run_id, owner_scope(user))
    return _run_response(run, backend(request).name)


@router.delete(
    "/runs/{run_id}",
    status_code=204,
    tags=["runs"],
    operation_id="deleteRun",
    dependencies=[Depends(require_seeded)],
)
def delete_run(request: Request, run_id: str, user: CurrentUser) -> None:
    if not experiments(request).delete_run(run_id, owner_scope(user)):
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")


# --- Historical replay ------------------------------------------------------
#
# Thin handlers again: the engine lives in quantlab.replay so it is testable
# without HTTP (Constitution I). These only resolve the run, guard its state,
# and frame the events.


def _replayable_run(request: Request, run_id: str, user) -> dict:
    store = experiments(request)
    run = store.get_run(run_id, owner_scope(user))
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    # A failed run has nothing to replay; as with performance, zeroed output
    # would read as a flat book rather than as an absent result.
    if run["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"run {run_id} failed; it cannot be replayed")
    return run


@router.get(
    "/runs/{run_id}/replay/stream",
    tags=["replay"],
    operation_id="streamRunReplay",
    dependencies=[Depends(require_seeded)],
)
def stream_run_replay(
    request: Request,
    run_id: str,
    user: CurrentUser,
    interval_ms: Annotated[int, Query(ge=0, le=10_000)] = 0,
    max_events: Annotated[int, Query(ge=1, le=5_000_000)] = 250_000,
    step: Annotated[int, Query(ge=1)] = 1,
) -> StreamingResponse:
    run = _replayable_run(request, run_id, user)
    signals, bars = replay_engine.load_replay_inputs(backend(request), experiments(request), run)

    def frames():
        emitted = 0
        truncated = False
        # A sync generator: StreamingResponse iterates it in a threadpool, so
        # the optional pacing sleep never blocks the event loop.
        for event in replay_engine.replay_events(run, signals, bars, step=step):
            if emitted >= max_events:
                truncated = True
                break
            yield f"data: {json.dumps(replay_engine.to_dict(event))}\n\n"
            emitted += 1
            if interval_ms and isinstance(event, replay_engine.ReplayEquity):
                time.sleep(interval_ms / 1000)
        if truncated:
            detail = f"max_events={max_events} reached before the summary"
            yield f"data: {json.dumps({'event': 'truncated', 'detail': detail})}\n\n"

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/runs/{run_id}/replay/summary",
    response_model=schemas.ReplaySummary,
    tags=["replay"],
    operation_id="getRunReplaySummary",
    dependencies=[Depends(require_seeded)],
)
def get_run_replay_summary(request: Request, run_id: str, user: CurrentUser) -> dict:
    run = _replayable_run(request, run_id, user)
    signals, bars = replay_engine.load_replay_inputs(backend(request), experiments(request), run)
    return asdict(replay_engine.replay_summary(run, signals, bars))


# --- Live replay over the event bus -------------------------------------------
#
# The streaming counterpart of the batch replay above: instead of a stored
# run's bars, the events are driven by bars arriving on the Kafka replay topic
# (see quantlab.streaming). Thin handler again: resolve and validate, connect
# (failing fast with a 503 when the bus is absent), frame the events.


@router.get(
    "/replay/live/stream",
    tags=["replay"],
    operation_id="streamLiveReplay",
)
def stream_live_replay(
    model: str = "sma-crossover",
    symbols: Annotated[str, Query(description="Comma-separated canonical symbols")] = "",
    start: date | None = None,
    end: date | None = None,
    params: Annotated[str | None, Query(description="JSON object of parameter overrides")] = None,
    initial_cash: Annotated[float, Query(gt=0)] = performance.INITIAL_CAPITAL,
    max_events: Annotated[int, Query(ge=1, le=5_000_000)] = 250_000,
) -> StreamingResponse:
    if not streaming_bus.configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "live replay is not configured: QUANTLAB_KAFKA_BROKERS is unset "
                "(start the stack with the 'streaming' profile)"
            ),
        )
    if start is None or end is None:
        raise HTTPException(status_code=400, detail="start and end are required (YYYY-MM-DD)")
    symbol_list = sorted({s.strip() for s in symbols.split(",") if s.strip()})
    if not symbol_list:
        raise HTTPException(status_code=400, detail="symbols must name at least one instrument")
    if start > end:
        raise HTTPException(status_code=400, detail="start must be on or before end")
    try:
        overrides = json.loads(params) if params else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"params is not valid JSON: {exc}") from exc
    if not isinstance(overrides, dict):
        raise HTTPException(status_code=400, detail="params must be a JSON object")

    # Resolve and validate eagerly, so a bad request is a 404/422 rather than
    # a stream that dies on its first frame.
    try:
        streaming_live.resolve_rule(model, overrides)
    except research_errors.UnknownModelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except research_errors.ParameterValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    stream = streaming_bus.KafkaBarStream(
        streaming_bus.brokers(),
        streaming_bus.topic(),
        symbol_list,
        start.isoformat(),
        end.isoformat(),
    )
    try:
        stream.open()
    except streaming_bus.BusUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    events = streaming_live.live_replay_events(
        model, overrides, symbol_list, start.isoformat(), end.isoformat(), stream,
        initial_cash=initial_cash,
    )

    def frames():
        emitted = 0
        truncated = False
        # A sync generator: StreamingResponse iterates it in a threadpool, so
        # blocking on the Kafka consumer never stalls the event loop.
        try:
            for event in events:
                if emitted >= max_events:
                    truncated = True
                    break
                yield f"data: {json.dumps(replay_engine.to_dict(event))}\n\n"
                emitted += 1
        finally:
            stream.close()
        if truncated:
            detail = f"max_events={max_events} reached before the summary"
            yield f"data: {json.dumps({'event': 'truncated', 'detail': detail})}\n\n"

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Identity ---------------------------------------------------------------
#
# Thin handlers again: every security decision lives in quantlab.auth, and this
# only maps a typed failure to a status code. The one rule enforced here is
# that registration is helpful about *why* a request failed and login is not --
# a login that explains itself is an account-enumeration oracle.


@router.post(
    "/auth/register",
    response_model=schemas.SessionOut,
    status_code=201,
    tags=["auth"],
    operation_id="register",
)
def register(request: Request, body: schemas.Credentials) -> dict:
    try:
        session = auth_service(request).register(body.email, body.password)
    except auth_lib.EmailAlreadyRegistered as exc:
        # A 409 here does disclose that an address is registered. That is
        # unavoidable for a self-service signup form -- refusing to say so
        # would mean silently not creating the account -- and it is why the
        # *login* path is the one hardened against enumeration.
        raise HTTPException(
            status_code=409, detail="that email address is already registered"
        ) from exc
    except auth_lib.PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "user": session.user.to_dict(),
        "token": session.token,
        "expires_at": session.expires_at,
    }


@router.post(
    "/auth/login",
    response_model=schemas.SessionOut,
    tags=["auth"],
    operation_id="login",
)
def login(request: Request, body: schemas.Credentials) -> dict:
    try:
        session = auth_service(request).login(body.email, body.password)
    except auth_lib.RateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except auth_lib.AuthError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return {
        "user": session.user.to_dict(),
        "token": session.token,
        "expires_at": session.expires_at,
    }


@router.post(
    "/auth/logout",
    status_code=204,
    tags=["auth"],
    operation_id="logout",
)
def logout(request: Request, user: CurrentUser) -> None:
    """Revoke this session and no other.

    Possible only because a session is a row. A signed stateless token could
    not be withdrawn before it expired, which would make this endpoint a
    gesture rather than a control.
    """
    token = security.bearer_token(request.headers.get("authorization"))
    if token:
        auth_service(request).logout(token)


@router.get(
    "/auth/me",
    response_model=schemas.UserOut,
    tags=["auth"],
    operation_id="getCurrentUser",
)
def get_current_user(user: CurrentUser) -> dict:
    return user.to_dict()


# --- Strategies -------------------------------------------------------------
#
# Every handler is scoped to the caller. A strategy that is not theirs reads as
# absent rather than forbidden: a 403 confirms the row exists.


def _strategy_response(stored: dict) -> dict:
    """Attach the warnings a spec generates about itself.

    Computed rather than stored: a strategy with no exit component was legal
    when it was saved and is still legal, but what is worth flagging about it
    can change as the engine does, and a stored copy would go stale.
    """
    body = dict(stored)
    try:
        body["warnings"] = StrategySpec.from_dict(stored).warnings
    except (StrategyValidationError, ValueError):
        # A stored spec this build can no longer validate is still readable;
        # saying so is more useful than refusing to list it at all.
        body["warnings"] = [
            "This strategy cannot be validated by this version of QuantLab and "
            "may not be runnable."
        ]
    return body


def _parse_strategy(body: schemas.StrategyRequest) -> StrategySpec:
    try:
        return StrategySpec.from_dict(body.model_dump())
    except (StrategyValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/strategies",
    response_model=schemas.StrategyList,
    tags=["strategies"],
    operation_id="listStrategies",
)
def list_strategies(request: Request, user: CurrentUser) -> dict:
    result = strategies_store(request).list(user.id)
    return {
        "total": result["total"],
        "items": [_strategy_response(item) for item in result["items"]],
    }


@router.post(
    "/strategies",
    response_model=schemas.Strategy,
    status_code=201,
    tags=["strategies"],
    operation_id="createStrategy",
)
def create_strategy(
    request: Request, body: schemas.StrategyRequest, user: CurrentUser
) -> dict:
    spec = _parse_strategy(body)
    return _strategy_response(strategies_store(request).create(user.id, spec))


@router.get(
    "/strategies/{strategy_id}",
    response_model=schemas.Strategy,
    tags=["strategies"],
    operation_id="getStrategy",
)
def get_strategy(request: Request, strategy_id: str, user: CurrentUser) -> dict:
    stored = strategies_store(request).get(user.id, strategy_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"unknown strategy: {strategy_id}")
    return _strategy_response(stored)


@router.put(
    "/strategies/{strategy_id}",
    response_model=schemas.Strategy,
    tags=["strategies"],
    operation_id="replaceStrategy",
)
def replace_strategy(
    request: Request,
    strategy_id: str,
    body: schemas.StrategyRequest,
    user: CurrentUser,
) -> dict:
    spec = _parse_strategy(body)
    stored = strategies_store(request).replace(user.id, strategy_id, spec)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"unknown strategy: {strategy_id}")
    return _strategy_response(stored)


@router.delete(
    "/strategies/{strategy_id}",
    status_code=204,
    tags=["strategies"],
    operation_id="deleteStrategy",
)
def delete_strategy(request: Request, strategy_id: str, user: CurrentUser) -> None:
    if not strategies_store(request).delete(user.id, strategy_id):
        raise HTTPException(status_code=404, detail=f"unknown strategy: {strategy_id}")


@router.get(
    "/strategy-templates",
    response_model=schemas.StrategyTemplateList,
    tags=["strategies"],
    operation_id="listStrategyTemplates",
)
def list_strategy_templates() -> dict:
    """Complete starter strategies, for a builder that would otherwise be a wall.

    Unauthenticated: they are identical for everyone and contain nothing of
    anybody's. Assembled at request time, so adding a template needs no change
    here.
    """
    items = templates.catalogue()
    return {"total": len(items), "items": items}
