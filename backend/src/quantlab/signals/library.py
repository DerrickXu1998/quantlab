"""The out-of-the-box signal rule library.

``builtins`` holds the original three rules the demo shipped with. This module
is everything added so a user can assemble a strategy from stock parts instead
of writing a plugin: eight more tradeable rules and three filters.

Every rule here obeys the same contract as ``builtins`` -- causal, deterministic,
and declaring its parameters as :class:`ParamSpec`s so the frontend can build a
form without knowing anything about the rule (Constitution II). The truncation
sweep in ``tests/lookahead`` runs over these automatically, because it sweeps the
registry rather than a list.

**Filters are different and the difference matters.** An entry or exit rule
emits an event when something *happens*. A filter describes a *state*, so it
emits on every bar: ``bullish`` means "the gate is open on this date",
``bearish`` means "closed". Entries are suppressed unless every filter attached
to the strategy is open, whichever direction the entry is going -- an ADX regime
filter says "there is a trend here", which qualifies a short exactly as much as
a long. A user who wants a directional filter inverts it in the strategy spec.
"""

from __future__ import annotations

import numpy as np

from quantlab.indicators import technical
from quantlab.indicators.builtins import rsi as rsi_indicator
from quantlab.indicators.builtins import sma as sma_indicator
from quantlab.signals.registry import ParamSpec, SignalEvent, register_signal_rule


def _series(bars, attribute: str) -> np.ndarray:
    return np.array([getattr(bar, attribute) for bar in bars], dtype=float)


def _crossover(previous_diff: float, diff: float) -> str | None:
    """Direction of a zero-crossing between two consecutive differences.

    Shared by every "A crossed B" rule so they all treat the touch case the
    same way: a diff of exactly zero yesterday that is positive today is a
    cross up, and is counted once rather than on both bars.
    """
    if previous_diff <= 0 < diff:
        return "bullish"
    if previous_diff >= 0 > diff:
        return "bearish"
    return None


def _gate_events(bars, open_on: np.ndarray) -> list[SignalEvent]:
    """Turn a per-bar boolean gate into filter events.

    ``open_on`` is a boolean array as long as ``bars``, NaN-free, where True
    means the gate is open. Bars before the indicator warms up must be False,
    not True -- an undefined filter that defaults to open would silently let
    every early entry through.
    """
    return [
        SignalEvent(
            date=bar.date,
            direction="bullish" if bool(open_on[i]) else "bearish",
            trigger_values={"gate": bool(open_on[i])},
            data_window_end=bar.date,
        )
        for i, bar in enumerate(bars)
    ]


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


@register_signal_rule(
    name="ema-crossover",
    version="1.0.0",
    category="trend",
    summary="Fast EMA crossing the slow EMA.",
    roles=("entry", "exit"),
    params={
        "fast": ParamSpec(
            name="fast", type="int", default=12, minimum=2, maximum=200,
            description="Fast exponential-moving-average window, in bars.",
        ),
        "slow": ParamSpec(
            name="slow", type="int", default=26, minimum=3, maximum=400,
            description="Slow exponential-moving-average window, in bars.",
        ),
    },
    lookback_days=28,  # EMA(slow) defined at index slow-1; a cross needs T-1 too
    scale_class="scale_free",
    direction_semantics=(
        "bullish: EMA(fast) crossed above EMA(slow) on the signal date; "
        "bearish: EMA(fast) crossed below EMA(slow). Reacts sooner than the SMA "
        "version and whipsaws more in a range."
    ),
)
def ema_crossover(bars, fast: int = 12, slow: int = 26) -> list[SignalEvent]:
    closes = _series(bars, "close")
    fast_ema = technical.ema(closes, window=fast)
    slow_ema = technical.ema(closes, window=slow)
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        window = (fast_ema[i - 1], slow_ema[i - 1], fast_ema[i], slow_ema[i])
        if np.isnan(window).any():
            continue
        direction = _crossover(fast_ema[i - 1] - slow_ema[i - 1], fast_ema[i] - slow_ema[i])
        if direction is None:
            continue
        events.append(
            SignalEvent(
                date=bars[i].date,
                direction=direction,
                trigger_values={"ema_fast": float(fast_ema[i]), "ema_slow": float(slow_ema[i])},
                data_window_end=bars[i].date,
            )
        )
    return events


@register_signal_rule(
    name="adx-trend-filter",
    version="1.0.0",
    category="trend",
    summary="Gate that opens only when ADX says a trend is actually present.",
    roles=("filter",),
    params={
        "period": ParamSpec(
            name="period", type="int", default=14, minimum=2, maximum=100,
            description="ADX lookback period, in bars.",
        ),
        "threshold": ParamSpec(
            name="threshold", type="float", default=25.0, minimum=0.0, maximum=100.0,
            description="ADX level above which the market counts as trending.",
        ),
    },
    lookback_days=30,  # ADX is defined from 2 * period
    scale_class="scale_free",
    direction_semantics=(
        "A filter, so it emits on every bar: bullish means ADX > threshold and the "
        "gate is open, bearish means it is shut. Direction-agnostic -- it asserts "
        "that a trend exists, not which way it points, so it qualifies shorts as "
        "readily as longs. Pair it with a breakout or crossover entry to drop the "
        "signals that fire in a range."
    ),
)
def adx_trend_filter(bars, period: int = 14, threshold: float = 25.0) -> list[SignalEvent]:
    adx_values, _, _ = technical.adx(
        _series(bars, "high"), _series(bars, "low"), _series(bars, "close"), period=period
    )
    # NaN (not yet warmed up) is a shut gate, never an open one.
    open_on = ~np.isnan(adx_values) & (adx_values > threshold)
    events = _gate_events(bars, open_on)
    for i, event in enumerate(events):
        if not np.isnan(adx_values[i]):
            event.trigger_values["adx"] = float(adx_values[i])
    return events


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------


@register_signal_rule(
    name="macd-crossover",
    version="1.0.0",
    category="momentum",
    summary="MACD line crossing its signal line.",
    roles=("entry", "exit"),
    params={
        "fast": ParamSpec(
            name="fast", type="int", default=12, minimum=2, maximum=100,
            description="Fast EMA window of the MACD line, in bars.",
        ),
        "slow": ParamSpec(
            name="slow", type="int", default=26, minimum=3, maximum=200,
            description="Slow EMA window of the MACD line, in bars.",
        ),
        "signal": ParamSpec(
            name="signal", type="int", default=9, minimum=2, maximum=100,
            description="EMA window of the signal line, in bars.",
        ),
    },
    lookback_days=36,  # signal line defined at slow + signal - 2; a cross needs T-1
    scale_class="scale_free",
    direction_semantics=(
        "bullish: the MACD line crossed above its signal line on the signal date; "
        "bearish: it crossed below. The histogram changing sign is the same event."
    ),
)
def macd_crossover(
    bars, fast: int = 12, slow: int = 26, signal: int = 9
) -> list[SignalEvent]:
    macd_line, signal_line, histogram = technical.macd(
        _series(bars, "close"), fast=fast, slow=slow, signal=signal
    )
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        if np.isnan(histogram[i - 1]) or np.isnan(histogram[i]):
            continue
        direction = _crossover(histogram[i - 1], histogram[i])
        if direction is None:
            continue
        events.append(
            SignalEvent(
                date=bars[i].date,
                direction=direction,
                trigger_values={
                    "macd": float(macd_line[i]),
                    "signal": float(signal_line[i]),
                    "histogram": float(histogram[i]),
                },
                data_window_end=bars[i].date,
            )
        )
    return events


@register_signal_rule(
    name="roc-momentum",
    version="1.0.0",
    category="momentum",
    summary="Rate of change crossing a positive or negative threshold.",
    roles=("entry", "exit"),
    params={
        "period": ParamSpec(
            name="period", type="int", default=12, minimum=1, maximum=250,
            description="Lookback over which the rate of change is measured, in bars.",
        ),
        "upper": ParamSpec(
            name="upper", type="float", default=5.0, minimum=0.0, maximum=1000.0,
            description="Percent gain over the period that counts as momentum.",
        ),
        "lower": ParamSpec(
            name="lower", type="float", default=-5.0, minimum=-1000.0, maximum=0.0,
            description="Percent loss over the period that counts as momentum the other way.",
        ),
    },
    lookback_days=15,
    scale_class="scale_free",
    direction_semantics=(
        "bullish: the `period`-bar rate of change crossed up through `upper`; "
        "bearish: it crossed down through `lower`. Crossings, not levels, so a "
        "name that simply stays strong fires once rather than every day."
    ),
)
def roc_momentum(
    bars, period: int = 12, upper: float = 5.0, lower: float = -5.0
) -> list[SignalEvent]:
    values = technical.roc(_series(bars, "close"), period=period)
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        previous, current = values[i - 1], values[i]
        if np.isnan(previous) or np.isnan(current):
            continue
        if previous <= upper < current:
            direction = "bullish"
        elif previous >= lower > current:
            direction = "bearish"
        else:
            continue
        events.append(
            SignalEvent(
                date=bars[i].date,
                direction=direction,
                trigger_values={"roc": float(current)},
                data_window_end=bars[i].date,
            )
        )
    return events


# ---------------------------------------------------------------------------
# Mean reversion
# ---------------------------------------------------------------------------


@register_signal_rule(
    name="stochastic-threshold",
    version="1.0.0",
    category="mean_reversion",
    summary="Stochastic %K leaving the overbought or oversold zone.",
    roles=("entry", "exit"),
    params={
        "k_period": ParamSpec(
            name="k_period", type="int", default=14, minimum=2, maximum=100,
            description="Window of the high-low range %K is measured against, in bars.",
        ),
        "d_period": ParamSpec(
            name="d_period", type="int", default=3, minimum=1, maximum=50,
            description="Smoothing window of the %D line, in bars.",
        ),
        "overbought": ParamSpec(
            name="overbought", type="float", default=80.0, minimum=50.0, maximum=100.0,
            description="%K level at or above which the instrument is treated as overbought.",
        ),
        "oversold": ParamSpec(
            name="oversold", type="float", default=20.0, minimum=0.0, maximum=50.0,
            description="%K level at or below which the instrument is treated as oversold.",
        ),
        "use_d": ParamSpec(
            name="use_d", type="bool", default=False,
            description="Trigger on the smoothed %D line instead of raw %K.",
        ),
    },
    lookback_days=20,
    scale_class="scale_free",
    direction_semantics=(
        "bullish: the oscillator exited the oversold zone (was < oversold, now >= "
        "oversold); bearish: it exited the overbought zone. Exits rather than "
        "entries into the zone, because an oscillator can sit pinned at an extreme "
        "for weeks in a strong trend."
    ),
)
def stochastic_threshold(
    bars,
    k_period: int = 14,
    d_period: int = 3,
    overbought: float = 80.0,
    oversold: float = 20.0,
    use_d: bool = False,
) -> list[SignalEvent]:
    k, d = technical.stochastic(
        _series(bars, "high"),
        _series(bars, "low"),
        _series(bars, "close"),
        k_period=k_period,
        d_period=d_period,
    )
    line = d if use_d else k
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        previous, current = line[i - 1], line[i]
        if np.isnan(previous) or np.isnan(current):
            continue
        if previous < oversold <= current:
            direction = "bullish"
        elif previous > overbought >= current:
            direction = "bearish"
        else:
            continue
        trigger = {"k": float(k[i])}
        if not np.isnan(d[i]):
            trigger["d"] = float(d[i])
        events.append(
            SignalEvent(
                date=bars[i].date,
                direction=direction,
                trigger_values=trigger,
                data_window_end=bars[i].date,
            )
        )
    return events


@register_signal_rule(
    name="bollinger-reversion",
    version="1.0.0",
    category="mean_reversion",
    summary="Close re-entering the Bollinger band after piercing it.",
    roles=("entry", "exit"),
    params={
        "window": ParamSpec(
            name="window", type="int", default=20, minimum=2, maximum=250,
            description="Window of the moving average and its standard deviation, in bars.",
        ),
        "num_std": ParamSpec(
            name="num_std", type="float", default=2.0, minimum=0.1, maximum=10.0,
            description="Band width, in population standard deviations.",
        ),
    },
    lookback_days=22,
    scale_class="price_scaled",
    direction_semantics=(
        "bullish: the close was below the lower band and has closed back inside it; "
        "bearish: it was above the upper band and has closed back inside. Waiting "
        "for re-entry rather than buying the pierce avoids standing in front of a "
        "band that is simply expanding."
    ),
)
def bollinger_reversion(
    bars, window: int = 20, num_std: float = 2.0
) -> list[SignalEvent]:
    closes = _series(bars, "close")
    lower, middle, upper = technical.bollinger(closes, window=window, num_std=num_std)
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        if np.isnan(lower[i - 1]) or np.isnan(lower[i]):
            continue
        if closes[i - 1] < lower[i - 1] and closes[i] >= lower[i]:
            direction = "bullish"
        elif closes[i - 1] > upper[i - 1] and closes[i] <= upper[i]:
            direction = "bearish"
        else:
            continue
        events.append(
            SignalEvent(
                date=bars[i].date,
                direction=direction,
                trigger_values={
                    "close": float(closes[i]),
                    "lower": float(lower[i]),
                    "middle": float(middle[i]),
                    "upper": float(upper[i]),
                },
                data_window_end=bars[i].date,
            )
        )
    return events


@register_signal_rule(
    name="zscore-reversion",
    version="1.0.0",
    category="mean_reversion",
    summary="Close reverting through a standard-score threshold.",
    roles=("entry", "exit"),
    params={
        "window": ParamSpec(
            name="window", type="int", default=20, minimum=3, maximum=250,
            description="Window the standard score is measured against, in bars.",
        ),
        "threshold": ParamSpec(
            name="threshold", type="float", default=2.0, minimum=0.1, maximum=10.0,
            description="Standard deviations from the mean that count as stretched.",
        ),
    },
    lookback_days=22,
    scale_class="scale_free",
    direction_semantics=(
        "bullish: the standard score was below -threshold and has come back above "
        "it; bearish: it was above +threshold and has come back below. Scale-free, "
        "so one threshold is comparable across a $400 name and a 90p one."
    ),
)
def zscore_reversion(
    bars, window: int = 20, threshold: float = 2.0
) -> list[SignalEvent]:
    scores = technical.rolling_zscore(_series(bars, "close"), window=window)
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        previous, current = scores[i - 1], scores[i]
        if np.isnan(previous) or np.isnan(current):
            continue
        if previous < -threshold <= current:
            direction = "bullish"
        elif previous > threshold >= current:
            direction = "bearish"
        else:
            continue
        events.append(
            SignalEvent(
                date=bars[i].date,
                direction=direction,
                trigger_values={"zscore": float(current)},
                data_window_end=bars[i].date,
            )
        )
    return events


@register_signal_rule(
    name="rsi-zone",
    version="1.0.0",
    category="mean_reversion",
    summary="Gate that opens while RSI sits inside a band.",
    roles=("filter",),
    params={
        "period": ParamSpec(
            name="period", type="int", default=14, minimum=2, maximum=100,
            description="RSI lookback period, in bars.",
        ),
        "floor": ParamSpec(
            name="floor", type="float", default=0.0, minimum=0.0, maximum=100.0,
            description="Lowest RSI value for which the gate is open.",
        ),
        "ceiling": ParamSpec(
            name="ceiling", type="float", default=50.0, minimum=0.0, maximum=100.0,
            description="Highest RSI value for which the gate is open.",
        ),
    },
    lookback_days=16,
    scale_class="scale_free",
    direction_semantics=(
        "A filter, so it emits on every bar: bullish while RSI is within "
        "[floor, ceiling], bearish outside it. Default band is the lower half, "
        "which keeps a momentum entry from buying something already extended."
    ),
)
def rsi_zone(bars, period: int = 14, floor: float = 0.0, ceiling: float = 50.0):
    values = rsi_indicator(_series(bars, "close"), period=period)
    open_on = ~np.isnan(values) & (values >= floor) & (values <= ceiling)
    events = _gate_events(bars, open_on)
    for i, event in enumerate(events):
        if not np.isnan(values[i]):
            event.trigger_values["rsi"] = float(values[i])
    return events


# ---------------------------------------------------------------------------
# Volatility / breakout
# ---------------------------------------------------------------------------


@register_signal_rule(
    name="donchian-breakout",
    version="1.0.0",
    category="volatility",
    summary="Close breaking the prior N-bar high or low channel.",
    roles=("entry", "exit"),
    params={
        "entry_window": ParamSpec(
            name="entry_window", type="int", default=20, minimum=2, maximum=400,
            description="Prior sessions whose high defines the upside breakout level.",
        ),
        "exit_window": ParamSpec(
            name="exit_window", type="int", default=10, minimum=2, maximum=400,
            description="Prior sessions whose low defines the downside break level.",
        ),
    },
    lookback_days=22,
    scale_class="price_scaled",
    direction_semantics=(
        "bullish: the close exceeded the highest high of the prior `entry_window` "
        "sessions; bearish: it fell below the lowest low of the prior `exit_window`. "
        "The two windows are separate on purpose -- the classic turtle asymmetry, "
        "entering slowly and leaving quickly."
    ),
)
def donchian_breakout(
    bars, entry_window: int = 20, exit_window: int = 10
) -> list[SignalEvent]:
    highs, lows = _series(bars, "high"), _series(bars, "low")
    closes = _series(bars, "close")
    _, upper = technical.donchian(highs, lows, window=entry_window)
    lower, _ = technical.donchian(highs, lows, window=exit_window)
    events: list[SignalEvent] = []
    for i in range(len(bars)):
        if not np.isnan(upper[i]) and closes[i] > upper[i]:
            direction, trigger = "bullish", {
                "close": float(closes[i]),
                "channel_high": float(upper[i]),
            }
        elif not np.isnan(lower[i]) and closes[i] < lower[i]:
            direction, trigger = "bearish", {
                "close": float(closes[i]),
                "channel_low": float(lower[i]),
            }
        else:
            continue
        events.append(
            SignalEvent(
                date=bars[i].date,
                direction=direction,
                trigger_values=trigger,
                data_window_end=bars[i].date,
            )
        )
    return events


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------


@register_signal_rule(
    name="volume-spike",
    version="1.0.0",
    category="volume",
    summary="Gate that opens on unusually heavy volume.",
    roles=("filter",),
    params={
        "window": ParamSpec(
            name="window", type="int", default=20, minimum=2, maximum=250,
            description="Window the day's volume is compared against, in bars.",
        ),
        "multiple": ParamSpec(
            name="multiple", type="float", default=1.5, minimum=0.1, maximum=50.0,
            description="Multiple of average volume that counts as a spike.",
        ),
    },
    lookback_days=22,
    scale_class="scale_free",
    direction_semantics=(
        "A filter, so it emits on every bar: bullish when the day's volume is at "
        "least `multiple` times the trailing average, bearish otherwise. Attach it "
        "to a breakout entry to drop the breaks that nobody participated in."
    ),
)
def volume_spike(bars, window: int = 20, multiple: float = 1.5) -> list[SignalEvent]:
    volumes = _series(bars, "volume")
    # The average is of the *prior* window, so the spike bar is not diluted by
    # being part of its own comparison.
    average = sma_indicator(volumes, window=window)
    shifted = np.full(volumes.shape, np.nan)
    shifted[1:] = average[:-1]
    ratio = np.full(volumes.shape, np.nan)
    usable = ~np.isnan(shifted) & (shifted > 0)
    ratio[usable] = volumes[usable] / shifted[usable]
    open_on = ~np.isnan(ratio) & (ratio >= multiple)
    events = _gate_events(bars, open_on)
    for i, event in enumerate(events):
        if not np.isnan(ratio[i]):
            event.trigger_values["volume_ratio"] = float(ratio[i])
    return events
