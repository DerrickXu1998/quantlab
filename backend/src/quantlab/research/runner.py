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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from typing import Any

import numpy as np

from quantlab.execution import ExecutionConfig, adjustments, minutes, simulate
from quantlab.execution.bars import BARS_PER_SESSION, is_intraday
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

#: Upper bound on instrument-days (symbols x calendar days) in one daily
#: run: ~6M weekday bars, the same budget as intraday below. Daily bars are
#: read as columns (~150 B a bar at peak): all 503 S&P 500 names x 10 years,
#: 1.3M bars, measured +189 MB (it was +765 MB as one object a bar).
MAX_SELECTION_INSTRUMENT_DAYS = 8_400_000

#: Upper bound on bars in one intraday run, estimated before anything is read.
#: Measured on production data at 5m: 2.0M bars +277 MB / 40 s, 4.1M bars
#: +462 MB / 79 s (laptop through the IAP tunnel). 6M is ~650 MB -- a third of
#: the backend's 2 GiB, with one large run at a time -- and ~2 minutes, which
#: is as long as a run should hold an API request open.
MAX_INTRADAY_BARS = 6_000_000

#: A run estimated above this many bars -- daily or intraday -- is "large":
#: it takes the server-wide large-run slot, so at most one is in memory at a
#: time across both workers and every thread. Smaller runs never wait.
LARGE_RUN_BARS = 300_000
#: How long a large run waits for the slot before being refused (429).
LARGE_RUN_WAIT_SECONDS = 30


def warmup_start_for(start: _date, lookback_bars: int, frequency: str) -> str:
    """Where to start loading so the first session of the window has its
    lookback behind it. Lookback is in bars; intraday, a session holds many."""
    sessions = -(-lookback_bars // BARS_PER_SESSION[frequency])  # ceiling
    return (start - timedelta(days=sessions * _CALENDAR_DAYS_PER_BAR)).isoformat()


def estimate_bars(symbols: int, start: str, end: str, frequency: str) -> int:
    """Bars a run over [start, end] would hold, from weekdays alone."""
    after_end = (_date.fromisoformat(end) + timedelta(days=1)).isoformat()
    sessions = int(np.busday_count(start, after_end))
    return symbols * sessions * BARS_PER_SESSION[frequency]


def load_bars(backend, symbols: list[str], start: str, end: str, config: ExecutionConfig) -> dict:
    """Signal bars at the config's frequency, as columns where the store can
    give them (the warehouse, any frequency) and rows where it cannot (the
    demo, daily). Both read the same to every rule and to the engine."""
    if is_intraday(config.bar_frequency):
        return backend.load_intraday_bars(symbols, start, end, config.bar_frequency)
    columns = getattr(backend, "load_daily_columns", None)
    if columns is not None:
        return columns(symbols, start, end)
    return backend.load_bars_for(symbols, start, end)


@dataclass(frozen=True)
class FactCoverage:
    """How much of the selection had the filings the run's rules read.

    A fundamental gate with no facts holds shut and says nothing, so a name
    missing its revenue looks exactly like a name whose revenue never grew.
    This is the part of that silence the result can carry.
    """

    concepts: list[str]
    #: Instruments with at least one filing for *every* concept in ``concepts``.
    instruments_with_facts: int
    #: Per concept, how many requested instruments have no filing for it.
    missing_by_concept: dict[str, int]
    #: The requested instruments lacking at least one concept, in request order.
    instruments_missing_facts: list[str]
    #: The first date every concept had a filing for some requested name.
    fundamentals_start: str | None = None
    #: What the user asked to start from, when that was before
    #: ``fundamentals_start`` and the run was started there instead.
    requested_start_date: str | None = None


@dataclass(frozen=True)
class RunCoverage:
    instruments_requested: int
    instruments_with_data: int
    instruments_full_warmup: int
    #: None when no rule in the run reads fundamentals.
    facts: FactCoverage | None = None


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
    #: The bars the run read, kept only when asked (keep_bars): the worker
    #: computes performance from them rather than reading every bar twice.
    #: Never persisted.
    bars: dict | None = field(default=None, repr=False, compare=False)


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
        raise errors.ParameterValidationError(
            _offending_field(str(exc)), str(exc), qualified=True
        ) from exc
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

    A message with no path -- "a strategy needs at least one entry component"
    -- is about the strategy as a whole, not a field named after its text.
    """
    if ":" not in message:
        return "strategy"
    path = message.split(":", 1)[0]
    leaf = path.rsplit(".", 1)[-1].strip()
    return leaf or "strategy"


@dataclass(frozen=True)
class PreparedRun:
    """A run that passed every check that needs no bars.

    What the API does inside the request before queueing: everything here is
    cheap, so a run that could never succeed is refused at once rather than
    queued and failed minutes later.
    """

    spec: StrategySpec
    symbols: list[str]
    start_date: str
    end_date: str
    warmup_start: str
    #: Bars the run will read, from weekdays alone (see estimate_bars).
    estimated_bars: int
    #: Where the fundamentals the rules read begin; None for bars-only runs.
    fundamentals_start: str | None = None
    #: The start as submitted, when it was moved up to ``fundamentals_start``.
    requested_start_date: str | None = None

    @property
    def large(self) -> bool:
        return self.estimated_bars > LARGE_RUN_BARS

    def request(self) -> dict[str, Any]:
        """Everything the worker needs to run this later, as plain JSON.

        The resolved spec rather than the request as sent: a run pinned to a
        saved strategy id would otherwise execute whatever that id holds when
        the worker reaches it, not what was submitted.
        """
        return {
            "strategy": self.spec.to_dict(),
            "symbols": list(self.symbols),
            # As submitted, not as limited: the worker prepares the run again,
            # and must still know what was asked for to report it.
            "start_date": self.requested_start_date or self.start_date,
            "end_date": self.end_date,
        }


def required_concepts(spec: StrategySpec) -> list[str]:
    """Fundamental concepts the strategy's rules read, e.g. net_income."""
    return sorted(
        {
            concept
            for index, component in enumerate(spec.components)
            for concept in component.resolve(index).requires_facts
        }
    )


def required_series(spec: StrategySpec) -> list[str]:
    """Other instruments' series the strategy's rules read, e.g. VIX.FRED."""
    return sorted(
        {
            name
            for index, component in enumerate(spec.components)
            for name in component.resolve(index).requires_series
        }
    )


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
    prepared = prepare_run(
        backend,
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        strategy=strategy,
        model_name=model_name,
        model_version=model_version,
        overrides=overrides,
        execution=execution,
    )
    if not prepared.large:
        return execute_prepared(backend, prepared, owner_id=owner_id)
    with backend.large_run_slot(LARGE_RUN_WAIT_SECONDS) as acquired:
        if not acquired:
            raise errors.LargeRunBusyError()
        return execute_prepared(backend, prepared, owner_id=owner_id)


def prepare_run(
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
) -> PreparedRun:
    """Resolve and check a run without reading a bar. Raises the same typed
    errors run_experiment always has, so the API maps them to the same codes."""
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

    # A strategy that reads fundamentals starts where they do. Before the
    # first filing every fundamental gate holds shut, so those years would be
    # a flat line against a moving benchmark -- a data gap reported as a
    # result. Limited rather than refused: the user asked for a backtest, and
    # the part of the window the data can answer is still one. Done before the
    # size checks, which then measure the window that will actually run.
    requested_start_date = None
    fundamentals_start = None
    concepts = required_concepts(spec)
    if concepts:
        fundamentals_start = backend.fundamentals_start(requested_symbols, concepts, end_date)
        if fundamentals_start is not None and fundamentals_start > start_date:
            requested_start_date, start_date = start_date, fundamentals_start
            start = _parse(start_date, "start_date")
    window_days = (end - start).days + 1
    frequency = spec.execution.bar_frequency
    intraday = is_intraday(frequency)
    selection_size = len(requested_symbols) * window_days
    if not intraday and selection_size > MAX_SELECTION_INSTRUMENT_DAYS:
        raise errors.SelectionTooLargeError(selection_size, MAX_SELECTION_INSTRUMENT_DAYS)
    if intraday and getattr(backend, "name", None) == "sqlite":
        raise errors.DatasetUnsupportedError(f"{frequency} bars", "synthetic demo")

    unknown = backend.validate_symbols(requested_symbols)
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
    # Macro series the rules read (the regime gate's VIX and HY spread).
    # Checked here, before queueing, so a missing one is an answer at submit
    # rather than a run that is queued, started and then failed.
    wanted_series = required_series(spec)
    if wanted_series:
        missing = backend.validate_symbols(wanted_series)
        if missing:
            raise errors.MissingSeriesError(missing)

    lookback_days = spec.lookback_days  # in bars, whatever the frequency
    window_bars = int(window_days * _BARS_PER_CALENDAR_DAY) * BARS_PER_SESSION[frequency]
    if window_bars < lookback_days:
        raise errors.WindowTooShortError(lookback_days, window_days)

    warmup_start = warmup_start_for(start, lookback_days, frequency)
    # Refused before a single bar is read: the estimate is cheap, the read and
    # the run are not.
    estimate = estimate_bars(len(requested_symbols), warmup_start, end_date, frequency)
    if intraday and estimate > MAX_INTRADAY_BARS:
        raise errors.IntradaySelectionTooLargeError(estimate, MAX_INTRADAY_BARS, frequency)

    return PreparedRun(
        spec=spec,
        symbols=requested_symbols,
        start_date=start_date,
        end_date=end_date,
        warmup_start=warmup_start,
        estimated_bars=estimate,
        fundamentals_start=fundamentals_start,
        requested_start_date=requested_start_date,
    )


def execute_prepared(
    backend,
    prepared: PreparedRun,
    *,
    owner_id: str | None = None,
    run_id: str | None = None,
    should_cancel=None,
    keep_bars: bool = False,
) -> RunResult:
    """Run a prepared run. ``run_id`` keeps the id the run was queued under;
    ``should_cancel`` is asked between stages and raises RunCancelledError."""
    return _execute(
        backend,
        prepared.spec,
        prepared.symbols,
        prepared.start_date,
        prepared.end_date,
        prepared.warmup_start,
        owner_id,
        run_id=run_id,
        should_cancel=should_cancel,
        keep_bars=keep_bars,
        fundamentals_start=prepared.fundamentals_start,
        requested_start_date=prepared.requested_start_date,
    )


def _execute(
    backend,
    spec: StrategySpec,
    requested_symbols: list[str],
    start_date: str,
    end_date: str,
    warmup_start: str,
    owner_id: str | None,
    *,
    run_id: str | None = None,
    should_cancel=None,
    keep_bars: bool = False,
    fundamentals_start: str | None = None,
    requested_start_date: str | None = None,
) -> RunResult:
    """Load, compose, execute and summarise a validated run."""

    def checkpoint() -> None:
        # Between stages, never inside one: a stage is the unit of work that
        # can be thrown away cleanly. Cancelling mid-read would leave nothing
        # half-written anyway, since nothing is written until the end.
        if should_cancel is not None and should_cancel():
            raise errors.RunCancelledError()

    checkpoint()
    bars_by_symbol = load_bars(backend, requested_symbols, warmup_start, end_date, spec.execution)
    checkpoint()

    # Only the concepts this strategy's rules declared. Loading the whole
    # vocabulary would be several million rows for a question nobody asked, and
    # loading none would leave every fundamental gate shut.
    #
    # There is no lower bound on filed_at inside the reader: the figure in
    # force on the warm-up morning was filed before it, often long before, so a
    # window bounded at `warmup_start` would start every run with no
    # fundamentals at all (docs/FUNDAMENTALS.md §2).
    wanted_concepts = required_concepts(spec)
    facts_by_symbol = (
        backend.load_facts_for(requested_symbols, wanted_concepts, warmup_start, end_date)
        if wanted_concepts
        else {}
    )
    fact_coverage = _fact_coverage(requested_symbols, wanted_concepts, facts_by_symbol)
    if fact_coverage is not None:
        fact_coverage = replace(
            fact_coverage,
            fundamentals_start=fundamentals_start,
            requested_start_date=requested_start_date,
        )
    if fact_coverage is not None and all(
        missing == len(requested_symbols) for missing in fact_coverage.missing_by_concept.values()
    ):
        # Not one filing for any concept the rules read: every fundamental gate
        # would hold shut, and the result would be indistinguishable from a
        # strategy that ran and found nothing. Refuse, naming the cause.
        requirement = f"fundamentals ({', '.join(wanted_concepts)})"
        if getattr(backend, "name", None) == "sqlite":
            raise errors.DatasetUnsupportedError(requirement, "synthetic demo")
        raise errors.NoFactCoverageError(wanted_concepts, len(requested_symbols), end_date)

    # Cross-instrument inputs (the macro gates' VIX and HY spread), loaded over
    # the same warm-up window. Refused up front if the store does not have
    # them: a gate reading an empty series stays shut, and a run that never
    # trades for want of data is indistinguishable from one with no signals.
    wanted_series = required_series(spec)
    series: dict[str, list] = {}
    if wanted_series:
        # Checked at submission (prepare_run); checked again here because a
        # queued run can wait while the catalog changes.
        missing = backend.validate_symbols(wanted_series)
        if missing:
            raise errors.MissingSeriesError(missing)
        series = backend.load_bars_for(wanted_series, warmup_start, end_date)

    # Splits and dividends from the warm-up start: an action in the warm-up
    # still restates every bar before it, and those bars feed the indicators.
    # Signals read back-adjusted bars; the engine trades the raw ones and is
    # handed the actions as events (execution.adjustments).
    mode = spec.execution.price_adjustment
    all_actions = backend.corporate_actions(requested_symbols, warmup_start, end_date)
    actions = adjustments.by_symbol(all_actions, mode, end=end_date)
    signal_bars = adjustments.adjust_all(bars_by_symbol, actions)

    decisions, composition = compose(
        spec,
        signal_bars,
        requested_symbols,
        facts_by_symbol=facts_by_symbol,
        series=series,
    )
    # Warm-up bars are inputs, not results: report only the requested window.
    in_window = [d for d in decisions if start_date <= d.date <= end_date]
    checkpoint()

    # Execute over the full loaded series -- an ATR stop set on the first
    # session of the window needs the bars behind it -- but score only from the
    # window start. Nothing can happen before it: no decision exists there.
    result = simulate(
        requested_symbols,
        bars_by_symbol,
        in_window,
        spec.execution,
        actions,
        # Read lazily, a symbol-month at a time, and only for sessions where
        # an order or a protective level lands; None for a daily run.
        minutes.source_for(backend, spec.execution),
    )
    checkpoint()

    # Surrogate identities, where the store has them. Recorded because the
    # canonical symbol is unique but editable, while instrument_id is the
    # stable key the bar store joins on.
    ids = backend.instrument_ids(requested_symbols)
    instrument_ids = [ids[s] for s in requested_symbols if s in ids] or None

    # Which ingest produced the bars we just read. Two runs with identical
    # configuration either side of a re-ingest differ here and nowhere else.
    ingest_runs = backend.ingest_run_ids(requested_symbols, warmup_start, end_date) or None

    earliest = backend.earliest_bar_dates(requested_symbols)
    # The window's actions, reported with the run. Whether they were applied
    # is the run's `execution.price_adjustment`; under `none` a split inside
    # the window makes the series jump in a way that is an artefact.
    window_actions = [a for a in all_actions if start_date <= str(a["ex_date"])[:10] <= end_date]
    instruments_with_facts = (
        fact_coverage.instruments_with_facts if fact_coverage is not None else None
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
        id=run_id or uuid.uuid4().hex,
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
            facts=fact_coverage,
        ),
        signals=in_window,
        dataset=getattr(backend, "name", "sqlite"),
        instrument_ids=instrument_ids,
        ingest_run_ids=ingest_runs,
        corporate_actions=window_actions,
        strategy=spec.to_dict(),
        execution=spec.execution.to_dict(),
        execution_summary={
            **vars(result.summary),
            "contradictions": composition.contradictions,
        },
        owner_id=owner_id,
        bars=bars_by_symbol if keep_bars else None,
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
            "corporate_actions": len(window_actions),
        },
    )
    return run


def _fact_coverage(
    symbols: list[str], concepts: list[str], facts_by_symbol: dict
) -> FactCoverage | None:
    """Which requested instruments had each concept the run's rules read."""
    if not concepts:
        return None

    def has(symbol: str, concept: str) -> bool:
        series = facts_by_symbol.get(symbol)
        return bool(series) and series.has(concept)

    missing = [s for s in symbols if not all(has(s, c) for c in concepts)]
    return FactCoverage(
        concepts=list(concepts),
        instruments_with_facts=len(symbols) - len(missing),
        missing_by_concept={c: sum(1 for s in symbols if not has(s, c)) for c in concepts},
        instruments_missing_facts=missing,
    )


def execution_config_for(run: dict) -> ExecutionConfig:
    """The execution criteria a stored run was executed under.

    A run recorded before execution criteria existed has none, and gets the
    defaults -- which are exactly the behaviour that was hardcoded at the time,
    so re-deriving its performance still reproduces it. Likewise a run recorded
    before ``price_adjustment`` existed traded raw prices, and gets ``none``.
    """
    stored = run.get("execution")
    if not stored:
        return ExecutionConfig(price_adjustment="none")
    # Recorded before splits and dividends were applied: it ran on raw prices.
    stored = {"price_adjustment": "none", **stored}
    try:
        return ExecutionConfig.from_dict(stored)
    except ValueError:
        # A stored config this build cannot parse is a forward-compatibility
        # problem, not a reason to refuse to show the run at all.
        logger.warning("run_execution_unreadable", extra={"run_id": run.get("id")})
        return ExecutionConfig(price_adjustment="none")
