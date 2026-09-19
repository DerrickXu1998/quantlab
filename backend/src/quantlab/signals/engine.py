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
) -> list[ComputedSignal]:
    rules = list(rules) if rules is not None else list_rules()
    out: list[ComputedSignal] = []
    for symbol in sorted(bars_by_symbol):
        bars = bars_by_symbol[symbol]
        for rule in rules:
            if len(bars) < rule.lookback_days:
                continue
            for event in rule.compute(bars, **rule.params):
                out.append(
                    ComputedSignal(
                        symbol=symbol,
                        date=event.date,
                        rule_name=rule.name,
                        rule_version=rule.version,
                        parameters=dict(rule.params),
                        direction=event.direction,
                        trigger_values=dict(event.trigger_values),
                        data_window_end=event.data_window_end,
                    )
                )
    out.sort(key=lambda s: (s.symbol, s.date, s.rule_name))
    return out
