"""Backward compatibility of the registration shorthand (feature 005).

Constitution II says adding or upgrading a plugin must not require changes to
unrelated code. Enriching the registry therefore must not break the existing
``params={"fast": 20}`` form, or every rule would have to be rewritten at once.
"""

from __future__ import annotations

from quantlab.signals.registry import get_rule, register_signal_rule


def test_bare_value_shorthand_still_registers():
    def compute(bars, fast: int = 20):
        return []

    register_signal_rule(
        name="test-compat-bare",
        version="1.0.0",
        params={"fast": 20},
        lookback_days=2,
        scale_class="scale_free",
        direction_semantics="test",
    )(compute)

    rule = get_rule("test-compat-bare")
    spec = rule.param_specs["fast"]
    assert spec.name == "fast"
    assert spec.default == 20
    assert spec.type == "int"  # inferred from the value
    assert spec.minimum is None  # no bounds are invented
    assert spec.maximum is None


def test_shorthand_infers_each_scalar_type():
    def compute(bars, i=1, f=1.5, b=True):
        return []

    register_signal_rule(
        name="test-compat-types",
        version="1.0.0",
        params={"i": 1, "f": 1.5, "b": True},
        lookback_days=2,
        scale_class="scale_free",
        direction_semantics="test",
    )(compute)

    specs = get_rule("test-compat-types").param_specs
    assert specs["i"].type == "int"
    assert specs["f"].type == "float"
    # bool must not be mistaken for int, even though bool subclasses int in Python
    assert specs["b"].type == "bool"


def test_params_property_still_exposes_plain_values():
    """The engine and the seeded `signal_rules` mirror both read plain values;
    that surface must keep working unchanged."""

    def compute(bars, fast: int = 20, slow: int = 50):
        return []

    register_signal_rule(
        name="test-compat-values",
        version="1.0.0",
        params={"fast": 20, "slow": 50},
        lookback_days=2,
        scale_class="scale_free",
        direction_semantics="test",
    )(compute)

    assert get_rule("test-compat-values").params == {"fast": 20, "slow": 50}


def test_existing_builtin_rules_unchanged_in_behaviour():
    from quantlab.signals import builtins  # noqa: F401
    from quantlab.signals.registry import list_rules

    names = {rule.name for rule in list_rules()}
    assert {"sma-crossover", "rsi-threshold", "breakout-20d"} <= names

    sma = get_rule("sma-crossover")
    assert sma.params == {"fast": 20, "slow": 50}
    assert sma.lookback_days == 51
