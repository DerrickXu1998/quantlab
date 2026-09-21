"""Configurable signal rules from fixed templates (feature 008, M2).

Templates, not expressions: a custom rule is a template id plus a config whose
every field comes from a fixed enum or a bounded numeric range. Nothing here
parses user-supplied code.

Every template is causal in exactly the sense the builtin rules are: the event
emitted at day T depends only on bars with ``date <= T``, which the truncation
sweep (tests/lookahead/test_truncation_sweep.py) enforces over a config matrix
the same way it sweeps the builtins.

``lookback_days`` is derived from the config, not declared: the first possible
event is one bar after the last operand's first defined value (a cross needs
the previous bar's pair), so lookback = max first-defined index + 2. That
matches the builtins' conventions exactly -- sma(50) -> 51, rsi(14) -> 16.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from quantlab import fundamentals as fundamentals_lib
from quantlab.indicators.builtins import ema as ema_indicator
from quantlab.indicators.builtins import rolling_max as rolling_max_indicator
from quantlab.indicators.builtins import rolling_min as rolling_min_indicator
from quantlab.indicators.builtins import rolling_std as rolling_std_indicator
from quantlab.indicators.builtins import rsi as rsi_indicator
from quantlab.indicators.builtins import sma as sma_indicator
from quantlab.signals.registry import SignalEvent, SignalRule

# --- Config vocabularies ------------------------------------------------------

INPUT_SOURCES: tuple[str, ...] = ("close", "indicator")
INDICATORS: tuple[str, ...] = ("sma", "ema", "rsi", "rolling_std", "rolling_max", "rolling_min")
TRANSFORMS: tuple[str, ...] = ("raw", "pct_change")
COMPARATORS: tuple[str, ...] = ("crosses_above", "crosses_below", "enters_zone", "exits_zone")
BULLISH_ON: tuple[str, ...] = ("above", "below")
OPERAND_KINDS: tuple[str, ...] = (
    "close",
    "sma",
    "ema",
    "rsi",
    "macd_line",
    "bollinger_upper",
    "bollinger_lower",
    "rolling_max",
    "rolling_min",
)

#: Per-kind parameter bounds: name -> (default, min, max). Validation rejects
#: anything else, so a config can never reach compute with a surprise key.
_PARAM_SPECS: dict[str, dict[str, tuple[Any, float, float]]] = {
    "sma": {"window": (20, 2, 400)},
    "ema": {"window": (20, 2, 400)},
    "rsi": {"period": (14, 2, 100)},
    "rolling_std": {"window": (20, 2, 400)},
    "rolling_max": {"window": (20, 2, 400)},
    "rolling_min": {"window": (20, 2, 400)},
    "macd_line": {"fast": (12, 2, 200), "slow": (26, 3, 400)},
    "bollinger_upper": {"window": (20, 2, 250), "num_std": (2.0, 0.5, 5.0)},
    "bollinger_lower": {"window": (20, 2, 250), "num_std": (2.0, 0.5, 5.0)},
}

#: Operands whose output is unit-invariant. Everything else is in price units
#: (macd_line is a difference of price EMAs; the bands are price levels).
_SCALE_FREE_KINDS: frozenset[str] = frozenset({"rsi"})


def _validate_params(kind: str, params: dict[str, Any]) -> None:
    specs = _PARAM_SPECS.get(kind, {})
    for key, value in (params or {}).items():
        spec = specs.get(key)
        if spec is None:
            raise ValueError(f"{kind}: unknown parameter {key!r}")
        default, minimum, maximum = spec
        if isinstance(default, int) and not isinstance(value, int):
            raise ValueError(f"{kind}.{key}: expected an int, got {type(value).__name__}")
        if isinstance(default, float) and not isinstance(value, (int, float)):
            raise ValueError(f"{kind}.{key}: expected a number, got {type(value).__name__}")
        if isinstance(value, bool) or not minimum <= value <= maximum:
            raise ValueError(f"{kind}.{key}: must be in [{minimum}, {maximum}], got {value!r}")


def _param(kind: str, params: dict[str, Any], name: str) -> Any:
    return (params or {}).get(name, _PARAM_SPECS[kind][name][0])


# --- Series evaluation ----------------------------------------------------------


def _eval_operand(closes: np.ndarray, spec: dict) -> tuple[np.ndarray, int]:
    """(series, index of its first defined value) for one operand."""
    kind = spec["kind"]
    params = spec.get("params") or {}
    if kind == "close":
        return closes, 0
    if kind == "sma":
        window = _param(kind, params, "window")
        return sma_indicator(closes, window=window), window - 1
    if kind == "ema":
        window = _param(kind, params, "window")
        return ema_indicator(closes, window=window), window - 1
    if kind == "rsi":
        period = _param(kind, params, "period")
        return rsi_indicator(closes, period=period), period
    if kind == "rolling_max":
        window = _param(kind, params, "window")
        return rolling_max_indicator(closes, window=window), window - 1
    if kind == "rolling_min":
        window = _param(kind, params, "window")
        return rolling_min_indicator(closes, window=window), window - 1
    if kind == "rolling_std":
        window = _param(kind, params, "window")
        return rolling_std_indicator(closes, window=window), window - 1
    if kind == "macd_line":
        fast = _param(kind, params, "fast")
        slow = _param(kind, params, "slow")
        return ema_indicator(closes, window=fast) - ema_indicator(closes, window=slow), slow - 1
    if kind in ("bollinger_upper", "bollinger_lower"):
        window = _param(kind, params, "window")
        num_std = _param(kind, params, "num_std")
        mid = sma_indicator(closes, window=window)
        spread = num_std * rolling_std_indicator(closes, window=window)
        return (mid + spread if kind == "bollinger_upper" else mid - spread), window - 1
    raise ValueError(f"unknown operand kind {kind!r}; expected one of {OPERAND_KINDS}")


def _eval_input(closes: np.ndarray, config: dict) -> tuple[np.ndarray, int]:
    """The threshold template's compared series: input, then transform."""
    source = config["input"]
    if source["source"] == "close":
        operand = {"kind": "close"}
    else:
        operand = {"kind": source["indicator"], "params": source.get("params") or {}}
    series, first_defined = _eval_operand(closes, operand)
    if config.get("transform", "raw") == "pct_change":
        window = int(config.get("transform_window", 1))
        changed = np.full(series.shape, np.nan)
        changed[window:] = series[window:] / series[:-window] - 1.0
        return changed, first_defined + window
    return series, first_defined


# --- indicator-threshold ----------------------------------------------------------
#
# Zone membership is strict (x > threshold for the "above" zone, x < threshold
# for "below"), matching the builtins' boundary conventions: crosses_above is
# sma-crossover's (prev <= t, curr > t); exits_zone is rsi-threshold's
# (prev in zone, curr out, inclusive on the way out).

def _threshold_direction(
    comparator: str, bullish_on: str, crossed_up: bool
) -> str | None:
    """Direction emitted for one cross, or None when the comparator filters it
    out. ``crossed_up`` is (prev <= t, curr > t)."""
    if comparator == "crosses_above":
        if not crossed_up:
            return None
        return "bullish" if bullish_on == "above" else "bearish"
    if comparator == "crosses_below":
        if crossed_up:
            return None
        return "bullish" if bullish_on == "below" else "bearish"
    if comparator == "enters_zone":
        # Entering the bullish_on side; the zone's side decides which cross qualifies.
        if (bullish_on == "above") != crossed_up:
            return None
        return "bullish"
    # exits_zone: leaving the bullish_on side. Leaving the high zone is bearish;
    # leaving the low zone (recovering from oversold) is bullish.
    if (bullish_on == "above") == crossed_up:
        return None
    return "bearish" if bullish_on == "above" else "bullish"


def _compute_threshold(bars, config: dict, facts: list[dict] | None = None) -> list[SignalEvent]:
    closes = np.array([bar.close for bar in bars], dtype=float)
    dates = [bar.date for bar in bars]
    series, _ = _eval_input(closes, config)
    threshold = float(config["threshold"])
    comparator = config["comparator"]
    bullish_on = config["bullish_on"]
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        prev, curr = float(series[i - 1]), float(series[i])
        if np.isnan(prev) or np.isnan(curr):
            continue
        in_zone_prev = prev > threshold if bullish_on == "above" else prev < threshold
        in_zone_curr = curr > threshold if bullish_on == "above" else curr < threshold
        if comparator in ("enters_zone", "exits_zone"):
            entered = not in_zone_prev and in_zone_curr
            exited = in_zone_prev and not in_zone_curr
            crossed_up = entered and bullish_on == "above" or exited and bullish_on == "below"
            if comparator == "enters_zone" and not entered:
                continue
            if comparator == "exits_zone" and not exited:
                continue
            direction = _threshold_direction(comparator, bullish_on, crossed_up)
        else:
            crossed_up = prev <= threshold < curr
            crossed_down = prev >= threshold > curr
            if not (crossed_up or crossed_down):
                continue
            direction = _threshold_direction(comparator, bullish_on, crossed_up)
        if direction is None:
            continue
        events.append(
            SignalEvent(
                date=dates[i],
                direction=direction,
                trigger_values={"value": curr, "threshold": threshold},
                data_window_end=dates[i],
            )
        )
    return events


def _validate_threshold(config: dict) -> None:
    source = config.get("input") or {}
    if source.get("source") not in INPUT_SOURCES:
        raise ValueError(f"input.source must be one of {INPUT_SOURCES}")
    if source["source"] == "indicator":
        if source.get("indicator") not in INDICATORS:
            raise ValueError(f"input.indicator must be one of {INDICATORS}")
        _validate_params(source["indicator"], source.get("params") or {})
    transform = config.get("transform", "raw")
    if transform not in TRANSFORMS:
        raise ValueError(f"transform must be one of {TRANSFORMS}")
    if transform == "pct_change":
        window = config.get("transform_window", 1)
        if isinstance(window, bool) or not isinstance(window, int) or not 1 <= window <= 63:
            raise ValueError("transform_window must be an int in [1, 63]")
    if config.get("comparator") not in COMPARATORS:
        raise ValueError(f"comparator must be one of {COMPARATORS}")
    threshold = config.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("threshold must be a number")
    if config.get("bullish_on") not in BULLISH_ON:
        raise ValueError(f"bullish_on must be one of {BULLISH_ON}")


def _first_defined_threshold(config: dict) -> int:
    source = config["input"]
    if source["source"] == "close":
        base = 0
    else:
        indicator = source["indicator"]
        params = source.get("params") or {}
        if indicator == "rsi":
            base = _param("rsi", params, "period")
        else:
            base = _param(indicator, params, "window") - 1
    if config.get("transform", "raw") == "pct_change":
        base += int(config.get("transform_window", 1))
    return base


def _scale_class_threshold(config: dict) -> str:
    if config.get("transform", "raw") == "pct_change":
        return "scale_free"
    source = config["input"]
    if source["source"] == "indicator" and source["indicator"] in _SCALE_FREE_KINDS:
        return "scale_free"
    return "price_scaled"


# --- indicator-crossover ----------------------------------------------------------


def _compute_crossover(bars, config: dict, facts: list[dict] | None = None) -> list[SignalEvent]:
    closes = np.array([bar.close for bar in bars], dtype=float)
    dates = [bar.date for bar in bars]
    a, _ = _eval_operand(closes, config["a"])
    b, _ = _eval_operand(closes, config["b"])
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        window = (a[i - 1], b[i - 1], a[i], b[i])
        if np.isnan(window).any():
            continue
        prev_diff = a[i - 1] - b[i - 1]
        diff = a[i] - b[i]
        if prev_diff <= 0 < diff:
            direction = "bullish"
        elif prev_diff >= 0 > diff:
            direction = "bearish"
        else:
            continue
        events.append(
            SignalEvent(
                date=dates[i],
                direction=direction,
                trigger_values={"a": float(a[i]), "b": float(b[i])},
                data_window_end=dates[i],
            )
        )
    return events


def _validate_operand(name: str, spec: Any) -> None:
    if not isinstance(spec, dict) or spec.get("kind") not in OPERAND_KINDS:
        raise ValueError(f"{name}.kind must be one of {OPERAND_KINDS}")
    _validate_params(spec["kind"], spec.get("params") or {})


def _validate_crossover(config: dict) -> None:
    _validate_operand("a", config.get("a"))
    _validate_operand("b", config.get("b"))


def _first_defined_operand(spec: dict) -> int:
    kind = spec["kind"]
    params = spec.get("params") or {}
    if kind == "close":
        return 0
    if kind == "rsi":
        return _param("rsi", params, "period")
    if kind == "macd_line":
        return _param("macd_line", params, "slow") - 1
    return _param(kind, params, "window") - 1


def _scale_class_crossover(config: dict) -> str:
    kinds = (config["a"]["kind"], config["b"]["kind"])
    return "scale_free" if all(k in _SCALE_FREE_KINDS for k in kinds) else "price_scaled"


# --- fundamental-condition (M3) ---------------------------------------------------
#
# Bars carry nothing about when a filing arrived, so this template's compared
# series is the point-in-time fundamentals series itself: as-of by filed_at
# (latest filing wins, per-holder filings summed), optionally YoY. Crossings
# are detected between consecutive filing dates -- signals characteristically
# fire ON filing dates, which is the point. data_window_end is the filing
# date, so the experiment_signals CHECK (data_window_end <= date) holds by
# construction.

FUNDAMENTAL_TRANSFORMS: tuple[str, ...] = ("level", "yoy_growth")
FUNDAMENTAL_COMPARATORS: tuple[str, ...] = ("crosses_above", "crosses_below")


def _compute_fundamental_condition(
    bars, config: dict, facts: list[dict] | None
) -> list[SignalEvent]:
    if facts is None:
        raise ValueError(
            "fundamental-condition needs PIT facts; the engine supplies them "
            "to rules whose inputs are bars+fundamentals"
        )
    points = fundamentals_lib.as_of_series(facts)
    if config.get("transform", "level") == "yoy_growth":
        points = fundamentals_lib.yoy_growth(points)
    threshold = float(config["threshold"])
    comparator = config["comparator"]
    bullish_on = config["bullish_on"]
    events: list[SignalEvent] = []
    for i in range(1, len(points)):
        prev, curr = points[i - 1]["value"], points[i]["value"]
        day = points[i]["date"]
        if prev <= threshold < curr:
            if comparator != "crosses_above":
                continue
            direction = "bullish" if bullish_on == "above" else "bearish"
        elif prev >= threshold > curr:
            if comparator != "crosses_below":
                continue
            direction = "bullish" if bullish_on == "below" else "bearish"
        else:
            continue
        events.append(
            SignalEvent(
                date=day,
                direction=direction,
                trigger_values={
                    "concept": config["concept"],
                    "value": curr,
                    "threshold": threshold,
                },
                # The filing date IS the visibility boundary: nothing later
                # than the filing that moved the series was consulted.
                data_window_end=day,
            )
        )
    return events


def _validate_fundamental_condition(config: dict) -> None:
    concept = config.get("concept")
    if not isinstance(concept, str) or not concept:
        raise ValueError("concept must be a non-empty string")
    if config.get("transform", "level") not in FUNDAMENTAL_TRANSFORMS:
        raise ValueError(f"transform must be one of {FUNDAMENTAL_TRANSFORMS}")
    if config.get("comparator") not in FUNDAMENTAL_COMPARATORS:
        raise ValueError(f"comparator must be one of {FUNDAMENTAL_COMPARATORS}")
    threshold = config.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("threshold must be a number")
    if config.get("bullish_on") not in BULLISH_ON:
        raise ValueError(f"bullish_on must be one of {BULLISH_ON}")


# --- The template registry --------------------------------------------------------


@dataclass(frozen=True)
class SignalTemplate:
    """A fixed rule shape a custom rule instantiates with a config."""

    id: str
    version: str
    description: str
    #: What the template reads: "bars" today; "bars+fundamentals" arrives with M3.
    inputs: str
    direction_semantics: str
    #: Enums and bounds, so a caller can build a form without knowing the template.
    config_fields: dict[str, Any]
    compute: Any  # (bars, config) -> list[SignalEvent]
    validate: Any  # (config) -> None, raising ValueError
    first_defined: Any  # (config) -> int, first index the compared series is defined

    def lookback_days(self, config: dict) -> int:
        """Bars of history a run needs before this config can emit.

        Derived, not declared: the first possible event is one bar after the
        compared series' first defined value (a cross needs the previous bar),
        and the engine guard needs one more. sma(50) -> 51 and rsi(14) -> 16,
        the builtins' own conventions.
        """
        return self.first_defined(config) + 2

    def scale_class(self, config: dict) -> str:
        return _scale_class_for(self.id, config)


_TEMPLATES: dict[str, SignalTemplate] = {}


def _register(template: SignalTemplate) -> None:
    if template.id in _TEMPLATES:
        raise ValueError(f"duplicate signal template: {template.id}")
    _TEMPLATES[template.id] = template


def get_template(template_id: str) -> SignalTemplate:
    try:
        return _TEMPLATES[template_id]
    except KeyError:
        raise KeyError(f"unknown signal template: {template_id!r}") from None


def list_templates() -> list[SignalTemplate]:
    return [_TEMPLATES[key] for key in sorted(_TEMPLATES)]


def _scale_class_for(template_id: str, config: dict) -> str:
    if template_id == "indicator-threshold":
        return _scale_class_threshold(config)
    if template_id == "fundamental-condition":
        # A YoY growth rate is unit-invariant; a raw level is in the filing's
        # currency units.
        return "scale_free" if config.get("transform", "level") == "yoy_growth" else "price_scaled"
    return _scale_class_crossover(config)


def rule_from_definition(
    template_id: str, config: dict, *, name: str, version: str = "1.0.0"
) -> SignalRule:
    """Instantiate a template as a registry-shaped rule for the engine.

    The config is validated and frozen into a closure: the resulting rule takes
    no parameters, which is why a custom run's effective parameters are empty
    and its provenance lives in the run's custom_rule snapshot instead. Rules
    whose template inputs are "bars+fundamentals" also take the symbol's
    point-in-time facts, supplied by the engine.
    """
    template = get_template(template_id)
    template.validate(config)
    config = dict(config)

    def compute(bars, facts: list[dict] | None = None) -> list[SignalEvent]:
        return template.compute(bars, config, facts)

    return SignalRule(
        name=name,
        version=version,
        param_specs={},
        lookback_days=template.lookback_days(config),
        scale_class=template.scale_class(config),
        direction_semantics=template.direction_semantics,
        compute=compute,
        inputs=template.inputs,
    )


_register(
    SignalTemplate(
        id="indicator-threshold",
        version="1.0.0",
        description=(
            "Fire when a series (close, or an indicator with parameters, optionally "
            "transformed to pct_change over a window) crosses a fixed threshold. "
            "enters_zone fires bullish on entering the bullish_on side; exits_zone "
            "fires on leaving it (bearish leaving the high zone, bullish recovering "
            "out of the low zone -- the rsi-threshold convention)."
        ),
        inputs="bars",
        direction_semantics=(
            "config-defined: comparator plus bullish_on fix the direction; zone "
            "boundaries are strict (above = value > threshold)"
        ),
        config_fields={
            "input": {"sources": list(INPUT_SOURCES), "indicators": list(INDICATORS)},
            "transform": {"choices": list(TRANSFORMS), "default": "raw"},
            "transform_window": {"type": "int", "default": 1, "minimum": 1, "maximum": 63},
            "comparator": {"choices": list(COMPARATORS)},
            "threshold": {"type": "float"},
            "bullish_on": {"choices": list(BULLISH_ON), "default": "above"},
        },
        compute=_compute_threshold,
        validate=_validate_threshold,
        first_defined=_first_defined_threshold,
    )
)

_register(
    SignalTemplate(
        id="indicator-crossover",
        version="1.0.0",
        description=(
            "Fire when operand A crosses operand B: bullish when A crosses above B, "
            "bearish when below. Operands come from a fixed catalog (close, sma, ema, "
            "rsi, macd_line, bollinger_upper/lower, rolling_max/min) with bounded params."
        ),
        inputs="bars",
        direction_semantics=(
            "bullish: A crossed above B on the signal date (prev diff <= 0 < diff); "
            "bearish: A crossed below B"
        ),
        config_fields={
            "a": {"operands": list(OPERAND_KINDS)},
            "b": {"operands": list(OPERAND_KINDS)},
        },
        compute=_compute_crossover,
        validate=_validate_crossover,
        first_defined=lambda config: max(
            _first_defined_operand(config["a"]), _first_defined_operand(config["b"])
        ),
    )
)

_register(
    SignalTemplate(
        id="fundamental-condition",
        version="1.0.0",
        description=(
            "Fire when a fundamental concept's point-in-time series (as-of by "
            "filed_at: latest filing wins, per-holder filings summed) crosses a fixed "
            "threshold -- level or year-over-year growth. Signals characteristically "
            "fire ON filing dates; that is the point. Requires the warehouse dataset "
            "(the synthetic demo has no fundamentals)."
        ),
        inputs="bars+fundamentals",
        direction_semantics=(
            "config-defined: crosses_above/crosses_below plus bullish_on fix the "
            "direction; the crossed series is the PIT as-of value, so the signal "
            "date is the filing date that moved it"
        ),
        config_fields={
            "concept": {
                "type": "string",
                "source": "GET /instruments/{symbol}/fundamentals/concepts",
            },
            "transform": {"choices": list(FUNDAMENTAL_TRANSFORMS), "default": "level"},
            "comparator": {"choices": list(FUNDAMENTAL_COMPARATORS)},
            "threshold": {"type": "float"},
            "bullish_on": {"choices": list(BULLISH_ON), "default": "above"},
        },
        compute=_compute_fundamental_condition,
        validate=_validate_fundamental_condition,
        # Bars say nothing about when filings arrive: there is no bar warm-up
        # to derive, and the runner loads facts from start - 3 years instead
        # (a YoY base needs prior-year filings). lookback_days is therefore
        # the minimum the engine guard accepts.
        first_defined=lambda config: -1,
    )
)
