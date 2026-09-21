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

from quantlab import fundamentals as fundamentals_lib
from quantlab.api import schemas
from quantlab.api.auth import require_session, user_id_of
from quantlab.replay import engine as replay_engine
from quantlab.research import errors as research_errors
from quantlab.research import performance, runner
from quantlab.signals import builtins as _builtins  # noqa: F401  (registers builtin rules)
from quantlab.signals import registry as signal_registry
from quantlab.signals import templates as signal_templates
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


def custom_rules(request: Request):
    """Where template-based custom rules live (feature 008)."""
    return request.app.state.custom_rules


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
    return schemas.Health(dataset=active.name, seeded=has_data, signal_count=signal_count)


@router.get(
    "/instruments",
    response_model=schemas.InstrumentList,
    tags=["instruments"],
    operation_id="listInstruments",
    dependencies=[Depends(require_session), Depends(require_seeded)],
)
def list_instruments(request: Request) -> dict:
    return backend(request).list_instruments()


@router.get(
    "/instruments/{symbol}/prices",
    response_model=schemas.PriceBarList,
    tags=["instruments"],
    operation_id="getPrices",
    dependencies=[Depends(require_session), Depends(require_seeded)],
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
    "/instruments/{symbol}/fundamentals/concepts",
    response_model=schemas.FundamentalConceptList,
    tags=["fundamentals"],
    operation_id="listInstrumentFundamentalConcepts",
    dependencies=[Depends(require_session), Depends(require_seeded)],
)
def list_instrument_fundamental_concepts(
    request: Request,
    symbol: Annotated[str, Path(pattern=SYMBOL_PATTERN)],
) -> dict:
    store = backend(request)
    if not store.instrument_exists(symbol):
        raise HTTPException(status_code=404, detail=f"unknown symbol: {symbol}")
    return store.list_fundamental_concepts(symbol)


@router.get(
    "/instruments/{symbol}/fundamentals/series",
    response_model=schemas.FundamentalSeries,
    tags=["fundamentals"],
    operation_id="getFundamentalSeries",
    dependencies=[Depends(require_session), Depends(require_seeded)],
)
def get_fundamental_series(
    request: Request,
    symbol: Annotated[str, Path(pattern=SYMBOL_PATTERN)],
    concept: str,
    transform: Literal["raw", "raw_facts", "yoy_growth"] = "raw",
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    store = backend(request)
    if not store.instrument_exists(symbol):
        raise HTTPException(status_code=404, detail=f"unknown symbol: {symbol}")
    facts, base_provenance = fundamentals_lib.fetch_facts(store, symbol, concept)
    return fundamentals_lib.build_series(
        symbol,
        concept,
        transform,
        facts,
        base_provenance,
        start=start_date.isoformat() if start_date else None,
        end=end_date.isoformat() if end_date else None,
    )


@router.get(
    "/signals",
    response_model=schemas.SignalList,
    tags=["signals"],
    operation_id="listSignals",
    dependencies=[Depends(require_session), Depends(require_seeded)],
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
    dependencies=[Depends(require_session)],
)
def list_models(
    request: Request, user: Annotated[dict | None, Depends(require_session)]
) -> dict:
    """Assembled from the registry at request time, so registering a model
    changes this response with no code change (Constitution II). Custom rules
    join the same catalog with ``origin: "custom"`` -- a model is a model."""
    items = [
        {
            **_model_to_schema(rule),
            "origin": "builtin",
            "custom_rule_id": None,
            "template": None,
        }
        for rule in signal_registry.list_rules()
    ]
    for record in custom_rules(request).list_rules(user_id_of(user))["items"]:
        try:
            template = signal_templates.get_template(record["template"])
            lookback = template.lookback_days(record["config"])
            scale_class = template.scale_class(record["config"])
        except (KeyError, ValueError):
            # A rule whose template no longer exists cannot run; it stays in
            # the rule list but not in the runnable catalog.
            continue
        items.append(
            {
                "name": record["slug"],
                "version": template.version,
                "parameters": [],
                "lookback_days": lookback,
                "scale_class": scale_class,
                "direction_semantics": template.direction_semantics,
                "origin": "custom",
                "custom_rule_id": record["rule_id"],
                "template": template.id,
            }
        )
    return {"total": len(items), "items": items}


@router.get(
    "/signal-templates",
    response_model=schemas.SignalTemplateList,
    tags=["models"],
    operation_id="listSignalTemplates",
    dependencies=[Depends(require_session)],
)
def list_signal_templates(request: Request) -> dict:
    """The template catalog, assembled from the registry at request time:
    registering a template changes this response with no code change."""
    dataset = backend(request).name
    items = [
        {
            "id": template.id,
            "version": template.version,
            "description": template.description,
            "inputs": template.inputs,
            # Templates reading fundamentals need the warehouse; bars-only
            # templates run on either dataset.
            "available_on_dataset": (
                template.inputs == "bars" or dataset == "warehouse"
            ),
            "config_fields": template.config_fields,
        }
        for template in signal_templates.list_templates()
    ]
    return {"total": len(items), "items": items}


def _is_registered(model_name: str, model_version: str) -> bool:
    try:
        signal_registry.get_rule(model_name, model_version)
    except KeyError:
        return False
    return True


def _run_response(
    run: dict, dataset: str = "sqlite", rules_store=None, user_id: int | None = None
) -> dict:
    run = dict(run)
    snapshot = run.get("custom_rule")
    if snapshot is not None and rules_store is not None:
        # A custom-rule run is reproducible from its snapshot, but
        # "model_available" answers "could I run this rule again": false once
        # the rule is deleted (or owned by someone else).
        run["model_available"] = (
            rules_store.get_rule(snapshot["rule_id"], user_id) is not None
        )
    else:
        run["model_available"] = _is_registered(run["model_name"], run["model_version"])
    run.setdefault("dataset", dataset)
    # A run recorded against a different dataset stays readable but cannot be
    # reproduced as recorded.
    run["re_runnable"] = run["dataset"] == dataset
    return run


@router.post(
    "/runs",
    response_model=schemas.Run,
    status_code=201,
    tags=["runs"],
    operation_id="createRun",
    dependencies=[Depends(require_session), Depends(require_seeded)],
)
def create_run(
    request: Request,
    body: schemas.RunRequest,
    user: Annotated[dict | None, Depends(require_session)],
) -> dict:
    active = backend(request)
    store = experiments(request)
    rule_record = None
    if body.custom_rule_id is not None:
        if body.model_name is not None:
            raise HTTPException(
                status_code=422,
                detail="model_name and custom_rule_id are mutually exclusive",
            )
        rule_record = custom_rules(request).get_rule(body.custom_rule_id, user_id_of(user))
        if rule_record is None:
            raise HTTPException(
                status_code=404, detail=f"unknown custom rule: {body.custom_rule_id}"
            )
    try:
        result = runner.run_experiment(
            active,
            model_name=body.model_name,
            model_version=body.model_version,
            overrides=body.parameters,
            symbols=body.symbols,
            start_date=body.start_date,
            end_date=body.end_date,
            execution=body.execution.model_dump() if body.execution else None,
            custom_rule=rule_record,
        )
    except research_errors.UnknownModelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except research_errors.UnknownSymbolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except research_errors.ParameterValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except research_errors.DatasetUnsupportedError as exc:
        # The template is valid; the active dataset cannot serve it (the demo
        # holds no fundamentals).
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        research_errors.InvalidWindowError,
        research_errors.WindowTooShortError,
        research_errors.SelectionTooLargeError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store.save_run(result, user_id=user_id_of(user))
    stored = store.get_run(result.id, user_id=user_id_of(user))
    return _run_response(stored, active.name, custom_rules(request), user_id_of(user))


@router.get(
    "/runs",
    response_model=schemas.RunList,
    tags=["runs"],
    operation_id="listRuns",
    dependencies=[Depends(require_session), Depends(require_seeded)],
)
def list_runs(
    request: Request,
    user: Annotated[dict | None, Depends(require_session)],
    saved_only: bool = False,
) -> dict:
    result = experiments(request).list_runs(saved_only=saved_only, user_id=user_id_of(user))
    active = backend(request).name
    store = custom_rules(request)
    uid = user_id_of(user)
    return {
        "total": result["total"],
        "items": [_run_response(r, active, store, uid) for r in result["items"]],
    }


@router.get(
    "/runs/{run_id}",
    response_model=schemas.RunDetail,
    tags=["runs"],
    operation_id="getRun",
    dependencies=[Depends(require_session), Depends(require_seeded)],
)
def get_run(
    request: Request, run_id: str, user: Annotated[dict | None, Depends(require_session)]
) -> dict:
    store = experiments(request)
    run = store.get_run(run_id, user_id=user_id_of(user))
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    signals = store.get_run_signals(run_id, user_id=user_id_of(user))
    return {
        **_run_response(
            run, backend(request).name, custom_rules(request), user_id_of(user)
        ),
        "signals": signals,
    }


@router.get(
    "/runs/{run_id}/performance",
    response_model=schemas.RunPerformance,
    tags=["runs"],
    operation_id="getRunPerformance",
    dependencies=[Depends(require_session), Depends(require_seeded)],
)
def get_run_performance(
    request: Request, run_id: str, user: Annotated[dict | None, Depends(require_session)]
) -> dict:
    """Still a thin handler: the analytics live in research.performance, which
    is where the frontend cannot reach them (Constitution V)."""
    store = experiments(request)
    run = store.get_run(run_id, user_id=user_id_of(user))
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    # A failed run has no performance. Zeroed figures would read as a flat
    # book rather than as an absent result -- the same distinction the UI
    # already draws between an empty run and a failed one.
    if run["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"run {run_id} failed; it has no performance")

    symbols = list(run["symbols"])
    # The reported window only: warm-up bars are inputs to the signals, not
    # part of the period being measured.
    bars = backend(request).load_bars_for(symbols, run["start_date"], run["end_date"])
    criteria = performance.execution_criteria(run["execution"]) if run.get("execution") else None
    result = performance.compute_performance(
        run_id=run_id,
        signals=store.get_run_signals(run_id, user_id=user_id_of(user)),
        bars_by_symbol=bars,
        symbols=symbols,
        execution=criteria,
    )
    return asdict(result)


@router.patch(
    "/runs/{run_id}",
    response_model=schemas.Run,
    tags=["runs"],
    operation_id="saveRun",
    dependencies=[Depends(require_session), Depends(require_seeded)],
)
def save_run(
    request: Request,
    run_id: str,
    body: schemas.RunNameRequest,
    user: Annotated[dict | None, Depends(require_session)],
) -> dict:
    store = experiments(request)
    if not store.set_run_name(run_id, body.name, user_id=user_id_of(user)):
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    run = store.get_run(run_id, user_id=user_id_of(user))
    return _run_response(run, backend(request).name, custom_rules(request), user_id_of(user))


@router.delete(
    "/runs/{run_id}",
    status_code=204,
    tags=["runs"],
    operation_id="deleteRun",
    dependencies=[Depends(require_session), Depends(require_seeded)],
)
def delete_run(
    request: Request, run_id: str, user: Annotated[dict | None, Depends(require_session)]
) -> None:
    if not experiments(request).delete_run(run_id, user_id=user_id_of(user)):
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")


# --- Custom signal rules (feature 008, M2) ------------------------------------
#
# Thin handlers over the CustomRuleStore seam; template validation lives in
# quantlab.signals.templates. Scoping mirrors runs: another user's rule id
# reads as 404.


def _rule_response(record: dict) -> dict:
    template = signal_templates.get_template(record["template"])
    return {**record, "lookback_days": template.lookback_days(record["config"])}


def _get_scoped_rule(request: Request, rule_id: str, user_id: int | None) -> dict:
    record = custom_rules(request).get_rule(rule_id, user_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown custom rule: {rule_id}")
    return record


@router.post(
    "/rules",
    response_model=schemas.CustomRule,
    status_code=201,
    tags=["rules"],
    operation_id="createCustomRule",
    dependencies=[Depends(require_session)],
)
def create_custom_rule(
    request: Request,
    body: schemas.CustomRuleRequest,
    user: Annotated[dict | None, Depends(require_session)],
) -> dict:
    try:
        template = signal_templates.get_template(body.template)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown template: {body.template}") from None
    try:
        template.validate(body.config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = custom_rules(request).create_rule(
        user_id_of(user), body.name, template.id, body.config
    )
    return _rule_response(record)


@router.get(
    "/rules",
    response_model=schemas.CustomRuleList,
    tags=["rules"],
    operation_id="listCustomRules",
    dependencies=[Depends(require_session)],
)
def list_custom_rules(
    request: Request, user: Annotated[dict | None, Depends(require_session)]
) -> dict:
    result = custom_rules(request).list_rules(user_id_of(user))
    return {"total": result["total"], "items": [_rule_response(r) for r in result["items"]]}


@router.get(
    "/rules/{rule_id}",
    response_model=schemas.CustomRule,
    tags=["rules"],
    operation_id="getCustomRule",
    dependencies=[Depends(require_session)],
)
def get_custom_rule(
    request: Request,
    rule_id: str,
    user: Annotated[dict | None, Depends(require_session)],
) -> dict:
    return _rule_response(_get_scoped_rule(request, rule_id, user_id_of(user)))


@router.patch(
    "/rules/{rule_id}",
    response_model=schemas.CustomRule,
    tags=["rules"],
    operation_id="updateCustomRule",
    dependencies=[Depends(require_session)],
)
def update_custom_rule(
    request: Request,
    rule_id: str,
    body: schemas.CustomRuleUpdateRequest,
    user: Annotated[dict | None, Depends(require_session)],
) -> dict:
    record = _get_scoped_rule(request, rule_id, user_id_of(user))
    if body.name is None and body.config is None:
        raise HTTPException(status_code=422, detail="nothing to update: send name and/or config")
    if body.config is not None:
        try:
            signal_templates.get_template(record["template"]).validate(body.config)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    updated = custom_rules(request).update_rule(
        rule_id, user_id_of(user), name=body.name, config=body.config
    )
    return _rule_response(updated)


@router.delete(
    "/rules/{rule_id}",
    status_code=204,
    tags=["rules"],
    operation_id="deleteCustomRule",
    dependencies=[Depends(require_session)],
)
def delete_custom_rule(
    request: Request,
    rule_id: str,
    user: Annotated[dict | None, Depends(require_session)],
) -> None:
    # Deleting a rule never touches the runs that used it: their snapshot
    # keeps them reproducible, and model_available flips to false.
    if not custom_rules(request).delete_rule(rule_id, user_id_of(user)):
        raise HTTPException(status_code=404, detail=f"unknown custom rule: {rule_id}")


# --- Historical replay ------------------------------------------------------
#
# Thin handlers again: the engine lives in quantlab.replay so it is testable
# without HTTP (Constitution I). These only resolve the run, guard its state,
# and frame the events.


def _replayable_run(request: Request, run_id: str, user_id: int | None = None) -> dict:
    store = experiments(request)
    run = store.get_run(run_id, user_id=user_id)
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
    dependencies=[Depends(require_session), Depends(require_seeded)],
)
def stream_run_replay(
    request: Request,
    run_id: str,
    user: Annotated[dict | None, Depends(require_session)],
    interval_ms: Annotated[int, Query(ge=0, le=10_000)] = 0,
    max_events: Annotated[int, Query(ge=1, le=5_000_000)] = 250_000,
    step: Annotated[int, Query(ge=1)] = 1,
) -> StreamingResponse:
    run = _replayable_run(request, run_id, user_id_of(user))
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
    dependencies=[Depends(require_session), Depends(require_seeded)],
)
def get_run_replay_summary(
    request: Request, run_id: str, user: Annotated[dict | None, Depends(require_session)]
) -> dict:
    run = _replayable_run(request, run_id, user_id_of(user))
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
    dependencies=[Depends(require_session)],
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
        model,
        overrides,
        symbol_list,
        start.isoformat(),
        end.isoformat(),
        stream,
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
