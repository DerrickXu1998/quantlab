"""Macro conditioning features from FRED (US) and the Bank of England (UK).

Both are free, official and stable -- unlike every free equity feed. Macro
state is a cheap, high-value conditioning variable: the same signal behaves
very differently when the curve is inverted or credit spreads are widening.
"""
from __future__ import annotations

import logging

import pandas as pd

from ..engine import Context
from ..indicators._util import zscore
from ..registry import derived

log = logging.getLogger(__name__)

# FRED series that condition equity behaviour, all free.
FRED_SERIES = {
    "yield_curve_10y2y": "T10Y2Y",
    "credit_spread_hy": "BAMLH0A0HYM2",
    "vix": "VIXCLS",
    "real_rate_10y": "DFII10",
    "usd_index": "DTWEXBGS",
    "unemployment": "UNRATE",
}

# Bank of England IADB series codes.
BOE_SERIES = {
    "boe_bank_rate": "IUDBEDR",
    "gbp_usd": "XUDLUSS",
    "gbp_eur": "XUDLERS",
}


def _broadcast(series: pd.Series, panel: pd.DataFrame, name: str) -> pd.Series:
    dates = panel.index.get_level_values("date")
    return pd.Series(series.reindex(dates).to_numpy(), index=panel.index, name=name)


@derived(
    "macro_us",
    cross_sectional=True,
    params={"series": None, "zscore_period": 756},
    outputs=tuple(FRED_SERIES) + tuple(f"{k}_z" for k in FRED_SERIES),
    lag=1,
    tags=("macro", "external", "us"),
)
def macro_us(panel: pd.DataFrame, ctx: Context, series: dict | None = None, zscore_period: int = 756) -> pd.DataFrame:
    """US macro conditioning series and their 3-year z-scores.

    Levels are not comparable across decades; z-scores are. Both are returned
    so you can choose.
    """
    wanted = dict(series or FRED_SERIES)
    if panel.empty:
        return pd.DataFrame(index=panel.index)
    dates = panel.index.get_level_values("date")
    try:
        fred = ctx.provider("fred")
    except Exception as exc:
        log.warning("FRED provider unavailable: %s", exc)
        return pd.DataFrame(index=panel.index)

    cols: dict[str, pd.Series] = {}
    trading_days = pd.DatetimeIndex(sorted(set(dates)))
    for name, code in wanted.items():
        try:
            s = fred.series(code, start=dates.min(), end=dates.max())
        except Exception as exc:
            log.warning("FRED series %s unavailable: %s", code, exc)
            continue
        s = s.reindex(trading_days.union(s.index)).ffill().reindex(trading_days)
        cols[name] = _broadcast(s, panel, name)
        cols[f"{name}_z"] = _broadcast(zscore(s, min(zscore_period, max(60, len(s) // 2))), panel, f"{name}_z")
    return pd.DataFrame(cols, index=panel.index) if cols else pd.DataFrame(index=panel.index)


@derived(
    "macro_uk",
    cross_sectional=True,
    params={"series": None},
    outputs=tuple(BOE_SERIES),
    lag=1,
    tags=("macro", "external", "uk"),
)
def macro_uk(panel: pd.DataFrame, ctx: Context, series: dict | None = None) -> pd.DataFrame:
    """Bank of England Bank Rate and GBP crosses.

    ``gbp_usd`` doubles as the conversion rate you need to rank LSE names
    against NYSE names in one currency.
    """
    wanted = dict(series or BOE_SERIES)
    if panel.empty:
        return pd.DataFrame(index=panel.index)
    dates = panel.index.get_level_values("date")
    try:
        boe = ctx.provider("boe")
    except Exception as exc:
        log.warning("BoE provider unavailable: %s", exc)
        return pd.DataFrame(index=panel.index)

    trading_days = pd.DatetimeIndex(sorted(set(dates)))
    cols: dict[str, pd.Series] = {}
    try:
        frame = boe.series_batch(list(wanted.values()), start=dates.min(), end=dates.max())
    except Exception as exc:
        log.warning("BoE series unavailable: %s", exc)
        return pd.DataFrame(index=panel.index)

    for name, code in wanted.items():
        if code not in frame.columns:
            continue
        s = frame[code].reindex(trading_days.union(frame.index)).ffill().reindex(trading_days)
        cols[name] = _broadcast(s, panel, name)
    return pd.DataFrame(cols, index=panel.index) if cols else pd.DataFrame(index=panel.index)
