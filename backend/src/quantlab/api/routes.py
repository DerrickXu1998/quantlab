"""API routes per contracts/openapi.yaml. Thin handlers only (Constitution I):
every handler is a storage call; zero analytics here.

Handlers do not know which dataset is behind them. ``app.state.backend`` is
either the real warehouse (ClickHouse bars + Postgres catalog) or the
synthetic SQLite demo, chosen once at startup.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict
from datetime import date
from typing import Annotated, Literal, get_args

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse

from quantlab import auth as auth_lib
from quantlab.api import schemas, security
from quantlab.api.security import CurrentUser, owner_scope
from quantlab.replay import engine as replay_engine
from quantlab.research import errors as research_errors
from quantlab.research import performance, runner
from quantlab.signals import registry as signal_registry
from quantlab.signals import templates as signal_templates
from quantlab.storage import facts as fact_defs
from quantlab.strategy import StrategySpec, StrategyValidationError, templates
from quantlab.streaming import bus as streaming_bus
from quantlab.streaming import live as streaming_live

router = APIRouter()

# Real tickers are not bare uppercase words: quantlab's canonical ids carry an
# exchange suffix (AAPL.US, HSBA.LON) and some venues use digits or hyphens
# (BRK-B.US, 0700.HK). The old ^[A-Z]{2,8}$ fitted only the synthetic universe.
SYMBOL_PATTERN = r"^[A-Z0-9][A-Z0-9._\-]{0,19}$"

#: A single SSE replay may not run longer than this. Each open stream iterates
#: its generator in a threadpool worker (and the live stream also holds a Kafka
#: consumer), so an unbounded stream is a worker-exhaustion vector: on reaching
#: the cap the stream ends with the same `truncated` frame `max_events` uses.
_STREAM_WALL_CLOCK_SECONDS = 15 * 60

#: Concurrent replay streams one user may hold. Every open stream pins a
#: threadpool worker (and the live variant a Kafka consumer) for its whole
#: lifetime, so without a cap one account can starve the API for everyone
#: else just by opening streams in a loop.
_STREAM_SLOTS_PER_USER = 3


class _StreamSlots:
    """Per-user count of open replay streams, in memory, per app instance."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, user_id: str) -> bool:
        with self._lock:
            held = self._counts.get(user_id, 0)
            if held >= _STREAM_SLOTS_PER_USER:
                return False
            self._counts[user_id] = held + 1
            return True

    def release(self, user_id: str) -> None:
        with self._lock:
            held = self._counts.get(user_id, 0)
            if held <= 1:
                # Drop the key rather than leaving a zero: user ids are
                # unbounded, so the dict must not grow per user ever seen.
                self._counts.pop(user_id, None)
            else:
                self._counts[user_id] = held - 1


def _stream_slots(request: Request) -> _StreamSlots:
    # Per app, on its state -- like the seeded cache below, a module-level
    # instance would leak counts between the apps tests create.
    slots = getattr(request.app.state, "_stream_slots", None)
    if slots is None:
        slots = request.app.state._stream_slots = _StreamSlots()
    return slots


def _acquire_stream_slot(request: Request, user) -> _StreamSlots:
    slots = _stream_slots(request)
    if not slots.acquire(user.id):
        raise HTTPException(
            status_code=429,
            detail="too many concurrent replay streams; wait for one to finish",
            headers={"Retry-After": "5"},
        )
    return slots


def backend(request: Request):
    return request.app.state.backend


def experiments(request: Request):
    """Where runs are kept. A separate seam from the dataset: on the
    warehouse these are different database systems."""
    return request.app.state.experiments


def strategies_store(request: Request):
    """Where saved strategies are kept. Every method takes an owner."""
    return request.app.state.strategies


def custom_rules_store(request: Request):
    """Where template-based custom rules are kept (feature 008). Every method
    takes an owner, exactly like strategies."""
    return request.app.state.custom_rules


def auth_service(request: Request):
    return request.app.state.auth


#: How long a "seeded" answer may be reused. health() on the warehouse runs a
#: full ClickHouse count plus a Postgres count, so asking it per data request
#: is the dominant cost of every guarded route; a few seconds of staleness on
#: a 503-vs-serve decision is invisible next to an ingest cycle.
_SEEDED_CACHE_TTL_SECONDS = 10.0


def require_seeded(request: Request) -> None:
    """Guard for data routes: 503 until there is data to serve (FR-003)."""
    now = time.monotonic()
    # Cached per app, on its state: app instances have different backends (a
    # test seeds a private database per case), so a module-level cache would
    # leak one app's answer into another's. A racy double-refresh costs one
    # extra health() call -- benign next to a lock.
    cache = getattr(request.app.state, "_seeded_cache", None)
    if cache is None or cache[0] <= now:
        has_data, _ = backend(request).health()
        cache = (now + _SEEDED_CACHE_TTL_SECONDS, has_data)
        request.app.state._seeded_cache = cache
    if not cache[1]:
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


# --- Research: the company, the universe, the screen (docs/RESEARCH.md) ----
#
# Thin handlers as everywhere else: these parse a query string and map an
# absent row to a status code. The point-in-time resolution, the ratios and the
# coverage arithmetic all live in storage, which is the only place they exist
# once (Constitution I and V).


def _as_of(value: date | None) -> str:
    """The date to resolve facts on. Today when the caller names none."""
    return (value or date.today()).isoformat()


def _concept_filter(concepts: str | None) -> list[str] | None:
    """Parse ``concepts=a,b`` into a validated filter, or None for everything.

    An unknown concept is refused rather than silently dropped: a filter that
    quietly matches nothing returns an empty inspector, which looks exactly
    like a company that has filed nothing.
    """
    if not concepts:
        return None
    wanted = [item.strip() for item in concepts.split(",") if item.strip()]
    unknown = sorted(set(wanted) - fact_defs.KNOWN_CONCEPTS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown concepts: {unknown}")
    return sorted(set(wanted))


@router.get(
    "/instruments/{symbol}/fundamentals",
    response_model=list[schemas.FundamentalFact],
    tags=["instruments"],
    operation_id="getFundamentals",
    dependencies=[Depends(require_seeded)],
)
def get_fundamentals(
    request: Request,
    symbol: Annotated[str, Path(pattern=SYMBOL_PATTERN)],
    as_of: date | None = None,
    concepts: Annotated[
        str | None, Query(description="Comma-separated concepts; default is all of them")
    ] = None,
) -> list[dict]:
    """The accounts that were public on a date, each with the filing behind it.

    A bare array rather than the ``{total, items}`` envelope: this is one
    company's balance sheet, not a page of a collection, and there is nothing
    to page through.
    """
    store = backend(request)
    if not store.instrument_exists(symbol):
        raise HTTPException(status_code=404, detail=f"unknown symbol: {symbol}")
    return store.facts_as_of(symbol, _as_of(as_of), _concept_filter(concepts))


@router.get(
    "/fundamentals/coverage",
    response_model=schemas.FundamentalsCoverage,
    tags=["instruments"],
    operation_id="getFundamentalsCoverage",
    dependencies=[Depends(require_seeded)],
)
def get_fundamentals_coverage(request: Request) -> dict:
    """What has been filed at all, so a screen can say what it could not measure."""
    return backend(request).fundamentals_coverage()


@router.get(
    "/instruments/{symbol}/overview",
    response_model=schemas.CompanyOverview,
    tags=["instruments"],
    operation_id="getCompanyOverview",
    dependencies=[Depends(require_seeded)],
)
def get_company_overview(
    request: Request,
    symbol: Annotated[str, Path(pattern=SYMBOL_PATTERN)],
    as_of: date | None = None,
) -> dict:
    """One request rather than the four it composes.

    The page needs price bounds, the point-in-time accounts, coverage and
    signal history before it can render at all; issuing those separately would
    paint it in four stages, each with its own failure, and a page that is
    briefly half-wrong is worse than one that is briefly empty.
    """
    overview = backend(request).company_overview(symbol, _as_of(as_of))
    if overview is None:
        raise HTTPException(status_code=404, detail=f"unknown symbol: {symbol}")
    return overview


@router.get(
    "/universes",
    response_model=schemas.UniverseList,
    tags=["instruments"],
    operation_id="listUniverses",
    dependencies=[Depends(require_seeded)],
)
def list_universes(request: Request) -> dict:
    """The dated membership lists a screen may be run over."""
    return backend(request).list_universes()


#: The metric vocabulary, taken from the response schema so the request cannot
#: accept a metric the response has no column for.
SCREEN_METRICS: tuple[str, ...] = get_args(schemas.ScreenMetric)


def _screen_metrics(metrics: str | None) -> list[str]:
    if not metrics:
        return list(SCREEN_METRICS)
    wanted = [item.strip() for item in metrics.split(",") if item.strip()]
    unknown = sorted(set(wanted) - set(SCREEN_METRICS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown metrics: {unknown}")
    return wanted


def _screen_constraints(constraints: str | None) -> list[tuple[str, float | None, float | None]]:
    """Parse ``metric:min:max,metric:min:max``; an empty bound is unbounded.

    A GET with the whole screen in the query string, so a screen is linkable
    and a colleague can be sent the exact one that was run rather than a
    description of it.
    """
    if not constraints:
        return []
    parsed: list[tuple[str, float | None, float | None]] = []
    for clause in constraints.split(","):
        clause = clause.strip()
        if not clause:
            continue
        parts = clause.split(":")
        if len(parts) != 3:
            raise HTTPException(
                status_code=422,
                detail=f"constraint must be metric:min:max, got {clause!r}",
            )
        metric, low_text, high_text = (part.strip() for part in parts)
        if metric not in SCREEN_METRICS:
            raise HTTPException(status_code=422, detail=f"unknown metric: {metric}")
        try:
            low = float(low_text) if low_text else None
            high = float(high_text) if high_text else None
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"constraint bounds must be numbers: {clause!r}"
            ) from exc
        if low is not None and high is not None and low > high:
            raise HTTPException(
                status_code=422, detail=f"constraint admits nothing: {clause!r}"
            )
        parsed.append((metric, low, high))
    return parsed


def _universe_detail(request: Request, universe: str, as_of: str) -> str:
    """Say which kind of miss it was: a name nobody has, or a date nobody reaches.

    Only ever built on the failure path. "Unknown universe" and "that universe
    does not go back that far" call for different corrections, and one message
    covering both would send the caller to fix the wrong half of the request.
    """
    dates = [
        item["as_of"]
        for item in backend(request).list_universes()["items"]
        if item["name"] == universe
    ]
    if not dates:
        return f"unknown universe: {universe}"
    return (
        f"universe {universe} has no snapshot on or before {as_of}; "
        f"its earliest is {min(dates)}"
    )


@router.get(
    "/screen",
    response_model=schemas.ScreenResult,
    tags=["instruments"],
    operation_id="screen",
    dependencies=[Depends(require_seeded)],
)
def screen(
    request: Request,
    universe: Annotated[str, Query(min_length=1, description="A universe from /universes")],
    as_of: date | None = None,
    metrics: Annotated[
        str | None, Query(description="Comma-separated metrics; default is all of them")
    ] = None,
    constraints: Annotated[
        str | None, Query(description="metric:min:max,metric:min:max; empty bound is unbounded")
    ] = None,
    sort_by: schemas.ScreenMetric | None = None,
    descending: bool = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> dict:
    """Narrow a named universe by filed ratios, point-in-time.

    ``universe`` is required by the index rather than by taste:
    ``fundamentals_pit_idx`` leads with ``instrument_id``, so an unbounded
    screen falls to a sequential scan and takes 6.7 s against 857 ms bounded
    (docs/RESEARCH.md §2). It is also what the work is -- nobody screens
    "everything".
    """
    wanted = _screen_metrics(metrics)
    parsed = _screen_constraints(constraints)
    # A constrained or sorted metric is reported whether or not it was asked
    # for: its coverage is the only thing that separates "few qualified" from
    # "most were never measured", and a sort on an absent column is silent.
    for metric in [*(metric for metric, _, _ in parsed), *([sort_by] if sort_by else [])]:
        if metric not in wanted:
            wanted.append(metric)

    resolved = _as_of(as_of)
    result = backend(request).screen(
        universe=universe,
        as_of=resolved,
        metrics=wanted,
        constraints=parsed,
        sort_by=sort_by,
        descending=descending,
        limit=limit,
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=_universe_detail(request, universe, resolved)
        )
    return result


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


@router.get(
    "/signal-templates",
    response_model=schemas.SignalTemplateList,
    tags=["models"],
    operation_id="listSignalTemplates",
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
            "available_on_dataset": template.inputs == "bars" or dataset == "warehouse",
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
    run: dict,
    dataset: str = "sqlite",
    resolved_rules: dict[str, dict] | None = None,
) -> dict:
    run = dict(run)
    run.pop("owner_id", None)  # internal; the caller is the owner by construction
    snapshot = run.get("custom_rule")
    if snapshot is not None and resolved_rules is not None:
        # A custom-rule run is reproducible from its snapshot, but
        # "model_available" answers "could I run this rule again": false once
        # the rule is deleted (or owned by someone else). Batch-resolved by
        # the caller (list_runs): one query for the whole page.
        run["model_available"] = snapshot["rule_id"] in resolved_rules
    else:
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
    # One query for every custom rule the page references; a per-run get_rule
    # is an N+1 against the catalog.
    rule_ids = sorted(
        {r["custom_rule"]["rule_id"] for r in result["items"] if r.get("custom_rule")}
    )
    resolved = (
        custom_rules_store(request).get_rules(rule_ids, owner_scope(user))
        if rule_ids
        else {}
    )
    return {
        "total": result["total"],
        "items": [
            _run_response(r, active, resolved_rules=resolved) for r in result["items"]
        ],
    }


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


# --- Custom signal rules (feature 008) -----------------------------------------
#
# Thin handlers over the CustomRuleStore seam; template validation lives in
# quantlab.signals.templates. Scoping mirrors strategies: every call is made
# with the caller's owner id, and another user's rule reads as absent, never
# forbidden -- a 403 would confirm the row exists.


def _rule_response(record: dict) -> dict:
    """Attach the lookback the config implies, derived from its template.

    Computed rather than stored: what a config needs follows the template's
    definition, and a stored copy would go stale when the template does.
    """
    template = signal_templates.get_template(record["template"])
    body = dict(record)
    body.pop("owner_id", None)  # internal; the caller is the owner by construction
    return {**body, "lookback_days": template.lookback_days(record["config"])}


def _rule_owner(user) -> str | None:
    """The owner id a rule call is made with.

    ``owner_scope(user)`` plain: with auth on, the caller's id, so another
    user's rule reads as absent. With auth off, None -- the unscoped rows the
    store reserves for single-user mode (``custom_rules.user_id`` is a real
    foreign key to ``users``, so the built-in local account's id would not
    even insert; NULL is the branch's convention for demo-mode rows).
    """
    return owner_scope(user)


def _get_scoped_rule(request: Request, rule_id: str, user) -> dict:
    record = custom_rules_store(request).get_rule(rule_id, _rule_owner(user))
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown custom rule: {rule_id}")
    return record


def _validate_rule_config(template_id: str, config: dict):
    """The template, or the HTTP failure naming why the config was refused."""
    try:
        template = signal_templates.get_template(template_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"unknown template: {template_id}"
        ) from None
    try:
        template.validate(config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return template


@router.post(
    "/rules",
    response_model=schemas.CustomRule,
    status_code=201,
    tags=["rules"],
    operation_id="createCustomRule",
)
def create_custom_rule(
    request: Request, body: schemas.CustomRuleRequest, user: CurrentUser
) -> dict:
    template = _validate_rule_config(body.template, body.config)
    record = custom_rules_store(request).create_rule(
        _rule_owner(user), body.name, template.id, body.config
    )
    return _rule_response(record)


@router.get(
    "/rules",
    response_model=schemas.CustomRuleList,
    tags=["rules"],
    operation_id="listCustomRules",
)
def list_custom_rules(request: Request, user: CurrentUser) -> dict:
    result = custom_rules_store(request).list_rules(_rule_owner(user))
    return {"total": result["total"], "items": [_rule_response(r) for r in result["items"]]}


@router.get(
    "/rules/{rule_id}",
    response_model=schemas.CustomRule,
    tags=["rules"],
    operation_id="getCustomRule",
)
def get_custom_rule(request: Request, rule_id: str, user: CurrentUser) -> dict:
    return _rule_response(_get_scoped_rule(request, rule_id, user))


@router.patch(
    "/rules/{rule_id}",
    response_model=schemas.CustomRule,
    tags=["rules"],
    operation_id="updateCustomRule",
)
def update_custom_rule(
    request: Request,
    rule_id: str,
    body: schemas.CustomRuleUpdateRequest,
    user: CurrentUser,
) -> dict:
    record = _get_scoped_rule(request, rule_id, user)
    if body.name is None and body.config is None:
        raise HTTPException(
            status_code=422, detail="nothing to update: send name and/or config"
        )
    if body.config is not None:
        # The template is immutable: changing what a rule IS makes a new rule.
        # Runs that already used it keep their definition snapshot; edits apply
        # to future runs only.
        _validate_rule_config(record["template"], body.config)
    updated = custom_rules_store(request).update_rule(
        rule_id, _rule_owner(user), name=body.name, config=body.config
    )
    return _rule_response(updated)


@router.delete(
    "/rules/{rule_id}",
    status_code=204,
    tags=["rules"],
    operation_id="deleteCustomRule",
)
def delete_custom_rule(request: Request, rule_id: str, user: CurrentUser) -> None:
    # Deleting a rule never touches the runs that used it: their snapshot
    # keeps them readable, and model_available flips to false.
    if not custom_rules_store(request).delete_rule(rule_id, _rule_owner(user)):
        raise HTTPException(status_code=404, detail=f"unknown custom rule: {rule_id}")


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
    interval_ms: Annotated[int, Query(ge=0, le=1_000)] = 0,
    max_events: Annotated[int, Query(ge=1, le=250_000)] = 250_000,
    step: Annotated[int, Query(ge=1)] = 1,
) -> StreamingResponse:
    run = _replayable_run(request, run_id, user)
    signals, bars = replay_engine.load_replay_inputs(backend(request), experiments(request), run)
    # Acquired only after validation above: a request that raises before the
    # response exists must not leak a slot its generator would never release.
    slots = _acquire_stream_slot(request, user)

    def frames():
        emitted = 0
        truncated = None
        deadline = time.monotonic() + _STREAM_WALL_CLOCK_SECONDS
        # A sync generator: StreamingResponse iterates it in a threadpool, so
        # the optional pacing sleep never blocks the event loop.
        try:
            for event in replay_engine.replay_events(run, signals, bars, step=step):
                if emitted >= max_events:
                    truncated = f"max_events={max_events} reached before the summary"
                    break
                if time.monotonic() >= deadline:
                    # A stream that outlives the cap pins a threadpool worker;
                    # end it like any other truncation.
                    truncated = "stream wall-clock limit reached before the summary"
                    break
                yield f"data: {json.dumps(replay_engine.to_dict(event))}\n\n"
                emitted += 1
                if interval_ms and isinstance(event, replay_engine.ReplayEquity):
                    time.sleep(interval_ms / 1000)
        finally:
            slots.release(user.id)
        if truncated:
            yield f"data: {json.dumps({'event': 'truncated', 'detail': truncated})}\n\n"

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
    request: Request,
    user: CurrentUser,
    model: str = "sma-crossover",
    symbols: Annotated[str, Query(description="Comma-separated canonical symbols")] = "",
    start: date | None = None,
    end: date | None = None,
    params: Annotated[str | None, Query(description="JSON object of parameter overrides")] = None,
    initial_cash: Annotated[float, Query(gt=0)] = performance.INITIAL_CAPITAL,
    max_events: Annotated[int, Query(ge=1, le=250_000)] = 250_000,
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

    # Acquired before the broker connect below: a request that fails earlier
    # (validation) never held a slot, and a failed connect releases its own.
    slots = _acquire_stream_slot(request, user)
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
        slots.release(user.id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    events = streaming_live.live_replay_events(
        model, overrides, symbol_list, start.isoformat(), end.isoformat(), stream,
        initial_cash=initial_cash,
    )

    def frames():
        emitted = 0
        truncated = None
        deadline = time.monotonic() + _STREAM_WALL_CLOCK_SECONDS
        # A sync generator: StreamingResponse iterates it in a threadpool, so
        # blocking on the Kafka consumer never stalls the event loop.
        try:
            for event in events:
                if emitted >= max_events:
                    truncated = f"max_events={max_events} reached before the summary"
                    break
                if time.monotonic() >= deadline:
                    # Holding a worker and a consumer open indefinitely is a
                    # resource-exhaustion vector; end it like a truncation.
                    truncated = "stream wall-clock limit reached before the summary"
                    break
                yield f"data: {json.dumps(replay_engine.to_dict(event))}\n\n"
                emitted += 1
        finally:
            stream.close()
            slots.release(user.id)
        if truncated:
            yield f"data: {json.dumps({'event': 'truncated', 'detail': truncated})}\n\n"

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
    service = auth_service(request)
    try:
        # request.client is the direct peer: a deployment behind a proxy must
        # configure trusted-proxy handling (e.g. uvicorn --proxy-headers) for
        # this to be the real client address rather than the proxy's.
        service.check_registration_rate(
            request.client.host if request.client else "unknown"
        )
    except auth_lib.RateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    try:
        session = service.register(body.email, body.password)
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
