"""Decorator-based plugin registry for indicators (Constitution II).

Adding an indicator never touches registry or engine code: decorate a function
with :func:`register_indicator` and it becomes enumerable at runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

SCALE_CLASSES: tuple[str, ...] = ("scale_free", "price_scaled")


@dataclass(frozen=True)
class IndicatorPlugin:
    name: str
    version: str
    scale_class: str
    params: dict[str, Any]
    description: str
    compute: Callable[..., Any]


_REGISTRY: dict[tuple[str, str], IndicatorPlugin] = {}


def register_indicator(
    *,
    name: str,
    version: str,
    scale_class: str,
    params: dict[str, Any] | None = None,
    description: str = "",
) -> Callable:
    if scale_class not in SCALE_CLASSES:
        raise ValueError(f"invalid scale_class {scale_class!r}; expected one of {SCALE_CLASSES}")

    def decorator(fn: Callable) -> Callable:
        key = (name, version)
        if key in _REGISTRY:
            raise ValueError(f"duplicate indicator registration: {name} v{version}")
        _REGISTRY[key] = IndicatorPlugin(
            name=name,
            version=version,
            scale_class=scale_class,
            params=dict(params or {}),
            description=description or (fn.__doc__ or "").strip(),
            compute=fn,
        )
        return fn

    return decorator


def get_indicator(name: str, version: str | None = None) -> IndicatorPlugin:
    if version is not None:
        return _REGISTRY[(name, version)]
    matches = [plugin for (n, _), plugin in _REGISTRY.items() if n == name]
    if not matches:
        raise KeyError(f"unknown indicator: {name!r}")
    return sorted(matches, key=lambda p: p.version)[-1]


def list_indicators() -> list[IndicatorPlugin]:
    return [_REGISTRY[key] for key in sorted(_REGISTRY)]
