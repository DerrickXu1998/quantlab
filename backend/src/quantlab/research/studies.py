"""The series a run's rules compared, for drawing beside its signals.

A marker on a chart says *that* a rule fired; the lines it compared say *why*.
They are computed here rather than in the browser (Constitution V) and from the
rule's own declared ``studies`` -- the same indicator functions, the same
parameters the run recorded -- so the lines cannot disagree with the markers.

Pure: given the run record and its bars the answer is byte-identical
(Constitution VI). Bars are expected from the run's warm-up start, so the first
session of the window already has a value; only the window is reported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StudyPoint:
    date: str
    value: float


@dataclass(frozen=True)
class Study:
    #: Stable within a run: ``<component index>.<line key>``, e.g. ``0.sma_fast``.
    key: str
    label: str
    rule_name: str
    points: list[StudyPoint] = field(default_factory=list)


@dataclass(frozen=True)
class RunStudies:
    run_id: str
    symbol: str
    studies: list[Study] = field(default_factory=list)


def _components(run: dict) -> list[tuple[Any, dict[str, Any]]]:
    """(rule, effective parameters) for each component the run executed."""
    from quantlab.strategy import StrategySpec, StrategyValidationError, promote_legacy

    spec = None
    stored = run.get("strategy")
    if stored:
        try:
            spec = StrategySpec.from_dict(stored)
        except (StrategyValidationError, ValueError):
            spec = None
    if spec is None:
        # A run recorded before strategies existed names one rule directly.
        try:
            spec = promote_legacy(
                run["model_name"], run.get("model_version"), run.get("parameters") or {}
            )
        except (KeyError, StrategyValidationError, ValueError):
            return []

    out = []
    for index, component in enumerate(spec.components):
        try:
            out.append((component.resolve(index), component.effective_parameters(index)))
        except (KeyError, StrategyValidationError, ValueError):
            continue
    return out


def compute_studies(
    *,
    run: dict,
    symbol: str,
    bars: list[Any],
    window_start: str | None = None,
    window_end: str | None = None,
) -> RunStudies:
    """Every drawable line the run's rules compared, on ``symbol``'s bars.

    A rule with no declared studies contributes nothing -- an empty list is the
    honest answer for RSI, whose scale is not the price axis. Two components
    running the same rule with the same parameters would draw identical lines,
    so the second is dropped.
    """
    dates = [bar.date for bar in bars]
    seen: set[tuple[str, tuple]] = set()
    studies: list[Study] = []
    for index, (rule, params) in enumerate(_components(run)):
        if rule.studies is None:
            continue
        identity = (rule.name, tuple(sorted(params.items())))
        if identity in seen:
            continue
        seen.add(identity)
        for line in rule.studies(bars, **params):
            points = [
                StudyPoint(date=day, value=float(value))
                for day, value in zip(dates, line.values, strict=True)
                if not math.isnan(value)
                and (window_start is None or day >= window_start)
                and (window_end is None or day <= window_end)
            ]
            studies.append(
                Study(
                    key=f"{index}.{line.key}",
                    label=line.label,
                    rule_name=rule.name,
                    points=points,
                )
            )
    return RunStudies(run_id=run["id"], symbol=symbol, studies=studies)
