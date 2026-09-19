"""Builtin signal rule plugins (research R5).

Each rule is causal: events emitted at day T depend only on bars with
``date <= T`` (verified by tests/lookahead/test_truncation_sweep.py).
"""

from __future__ import annotations

import numpy as np

from quantlab.indicators.builtins import rsi as rsi_indicator
from quantlab.indicators.builtins import sma as sma_indicator
from quantlab.signals.registry import SignalEvent, register_signal_rule


@register_signal_rule(
    name="sma-crossover",
    version="1.0.0",
    params={"fast": 20, "slow": 50},
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
    params={"period": 14, "overbought": 70, "oversold": 30},
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
    params={"window": 20},
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
