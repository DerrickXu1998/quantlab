"""Decorator-based plugin registry for signal rules (Constitution II).

A signal rule maps one instrument's bar history (objects with ``date``, ``open``,
``high``, ``low``, ``close``, ``volume`` attributes, ascending by date) to zero
or more :class:`SignalEvent`s. Rules MUST be causal: the event emitted at day T
may only depend on bars with ``date <= T`` (Constitution VII), which the
truncation sweep test enforces for every registered rule.

Rules declare their parameters as :class:`ParamSpec`s so the registry can expose
parameter metadata for runtime discovery (Constitution II: the frontend
enumerates available models *and their parameter metadata*). The older
``params={"fast": 20}`` shorthand remains supported and is normalised into
specs with an inferred type and no bounds, so existing rules register unchanged.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Pure stdlib module -- dataclasses and bisect, no database driver -- so the
# signal registry can know the fundamental vocabulary without dragging the
# storage layer into its import path.
from quantlab.storage.facts import KNOWN_CONCEPTS

DIRECTIONS: tuple[str, ...] = ("bullish", "bearish")
SCALE_CLASSES: tuple[str, ...] = ("scale_free", "price_scaled")
PARAM_TYPES: tuple[str, ...] = ("int", "float", "bool", "enum")

#: How a rule is grouped in the catalogue. Presentation metadata, not
#: behaviour: nothing in the engine branches on it.
CATEGORIES: tuple[str, ...] = (
    "trend",
    "momentum",
    "mean_reversion",
    "volatility",
    "volume",
    # Rules reading filed company accounts rather than the tape. Grouped apart
    # because a user needs to know *before* building that these names may have
    # no fundamentals at all, and that they step a few times a year rather
    # than every bar (docs/FUNDAMENTALS.md §6).
    "fundamental",
)

#: Which slots in a strategy a rule may occupy. A rule that reports a *regime*
#: rather than a tradeable event -- ADX above a threshold, say -- advertises
#: ("filter",) only, and the strategy validator refuses to wire it as an entry.
#: Without this a user can build a strategy that enters every single bar and
#: has no way to see why.
ROLES: tuple[str, ...] = ("entry", "exit", "filter")

_NUMERIC_TYPES: tuple[str, ...] = ("int", "float")


@dataclass(frozen=True)
class SignalEvent:
    """One emitted signal. ``data_window_end`` is the latest bar date used as
    input and must always be ``<= date`` (point-in-time proof)."""

    date: str
    direction: str
    trigger_values: dict[str, Any]
    data_window_end: str


@dataclass(frozen=True)
class ParamSpec:
    """One configurable input of a rule, with enough metadata for a caller to
    build a form and validate a value without knowing the rule.

    Declaration errors raise at registration (import time) rather than surfacing
    later as a confusing run-time rejection.
    """

    name: str
    type: str
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    choices: list[Any] | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if self.type not in PARAM_TYPES:
            raise ValueError(f"invalid param type {self.type!r}; expected one of {PARAM_TYPES}")

        numeric = self.type in _NUMERIC_TYPES
        if not numeric and (self.minimum is not None or self.maximum is not None):
            raise ValueError(
                f"{self.name}: minimum/maximum are only valid on numeric types {_NUMERIC_TYPES}"
            )
        if self.type == "enum":
            if not self.choices:
                raise ValueError(f"{self.name}: choices is required and must be non-empty for enum")
        elif self.choices is not None:
            raise ValueError(f"{self.name}: choices is only valid when type is 'enum'")

        if self.minimum is not None and self.maximum is not None and self.maximum < self.minimum:
            raise ValueError(f"{self.name}: maximum must be >= minimum")

        # A default that violates its own constraints is a declaration bug.
        problem = self.validation_error(self.default)
        if problem is not None:
            raise ValueError(f"{self.name}: default is invalid: {problem}")

    def validation_error(self, value: Any) -> str | None:
        """Return why ``value`` is unacceptable, or None when it is fine."""
        if self.type == "bool":
            if not isinstance(value, bool):
                return f"expected a bool, got {type(value).__name__}"
            return None
        if self.type == "int":
            # bool is a subclass of int in Python; do not accept it as one.
            if isinstance(value, bool) or not isinstance(value, int):
                return f"expected an int, got {type(value).__name__}"
        elif self.type == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"expected a number, got {type(value).__name__}"
        elif self.type == "enum":
            if value not in (self.choices or []):
                return f"expected one of {self.choices!r}"
            return None

        if self.minimum is not None and value < self.minimum:
            return f"must be >= {self.minimum}"
        if self.maximum is not None and value > self.maximum:
            return f"must be <= {self.maximum}"
        return None


def _infer_type(value: Any) -> str:
    # Order matters: bool is a subclass of int.
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    raise ValueError(f"cannot infer a param type from {value!r}; declare a ParamSpec explicitly")


def _normalise_params(params: dict[str, Any] | None) -> dict[str, ParamSpec]:
    """Accept either ParamSpecs or the bare-value shorthand."""
    specs: dict[str, ParamSpec] = {}
    for name, value in (params or {}).items():
        if isinstance(value, ParamSpec):
            if value.name != name:
                raise ValueError(f"param key {name!r} does not match ParamSpec name {value.name!r}")
            specs[name] = value
        else:
            specs[name] = ParamSpec(name=name, type=_infer_type(value), default=value)
    return specs


@dataclass(frozen=True)
class SignalRule:
    name: str
    version: str
    param_specs: dict[str, ParamSpec]
    lookback_days: int
    scale_class: str
    direction_semantics: str
    compute: Callable[..., list[SignalEvent]]
    #: Catalogue metadata. Defaulted so every rule registered before the
    #: catalogue existed keeps registering unchanged.
    category: str = "trend"
    summary: str = ""
    roles: tuple[str, ...] = ("entry", "exit")
    #: Fundamental concepts this rule cannot work without. Empty for every
    #: rule that reads only bars, which is what keeps the contract backwards
    #: compatible. The runner loads exactly these, and the catalogue reports
    #: them so a user can be told which of their instruments will never trade
    #: before they run rather than after (docs/FUNDAMENTALS.md §5.1).
    requires_facts: tuple[str, ...] = ()

    @property
    def needs_facts(self) -> bool:
        return bool(self.requires_facts)

    @property
    def params(self) -> dict[str, Any]:
        """Declared defaults as plain values (the pre-existing surface)."""
        return {name: spec.default for name, spec in self.param_specs.items()}

    def effective_params(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """Declared defaults merged with ``overrides``.

        This is what must be recorded as a run's provenance — recording the bare
        defaults while executing overrides would make the record unreproducible
        (Constitution VI).
        """
        merged = self.params
        for key, value in (overrides or {}).items():
            if key not in self.param_specs:
                raise KeyError(f"{self.name}: unknown parameter {key!r}")
            merged[key] = value
        return merged

    def validate(self, values: dict[str, Any]) -> None:
        """Raise ValueError naming the first parameter that fails its spec."""
        for key, value in values.items():
            spec = self.param_specs.get(key)
            if spec is None:
                raise ValueError(f"unknown parameter {key!r}")
            problem = spec.validation_error(value)
            if problem is not None:
                raise ValueError(f"{key}: {problem}")


_REGISTRY: dict[tuple[str, str], SignalRule] = {}


def register_signal_rule(
    *,
    name: str,
    version: str,
    params: dict[str, Any] | None = None,
    lookback_days: int,
    scale_class: str,
    direction_semantics: str,
    category: str = "trend",
    summary: str = "",
    roles: tuple[str, ...] = ("entry", "exit"),
    requires_facts: tuple[str, ...] = (),
) -> Callable:
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    if scale_class not in SCALE_CLASSES:
        raise ValueError(f"invalid scale_class {scale_class!r}; expected one of {SCALE_CLASSES}")
    if category not in CATEGORIES:
        raise ValueError(f"invalid category {category!r}; expected one of {CATEGORIES}")
    if not roles:
        raise ValueError(f"{name}: roles must name at least one of {ROLES}")
    unknown_roles = [role for role in roles if role not in ROLES]
    if unknown_roles:
        raise ValueError(f"{name}: invalid roles {unknown_roles}; expected from {ROLES}")
    # A rule that names a concept nobody ingests would register cleanly and then
    # never open its gate, which is indistinguishable from a rule that simply
    # found nothing. Fail at import instead.
    unknown_concepts = [c for c in requires_facts if c not in KNOWN_CONCEPTS]
    if unknown_concepts:
        raise ValueError(
            f"{name}: requires unknown fundamental concept(s) {unknown_concepts}; "
            f"expected from {sorted(KNOWN_CONCEPTS)}"
        )


    param_specs = _normalise_params(params)

    def decorator(fn: Callable) -> Callable:
        # Every declared parameter must be an accepted keyword of the compute
        # function, or a run would fail with an opaque TypeError in the engine.
        signature = inspect.signature(fn)
        accepts_kwargs = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()
        )
        if not accepts_kwargs:
            for param_name in param_specs:
                if param_name not in signature.parameters:
                    raise ValueError(
                        f"{name}: declared parameter {param_name!r} is not a keyword of "
                        f"{fn.__name__}{signature}"
                    )

        # A rule that reads facts must accept them. Without this it registers
        # cleanly, the runner loads its concepts, and compute() raises
        # TypeError partway through the first run that uses it.
        if requires_facts and not accepts_kwargs and "facts" not in signature.parameters:
            raise ValueError(
                f"{name}: declares requires_facts but {fn.__name__}{signature} has no "
                f"'facts' keyword. Fundamental rules take compute(bars, *, facts=None, ...)."
            )

        key = (name, version)
        if key in _REGISTRY:
            raise ValueError(f"duplicate signal rule registration: {name} v{version}")
        _REGISTRY[key] = SignalRule(
            name=name,
            version=version,
            param_specs=param_specs,
            lookback_days=lookback_days,
            scale_class=scale_class,
            direction_semantics=direction_semantics,
            compute=fn,
            category=category,
            summary=summary or (fn.__doc__ or "").strip().split("\n")[0],
            roles=tuple(roles),
            requires_facts=tuple(requires_facts),
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


def tradeable_rules() -> list[SignalRule]:
    """Rules that emit events, excluding the pure filters.

    A filter describes a *state*, so it emits on every single bar. That is
    correct for gating a strategy and wrong for anything that materialises
    signals into a table: twelve instruments over three years of a filter is
    tens of thousands of "the gate is shut" rows, which would bury the actual
    signals in the viewer and inflate every count on the page.
    """
    return [rule for rule in list_rules() if set(rule.roles) & {"entry", "exit"}]
