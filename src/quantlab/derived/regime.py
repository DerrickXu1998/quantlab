"""Market-wide regime and breadth features.

Breadth is free: it is computed from the panel you already have. It is also
one of the few genuinely additive signals you can build without paying for
data, because it describes the market's internal state rather than any one
name's.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..engine import Context
from ..indicators._util import safe_div
from ..registry import derived
from ..schema import wide


def _broadcast(series: pd.Series, panel: pd.DataFrame, name: str) -> pd.DataFrame:
    """Attach a per-date market series to every row of the panel."""
    dates = panel.index.get_level_values("date")
    return pd.DataFrame({name: series.reindex(dates).to_numpy()}, index=panel.index)


@derived(
    "breadth",
    cross_sectional=True,
    params={"ma_period": 200, "price_column": "adj_close"},
    outputs=("breadth_above_ma", "breadth_advancing", "breadth_new_highs", "breadth_mcclellan"),
    tags=("regime", "breadth", "market"),
)
def breadth(panel: pd.DataFrame, ctx: Context, ma_period: int = 200, price_column: str = "adj_close") -> pd.DataFrame:
    """Four classic breadth measures, computed across the whole panel.

    * ``breadth_above_ma``   -- fraction of the universe above its long MA
    * ``breadth_advancing``  -- fraction up on the day
    * ``breadth_new_highs``  -- new 52w highs minus new lows, as a fraction
    * ``breadth_mcclellan``  -- McClellan oscillator (19/39 EMA of net advances)

    Divergence between price and breadth is the classic late-cycle tell.
    """
    col = price_column if price_column in panel.columns else "close"
    px = wide(panel, col)
    if px.empty:
        return pd.DataFrame(index=panel.index)

    ma = px.rolling(ma_period, min_periods=max(20, ma_period // 4)).mean()
    above = (px > ma).where(ma.notna()).mean(axis=1, skipna=True)

    chg = px.diff()
    adv = (chg > 0).where(chg.notna())
    advancing = adv.mean(axis=1, skipna=True)

    hi = px.rolling(252, min_periods=60).max()
    lo = px.rolling(252, min_periods=60).min()
    new_high = (px >= hi).where(hi.notna()).mean(axis=1, skipna=True)
    new_low = (px <= lo).where(lo.notna()).mean(axis=1, skipna=True)

    net = advancing - (1.0 - advancing)
    mcclellan = net.ewm(span=19, adjust=False).mean() - net.ewm(span=39, adjust=False).mean()

    parts = {
        "breadth_above_ma": above,
        "breadth_advancing": advancing,
        "breadth_new_highs": new_high - new_low,
        "breadth_mcclellan": mcclellan * 1000.0,
    }
    return pd.concat([_broadcast(s, panel, n) for n, s in parts.items()], axis=1)


@derived(
    "market_regime",
    cross_sectional=True,
    params={"vol_period": 20, "vol_lookback": 252, "trend_period": 200, "price_column": "adj_close"},
    outputs=("market_vol", "market_vol_pct", "market_trend", "regime_label"),
    tags=("regime", "market"),
)
def market_regime(
    panel: pd.DataFrame,
    ctx: Context,
    vol_period: int = 20,
    vol_lookback: int = 252,
    trend_period: int = 200,
    price_column: str = "adj_close",
) -> pd.DataFrame:
    """A simple, honest 2x2 regime classification.

    Volatility percentile (low/high) crossed with trend (up/down) gives four
    regimes coded 0-3. Crude, but it beats a single trailing average, and
    conditioning any signal on it is usually worth more than adding another
    oscillator.

    Codes: 0 = quiet uptrend, 1 = quiet downtrend, 2 = volatile uptrend,
    3 = volatile downtrend.
    """
    col = price_column if price_column in panel.columns else "close"
    px = wide(panel, col)
    if px.empty:
        return pd.DataFrame(index=panel.index)

    index_level = px.div(px.bfill().iloc[0]).mean(axis=1, skipna=True)
    r = np.log(index_level.where(index_level > 0)).diff()

    vol = r.rolling(vol_period, min_periods=max(5, vol_period // 2)).std(ddof=1) * np.sqrt(252.0)
    vol_pct = vol.rolling(vol_lookback, min_periods=60).rank(pct=True)
    trend = index_level - index_level.rolling(trend_period, min_periods=max(20, trend_period // 4)).mean()

    up = (trend > 0).astype(float)
    volatile = (vol_pct > 0.5).astype(float)
    label = (2 * volatile + (1 - up)).where(vol_pct.notna() & trend.notna())

    parts = {
        "market_vol": vol,
        "market_vol_pct": vol_pct,
        "market_trend": trend,
        "regime_label": label,
    }
    return pd.concat([_broadcast(s, panel, n) for n, s in parts.items()], axis=1)


@derived(
    "dispersion",
    cross_sectional=True,
    params={"period": 20, "price_column": "adj_close"},
    outputs=("cs_dispersion", "avg_pairwise_corr"),
    tags=("regime", "market"),
)
def dispersion(panel: pd.DataFrame, ctx: Context, period: int = 20, price_column: str = "adj_close") -> pd.DataFrame:
    """Cross-sectional return dispersion and implied average pairwise correlation.

    High dispersion / low correlation is a stock-pickers' market and the
    environment where single-name signals actually pay. When correlation spikes
    toward 1, everything is one trade and your factor model is not adding much.

    The correlation estimate uses the standard identity
    ``var(index) = mean(var) * (rho + (1-rho)/n)``, solved for rho -- far
    cheaper than an n x n rolling correlation matrix.
    """
    col = price_column if price_column in panel.columns else "close"
    px = wide(panel, col)
    if px.empty:
        return pd.DataFrame(index=panel.index)

    rets = np.log(px.where(px > 0)).diff()
    disp = rets.std(axis=1, ddof=1, skipna=True)

    mp = max(5, period // 2)
    var_i = rets.rolling(period, min_periods=mp).var(ddof=1)
    mean_var = var_i.mean(axis=1, skipna=True)
    index_ret = rets.mean(axis=1, skipna=True)
    var_index = index_ret.rolling(period, min_periods=mp).var(ddof=1)
    n = rets.notna().sum(axis=1).replace(0, np.nan)

    ratio = safe_div(var_index, mean_var)
    rho = ((ratio * n) - 1.0) / (n - 1.0)
    rho = rho.clip(-1.0, 1.0)

    return pd.concat(
        [_broadcast(disp, panel, "cs_dispersion"), _broadcast(rho, panel, "avg_pairwise_corr")],
        axis=1,
    )
