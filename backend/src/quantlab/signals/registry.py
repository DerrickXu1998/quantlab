"""Decorator-based plugin registry for signal rules (Constitution II).

A signal rule maps one instrument's bar history (objects with ``date``, ``open``,
``high``, ``low``, ``close``, ``volume`` attributes, ascending by date) to zero
or more :class:`SignalEvent`s. Rules MUST be causal: the event emitted at day T
may only depend on bars with ``date <= T`` (Constitution VII), which the
truncation sweep test enforces for every registered rule.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

DIRECTIONS: tuple[str, ...] = ("bullish", "bearish")
SCALE_CLASSES: tuple[str, ...] = ("scale_free", "price_scaled")


@dataclass(frozen=True)
class SignalEvent:
    """One emitted signal. ``data_window_end`` is the latest bar date used as
    input and must always be ``<= date`` (point-in-time proof)."""

    date: str
    direction: str
    trigger_values: dict[str, Any]
    data_window_end: str


@dataclass(frozen=True)
class SignalRule:
    name: str
    version: str
    params: dict[str, Any]
    lookback_days: int
    scale_class: str
    direction_semantics: str
    compute: Callable[[Sequence[Any]], list[SignalEvent]]


_REGISTRY: dict[tuple[str, str], SignalRule] = {}


def register_signal_rule(
    *,
    name: str,
    version: str,
    params: dict[str, Any] | None = None,
    lookback_days: int,
    scale_class: str,
    direction_semantics: str,
) -> Callable:
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    if scale_class not in SCALE_CLASSES:
        raise ValueError(f"invalid scale_class {scale_class!r}; expected one of {SCALE_CLASSES}")

    def decorator(fn: Callable) -> Callable:
        key = (name, version)
        if key in _REGISTRY:
            raise ValueError(f"duplicate signal rule registration: {name} v{version}")
        _REGISTRY[key] = SignalRule(
            name=name,
            version=version,
            params=dict(params or {}),
            lookback_days=lookback_days,
            scale_class=scale_class,
            direction_semantics=direction_semantics,
            compute=fn,
        )
        return fn

    return decorator


def get_rule(name: str, version: str | None = None) -> SignalRule:
    if version is not None:
        return _REGISTRY[(name, version)]
    matches = [rule for (n, _), rule in _REGISTRY.items() if n == name]
    if not matches:
        raise KeyError(f"unknown signal rule: {name!r}")
    return sorted(matches, key=lambda r: r.version)[-1]


def list_rules() -> list[SignalRule]:
    return [_REGISTRY[key] for key in sorted(_REGISTRY)]
