"""The plugin system -- registration, override, discovery, isolation."""
from __future__ import annotations

import textwrap

import pandas as pd
import pytest

import quantlab as ql
from quantlab.registry import (
    DERIVED,
    INDICATORS,
    DuplicatePlugin,
    PluginNotFound,
    Registry,
    load_plugin_file,
)


def test_decorator_registers_and_is_usable(bars):
    @ql.indicator("t_double_close", inputs=("close",), tags=("test",))
    def double_close(df, factor: float = 2.0):
        """Toy indicator."""
        return df["close"] * factor

    try:
        assert "t_double_close" in INDICATORS
        plug = INDICATORS.get("t_double_close")
        assert plug.spec.description.startswith("Toy")
        pd.testing.assert_series_equal(
            plug.fn(bars, factor=3.0), bars["close"] * 3.0, check_names=False
        )
    finally:
        INDICATORS.unregister("t_double_close")


def test_duplicate_registration_is_rejected():
    reg = Registry[int]("thing")
    reg.register("a", 1, origin="first")
    with pytest.raises(DuplicatePlugin, match="already registered by first"):
        reg.register("a", 2)
    reg.register("a", 2, override=True)
    assert reg.get("a") == 2


def test_unknown_plugin_lists_alternatives():
    with pytest.raises(PluginNotFound) as exc:
        ql.lookup_feature("definitely_not_a_feature")
    assert "rsi" in str(exc.value)


def test_override_a_builtin(bars):
    """A third party must be able to replace a builtin deliberately."""
    original = INDICATORS.get("rsi")
    original_origin = INDICATORS.origin("rsi")
    try:
        @ql.indicator("rsi", inputs=("close",), override=True)
        def my_rsi(df, period: int = 14):
            return pd.Series(42.0, index=df.index)

        assert INDICATORS.get("rsi").fn(bars).iloc[0] == 42.0
    finally:
        INDICATORS.unregister("rsi")
        INDICATORS.register("rsi", original, origin=original_origin)
        assert INDICATORS.get("rsi").fn(bars, 14).dropna().between(0, 100).all()


def test_plugin_file_is_loaded_from_disk(tmp_path, bars):
    """A .py file in a plugin directory needs no packaging at all."""
    plugin = tmp_path / "my_plugin.py"
    plugin.write_text(
        textwrap.dedent(
            '''
            from quantlab.registry import indicator, derived

            @indicator("file_range_pct", inputs=("high", "low", "close"), tags=("test",))
            def range_pct(df, period: int = 5):
                """High-low range as a fraction of close."""
                return (df["high"] - df["low"]) / df["close"]

            @derived("file_cs_mean", cross_sectional=True, params={"column": "close"})
            def cs_mean(panel, ctx, column="close"):
                m = panel[column].groupby(level="date").transform("mean")
                return m.to_frame("file_cs_mean")
            '''
        )
    )
    load_plugin_file(plugin)
    try:
        assert "file_range_pct" in INDICATORS
        assert "file_cs_mean" in DERIVED
        out = INDICATORS.get("file_range_pct").fn(bars)
        assert (out > 0).all()
    finally:
        INDICATORS.unregister("file_range_pct")
        DERIVED.unregister("file_cs_mean")


def test_plugin_from_directory_env(tmp_path, monkeypatch, bars):
    d = tmp_path / "plugins"
    d.mkdir()
    (d / "auto.py").write_text(
        'from quantlab.registry import indicator\n'
        '@indicator("auto_loaded", inputs=("close",))\n'
        'def f(df):\n'
        '    return df["close"] * 0 + 1\n'
    )
    monkeypatch.setenv("QUANTLAB_PLUGIN_PATH", str(d))
    ql.load_plugins(force=True)
    try:
        assert "auto_loaded" in INDICATORS
    finally:
        INDICATORS.unregister("auto_loaded")


def test_describe_reports_origins():
    inv = ql.describe()
    assert inv["indicators"]["rsi"].endswith("momentum")
    assert inv["providers"]["stooq"].endswith("stooq")
    assert set(inv) == {"providers", "universes", "indicators", "derived"}


def test_registry_is_case_insensitive_and_trims():
    assert ql.lookup_feature("  RSI ").name == "rsi"


def test_entry_point_groups_are_declared():
    """The pyproject entry points must match what the loader looks for."""
    from quantlab.registry import ENTRY_POINT_GROUPS

    assert set(ENTRY_POINT_GROUPS.values()) == {
        "quantlab.providers", "quantlab.universes",
        "quantlab.indicators", "quantlab.derived",
    }
