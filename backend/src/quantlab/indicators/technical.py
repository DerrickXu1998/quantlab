"""Technical indicators beyond the original four (SMA, RSI, rolling max/min).

Same contract as :mod:`quantlab.indicators.builtins`: every function takes
array-like input and returns a float ndarray of the *same length*, NaN where
there is not yet enough history. Keeping the length fixed is what lets a signal
rule index an indicator array and a bar list with the same ``i``.

Some indicators here need more than one series (ATR needs high, low and close).
Those take the series as separate leading arguments; they register with the same
plugin decorator so they stay enumerable at runtime (Constitution II), and their
``params`` describe only the scalar knobs.

Wilder's smoothing appears in ATR and ADX and is written the same way it already
is in ``builtins.rsi`` -- the averaged form, ``avg = (avg * (n - 1) + x) / n`` --
so the three agree rather than each picking a convention.
"""

from __future__ import annotations

import numpy as np

from quantlab.indicators.builtins import sma
from quantlab.indicators.registry import register_indicator


def _asarray(values) -> np.ndarray:
    return np.asarray(values, dtype=float)


def _first_full_window(valid: np.ndarray, window: int) -> int | None:
    """Index of the first bar with ``window`` consecutive non-NaN values.

    Derived series (a MACD line, say) carry leading NaNs, so an EMA taken over
    one cannot simply start at ``window - 1``.
    """
    for i in range(window - 1, len(valid)):
        if valid[i - window + 1 : i + 1].all():
            return i
    return None


@register_indicator(
    name="ema",
    version="1.0.0",
    scale_class="price_scaled",
    params={"window": 20},
    description=(
        "Exponential moving average, seeded with the SMA of the first full window "
        "and smoothed with alpha = 2 / (window + 1)."
    ),
)
def ema(values, window: int = 20) -> np.ndarray:
    values = _asarray(values)
    out = np.full(values.shape, np.nan)
    start = _first_full_window(~np.isnan(values), window)
    if start is None:
        return out
    alpha = 2.0 / (window + 1.0)
    out[start] = float(values[start - window + 1 : start + 1].mean())
    for i in range(start + 1, len(values)):
        if np.isnan(values[i]):
            # A hole in the input ends the recursion rather than silently
            # carrying a stale level forward.
            break
        out[i] = alpha * float(values[i]) + (1.0 - alpha) * out[i - 1]
    return out


@register_indicator(
    name="macd",
    version="1.0.0",
    scale_class="price_scaled",
    params={"fast": 12, "slow": 26, "signal": 9},
    description=(
        "Moving Average Convergence Divergence: EMA(fast) - EMA(slow), its EMA(signal) "
        "line, and the histogram between them. Returns (macd, signal, histogram)."
    ),
)
def macd(
    values, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = _asarray(values)
    macd_line = ema(values, window=fast) - ema(values, window=slow)
    signal_line = ema(macd_line, window=signal)
    return macd_line, signal_line, macd_line - signal_line


@register_indicator(
    name="rolling-std",
    version="1.0.0",
    scale_class="price_scaled",
    params={"window": 20},
    description="Population standard deviation of the trailing `window` values (inclusive).",
)
def rolling_std(values, window: int = 20) -> np.ndarray:
    values = _asarray(values)
    out = np.full(values.shape, np.nan)
    if len(values) >= window:
        windows = np.lib.stride_tricks.sliding_window_view(values, window)
        # Population (ddof=0), which is the Bollinger convention.
        out[window - 1 :] = windows.std(axis=1)
    return out


@register_indicator(
    name="bollinger",
    version="1.0.0",
    scale_class="price_scaled",
    params={"window": 20, "num_std": 2.0},
    description=(
        "Bollinger Bands: the SMA of `window` with bands at +/- `num_std` population "
        "standard deviations. Returns (lower, middle, upper)."
    ),
)
def bollinger(
    values, window: int = 20, num_std: float = 2.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    middle = sma(values, window=window)
    spread = rolling_std(values, window=window) * float(num_std)
    return middle - spread, middle, middle + spread


@register_indicator(
    name="rolling-zscore",
    version="1.0.0",
    scale_class="scale_free",
    params={"window": 20},
    description=(
        "Standard score of each value against the trailing `window` (inclusive): "
        "(x - mean) / population std. NaN where the window is flat."
    ),
)
def rolling_zscore(values, window: int = 20) -> np.ndarray:
    values = _asarray(values)
    mean = sma(values, window=window)
    deviation = rolling_std(values, window=window)
    out = np.full(values.shape, np.nan)
    # A flat window has no dispersion, so the score is undefined rather than
    # infinite -- the same stance performance._sharpe takes on zero variance.
    usable = ~np.isnan(deviation) & (deviation > 0)
    out[usable] = (values[usable] - mean[usable]) / deviation[usable]
    return out


def true_range(high, low, close) -> np.ndarray:
    """Wilder's true range. ``TR[0]`` is the bar's own range: there is no prior
    close to gap from."""
    high, low, close = _asarray(high), _asarray(low), _asarray(close)
    out = np.empty(high.shape)
    out[0] = high[0] - low[0]
    if len(high) > 1:
        previous = close[:-1]
        out[1:] = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - previous), np.abs(low[1:] - previous)),
        )
    return out


def _wilder_average(values: np.ndarray, period: int, start: int) -> np.ndarray:
    """Wilder's smoothing, seeded at ``start`` with the mean of the preceding
    ``period`` values (inclusive of ``start``)."""
    out = np.full(values.shape, np.nan)
    if start >= len(values):
        return out
    out[start] = float(values[start - period + 1 : start + 1].mean())
    for i in range(start + 1, len(values)):
        out[i] = (out[i - 1] * (period - 1) + float(values[i])) / period
    return out


@register_indicator(
    name="atr",
    version="1.0.0",
    scale_class="price_scaled",
    params={"period": 14},
    description=(
        "Average True Range with Wilder's smoothing; first value at index `period`. "
        "Takes (high, low, close)."
    ),
)
def atr(high, low, close, period: int = 14) -> np.ndarray:
    ranges = true_range(high, low, close)
    n = len(ranges)
    if n <= period:
        return np.full(n, np.nan)
    # TR[0] is a partial bar (no gap component), so the seed averages
    # TR[1..period] and the first ATR lands at index `period`.
    out = np.full(n, np.nan)
    out[period] = float(ranges[1 : period + 1].mean())
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + float(ranges[i])) / period
    return out


@register_indicator(
    name="stochastic",
    version="1.0.0",
    scale_class="scale_free",
    params={"k_period": 14, "d_period": 3},
    description=(
        "Stochastic oscillator: %K is the close's position in the trailing "
        "`k_period` high-low range, %D is the SMA of %K. Takes (high, low, close). "
        "Returns (k, d)."
    ),
)
def stochastic(
    high, low, close, k_period: int = 14, d_period: int = 3
) -> tuple[np.ndarray, np.ndarray]:
    high, low, close = _asarray(high), _asarray(low), _asarray(close)
    n = len(close)
    k = np.full(n, np.nan)
    for i in range(k_period - 1, n):
        window_high = float(high[i - k_period + 1 : i + 1].max())
        window_low = float(low[i - k_period + 1 : i + 1].min())
        span = window_high - window_low
        # A range of zero leaves the close's position in it undefined; 50 would
        # be a fabricated midpoint.
        if span > 0:
            k[i] = 100.0 * (float(close[i]) - window_low) / span
    return k, sma(k, window=d_period)


@register_indicator(
    name="roc",
    version="1.0.0",
    scale_class="scale_free",
    params={"period": 12},
    description="Rate of change over `period` bars, in percent: 100 * (x[t] / x[t-period] - 1).",
)
def roc(values, period: int = 12) -> np.ndarray:
    values = _asarray(values)
    out = np.full(values.shape, np.nan)
    if len(values) > period:
        base = values[:-period]
        usable = base != 0
        result = np.full(base.shape, np.nan)
        result[usable] = 100.0 * (values[period:][usable] / base[usable] - 1.0)
        out[period:] = result
    return out


@register_indicator(
    name="adx",
    version="1.0.0",
    scale_class="scale_free",
    params={"period": 14},
    description=(
        "Average Directional Index with Wilder's smoothing, plus the two directional "
        "indicators. Takes (high, low, close). Returns (adx, plus_di, minus_di)."
    ),
)
def adx(
    high, low, close, period: int = 14
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    high, low, close = _asarray(high), _asarray(low), _asarray(close)
    n = len(close)
    empty = np.full(n, np.nan)
    if n <= 2 * period:
        return empty, empty.copy(), empty.copy()

    up = np.zeros(n)
    down = np.zeros(n)
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    # Only the larger of the two moves counts, and only when it is positive:
    # an inside bar is directionless, not weakly both ways.
    up[1:] = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    down[1:] = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    ranges = true_range(high, low, close)
    # Seeded at index `period` over TR[1..period], matching atr().
    smooth_tr = _wilder_average(ranges[1:], period, period - 1)
    smooth_up = _wilder_average(up[1:], period, period - 1)
    smooth_down = _wilder_average(down[1:], period, period - 1)

    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        usable = ~np.isnan(smooth_tr) & (smooth_tr > 0)
        plus_di[1:][usable] = 100.0 * smooth_up[usable] / smooth_tr[usable]
        minus_di[1:][usable] = 100.0 * smooth_down[usable] / smooth_tr[usable]

    total = plus_di + minus_di
    dx = np.full(n, np.nan)
    defined = ~np.isnan(total) & (total > 0)
    dx[defined] = 100.0 * np.abs(plus_di[defined] - minus_di[defined]) / total[defined]

    # ADX is Wilder's average of DX, and DX itself only begins at `period`, so
    # the first ADX lands at 2 * period.
    out = np.full(n, np.nan)
    first_dx = period
    seed_end = first_dx + period
    if seed_end <= n:
        window = dx[first_dx:seed_end]
        if not np.isnan(window).any():
            out[seed_end - 1] = float(window.mean())
            for i in range(seed_end, n):
                out[i] = (out[i - 1] * (period - 1) + float(dx[i])) / period
    return out, plus_di, minus_di


@register_indicator(
    name="obv",
    version="1.0.0",
    scale_class="price_scaled",
    params={},
    description=(
        "On-Balance Volume: the running sum of volume signed by the close-to-close "
        "direction. Takes (close, volume)."
    ),
)
def obv(close, volume) -> np.ndarray:
    close, volume = _asarray(close), _asarray(volume)
    out = np.zeros(close.shape)
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            out[i] = out[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            out[i] = out[i - 1] - volume[i]
        else:
            out[i] = out[i - 1]
    return out


@register_indicator(
    name="donchian",
    version="1.0.0",
    scale_class="price_scaled",
    params={"window": 20},
    description=(
        "Donchian channel over the *prior* `window` bars, excluding the current one, "
        "so a close can be compared against it without comparing it to itself. "
        "Takes (high, low). Returns (lower, upper)."
    ),
)
def donchian(high, low, window: int = 20) -> tuple[np.ndarray, np.ndarray]:
    high, low = _asarray(high), _asarray(low)
    n = len(high)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(window, n):
        upper[i] = float(high[i - window : i].max())
        lower[i] = float(low[i - window : i].min())
    return lower, upper
