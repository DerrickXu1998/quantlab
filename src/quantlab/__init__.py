"""quantlab -- pluggable quantitative equity analytics for NYSE + LSE.

Quick start::

    import quantlab as ql

    panel  = ql.load(["AAPL.US", "HSBA.LON"], start="2020-01-01")
    result = ql.compute(panel, ["rsi", "atr", "yang_zhang_vol", "momentum_12_1"])
"""
from __future__ import annotations

__version__ = "0.1.0"

from .config import PipelineConfig, Settings, configure, settings
from .registry import (
    DERIVED,
    INDICATORS,
    PROVIDERS,
    UNIVERSES,
    all_features,
    derived as derived_feature,
    describe,
    indicator,
    load_plugins,
    lookup_feature,
    provider,
    universe,
)
from .schema import (
    BAR_COLUMNS,
    OHLCV_COLUMNS,
    Currency,
    FeatureSpec,
    Frequency,
    Security,
    concat_panel,
    validate_bars,
    wide,
)

__all__ = [
    "__version__",
    "BAR_COLUMNS",
    "Currency",
    "DERIVED",
    "FeatureSpec",
    "Frequency",
    "INDICATORS",
    "OHLCV_COLUMNS",
    "PROVIDERS",
    "PipelineConfig",
    "Security",
    "Settings",
    "UNIVERSES",
    "all_features",
    "compute",
    "concat_panel",
    "configure",
    "derived_feature",
    "describe",
    "get_provider",
    "get_universe",
    "indicator",
    "load",
    "load_plugins",
    "lookup_feature",
    "provider",
    "settings",
    "universe",
    "validate_bars",
    "wide",
]


# NOTE: `quantlab.derived` is the builtin-feature *package*, so the registry's
# `derived` decorator is exported here under the unambiguous name
# `derived_feature`. Inside the package itself, `from ..registry import derived`
# still works as normal.


def __getattr__(name: str):
    # Lazy re-exports so `import quantlab` stays cheap.
    if name in {"compute", "FeatureEngine", "Context"}:
        from . import engine

        return getattr(engine, name)
    if name in {"load", "get_provider", "get_universe", "load_universe"}:
        from . import data

        return getattr(data, name)
    raise AttributeError(name)
