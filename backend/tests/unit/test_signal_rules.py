"""Reference-value and boundary tests for the builtin signal rules."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from quantlab import config
from quantlab.signals import (
    builtins,  # noqa: F401  (registers the builtin rules)
    engine,
)
from quantlab.signals.registry import get_rule, list_rules


@dataclass(frozen=True)
class FakeBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int = 1000


def make_bars(closes, highs=None, lows=None):
    calendar = config.trading_calendar()
    bars = []
    for i, close in enumerate(closes):
        high = highs[i] if highs is not None else close
        low = lows[i] if lows is not None else close
        bars.append(FakeBar(calendar[i].isoformat(), close, high, low, close, 1000))
    return bars


def ref_sma(values, window):
    out = [math.nan] * len(values)
    for i in range(window - 1, len(values)):
        out[i] = sum(values[i - window + 1 : i + 1]) / window
    return out


def ref_ema(values, window):
    """Independent EMA reference: alpha = 2/(window+1), SMA-seeded."""
    alpha = 2.0 / (window + 1)
    out = [math.nan] * len(values)
    start = next((i for i, v in enumerate(values) if not math.isnan(v)), None)
    if start is None or len(values) - start < window:
        return out
    acc = sum(values[start : start + window]) / window
    out[start + window - 1] = acc
    for i in range(start + window, len(values)):
        acc += alpha * (values[i] - acc)
        out[i] = acc
    return out


def ref_bollinger(closes, window, num_std):
    """Independent band reference: SMA +/- num_std * population stdev."""
    upper = [math.nan] * len(closes)
    lower = [math.nan] * len(closes)
    for i in range(window - 1, len(closes)):
        segment = closes[i - window + 1 : i + 1]
        mean = sum(segment) / window
        sd = math.sqrt(sum((v - mean) ** 2 for v in segment) / window)
        upper[i] = mean + num_std * sd
        lower[i] = mean - num_std * sd
    return upper, lower


def test_registry_lists_the_builtin_rules():
    rules = {(r.name, r.version): r for r in list_rules()}
    for name in (
        "sma-crossover",
        "rsi-threshold",
        "breakout-20d",
        "macd-crossover",
        "bollinger-breakout",
        "bollinger-mean-reversion",
    ):
        assert (name, "1.0.0") in rules, f"missing rule {name}"
    for rule in rules.values():
        assert rule.lookback_days >= 1
        assert rule.direction_semantics
        assert rule.scale_class in ("scale_free", "price_scaled")
        assert rule.params


def test_sma_crossover_matches_reference():
    rule = get_rule("sma-crossover", "1.0.0")
    closes = [100.0 - 0.5 * i for i in range(60)] + [70.0 + 0.9 * j for j in range(1, 61)]
    bars = make_bars(closes)
    events = rule.compute(bars, **rule.params)

    fast = ref_sma(closes, 20)
    slow = ref_sma(closes, 50)
    expected = []
    for i in range(1, len(closes)):
        if any(math.isnan(v) for v in (fast[i - 1], slow[i - 1], fast[i], slow[i])):
            continue
        prev_diff, diff = fast[i - 1] - slow[i - 1], fast[i] - slow[i]
        if prev_diff <= 0 < diff:
            expected.append((bars[i].date, "bullish"))
        elif prev_diff >= 0 > diff:
            expected.append((bars[i].date, "bearish"))
    assert [(e.date, e.direction) for e in events] == expected
    assert expected, "crafted series must produce at least one crossover"
    assert events[0].direction == "bullish"  # decline then rise => upward cross first
    first = events[0]
    i = [b.date for b in bars].index(first.date)
    assert first.trigger_values["sma_fast"] == pytest.approx(fast[i], rel=1e-12)
    assert first.trigger_values["sma_slow"] == pytest.approx(slow[i], rel=1e-12)
    assert first.data_window_end == first.date


def test_sma_crossover_flat_series_emits_nothing():
    rule = get_rule("sma-crossover")
    assert rule.compute(make_bars([50.0] * 80), **rule.params) == []


def test_sma_crossover_insufficient_lookback():
    rule = get_rule("sma-crossover")
    closes = [100.0 - 0.5 * i for i in range(60)]
    assert rule.compute(make_bars(closes[:50]), **rule.params) == []
    # engine enforces the declared lookback (51 bars) before calling the rule
    assert engine.compute_signals({"ZZTEST": make_bars(closes)}, rules=[rule]) == []


def test_rsi_threshold_hand_computed_bearish_exit():
    """RSI(14) on this series: 78.5714, 72.9592, then 67.7478 — the third value
    exits the >70 overbought zone, so exactly one bearish signal on the last day."""
    rule = get_rule("rsi-threshold", "1.0.0")
    closes = [10, 11, 12, 11, 12, 13, 14, 13, 14, 15, 16, 15, 16, 17, 18, 17, 16]
    bars = make_bars([float(c) for c in closes])
    events = rule.compute(bars, **rule.params)
    assert len(events) == 1
    event = events[0]
    assert event.date == bars[-1].date
    assert event.direction == "bearish"
    assert event.trigger_values["rsi"] == pytest.approx(67.74781341107872, rel=1e-9)
    assert event.data_window_end == event.date


def test_rsi_threshold_hand_computed_bullish_exit():
    """Mirror image: RSI enters <30 oversold then exits upward -> one bullish signal."""
    rule = get_rule("rsi-threshold", "1.0.0")
    closes = [18, 17, 16, 17, 16, 15, 14, 15, 14, 13, 12, 13, 12, 11, 10, 11, 12]
    bars = make_bars([float(c) for c in closes])
    events = rule.compute(bars, **rule.params)
    assert len(events) == 1
    assert events[0].direction == "bullish"
    assert events[0].date == bars[-1].date
    assert events[0].trigger_values["rsi"] == pytest.approx(32.25218658892128, rel=1e-9)


def test_rsi_threshold_flat_series_emits_nothing():
    rule = get_rule("rsi-threshold")
    assert rule.compute(make_bars([9.0] * 40), **rule.params) == []


def test_rsi_threshold_insufficient_lookback():
    rule = get_rule("rsi-threshold")
    closes = [10, 11, 12, 11, 12, 13, 14, 13, 14, 15, 16, 15, 16, 17, 18]
    assert rule.compute(make_bars([float(c) for c in closes]), **rule.params) == []


def test_breakout_bullish_and_bearish():
    rule = get_rule("breakout-20d", "1.0.0")
    flat = [100.0] * 20
    up = rule.compute(make_bars(flat + [105.0]), **rule.params)
    assert [(e.date, e.direction) for e in up] == [
        (config.trading_calendar()[20].isoformat(), "bullish")
    ]
    assert up[0].trigger_values == {"close": 105.0, "prior_max_high": 100.0}
    assert up[0].data_window_end == up[0].date

    down = rule.compute(make_bars(flat + [95.0]), **rule.params)
    assert [e.direction for e in down] == ["bearish"]
    assert down[0].trigger_values == {"close": 95.0, "prior_min_low": 100.0}


def test_breakout_uses_prior_highs_not_closes():
    """A close above all prior closes but below a prior wick high is NOT a breakout."""
    rule = get_rule("breakout-20d")
    closes = [100.0] * 20 + [100.5]
    highs = [101.0] * 20 + [100.5]
    lows = [99.0] * 20 + [100.5]
    assert rule.compute(make_bars(closes, highs, lows), **rule.params) == []


def test_breakout_window_excludes_current_bar():
    """With 21 bars, day 20 compares against bars 0..19 only (no self-reference)."""
    rule = get_rule("breakout-20d")
    closes = [float(100 + i) for i in range(21)]  # every day a new high
    events = rule.compute(make_bars(closes), **rule.params)
    assert len(events) == 1
    assert events[0].direction == "bullish"
    assert events[0].trigger_values["prior_max_high"] == 119.0


def test_breakout_insufficient_lookback():
    rule = get_rule("breakout-20d")
    assert rule.compute(make_bars([100.0] * 19 + [200.0]), **rule.params) == []


def test_engine_orders_output_deterministically():
    bars = make_bars([100.0] * 20 + [105.0])
    signals = engine.compute_signals({"ZZTEST": bars})
    assert [(s.symbol, s.date, s.rule_name) for s in signals] == sorted(
        (s.symbol, s.date, s.rule_name) for s in signals
    )
    # A step up out of a flat series is both a 20-day breakout and a zero-width
    # band breakout; macd-crossover's lookback (35) exceeds the 21 bars given.
    assert [s.rule_name for s in signals] == ["bollinger-breakout", "breakout-20d"]


# --- macd-crossover --------------------------------------------------------


def _ref_macd_events(closes, fast, slow, signal):
    line = [
        (f - s) if not (math.isnan(f) or math.isnan(s)) else math.nan
        for f, s in zip(ref_ema(closes, fast), ref_ema(closes, slow), strict=True)
    ]
    signal_line = ref_ema(line, signal)
    events = []
    for i in range(1, len(closes)):
        window = (line[i - 1], signal_line[i - 1], line[i], signal_line[i])
        if any(math.isnan(v) for v in window):
            continue
        prev_diff, diff = line[i - 1] - signal_line[i - 1], line[i] - signal_line[i]
        if prev_diff <= 0 < diff:
            events.append((i, "bullish"))
        elif prev_diff >= 0 > diff:
            events.append((i, "bearish"))
    return events, line, signal_line


def test_macd_crossover_matches_reference():
    rule = get_rule("macd-crossover", "1.0.0")
    closes = [100.0 - 0.5 * i for i in range(60)] + [70.0 + 0.9 * j for j in range(1, 61)]
    bars = make_bars(closes)
    events = rule.compute(bars, **rule.params)

    expected, line, signal_line = _ref_macd_events(closes, 12, 26, 9)
    assert [(b.date, d) for (i, d) in expected for b in [bars[i]]] == [
        (e.date, e.direction) for e in events
    ]
    assert expected, "crafted series must produce at least one crossover"
    first = events[0]
    i = [b.date for b in bars].index(first.date)
    assert first.trigger_values["macd"] == pytest.approx(line[i], rel=1e-12)
    assert first.trigger_values["signal_line"] == pytest.approx(signal_line[i], rel=1e-12)
    assert first.data_window_end == first.date


def test_macd_crossover_flat_series_emits_nothing():
    rule = get_rule("macd-crossover")
    assert rule.compute(make_bars([50.0] * 80), **rule.params) == []


def test_macd_crossover_insufficient_lookback():
    rule = get_rule("macd-crossover")
    closes = [100.0 - 0.5 * i for i in range(40)]
    # The signal line needs slow+signal-1 bars before a cross can be seen.
    assert engine.compute_signals({"ZZTEST": make_bars(closes[:34])}, rules=[rule]) == []


# --- bollinger-breakout ----------------------------------------------------


def test_bollinger_breakout_bullish_and_bearish():
    rule = get_rule("bollinger-breakout", "1.0.0")
    flat = [100.0] * 20
    up = rule.compute(make_bars(flat + [105.0]), **rule.params)
    assert [(e.date, e.direction) for e in up] == [
        (config.trading_calendar()[20].isoformat(), "bullish")
    ]
    # The band is the trailing inclusive window: the 105 close is part of it,
    # so the upper band on the breakout day is pulled above 100.
    ref_upper, _ = ref_bollinger(flat + [105.0], 20, 2.0)
    assert up[0].trigger_values["close"] == 105.0
    assert up[0].trigger_values["upper_band"] == pytest.approx(ref_upper[20], rel=1e-12)
    assert up[0].data_window_end == up[0].date

    down = rule.compute(make_bars(flat + [95.0]), **rule.params)
    assert [e.direction for e in down] == ["bearish"]
    _, ref_lower = ref_bollinger(flat + [95.0], 20, 2.0)
    assert down[0].trigger_values["close"] == 95.0
    assert down[0].trigger_values["lower_band"] == pytest.approx(ref_lower[20], rel=1e-12)


def test_bollinger_breakout_matches_reference():
    rule = get_rule("bollinger-breakout", "1.0.0")
    closes = [100.0] * 15 + [103.0, 97.0, 104.0, 96.0, 105.5, 94.0, 102.0] + [100.0] * 10
    bars = make_bars(closes)
    events = rule.compute(bars, **rule.params)

    upper, lower = ref_bollinger(closes, 20, 2.0)
    expected = []
    for i in range(1, len(closes)):
        if any(math.isnan(v) for v in (upper[i - 1], lower[i - 1], upper[i], lower[i])):
            continue
        if closes[i - 1] <= upper[i - 1] and closes[i] > upper[i]:
            expected.append((bars[i].date, "bullish"))
        elif closes[i - 1] >= lower[i - 1] and closes[i] < lower[i]:
            expected.append((bars[i].date, "bearish"))
    assert expected, "crafted series must produce at least one band cross"
    assert [(e.date, e.direction) for e in events] == expected


def test_bollinger_breakout_inside_the_band_emits_nothing():
    rule = get_rule("bollinger-breakout")
    # Oscillating tightly around the mean: never a cross of a 2-sigma band.
    closes = [100.0 + (0.5 if i % 2 else -0.5) for i in range(40)]
    assert rule.compute(make_bars(closes), **rule.params) == []


def test_bollinger_breakout_insufficient_lookback():
    rule = get_rule("bollinger-breakout")
    assert rule.compute(make_bars([100.0] * 19 + [200.0]), **rule.params) == []


# --- bollinger-mean-reversion ----------------------------------------------


def test_bollinger_mean_reversion_matches_reference():
    rule = get_rule("bollinger-mean-reversion", "1.0.0")
    closes = [100.0] * 15 + [103.0, 97.0, 104.0, 96.0, 105.5, 94.0, 102.0] + [100.0] * 10
    bars = make_bars(closes)
    events = rule.compute(bars, **rule.params)

    upper, lower = ref_bollinger(closes, 20, 2.0)
    expected = []
    for i in range(1, len(closes)):
        if any(math.isnan(v) for v in (upper[i - 1], lower[i - 1], upper[i], lower[i])):
            continue
        if closes[i - 1] < lower[i - 1] and closes[i] >= lower[i]:
            expected.append((bars[i].date, "bullish"))
        elif closes[i - 1] > upper[i - 1] and closes[i] <= upper[i]:
            expected.append((bars[i].date, "bearish"))
    assert [(e.date, e.direction) for e in events] == expected


def test_bollinger_mean_reversion_fires_on_reentry_only():
    rule = get_rule("bollinger-mean-reversion", "1.0.0")
    # Out through the lower band and straight back in: one bullish re-entry.
    closes = [100.0] * 20 + [90.0, 100.0]
    events = rule.compute(make_bars(closes), **rule.params)
    assert [e.direction for e in events] == ["bullish"]
    assert events[0].date == config.trading_calendar()[21].isoformat()
    assert events[0].data_window_end == events[0].date

    # A breakout with no re-entry is not this rule's event.
    assert rule.compute(make_bars([100.0] * 20 + [105.0]), **rule.params) == []


def test_bollinger_mean_reversion_insufficient_lookback():
    rule = get_rule("bollinger-mean-reversion")
    # 20 bars: the first band is defined at index 19 but a re-entry cross needs
    # the prior band as well, so nothing can fire.
    assert rule.compute(make_bars([100.0] * 19 + [50.0]), **rule.params) == []
