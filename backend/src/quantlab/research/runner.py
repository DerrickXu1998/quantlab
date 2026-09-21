"""Run a registered model over a dataset selection (feature 005).

Library logic, not route logic (Constitution I): this is independently testable
without HTTP, and the API layer is a thin adapter over it.

The warm-up window is the subtle part. A model declares ``lookback_days``; if a
run loaded only the bars inside the requested window, the first ``lookback_days``
of that window could not emit, and a short window would understate the model
without anything saying so. Bars are therefore loaded from ``start - lookback``
and only signals dated inside the requested window are reported.

Reading bars *before* the window start is past data relative to every emitted
signal, so it cannot introduce look-ahead; the forbidden direction (a signal
built from a later bar) is enforced by the CHECK constraint on
``experiment_signals`` and by the truncation sweep (Constitution VII).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from typing import Any

from quantlab import fundamentals as fundamentals_lib
from quantlab.logging import get_logger
from quantlab.research import errors, performance
from quantlab.signals import templates as signal_templates
from quantlab.signals.engine import ComputedSignal, compute_signals
from quantlab.signals.registry import SignalRule, get_rule

logger = get_logger(__name__)

#: Calendar days of padding per lookback bar. Bars are weekdays only, so a
#: lookback of N bars spans at most roughly N * 7/5 calendar days; the extra
#: margin absorbs holidays.
_CALENDAR_DAYS_PER_BAR = 2

#: Upper bound on instrument-days accepted in one synchronous run.
MAX_SELECTION_INSTRUMENT_DAYS = 2_000_000

#: How far before the window facts load for a fundamental rule: a yoy_growth
#: crossing needs the prior year's filings as its base, plus margin for a
#: late-filed prior-year report.
_FUNDAMENTALS_WARMUP_DAYS = 3 * 365


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
    signals: list[ComputedSignal] = field(default_factory=list)
    error: str | None = None
    name: str | None = None
    # Provenance (feature 006). `dataset` says which store produced the run;
    # the other two are warehouse-only and stay None on the demo.
    dataset: str = "sqlite"
    instrument_ids: list[int] | None = None
    ingest_run_ids: list[int] | None = None
    corporate_actions: list[dict] = field(default_factory=list)
    # Execution criteria the run was created with (costs, stops, sizing, fill
    # timing). None means the historical zero-cost equal-weight measuring
    # instrument -- and is what every run recorded before they existed carries.
    execution: dict[str, Any] | None = None
    # Snapshot of the custom rule's definition at run time (feature 008):
    # template + config + derived lookback. None for builtin-model runs. The
    # snapshot is what makes a run reproducible after the rule is edited or
    # deleted.
    custom_rule: dict[str, Any] | None = None


def _parse(value: str, field_name: str) -> _date:
    try:
        return _date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise errors.InvalidWindowError(f"{field_name} is not an ISO date: {value!r}") from exc


def _resolve_model(model_name: str, model_version: str | None) -> SignalRule:
    try:
        return get_rule(model_name, model_version)
    except KeyError as exc:
        raise errors.UnknownModelError(model_name, model_version) from exc


def _resolve_custom_rule(custom_rule: dict[str, Any]) -> tuple[SignalRule, dict[str, Any]]:
    """Instantiate a stored custom rule and snapshot its resolved definition.

    The snapshot (template + config + derived lookback) is recorded on the run:
    editing or deleting the rule afterwards must never rewrite what the run
    actually computed (Constitution VI).
    """
    try:
        template = signal_templates.get_template(custom_rule["template"])
    except KeyError as exc:
        raise errors.UnknownModelError(custom_rule.get("template", "?")) from exc
    try:
        template.validate(custom_rule["config"])
    except ValueError as exc:
        raise errors.ParameterValidationError("custom_rule_id", f"invalid config: {exc}") from exc
    rule = signal_templates.rule_from_definition(
        template.id,
        custom_rule["config"],
        name=custom_rule["slug"],
        version=template.version,
    )
    snapshot = {
        "rule_id": custom_rule["rule_id"],
        "name": custom_rule["name"],
        "slug": custom_rule["slug"],
        "template": template.id,
        "config": custom_rule["config"],
        "lookback_days": rule.lookback_days,
    }
    return rule, snapshot


def _validate_overrides(rule: SignalRule, overrides: dict[str, Any]) -> dict[str, Any]:
    for key, value in overrides.items():
        spec = rule.param_specs.get(key)
        if spec is None:
            raise errors.ParameterValidationError(key, "is not a parameter of this model")
        problem = spec.validation_error(value)
        if problem is not None:
            raise errors.ParameterValidationError(key, problem)
    return rule.effective_params(overrides)


def run_experiment(
    backend,
    *,
    model_name: str | None = None,
    overrides: dict[str, Any] | None = None,
    symbols: list[str],
    start_date: str,
    end_date: str,
    model_version: str | None = None,
    execution: dict[str, Any] | None = None,
    custom_rule: dict[str, Any] | None = None,
) -> RunResult:
    """Validate, execute, and summarise one run. Does not persist.

    Takes a StorageBackend rather than a connection, so the runner does not
    know whether it is reading the synthetic demo or real ingested history.

    ``execution`` is provenance, not an input to the signal compute: the
    criteria change how the run's signals are later turned into fills, so the
    effective set is validated here and recorded on the run.

    Exactly one model selector applies: ``model_name`` (a registry builtin) or
    ``custom_rule`` (a stored custom-rule record). A custom rule's config is
    fixed at definition time, so parameter overrides cannot combine with it.
    """
    overrides = dict(overrides or {})
    if (model_name is None) == (custom_rule is None):
        raise errors.ParameterValidationError(
            "model_name", "exactly one of model_name and custom_rule_id is required"
        )
    if custom_rule is not None:
        if overrides:
            raise errors.ParameterValidationError(
                "parameters", "a custom rule's config is fixed; overrides do not apply"
            )
        rule, snapshot = _resolve_custom_rule(custom_rule)
        effective: dict[str, Any] = {}
    else:
        snapshot = None
        rule = _resolve_model(model_name, model_version)
        effective = _validate_overrides(rule, overrides)

    if rule.inputs != "bars" and getattr(backend, "name", "sqlite") != "warehouse":
        # A clean refusal, not a crash on an empty facts read: the demo holds
        # no fundamentals, and an all-empty run would look like "no signals".
        raise errors.DatasetUnsupportedError(rule.inputs, getattr(backend, "name", "sqlite"))

    effective_execution: dict[str, Any] | None = None
    if execution is not None:
        try:
            effective_execution = asdict(performance.execution_criteria(execution))
        except ValueError as exc:
            raise errors.ParameterValidationError("execution", str(exc)) from exc

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

    # A window narrower than the model's lookback cannot produce a meaningful
    # result; refuse it rather than returning a misleading empty one.
    if window_days < rule.lookback_days:
        raise errors.WindowTooShortError(rule.lookback_days, window_days)

    warmup_start = (start - timedelta(days=rule.lookback_days * _CALENDAR_DAYS_PER_BAR)).isoformat()
    bars_by_symbol = backend.load_bars_for(requested_symbols, warmup_start, end_date)

    facts_by_symbol = None
    if rule.inputs == "bars+fundamentals":
        # Bar lookback says nothing about when filings arrive. A yoy_growth
        # crossing needs the prior year's facts as its base, so facts load
        # from start - 3 years; facts earlier than that cannot move a signal
        # inside the window.
        facts_start = (start - timedelta(days=_FUNDAMENTALS_WARMUP_DAYS)).isoformat()
        facts_by_symbol = {
            symbol: fundamentals_lib.fetch_facts(
                backend, symbol, snapshot["config"]["concept"], start=facts_start
            )[0]
            for symbol in requested_symbols
        }

    computed = compute_signals(
        bars_by_symbol, rules=[rule], overrides=overrides, facts_by_symbol=facts_by_symbol
    )
    # Warm-up bars are inputs, not results: report only the requested window.
    in_window = [s for s in computed if start_date <= s.date <= end_date]

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
    instruments_with_data = sum(1 for symbol in requested_symbols if bars_by_symbol.get(symbol))
    instruments_full_warmup = sum(
        1
        for symbol in requested_symbols
        if bars_by_symbol.get(symbol) and earliest.get(symbol, "9999-12-31") <= warmup_start
    )

    result = RunResult(
        id=uuid.uuid4().hex,
        model_name=rule.name,
        model_version=rule.version,
        parameters=effective,
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
        execution=effective_execution,
        custom_rule=snapshot,
    )

    logger.info(
        "experiment_run",
        extra={
            "run_id": result.id,
            "model": f"{rule.name}@{rule.version}",
            "parameters": effective,
            "instruments": len(requested_symbols),
            "window": f"{start_date}..{end_date}",
            "signal_count": result.signal_count,
            "instruments_with_data": instruments_with_data,
            "instruments_full_warmup": instruments_full_warmup,
            "dataset": result.dataset,
            "ingest_run_ids": ingest_runs,
            "corporate_actions": len(actions),
        },
    )
    return result
