"""What a strategy *is*: several signals, a way of combining them, and the
execution criteria that turn the combination into trades.

Before this, a "strategy" was one rule. You could run RSI, or you could run
MACD, but you could not run "RSI oversold, but only while ADX says there is a
trend" -- which is the first thing anyone actually wants. The unit of
configuration was the rule, so composition had nowhere to live.

A spec is data, not code: it round-trips through JSON, is stored on the run that
executed it, and is revalidated on the way back in. That is what makes a saved
strategy re-runnable rather than merely re-readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quantlab.execution.config import DEFAULT_EXECUTION, ExecutionConfig
from quantlab.signals.registry import ROLES, SignalRule, get_rule

#: How the active components on a date are reduced to one decision.
COMBINE_LOGIC: tuple[str, ...] = ("all", "any", "majority", "weighted")


class StrategyValidationError(ValueError):
    """A spec that cannot be executed, with the offending part named.

    Always names the component index and the field. "invalid strategy" sends a
    user back to a form of twenty inputs with no idea which one is wrong.
    """


@dataclass(frozen=True)
class StrategyComponent:
    """One signal rule doing one job inside a strategy."""

    rule_name: str
    rule_version: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    role: str = "entry"
    #: Read only by ``weighted`` logic.
    weight: float = 1.0
    #: Swap this component's two directions. How a long-biased filter becomes
    #: a short-biased one without needing a second rule.
    invert: bool = False

    def resolve(self, index: int) -> SignalRule:
        try:
            rule = get_rule(self.rule_name, self.rule_version)
        except KeyError as exc:
            version = f" v{self.rule_version}" if self.rule_version else ""
            raise StrategyValidationError(
                f"components[{index}]: unknown signal rule "
                f"{self.rule_name!r}{version}"
            ) from exc
        return rule

    def validate(self, index: int) -> SignalRule:
        if self.role not in ROLES:
            raise StrategyValidationError(
                f"components[{index}].role: {self.role!r} is not one of {ROLES}"
            )
        if self.weight <= 0:
            raise StrategyValidationError(
                f"components[{index}].weight: must be > 0, got {self.weight}"
            )
        rule = self.resolve(index)
        if self.role not in rule.roles:
            raise StrategyValidationError(
                f"components[{index}]: {rule.name} cannot be used as an "
                f"{self.role!r} component -- it declares roles {list(rule.roles)}. "
                f"{rule.direction_semantics}"
            )
        for key, value in self.parameters.items():
            spec = rule.param_specs.get(key)
            if spec is None:
                raise StrategyValidationError(
                    f"components[{index}].parameters: {rule.name} has no parameter {key!r}"
                )
            problem = spec.validation_error(value)
            if problem is not None:
                raise StrategyValidationError(
                    f"components[{index}].parameters.{key}: {problem}"
                )
        return rule

    def effective_parameters(self, index: int) -> dict[str, Any]:
        """Declared defaults merged with this component's overrides.

        Recorded on the run, because recording the bare defaults while
        executing overrides would make the record unreproducible
        (Constitution VI).
        """
        return self.resolve(index).effective_params(self.parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "rule_version": self.rule_version,
            "parameters": dict(self.parameters),
            "role": self.role,
            "weight": self.weight,
            "invert": self.invert,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int = 0) -> StrategyComponent:
        if not isinstance(data, dict):
            raise StrategyValidationError(f"components[{index}]: expected an object")
        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - known)
        if unknown:
            raise StrategyValidationError(
                f"components[{index}]: unknown field(s) {', '.join(unknown)}"
            )
        if "rule_name" not in data:
            raise StrategyValidationError(f"components[{index}].rule_name is required")
        return cls(
            rule_name=data["rule_name"],
            rule_version=data.get("rule_version"),
            parameters=dict(data.get("parameters") or {}),
            role=data.get("role", "entry"),
            weight=float(data.get("weight", 1.0)),
            invert=bool(data.get("invert", False)),
        )


@dataclass(frozen=True)
class StrategySpec:
    """A complete, executable strategy."""

    name: str
    components: tuple[StrategyComponent, ...]
    description: str = ""
    entry_logic: str = "all"
    exit_logic: str = "any"
    entry_threshold: float = 1.0
    exit_threshold: float = 1.0
    #: How many sessions components have to agree within. 1 means "the same
    #: bar", which is strict enough that two oscillators rarely coincide; a
    #: window of 3 lets a confirmation arrive a couple of sessions late.
    combine_window_days: int = 1
    execution: ExecutionConfig = DEFAULT_EXECUTION

    def __post_init__(self) -> None:
        self.validate()

    # -- validation --------------------------------------------------------

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise StrategyValidationError("name is required")
        if not self.components:
            raise StrategyValidationError("a strategy needs at least one component")
        for logic_field in ("entry_logic", "exit_logic"):
            value = getattr(self, logic_field)
            if value not in COMBINE_LOGIC:
                raise StrategyValidationError(
                    f"{logic_field}: {value!r} is not one of {COMBINE_LOGIC}"
                )
        if self.combine_window_days < 1:
            raise StrategyValidationError("combine_window_days must be >= 1")
        if self.entry_threshold <= 0 or self.exit_threshold <= 0:
            raise StrategyValidationError("entry_threshold and exit_threshold must be > 0")

        for index, component in enumerate(self.components):
            component.validate(index)

        if not self.by_role("entry"):
            raise StrategyValidationError(
                "a strategy needs at least one entry component -- filters gate "
                "entries but can never open a position on their own"
            )

        # A weighted rule whose threshold no combination of weights can reach
        # is not a strict strategy, it is a strategy that never trades.
        if self.entry_logic == "weighted":
            reachable = sum(c.weight for c in self.by_role("entry"))
            if self.entry_threshold > reachable:
                raise StrategyValidationError(
                    f"entry_threshold {self.entry_threshold} exceeds the total entry weight "
                    f"{reachable}; no combination of components could ever reach it"
                )
        if self.exit_logic == "weighted" and self.by_role("exit"):
            reachable = sum(c.weight for c in self.by_role("exit"))
            if self.exit_threshold > reachable:
                raise StrategyValidationError(
                    f"exit_threshold {self.exit_threshold} exceeds the total exit weight "
                    f"{reachable}; no combination of components could ever reach it"
                )

        self.execution.validate()

    # -- introspection -----------------------------------------------------

    def by_role(self, role: str) -> list[StrategyComponent]:
        return [c for c in self.components if c.role == role]

    @property
    def lookback_days(self) -> int:
        """Warm-up the whole strategy needs.

        The deepest component sets the floor; the agreement window adds to it,
        because a component that fired ``combine_window_days - 1`` sessions ago
        still counts today and so its own warm-up must have completed by then.
        Execution adds its own (an ATR stop needs an ATR).
        """
        deepest = max(
            component.resolve(index).lookback_days
            for index, component in enumerate(self.components)
        )
        return deepest + self.combine_window_days - 1 + self.execution.extra_lookback_days

    @property
    def warnings(self) -> list[str]:
        """Things that are legal but probably not what the user meant.

        Returned rather than raised: refusing these would block real
        strategies, and saying nothing would let a user quietly build a book
        that only ever exits on a stop.
        """
        out: list[str] = []
        if not self.by_role("exit"):
            if self.execution.stop_loss_pct is None and self.execution.max_holding_days is None:
                out.append(
                    "This strategy has no exit component and no stop or holding limit, so a "
                    "position opens and is never closed until the window ends."
                )
            else:
                out.append(
                    "This strategy has no exit component: positions are closed only by the "
                    "execution criteria (a stop, a target or a holding limit)."
                )
        if self.entry_logic == "all" and len(self.by_role("entry")) > 3:
            out.append(
                f"{len(self.by_role('entry'))} entry components must all fire within "
                f"{self.combine_window_days} session(s). That combination may never occur; "
                "consider 'majority' or a wider agreement window."
            )
        if self.execution.allow_shorts and any(
            c.role == "filter" for c in self.components
        ):
            out.append(
                "Filters gate both long and short entries. A filter meant to qualify longs "
                "only will also be gating your shorts."
            )
        return out

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "components": [c.to_dict() for c in self.components],
            "entry_logic": self.entry_logic,
            "exit_logic": self.exit_logic,
            "entry_threshold": self.entry_threshold,
            "exit_threshold": self.exit_threshold,
            "combine_window_days": self.combine_window_days,
            "execution": self.execution.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategySpec:
        if not isinstance(data, dict):
            raise StrategyValidationError("strategy: expected an object")
        # Identity and timestamps belong to the store, not the spec; accept and
        # drop them so a strategy read from the API can be posted straight back.
        ignored = {"id", "owner_id", "created_at", "updated_at"}
        known = set(cls.__dataclass_fields__) | ignored
        unknown = sorted(set(data) - known)
        if unknown:
            raise StrategyValidationError(f"strategy: unknown field(s) {', '.join(unknown)}")

        raw_components = data.get("components")
        if not isinstance(raw_components, list) or not raw_components:
            raise StrategyValidationError("components must be a non-empty list")

        try:
            execution = ExecutionConfig.from_dict(data.get("execution"))
        except ValueError as exc:
            raise StrategyValidationError(f"execution: {exc}") from exc

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            components=tuple(
                StrategyComponent.from_dict(item, index)
                for index, item in enumerate(raw_components)
            ),
            entry_logic=data.get("entry_logic", "all"),
            exit_logic=data.get("exit_logic", "any"),
            entry_threshold=float(data.get("entry_threshold", 1.0)),
            exit_threshold=float(data.get("exit_threshold", 1.0)),
            combine_window_days=int(data.get("combine_window_days", 1)),
            execution=execution,
        )

    def with_execution(self, execution: ExecutionConfig) -> StrategySpec:
        from dataclasses import replace

        return replace(self, execution=execution)


def promote_legacy(
    model_name: str,
    model_version: str | None = None,
    parameters: dict[str, Any] | None = None,
    execution: ExecutionConfig | None = None,
) -> StrategySpec:
    """Turn a pre-strategy single-model request into a one-rule strategy.

    The rule is attached twice, as both the entry and the exit component, which
    is exactly what the old code did implicitly: a bullish event opened and a
    bearish event closed. Doing the promotion here means there is one execution
    path rather than a legacy branch that slowly stops matching the real one.
    """
    parameters = dict(parameters or {})
    shared = {
        "rule_name": model_name,
        "rule_version": model_version,
        "parameters": parameters,
    }
    return StrategySpec(
        name=model_name,
        description=f"Single-model run of {model_name}.",
        components=(
            StrategyComponent(role="entry", **shared),
            StrategyComponent(role="exit", **shared),
        ),
        entry_logic="any",
        exit_logic="any",
        execution=execution or DEFAULT_EXECUTION,
    )
