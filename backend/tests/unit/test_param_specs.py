"""ParamSpec declaration and registration-time validation (feature 005).

Constitution II requires plugins to declare their parameters and the registry to
expose parameter metadata for runtime discovery. These tests pin the declaration
contract: a bad declaration must fail loudly at import time, never silently at
run time.
"""

from __future__ import annotations

import pytest

from quantlab.signals.registry import ParamSpec, SignalEvent, register_signal_rule


def _noop(bars, **kwargs):  # pragma: no cover - never executed
    return []


def test_declares_name_type_and_default():
    spec = ParamSpec(name="fast", type="int", default=20)
    assert (spec.name, spec.type, spec.default) == ("fast", "int", 20)
    assert spec.minimum is None and spec.maximum is None and spec.choices is None


@pytest.mark.parametrize("type_", ["int", "float", "bool", "enum"])
def test_permitted_types(type_):
    default = {"int": 1, "float": 1.0, "bool": True, "enum": "a"}[type_]
    choices = ["a", "b"] if type_ == "enum" else None
    ParamSpec(name="p", type=type_, default=default, choices=choices)


def test_rejects_unknown_type():
    with pytest.raises(ValueError, match="type"):
        ParamSpec(name="p", type="complex", default=1)


def test_bounds_only_on_numeric_types():
    ParamSpec(name="p", type="int", default=5, minimum=1, maximum=10)
    ParamSpec(name="p", type="float", default=0.5, minimum=0.0, maximum=1.0)

    with pytest.raises(ValueError, match="minimum|maximum|numeric"):
        ParamSpec(name="p", type="bool", default=True, minimum=0)
    with pytest.raises(ValueError, match="minimum|maximum|numeric"):
        ParamSpec(name="p", type="enum", default="a", choices=["a"], maximum=3)


def test_choices_only_on_enum_and_must_be_non_empty():
    with pytest.raises(ValueError, match="choices"):
        ParamSpec(name="p", type="int", default=1, choices=[1, 2])
    with pytest.raises(ValueError, match="choices"):
        ParamSpec(name="p", type="enum", default="a", choices=[])
    with pytest.raises(ValueError, match="choices"):
        ParamSpec(name="p", type="enum", default="a")


def test_maximum_must_be_at_least_minimum():
    with pytest.raises(ValueError, match="maximum|minimum"):
        ParamSpec(name="p", type="int", default=5, minimum=10, maximum=1)


def test_default_must_satisfy_its_own_constraints():
    """A default that violates its own bounds is a declaration bug; it must fail
    at registration rather than surfacing as a confusing run-time rejection."""
    with pytest.raises(ValueError, match="default"):
        ParamSpec(name="p", type="int", default=99, minimum=1, maximum=10)
    with pytest.raises(ValueError, match="default"):
        ParamSpec(name="p", type="enum", default="z", choices=["a", "b"])


def test_default_must_match_declared_type():
    with pytest.raises(ValueError, match="default|type"):
        ParamSpec(name="p", type="int", default="not-an-int")


def test_registration_rejects_param_not_accepted_by_compute():
    """Every declared name must be an accepted keyword of the compute function,
    or a run would fail with an opaque TypeError deep in the engine."""

    def compute(bars, fast: int = 20):
        return []

    with pytest.raises(ValueError, match="nonexistent|keyword|signature"):
        register_signal_rule(
            name="test-bad-param",
            version="1.0.0",
            params={"nonexistent": ParamSpec(name="nonexistent", type="int", default=1)},
            lookback_days=2,
            scale_class="scale_free",
            direction_semantics="test",
        )(compute)


def test_registered_rule_exposes_param_specs():
    def compute(bars, window: int = 5):
        return []

    register_signal_rule(
        name="test-exposes-specs",
        version="1.0.0",
        params={"window": ParamSpec(name="window", type="int", default=5, minimum=2, maximum=50)},
        lookback_days=2,
        scale_class="scale_free",
        direction_semantics="test",
    )(compute)

    from quantlab.signals.registry import get_rule

    rule = get_rule("test-exposes-specs")
    spec = rule.param_specs["window"]
    assert (spec.type, spec.default, spec.minimum, spec.maximum) == ("int", 5, 2, 50)


def test_builtin_rules_declare_bounded_specs():
    """The shipped rules must carry real metadata, not just defaults — this is
    what makes the catalog's generated form meaningful."""
    from quantlab.signals import builtins  # noqa: F401  (registers builtins)
    from quantlab.signals.registry import get_rule

    fast = get_rule("sma-crossover").param_specs["fast"]
    assert fast.type == "int"
    assert fast.minimum is not None and fast.maximum is not None

    period = get_rule("rsi-threshold").param_specs["period"]
    assert period.type == "int" and period.minimum is not None


def test_signal_event_shape_unchanged():
    """Guard: this feature must not alter the emitted event contract."""
    event = SignalEvent(
        date="2024-01-02", direction="bullish", trigger_values={}, data_window_end="2024-01-02"
    )
    assert event.data_window_end <= event.date
