"""Cross-sectional derived features.

These are the features that only exist because you have a *universe*. A z-score
of RSI tells you nothing; a z-score of RSI against the other 4,999 names tells
you a lot. Everything here is computed per date across symbols, which is also
the only honest way to compare a NYSE mega cap with an AIM micro cap.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..engine import Context
from ..indicators._util import safe_div
from ..registry import derived
from ..schema import wide


def _grouped_z(series: pd.Series, by, limit: float = 3.0) -> pd.Series:
    """Winsorised z-score within groups, vectorised.

    Written with ``transform("mean")`` / ``transform("std")`` rather than
    ``transform(python_function)`` on purpose: at 5,000 symbols the Python-level
    version is two orders of magnitude slower and dominates a pipeline run.
    """
    g = series.groupby(by, group_keys=False)
    mu = g.transform("mean")
    sd = g.transform("std")  # ddof=1
    z = (series - mu) / sd.where(sd > 1e-12)
    return z.clip(-limit, limit)


def _grouped_rank(series: pd.Series, by) -> pd.Series:
    return series.groupby(by, group_keys=False).rank(pct=True, na_option="keep")


def _dates(obj: pd.Series | pd.DataFrame):
    return obj.index.get_level_values("date")


@derived(
    "cs_zscore",
    cross_sectional=True,
    params={"column": "close", "winsor": 3.0},
    outputs=("cs_zscore",),
    tags=("cross-sectional", "normalisation"),
)
def cs_zscore(panel: pd.DataFrame, ctx: Context, column: str = "close", winsor: float = 3.0) -> pd.DataFrame:
    """Winsorised cross-sectional z-score of any column, per date."""
    if column not in panel.columns:
        raise KeyError(f"cs_zscore: column {column!r} not in panel")
    z = _grouped_z(panel[column], _dates(panel), winsor)
    return z.to_frame("cs_zscore")


@derived(
    "cs_rank",
    cross_sectional=True,
    params={"column": "close"},
    outputs=("cs_rank",),
    tags=("cross-sectional", "normalisation"),
)
def cs_rank(panel: pd.DataFrame, ctx: Context, column: str = "close") -> pd.DataFrame:
    """Cross-sectional percentile rank, per date. Robust to fat tails."""
    if column not in panel.columns:
        raise KeyError(f"cs_rank: column {column!r} not in panel")
    return _grouped_rank(panel[column], _dates(panel)).to_frame("cs_rank")


@derived(
    "sector_neutral",
    cross_sectional=True,
    params={"column": "close", "group": "sector"},
    outputs=("sector_neutral",),
    tags=("cross-sectional", "normalisation", "factor"),
)
def sector_neutral(panel: pd.DataFrame, ctx: Context, column: str = "close", group: str = "sector") -> pd.DataFrame:
    """Demean a column within its sector (or country) each date.

    Without this, a "momentum" screen on a mixed universe is often just a bet
    on whichever sector ran. ``group`` may be 'sector', 'industry' or 'country'.
    """
    if column not in panel.columns:
        raise KeyError(f"sector_neutral: column {column!r} not in panel")
    syms = panel.index.get_level_values("symbol")
    getter = {"sector": ctx.sector_of, "country": ctx.country_of}.get(
        group, lambda s: (ctx.securities.get(s).industry if ctx.securities.get(s) else "") or "UNKNOWN"
    )
    # Resolve the group label once per distinct symbol, not once per row.
    lookup = {s: getter(s) for s in dict.fromkeys(syms)}
    labels = pd.Series([lookup[s] for s in syms], index=panel.index, name=group)
    out = _grouped_z(panel[column], [_dates(panel), labels])
    return out.to_frame("sector_neutral")


@derived(
    "market_beta",
    cross_sectional=True,
    params={"period": 252, "min_periods": 60, "price_column": "adj_close", "benchmark": ""},
    outputs=("market_beta", "market_alpha", "idio_vol", "r2_market"),
    lag=0,
    tags=("cross-sectional", "risk", "factor"),
)
def market_beta(
    panel: pd.DataFrame,
    ctx: Context,
    period: int = 252,
    min_periods: int = 60,
    price_column: str = "adj_close",
    benchmark: str = "",
) -> pd.DataFrame:
    """Rolling beta/alpha vs a benchmark, plus idiosyncratic vol and fit R2.

    If no benchmark is supplied, an equal-weighted index of the panel itself is
    used -- which is usually what you want for a cross-sectional model anyway,
    since it removes the common factor by construction.

    ``idio_vol`` (residual volatility) is the input to idiosyncratic-volatility
    and residual-momentum factors, both of which are better behaved than their
    raw equivalents.
    """
    px = wide(panel, price_column if price_column in panel.columns else "close")
    rets = np.log(px.where(px > 0)).diff()

    if benchmark and benchmark in rets.columns:
        bench = rets[benchmark]
    elif ctx.benchmark is not None:
        bench = np.log(ctx.benchmark.where(ctx.benchmark > 0)).diff().reindex(rets.index)
    else:
        bench = rets.mean(axis=1, skipna=True)

    mp = min(min_periods, period)
    bench_var = bench.rolling(period, min_periods=mp).var(ddof=1)
    bench_mean = bench.rolling(period, min_periods=mp).mean()

    betas, alphas, idios, r2s = {}, {}, {}, {}
    for col in rets.columns:
        r = rets[col]
        cov = r.rolling(period, min_periods=mp).cov(bench)
        beta = safe_div(cov, bench_var)
        alpha = r.rolling(period, min_periods=mp).mean() - beta * bench_mean
        resid = r - (alpha + beta * bench)
        idio = resid.rolling(period, min_periods=mp).std(ddof=1) * np.sqrt(252.0)
        var_r = r.rolling(period, min_periods=mp).var(ddof=1)
        r2 = safe_div(beta**2 * bench_var, var_r).clip(0, 1)
        betas[col], alphas[col], idios[col], r2s[col] = beta, alpha * 252.0, idio, r2

    def stack(d: dict[str, pd.Series], name: str) -> pd.Series:
        return pd.DataFrame(d).stack(future_stack=True).rename(name).rename_axis(["date", "symbol"])

    return pd.concat(
        [
            stack(betas, "market_beta"),
            stack(alphas, "market_alpha"),
            stack(idios, "idio_vol"),
            stack(r2s, "r2_market"),
        ],
        axis=1,
    )


@derived(
    "residual_momentum",
    cross_sectional=True,
    params={"lookback": 252, "skip": 21, "beta_period": 252, "price_column": "adj_close"},
    outputs=("residual_momentum",),
    tags=("cross-sectional", "factor", "momentum"),
)
def residual_momentum(
    panel: pd.DataFrame,
    ctx: Context,
    lookback: int = 252,
    skip: int = 21,
    beta_period: int = 252,
    price_column: str = "adj_close",
) -> pd.DataFrame:
    """Momentum of the market-residual return, standardised.

    Strips out the beta-driven part of a name's run, which is where most of
    plain momentum's crash risk lives. Historically the better-behaved sibling
    of 12-1 momentum.
    """
    px = wide(panel, price_column if price_column in panel.columns else "close")
    rets = np.log(px.where(px > 0)).diff()
    bench = rets.mean(axis=1, skipna=True)

    mp = min(60, beta_period)
    bvar = bench.rolling(beta_period, min_periods=mp).var(ddof=1)
    out = {}
    for col in rets.columns:
        r = rets[col]
        beta = safe_div(r.rolling(beta_period, min_periods=mp).cov(bench), bvar)
        resid = r - beta * bench
        cum = resid.rolling(lookback - skip, min_periods=(lookback - skip) // 2).sum().shift(skip)
        sd = resid.rolling(lookback, min_periods=mp).std(ddof=1) * np.sqrt(lookback - skip)
        out[col] = safe_div(cum, sd)
    return (
        pd.DataFrame(out)
        .stack(future_stack=True)
        .rename("residual_momentum")
        .rename_axis(["date", "symbol"])
        .to_frame()
    )


@derived(
    "relative_strength",
    cross_sectional=True,
    params={"period": 63, "price_column": "adj_close"},
    outputs=("relative_strength", "rs_rank"),
    tags=("cross-sectional", "momentum"),
)
def relative_strength(panel: pd.DataFrame, ctx: Context, period: int = 63, price_column: str = "adj_close") -> pd.DataFrame:
    """Return relative to the universe mean, and its percentile rank."""
    col = price_column if price_column in panel.columns else "close"
    px = wide(panel, col)
    r = px.pct_change(period)
    rel = r.sub(r.mean(axis=1, skipna=True), axis=0)
    rank = r.rank(axis=1, pct=True)
    return pd.concat(
        [
            rel.stack(future_stack=True).rename("relative_strength"),
            rank.stack(future_stack=True).rename("rs_rank"),
        ],
        axis=1,
    ).rename_axis(["date", "symbol"])


@derived(
    "correlation_to_market",
    cross_sectional=True,
    params={"period": 120, "price_column": "adj_close"},
    outputs=("correlation_to_market",),
    tags=("cross-sectional", "risk"),
)
def correlation_to_market(panel: pd.DataFrame, ctx: Context, period: int = 120, price_column: str = "adj_close") -> pd.DataFrame:
    """Rolling correlation with the equal-weighted universe.

    Low-correlation names are where diversification and genuinely idiosyncratic
    signals live.
    """
    col = price_column if price_column in panel.columns else "close"
    px = wide(panel, col)
    rets = np.log(px.where(px > 0)).diff()
    bench = rets.mean(axis=1, skipna=True)
    out = {c: rets[c].rolling(period, min_periods=period // 2).corr(bench) for c in rets.columns}
    return (
        pd.DataFrame(out)
        .stack(future_stack=True)
        .rename("correlation_to_market")
        .rename_axis(["date", "symbol"])
        .to_frame()
    )


@derived(
    "liquidity_tier",
    cross_sectional=True,
    params={"period": 20, "tiers": 5},
    outputs=("liquidity_tier", "adv_rank"),
    tags=("cross-sectional", "liquidity"),
)
def liquidity_tier(panel: pd.DataFrame, ctx: Context, period: int = 20, tiers: int = 5) -> pd.DataFrame:
    """Bucket the universe by traded value each date.

    Essential for a mixed NYSE/LSE universe: nearly every apparent anomaly in
    the bottom tier is an artefact of not being able to trade it.
    """
    value = (panel["close"] * panel["volume"]).rename("v")
    adv = value.groupby(level="symbol", group_keys=False).transform(
        lambda s: s.rolling(period, min_periods=1).mean()
    )
    rank = _grouped_rank(adv, _dates(panel))
    tier = np.ceil(rank * tiers).clip(1, tiers)
    return pd.DataFrame({"liquidity_tier": tier, "adv_rank": rank})
