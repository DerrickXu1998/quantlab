"""Run a strategy over a dataset selection.

Library logic, not route logic (Constitution I): independently testable without
HTTP, with the API layer a thin adapter over it.

A run is now four stages rather than one:

1. resolve and validate the strategy (every component, every parameter);
2. load bars from ``start - lookback`` so the first session of the requested
   window can already emit;
3. compose the components into entry/exit decisions;
4. execute those decisions under the run's execution criteria.

The warm-up window is the subtle part. A strategy declares a ``lookback_days``
taken from its deepest component, its agreement window, and anything execution
needs (an ATR stop needs an ATR). If a run loaded only the bars inside the
requested window, the first ``lookback_days`` of that window could not emit, and
a short window would understate the strategy without anything saying so.

Reading bars *before* the window start is past data relative to every emitted
signal, so it cannot introduce look-ahead; the forbidden direction (a signal
built from a later bar) is enforced by the CHECK constraint on
``experiment_signals`` and by the truncation sweep (Constitution VII).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from typing import Any

from quantlab.execution import ExecutionConfig, simulate
from quantlab.logging import get_logger
from quantlab.research import errors
from quantlab.signals.registry import get_rule
from quantlab.strategy import StrategySpec, StrategyValidationError, compose, promote_legacy

logger = get_logger(__name__)

#: Calendar days of padding per lookback bar. Bars are weekdays only, so a
#: lookback of N bars spans at most roughly N * 7/5 calendar days; the extra
#: margin absorbs holidays.
_CALENDAR_DAYS_PER_BAR = 2

#: The reverse conversion, used to decide whether a requested window is long
#: enough. Five sessions per seven calendar days, rounded down -- pessimistic,
#: so a window that is only just long enough is accepted rather than refused.
_BARS_PER_CALENDAR_DAY = 5 / 7

#: Upper bound on instrument-days accepted in one synchronous run.
MAX_SELECTION_INSTRUMENT_DAYS = 2_000_000


@dataclass(frozen=True)
class RunCoverage:
    instruments_requested: int
    instruments_with_data: int
    instruments_full_warmup: int


@dataclass(frozen=True)
class RunResult:
    id: str
    model_name: str
    model_version: str
    parameters: dict[str, Any]
    symbols: list[str]
    start_date: str
    end_date: str
    status: str
    created_at: str
    signal_count: int
    coverage: RunCoverage
    signals: list[Any] = field(default_factory=list)
    error: str | None = None
    name: str | None = None
    # Provenance (feature 006). `dataset` says which store produced the run;
    # the other two are warehouse-only and stay None on the demo.
    dataset: str = "sqlite"
    instrument_ids: list[int] | None = None
    ingest_run_ids: list[int] | None = None
    corporate_actions: list[dict] = field(default_factory=list)
    # The strategy and execution criteria that actually ran, and what the
    # engine did with them. Recorded so a result carries the assumptions that
    # produced it rather than relying on the reader to remember them.
    strategy: dict | None = None
    execution: dict | None = None
    execution_summary: dict | None = None
    #: Who the run belongs to. Every read is filtered by it.
    owner_id: str | None = None


def _parse(value: str, field_name: str) -> _date:
    try:
        return _date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise errors.InvalidWindowError(f"{field_name} is not an ISO date: {value!r}") from exc


def resolve_model(model_name: str, model_version: str | None = None):
    """One rule by name, as a typed failure rather than a KeyError.

    Kept as a public helper because the live (bus-driven) replay resolves a
    single rule directly -- it has no strategy, only a model and a stream of
    bars -- and should not have to reach into a private name to do it.
    """
    try:
        return get_rule(model_name, model_version)
    except KeyError as exc:
        raise errors.UnknownModelError(model_name, model_version) from exc


def validate_overrides(rule, overrides: dict[str, Any]) -> dict[str, Any]:
    """Effective parameters, or a typed failure naming the offending one."""
    for key, value in (overrides or {}).items():
        spec = rule.param_specs.get(key)
        if spec is None:
            raise errors.ParameterValidationError(key, "is not a parameter of this model")
        problem = spec.validation_error(value)
        if problem is not None:
            raise errors.ParameterValidationError(key, problem)
    return rule.effective_params(overrides)


# The pre-strategy private names, kept as aliases so an external caller that
# reached for them still works.
_resolve_model = resolve_model
_validate_overrides = validate_overrides


def resolve_spec(
    *,
    strategy: StrategySpec | dict | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    parameters: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
) -> StrategySpec:
    """Turn any accepted request shape into one executable spec.

    A single-model request is promoted into a one-rule strategy rather than
    taking a separate code path, so there is one execution engine and not a
    legacy branch that slowly stops matching the real one.
    """
    if strategy is not None and model_name is not None:
        raise errors.InvalidWindowError(
            "give either a strategy or a model_name, not both"
        )

    try:
        if strategy is not None:
            spec = (
                strategy
                if isinstance(strategy, StrategySpec)
                else StrategySpec.from_dict(strategy)
            )
        elif model_name is not None:
            # Fail with UnknownModelError rather than a generic validation
            # error, so the API still answers 404 for an unknown model.
            try:
                get_rule(model_name, model_version)
            except KeyError as exc:
                raise errors.UnknownModelError(model_name, model_version) from exc
            spec = promote_legacy(model_name, model_version, parameters)
        else:
            raise errors.InvalidWindowError(
                "a run needs either a strategy or a model_name"
            )

        if execution:
            spec = spec.with_execution(spec.execution.merged_with(execution))
    except StrategyValidationError as exc:
        raise errors.ParameterValidationError(_offending_field(str(exc)), str(exc)) from exc
    except ValueError as exc:
        if isinstance(exc, errors.ExperimentError):
            raise
        raise errors.ParameterValidationError("execution", str(exc)) from exc
    return spec


def _offending_field(message: str) -> str:
    """The field a validation message is about.

    ``ParameterValidationError`` carries the offending name so the UI can
    report against that input rather than as a form-level banner. A strategy
    error already names its path -- ``components[0].parameters.fast: must be
    <= 200`` -- so the leaf of that path is the field, and for a single-model
    run it is exactly the parameter name the pre-strategy code reported.
    """
    path = message.split(":", 1)[0]
    leaf = path.rsplit(".", 1)[-1].strip()
    return leaf or "strategy"


def run_experiment(
    backend,
    *,
    symbols: list[str],
    start_date: str,
    end_date: str,
    strategy: StrategySpec | dict | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    overrides: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    owner_id: str | None = None,
) -> RunResult:
    """Validate, execute, and summarise one run. Does not persist.

    Takes a StorageBackend rather than a connection, so the runner does not
    know whether it is reading the synthetic demo or real ingested history.
    """
    spec = resolve_spec(
        strategy=strategy,
        model_name=model_name,
        model_version=model_version,
        parameters=overrides,
        execution=execution,
    )

    start = _parse(start_date, "start_date")
    end = _parse(end_date, "end_date")
    if start > end:
        raise errors.InvalidWindowError("start_date must be on or before end_date")

    if not symbols:
        raise errors.UnknownSymbolError([])

    requested_symbols = sorted(set(symbols))
    window_days = (end - start).days + 1
    selection_size = len(requested_symbols) * window_days
    if selection_size > MAX_SELECTION_INSTRUMENT_DAYS:
        raise errors.SelectionTooLargeError(selection_size, MAX_SELECTION_INSTRUMENT_DAYS)

    known = {item["symbol"] for item in backend.list_instruments()["items"]}
    unknown = [symbol for symbol in requested_symbols if symbol not in known]
    if unknown:
        raise errors.UnknownSymbolError(unknown)

    # A window narrower than the strategy's lookback cannot produce a
    # meaningful result; refuse it rather than returning a misleading empty one.
    #
    # Lookback is counted in *bars* and the window is given in *calendar days*,
    # so one must be converted before they can be compared. Comparing them
    # directly -- which this did until the units were noticed -- accepts a
    # 60-day window against a 50-bar lookback, when 60 calendar days hold only
    # about 43 sessions.
    lookback_days = spec.lookback_days
    window_bars = int(window_days * _BARS_PER_CALENDAR_DAY)
    if window_bars < lookback_days:
        raise errors.WindowTooShortError(lookback_days, window_days)

    warmup_start = (start - timedelta(days=lookback_days * _CALENDAR_DAYS_PER_BAR)).isoformat()
    bars_by_symbol = backend.load_bars_for(requested_symbols, warmup_start, end_date)

    # Only the concepts this strategy's rules declared. Loading the whole
    # vocabulary would be several million rows for a question nobody asked, and
    # loading none would leave every fundamental gate shut.
    #
    # There is no lower bound on filed_at inside the reader: the figure in
    # force on the warm-up morning was filed before it, often long before, so a
    # window bounded at `warmup_start` would start every run with no
    # fundamentals at all (docs/FUNDAMENTALS.md §2).
    wanted_concepts = sorted(
        {
            concept
            for index, component in enumerate(spec.components)
            for concept in component.resolve(index).requires_facts
        }
    )
    facts_by_symbol = (
        backend.load_facts_for(requested_symbols, wanted_concepts, warmup_start, end_date)
        if wanted_concepts
        else {}
    )

    decisions, composition = compose(
        spec, bars_by_symbol, requested_symbols, facts_by_symbol=facts_by_symbol
    )
    # Warm-up bars are inputs, not results: report only the requested window.
    in_window = [d for d in decisions if start_date <= d.date <= end_date]

    # Execute over the full loaded series -- an ATR stop set on the first
    # session of the window needs the bars behind it -- but score only from the
    # window start. Nothing can happen before it: no decision exists there.
    result = simulate(requested_symbols, bars_by_symbol, in_window, spec.execution)

    # Surrogate identities, where the store has them. Recorded because the
    # canonical symbol is unique but editable, while instrument_id is the
    # stable key the bar store joins on.
    ids = backend.instrument_ids(requested_symbols)
    instrument_ids = [ids[s] for s in requested_symbols if s in ids] or None

    # Which ingest produced the bars we just read. Two runs with identical
    # configuration either side of a re-ingest differ here and nowhere else.
    ingest_runs = backend.ingest_run_ids(requested_symbols, warmup_start, end_date) or None

    earliest = backend.earliest_bar_dates(requested_symbols)
    # Reported, never applied: stored bars are unadjusted, so a split inside
    # the window makes the series jump in a way that is an artefact.
    actions = backend.corporate_actions(requested_symbols, start_date, end_date)
    instruments_with_facts = (
        sum(1 for symbol in requested_symbols if facts_by_symbol.get(symbol))
        if wanted_concepts
        else None
    )
    instruments_with_data = sum(1 for symbol in requested_symbols if bars_by_symbol.get(symbol))
    instruments_full_warmup = sum(
        1
        for symbol in requested_symbols
        if bars_by_symbol.get(symbol) and earliest.get(symbol, "9999-12-31") <= warmup_start
    )

    entry_component = next(
        (c for c in spec.components if c.role == "entry"), spec.components[0]
    )
    entry_rule = entry_component.resolve(0)

    run = RunResult(
        id=uuid.uuid4().hex,
        # Kept populated for clients that predate strategies: for a composed
        # strategy these carry the first entry component.
        model_name=entry_rule.name,
        model_version=entry_rule.version,
        parameters=entry_component.effective_parameters(0),
        symbols=requested_symbols,
        start_date=start_date,
        end_date=end_date,
        status="completed",
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        signal_count=len(in_window),
        coverage=RunCoverage(
            instruments_requested=len(requested_symbols),
            instruments_with_data=instruments_with_data,
            instruments_full_warmup=instruments_full_warmup,
        ),
        signals=in_window,
        dataset=getattr(backend, "name", "sqlite"),
        instrument_ids=instrument_ids,
        ingest_run_ids=ingest_runs,
        corporate_actions=actions,
        strategy=spec.to_dict(),
        execution=spec.execution.to_dict(),
        execution_summary={
            **vars(result.summary),
            "contradictions": composition.contradictions,
        },
        owner_id=owner_id,
    )

    logger.info(
        "experiment_run",
        extra={
            "run_id": run.id,
            "owner_id": owner_id,
            "strategy": spec.name,
            "components": [f"{c.rule_name}:{c.role}" for c in spec.components],
            "entry_logic": spec.entry_logic,
            "exit_logic": spec.exit_logic,
            "instruments": len(requested_symbols),
            "window": f"{start_date}..{end_date}",
            "signal_count": run.signal_count,
            "trades": len(result.trades),
            "instruments_with_data": instruments_with_data,
            "instruments_full_warmup": instruments_full_warmup,
            # None when the strategy reads no fundamentals at all, which is a
            # different statement from "none of them had any".
            "instruments_with_facts": instruments_with_facts,
            "fact_concepts": wanted_concepts or None,
            "dataset": run.dataset,
            "ingest_run_ids": ingest_runs,
            "corporate_actions": len(actions),
        },
    )
    return run


def execution_config_for(run: dict) -> ExecutionConfig:
    """The execution criteria a stored run was executed under.

    A run recorded before execution criteria existed has none, and gets the
    defaults -- which are exactly the behaviour that was hardcoded at the time,
    so re-deriving its performance still reproduces it.
    """
    stored = run.get("execution")
    if not stored:
        return ExecutionConfig()
    try:
        return ExecutionConfig.from_dict(stored)
    except ValueError:
        # A stored config this build cannot parse is a forward-compatibility
        # problem, not a reason to refuse to show the run at all.
        logger.warning("run_execution_unreadable", extra={"run_id": run.get("id")})
        return ExecutionConfig()
