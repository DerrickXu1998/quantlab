"""Calendar and seasonality features -- free by construction, no data source
required. Cheap to compute, and several are genuinely robust (turn-of-month in
particular)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import indicator


@indicator(
    "calendar",
    inputs=("close",),
    outputs=("day_of_week", "day_of_month", "month", "quarter", "is_month_end", "is_quarter_end"),
    tags=("seasonality", "calendar"),
)
def calendar(df: pd.DataFrame) -> pd.DataFrame:
    """Plain calendar decomposition. Use as categorical controls, not signals."""
    idx = df.index
    return pd.DataFrame(
        {
            "day_of_week": idx.dayofweek.astype(float),
            "day_of_month": idx.day.astype(float),
            "month": idx.month.astype(float),
            "quarter": idx.quarter.astype(float),
            "is_month_end": idx.is_month_end.astype(float),
            "is_quarter_end": idx.is_quarter_end.astype(float),
        },
        index=idx,
    )


@indicator(
    "turn_of_month",
    inputs=("close",),
    params={"window": 4},
    outputs=("turn_of_month", "trading_day_of_month"),
    tags=("seasonality", "calendar"),
)
def turn_of_month(df: pd.DataFrame, window: int = 4) -> pd.DataFrame:
    """Turn-of-month flag: the last `window` and first `window` trading days.

    One of the more durable calendar effects -- driven by pension and index
    flows, which have not gone away.
    """
    idx = df.index
    s = pd.Series(np.arange(len(idx)), index=idx)
    tdom = s.groupby(idx.to_period("M")).cumcount() + 1

    # Business days remaining to calendar month end, from the exchange
    # calendar rather than from the data. Counting rows instead would need to
    # know how many bars the month ends up containing, which is a look-ahead
    # at the final bar of every month.
    month_end = idx.to_period("M").to_timestamp(how="end").normalize()
    to_end = np.busday_count(
        idx.normalize().values.astype("datetime64[D]"),
        (month_end + pd.Timedelta(days=1)).values.astype("datetime64[D]"),
    ) - 1

    flag = ((tdom.to_numpy() <= window) | (to_end < window)).astype(float)
    return pd.DataFrame(
        {"turn_of_month": flag, "trading_day_of_month": tdom.astype(float).to_numpy()}, index=idx
    )


@indicator(
    "days_since_extreme",
    inputs=("close",),
    params={"period": 252},
    outputs=("days_since_high", "days_since_low"),
    min_periods=60,
    tags=("seasonality", "position"),
)
def days_since_extreme(df: pd.DataFrame, period: int = 252) -> pd.DataFrame:
    """Bars since the rolling high and low.

    A clean way to encode "how long has this been out of favour", which is
    orthogonal to the size of the move.
    """
    close = df["close"]
    win = period + 1

    def since_max(x: np.ndarray) -> float:
        return float(len(x) - 1 - int(np.argmax(x)))

    def since_min(x: np.ndarray) -> float:
        return float(len(x) - 1 - int(np.argmin(x)))

    return pd.DataFrame(
        {
            "days_since_high": close.rolling(win, min_periods=60).apply(since_max, raw=True),
            "days_since_low": close.rolling(win, min_periods=60).apply(since_min, raw=True),
        }
    )
