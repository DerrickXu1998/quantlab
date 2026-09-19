"""An example third-party plugin.

Shows all three extension points:

* a **per-symbol indicator** -- gets one symbol's bars, returns a Series
* a **multi-output indicator** -- returns a DataFrame matching `outputs`
* a **cross-sectional derived feature** -- gets the whole panel plus a Context

Install with ``pip install -e .`` from this directory, then::

    quantlab list indicators --tag custom
    quantlab compute --features vwap_reversion regime_scaled_momentum \\
        --symbols AAPL.US HSBA.LON
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab.registry import derived, indicator

_REGISTERED = False


def register_all() -> None:
    """Entry point target. Must be idempotent -- it can be called more than once."""
    global _REGISTERED
    if _REGISTERED:
        return
    _register_indicators()
    _register_derived()
    _REGISTERED = True


def _register_indicators() -> None:
    @indicator(
        "vwap_reversion",
        params={"period": 20, "vol_period": 20},
        inputs=("high", "low", "close", "volume"),
        min_periods=25,
        tags=("custom", "mean-reversion"),
    )
    def vwap_reversion(df: pd.DataFrame, period: int = 20, vol_period: int = 20) -> pd.Series:
        """Distance from rolling VWAP, scaled by realised volatility.

        Scaling by volatility is what makes the number comparable between a
        quiet utility and a volatile miner -- and between markets.
        """
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        pv = (tp * df["volume"]).rolling(period, min_periods=period).sum()
        vol = df["volume"].rolling(period, min_periods=period).sum()
        vwap = pv / vol.where(vol > 0)
        sigma = np.log(df["close"]).diff().rolling(vol_period, min_periods=vol_period).std(ddof=1)
        return ((df["close"] - vwap) / vwap) / sigma.where(sigma > 0)

    @indicator(
        "range_position",
        params={"period": 60},
        inputs=("high", "low", "close"),
        outputs=("range_pos", "range_width"),
        min_periods=60,
        tags=("custom", "position"),
    )
    def range_position(df: pd.DataFrame, period: int = 60) -> pd.DataFrame:
        """Where in its recent range price sits, and how wide that range is."""
        hi = df["high"].rolling(period, min_periods=period).max()
        lo = df["low"].rolling(period, min_periods=period).min()
        span = (hi - lo).where(hi > lo)
        return pd.DataFrame({"range_pos": (df["close"] - lo) / span, "range_width": span / df["close"]})


def _register_derived() -> None:
    @derived(
        "regime_scaled_momentum",
        cross_sectional=True,
        params={"period": 63, "vol_period": 20},
        outputs=("regime_scaled_momentum",),
        tags=("custom", "cross-sectional", "momentum"),
    )
    def regime_scaled_momentum(panel: pd.DataFrame, ctx, period: int = 63, vol_period: int = 20):
        """Cross-sectional momentum rank, damped when the market is volatile.

        Demonstrates the two things a cross-sectional plugin can do that a
        per-symbol one cannot: see every name on a date, and read the Context
        for reference data.
        """
        close = panel["close"]
        by_symbol = close.groupby(level="symbol", group_keys=False)
        mom = by_symbol.pct_change(period)
        vol = by_symbol.transform(
            lambda s: np.log(s).diff().rolling(vol_period, min_periods=vol_period).std(ddof=1)
        )
        risk_adjusted = mom / vol.where(vol > 0)

        dates = panel.index.get_level_values("date")
        rank = risk_adjusted.groupby(dates, group_keys=False).rank(pct=True)

        market_vol = vol.groupby(dates).transform("median")
        damping = 1.0 / (1.0 + market_vol.rank(pct=True))
        return ((rank - 0.5) * damping).to_frame("regime_scaled_momentum")
