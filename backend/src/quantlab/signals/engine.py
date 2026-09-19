"""Signal engine: run every registered rule over the universe.

Deterministic output ordering (symbol, date, rule_name); rules are skipped
until their declared ``lookback_days`` of history is available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quantlab.signals import builtins as _builtins  # noqa: F401  (registers builtin rules)
from quantlab.signals.registry import SignalRule, list_rules


@dataclass(frozen=True)
class ComputedSignal:
    symbol: str
    date: str
    rule_name: str
    rule_version: str
    parameters: dict[str, Any]
    direction: str
    trigger_values: dict[str, Any]
    data_window_end: str


def compute_signals(
    bars_by_symbol: dict[str, list[Any]],
    rules: list[SignalRule] | None = None,
    overrides: dict[str, Any] | None = None,
) -> list[ComputedSignal]:
    """Run ``rules`` over the supplied bars.

    ``overrides`` replaces declared parameter defaults for this call. The
    *effective* parameters (defaults merged with overrides) are what get
    recorded on each signal — recording the bare defaults while executing
    overrides would make the record unreproducible (Constitution VI).
    """
    rules = list(rules) if rules is not None else list_rules()
    # Resolved once per rule so an unknown override key fails immediately,
    # rather than after part of the universe has already been processed.
    effective_by_rule = {
        (rule.name, rule.version): rule.effective_params(overrides) for rule in rules
    }

    out: list[ComputedSignal] = []
    for symbol in sorted(bars_by_symbol):
        bars = bars_by_symbol[symbol]
        for rule in rules:
            if len(bars) < rule.lookback_days:
                continue
            effective = effective_by_rule[(rule.name, rule.version)]
            for event in rule.compute(bars, **effective):
                out.append(
                    ComputedSignal(
                        symbol=symbol,
                        date=event.date,
                        rule_name=rule.name,
                        rule_version=rule.version,
                        parameters=dict(effective),
                        direction=event.direction,
                        trigger_values=dict(event.trigger_values),
                        data_window_end=event.data_window_end,
                    )
                )
    out.sort(key=lambda s: (s.symbol, s.date, s.rule_name))
    return out
