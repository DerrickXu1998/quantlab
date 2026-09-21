"""Builtin signal rule plugins (research R5).

Each rule is causal: events emitted at day T depend only on bars with
``date <= T`` (verified by tests/lookahead/test_truncation_sweep.py).
"""

from __future__ import annotations

import numpy as np

from quantlab.indicators.builtins import ema as ema_indicator
from quantlab.indicators.builtins import rolling_std as rolling_std_indicator
from quantlab.indicators.builtins import rsi as rsi_indicator
from quantlab.indicators.builtins import sma as sma_indicator
from quantlab.signals.registry import ParamSpec, SignalEvent, register_signal_rule


@register_signal_rule(
    name="sma-crossover",
    version="1.0.0",
    params={
        "fast": ParamSpec(
            name="fast",
            type="int",
            default=20,
            minimum=2,
            maximum=200,
            description="Fast simple-moving-average window, in bars.",
        ),
        "slow": ParamSpec(
            name="slow",
            type="int",
            default=50,
            minimum=3,
            maximum=400,
            description="Slow simple-moving-average window, in bars.",
        ),
    },
    lookback_days=51,  # SMA(slow) must be defined at both T-1 and T
    scale_class="scale_free",
    direction_semantics=(
        "bullish: SMA(fast) crossed above SMA(slow) on the signal date; "
        "bearish: SMA(fast) crossed below SMA(slow)"
    ),
)
def sma_crossover(bars, fast: int = 20, slow: int = 50) -> list[SignalEvent]:
    closes = np.array([bar.close for bar in bars], dtype=float)
    dates = [bar.date for bar in bars]
    fast_sma = sma_indicator(closes, window=fast)
    slow_sma = sma_indicator(closes, window=slow)
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        window = (fast_sma[i - 1], slow_sma[i - 1], fast_sma[i], slow_sma[i])
        if np.isnan(window).any():
            continue
        prev_diff = fast_sma[i - 1] - slow_sma[i - 1]
        diff = fast_sma[i] - slow_sma[i]
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
                trigger_values={"sma_fast": float(fast_sma[i]), "sma_slow": float(slow_sma[i])},
                data_window_end=dates[i],
            )
        )
    return events


@register_signal_rule(
    name="rsi-threshold",
    version="1.0.0",
    params={
        "period": ParamSpec(
            name="period",
            type="int",
            default=14,
            minimum=2,
            maximum=100,
            description="RSI lookback period, in bars.",
        ),
        "overbought": ParamSpec(
            name="overbought",
            type="float",
            default=70,
            minimum=50,
            maximum=100,
            description="RSI level at or above which the instrument is treated as overbought.",
        ),
        "oversold": ParamSpec(
            name="oversold",
            type="float",
            default=30,
            minimum=0,
            maximum=50,
            description="RSI level at or below which the instrument is treated as oversold.",
        ),
    },
    lookback_days=16,  # RSI(period) defined at index `period`; an exit needs the prior value
    scale_class="scale_free",
    direction_semantics=(
        "bearish: RSI exited the overbought zone (was > overbought, now <= overbought); "
        "bullish: RSI exited the oversold zone (was < oversold, now >= oversold)"
    ),
)
def rsi_threshold(
    bars, period: int = 14, overbought: float = 70, oversold: float = 30
) -> list[SignalEvent]:
    closes = np.array([bar.close for bar in bars], dtype=float)
    dates = [bar.date for bar in bars]
    rsi_values = rsi_indicator(closes, period=period)
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        prev, curr = rsi_values[i - 1], rsi_values[i]
        if np.isnan(prev) or np.isnan(curr):
            continue
        if prev > overbought and curr <= overbought:
            direction = "bearish"
        elif prev < oversold and curr >= oversold:
            direction = "bullish"
        else:
            continue
        events.append(
            SignalEvent(
                date=dates[i],
                direction=direction,
                trigger_values={"rsi": float(curr)},
                data_window_end=dates[i],
            )
        )
    return events


@register_signal_rule(
    name="breakout-20d",
    version="1.0.0",
    params={
        "window": ParamSpec(
            name="window",
            type="int",
            default=20,
            minimum=2,
            maximum=250,
            description="Number of prior sessions whose high/low defines the breakout level.",
        ),
    },
    lookback_days=21,  # day T plus 20 prior sessions
    scale_class="price_scaled",
    direction_semantics=(
        "bullish: close exceeded the max high of the prior `window` sessions; "
        "bearish: close fell below the min low of the prior `window` sessions"
    ),
)
def breakout_20d(bars, window: int = 20) -> list[SignalEvent]:
    events: list[SignalEvent] = []
    for i in range(window, len(bars)):
        prior = bars[i - window : i]
        bar = bars[i]
        if bar.close > (prior_max_high := max(b.high for b in prior)):
            events.append(
                SignalEvent(
                    date=bar.date,
                    direction="bullish",
                    trigger_values={
                        "close": float(bar.close),
                        "prior_max_high": float(prior_max_high),
                    },
                    data_window_end=bar.date,
                )
            )
        elif bar.close < (prior_min_low := min(b.low for b in prior)):
            events.append(
                SignalEvent(
                    date=bar.date,
                    direction="bearish",
                    trigger_values={
                        "close": float(bar.close),
                        "prior_min_low": float(prior_min_low),
                    },
                    data_window_end=bar.date,
                )
            )
    return events


def _macd_line(closes: np.ndarray, fast: int, slow: int) -> np.ndarray:
    return ema_indicator(closes, window=fast) - ema_indicator(closes, window=slow)


@register_signal_rule(
    name="macd-crossover",
    version="1.0.0",
    params={
        "fast": ParamSpec(
            name="fast",
            type="int",
            default=12,
            minimum=2,
            maximum=200,
            description="Fast EMA window of the MACD line, in bars.",
        ),
        "slow": ParamSpec(
            name="slow",
            type="int",
            default=26,
            minimum=3,
            maximum=400,
            description="Slow EMA window of the MACD line, in bars.",
        ),
        "signal": ParamSpec(
            name="signal",
            type="int",
            default=9,
            minimum=2,
            maximum=100,
            description="EMA window smoothing the MACD line into its signal line.",
        ),
    },
    lookback_days=35,  # signal line defined at index slow+signal-2; a cross needs the prior pair
    scale_class="scale_free",
    direction_semantics=(
        "bullish: the MACD line (EMA(fast) - EMA(slow)) crossed above its "
        "EMA(signal) signal line on the signal date; bearish: crossed below"
    ),
)
def macd_crossover(bars, fast: int = 12, slow: int = 26, signal: int = 9) -> list[SignalEvent]:
    closes = np.array([bar.close for bar in bars], dtype=float)
    dates = [bar.date for bar in bars]
    line = _macd_line(closes, fast, slow)
    signal_line = ema_indicator(line, window=signal)
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        window = (line[i - 1], signal_line[i - 1], line[i], signal_line[i])
        if np.isnan(window).any():
            continue
        prev_diff = line[i - 1] - signal_line[i - 1]
        diff = line[i] - signal_line[i]
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
                trigger_values={"macd": float(line[i]), "signal_line": float(signal_line[i])},
                data_window_end=dates[i],
            )
        )
    return events


def _bollinger_bands(closes: np.ndarray, window: int, num_std: float):
    mid = sma_indicator(closes, window=window)
    spread = num_std * rolling_std_indicator(closes, window=window)
    return mid + spread, mid - spread


@register_signal_rule(
    name="bollinger-breakout",
    version="1.0.0",
    params={
        "window": ParamSpec(
            name="window",
            type="int",
            default=20,
            minimum=2,
            maximum=250,
            description="Sessions in the band's rolling mean and standard deviation.",
        ),
        "num_std": ParamSpec(
            name="num_std",
            type="float",
            default=2.0,
            minimum=0.5,
            maximum=5.0,
            description="Band width in population standard deviations from the mean.",
        ),
    },
    lookback_days=21,  # band defined at index window-1; a cross needs the prior band too
    scale_class="price_scaled",
    direction_semantics=(
        "bullish: close crossed above the upper Bollinger band (was at or below, "
        "now above); bearish: close crossed below the lower band"
    ),
)
def bollinger_breakout(bars, window: int = 20, num_std: float = 2.0) -> list[SignalEvent]:
    closes = np.array([bar.close for bar in bars], dtype=float)
    dates = [bar.date for bar in bars]
    upper, lower = _bollinger_bands(closes, window, num_std)
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        band_window = (upper[i - 1], lower[i - 1], upper[i], lower[i])
        if np.isnan(band_window).any():
            continue
        if closes[i - 1] <= upper[i - 1] and closes[i] > upper[i]:
            direction = "bullish"
            trigger = {"close": float(closes[i]), "upper_band": float(upper[i])}
        elif closes[i - 1] >= lower[i - 1] and closes[i] < lower[i]:
            direction = "bearish"
            trigger = {"close": float(closes[i]), "lower_band": float(lower[i])}
        else:
            continue
        events.append(
            SignalEvent(
                date=dates[i],
                direction=direction,
                trigger_values=trigger,
                data_window_end=dates[i],
            )
        )
    return events


@register_signal_rule(
    name="bollinger-mean-reversion",
    version="1.0.0",
    params={
        "window": ParamSpec(
            name="window",
            type="int",
            default=20,
            minimum=2,
            maximum=250,
            description="Sessions in the band's rolling mean and standard deviation.",
        ),
        "num_std": ParamSpec(
            name="num_std",
            type="float",
            default=2.0,
            minimum=0.5,
            maximum=5.0,
            description="Band width in population standard deviations from the mean.",
        ),
    },
    lookback_days=21,  # band defined at index window-1; a re-entry needs the prior band too
    scale_class="price_scaled",
    direction_semantics=(
        "bullish: close re-entered the bands from below (was under the lower band, "
        "now back at or above it); bearish: close re-entered from above the upper band"
    ),
)
def bollinger_mean_reversion(bars, window: int = 20, num_std: float = 2.0) -> list[SignalEvent]:
    closes = np.array([bar.close for bar in bars], dtype=float)
    dates = [bar.date for bar in bars]
    upper, lower = _bollinger_bands(closes, window, num_std)
    events: list[SignalEvent] = []
    for i in range(1, len(bars)):
        band_window = (upper[i - 1], lower[i - 1], upper[i], lower[i])
        if np.isnan(band_window).any():
            continue
        if closes[i - 1] < lower[i - 1] and closes[i] >= lower[i]:
            direction = "bullish"
            trigger = {"close": float(closes[i]), "lower_band": float(lower[i])}
        elif closes[i - 1] > upper[i - 1] and closes[i] <= upper[i]:
            direction = "bearish"
            trigger = {"close": float(closes[i]), "upper_band": float(upper[i])}
        else:
            continue
        events.append(
            SignalEvent(
                date=dates[i],
                direction=direction,
                trigger_values=trigger,
                data_window_end=dates[i],
            )
        )
    return events
