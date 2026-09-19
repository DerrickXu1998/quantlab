"""Fundamentals-derived features.

Prices are the easy half. These features come from SEC XBRL (US) and
Companies House iXBRL (UK) and are what turn a chart package into a quant
platform.

**Point-in-time discipline.** Every fundamental feature here is stamped at the
filing/acceptance date, never the fiscal period end. A 2024-Q4 number was not
knowable in December 2024; it was knowable when the 10-K was accepted in
February 2025. Getting this wrong is the single most common way backtests
produce fictitious alpha, so the plugins carry an explicit ``lag`` and the
providers return acceptance dates.
"""
from __future__ import annotations

import logging

import pandas as pd

from ..engine import Context
from ..indicators._util import safe_div
from ..registry import derived

log = logging.getLogger(__name__)


def _align_pit(facts: pd.DataFrame, panel: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Forward-fill filed fundamentals onto trading dates, per symbol.

    ``facts`` must be indexed by (filed_date, symbol) -- the date the number
    became public, not the period it describes.
    """
    if facts.empty:
        return pd.DataFrame(index=panel.index, columns=columns, dtype=float)
    facts = facts.sort_index()
    out = facts.reindex(panel.index.union(facts.index)).sort_index()
    out = out.groupby(level="symbol", group_keys=False).ffill()
    return out.reindex(panel.index)[columns]


def _fetch_facts(ctx: Context, symbols: list[str], concepts: list[str]) -> pd.DataFrame:
    """Pull fundamentals from whichever provider covers each symbol's market."""
    frames = []
    us = [s for s in symbols if ctx.country_of(s) == "US"]
    gb = [s for s in symbols if ctx.country_of(s) == "GB"]
    if us:
        try:
            frames.append(ctx.provider("sec_edgar").fundamentals(us, concepts, ctx=ctx))
        except Exception as exc:
            log.warning("SEC fundamentals unavailable: %s", exc)
    if gb:
        try:
            frames.append(ctx.provider("companies_house").fundamentals(gb, concepts, ctx=ctx))
        except Exception as exc:
            log.warning("Companies House fundamentals unavailable: %s", exc)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_index()


# Canonical concept names. Providers map their own vocabulary onto these, so a
# feature never has to know whether it is reading us-gaap or UK GAAP tags.
CORE_CONCEPTS = [
    "revenue", "net_income", "operating_income", "gross_profit",
    "total_assets", "total_liabilities", "equity", "cash",
    "current_assets", "current_liabilities", "long_term_debt",
    "operating_cash_flow", "capex", "shares_outstanding",
]


@derived(
    "valuation",
    cross_sectional=True,
    params={},
    outputs=("market_cap", "pe_ratio", "pb_ratio", "ps_ratio", "ev_ebit", "fcf_yield", "earnings_yield"),
    lag=1,
    tags=("fundamentals", "value", "external"),
)
def valuation(panel: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    """Point-in-time valuation multiples.

    Built from the *filed* fundamentals joined to daily prices, so the ratio
    changes every day with price but only steps when a new filing lands --
    which is how a real point-in-time value factor behaves.
    """
    symbols = sorted(set(panel.index.get_level_values("symbol")))
    facts = _fetch_facts(ctx, symbols, CORE_CONCEPTS)
    cols = ["net_income", "equity", "revenue", "shares_outstanding",
            "operating_income", "total_liabilities", "cash",
            "operating_cash_flow", "capex"]
    f = _align_pit(facts, panel, cols)

    price = panel["close"]
    shares = f["shares_outstanding"]
    mcap = price * shares
    ev = mcap + f["total_liabilities"] - f["cash"]
    fcf = f["operating_cash_flow"] - f["capex"].abs()

    return pd.DataFrame(
        {
            "market_cap": mcap,
            "pe_ratio": safe_div(mcap, f["net_income"]),
            "pb_ratio": safe_div(mcap, f["equity"]),
            "ps_ratio": safe_div(mcap, f["revenue"]),
            "ev_ebit": safe_div(ev, f["operating_income"]),
            "fcf_yield": safe_div(fcf, mcap),
            "earnings_yield": safe_div(f["net_income"], mcap),
        },
        index=panel.index,
    )


@derived(
    "quality",
    cross_sectional=True,
    params={},
    outputs=("roe", "roa", "gross_margin", "accruals", "leverage", "current_ratio", "asset_turnover"),
    lag=1,
    tags=("fundamentals", "quality", "external"),
)
def quality(panel: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    """Profitability, efficiency and balance-sheet quality ratios.

    ``accruals`` (the gap between accounting earnings and cash flow) is the one
    to watch: high accruals reliably predict disappointment, and it is free.
    """
    symbols = sorted(set(panel.index.get_level_values("symbol")))
    facts = _fetch_facts(ctx, symbols, CORE_CONCEPTS)
    cols = ["net_income", "equity", "total_assets", "revenue", "gross_profit",
            "operating_cash_flow", "total_liabilities", "current_assets",
            "current_liabilities"]
    f = _align_pit(facts, panel, cols)

    return pd.DataFrame(
        {
            "roe": safe_div(f["net_income"], f["equity"]),
            "roa": safe_div(f["net_income"], f["total_assets"]),
            "gross_margin": safe_div(f["gross_profit"], f["revenue"]),
            "accruals": safe_div(f["net_income"] - f["operating_cash_flow"], f["total_assets"]),
            "leverage": safe_div(f["total_liabilities"], f["equity"]),
            "current_ratio": safe_div(f["current_assets"], f["current_liabilities"]),
            "asset_turnover": safe_div(f["revenue"], f["total_assets"]),
        },
        index=panel.index,
    )


@derived(
    "piotroski_f",
    cross_sectional=True,
    params={},
    outputs=("piotroski_f",),
    lag=1,
    tags=("fundamentals", "quality", "composite", "external"),
)
def piotroski_f(panel: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    """Piotroski F-Score (0-9): nine binary accounting health tests.

    Cheap to compute from free filings and still one of the better-documented
    quality screens, especially on small caps -- which is most of what a free
    NYSE+LSE universe actually contains.
    """
    symbols = sorted(set(panel.index.get_level_values("symbol")))
    facts = _fetch_facts(ctx, symbols, CORE_CONCEPTS)
    cols = ["net_income", "operating_cash_flow", "total_assets", "long_term_debt",
            "current_assets", "current_liabilities", "shares_outstanding",
            "gross_profit", "revenue"]
    f = _align_pit(facts, panel, cols)

    def yoy(col: str) -> pd.Series:
        return f[col].groupby(level="symbol", group_keys=False).diff(252)

    roa = safe_div(f["net_income"], f["total_assets"])
    cfo = safe_div(f["operating_cash_flow"], f["total_assets"])
    gm = safe_div(f["gross_profit"], f["revenue"])
    turnover = safe_div(f["revenue"], f["total_assets"])
    current = safe_div(f["current_assets"], f["current_liabilities"])
    lev = safe_div(f["long_term_debt"], f["total_assets"])

    tests = [
        roa > 0,
        cfo > 0,
        roa.groupby(level="symbol", group_keys=False).diff(252) > 0,
        cfo > roa,                                        # accruals quality
        lev.groupby(level="symbol", group_keys=False).diff(252) < 0,
        current.groupby(level="symbol", group_keys=False).diff(252) > 0,
        yoy("shares_outstanding") <= 0,                   # no dilution
        gm.groupby(level="symbol", group_keys=False).diff(252) > 0,
        turnover.groupby(level="symbol", group_keys=False).diff(252) > 0,
    ]
    known = roa.notna()
    score = sum(t.astype(float) for t in tests)
    return score.where(known).to_frame("piotroski_f")


@derived(
    "altman_z",
    cross_sectional=True,
    params={},
    outputs=("altman_z",),
    lag=1,
    tags=("fundamentals", "risk", "composite", "external"),
)
def altman_z(panel: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    """Altman Z-Score for distress risk. Below ~1.8 is the distress zone.

    Useful as a *filter* rather than a signal: cheap-and-distressed is the
    classic value trap, and this is the free way to separate the two.
    """
    symbols = sorted(set(panel.index.get_level_values("symbol")))
    facts = _fetch_facts(ctx, symbols, CORE_CONCEPTS)
    cols = ["current_assets", "current_liabilities", "total_assets", "total_liabilities",
            "operating_income", "revenue", "equity", "shares_outstanding", "net_income"]
    f = _align_pit(facts, panel, cols)

    ta = f["total_assets"]
    working_capital = f["current_assets"] - f["current_liabilities"]
    mcap = panel["close"] * f["shares_outstanding"]
    retained_proxy = f["equity"] - (f["shares_outstanding"] * 0.0)  # equity as RE proxy

    z = (
        1.2 * safe_div(working_capital, ta)
        + 1.4 * safe_div(retained_proxy, ta)
        + 3.3 * safe_div(f["operating_income"], ta)
        + 0.6 * safe_div(mcap, f["total_liabilities"])
        + 1.0 * safe_div(f["revenue"], ta)
    )
    return z.to_frame("altman_z")


@derived(
    "fundamental_momentum",
    cross_sectional=True,
    params={"period": 252},
    outputs=("revenue_growth", "earnings_growth", "margin_trend"),
    lag=1,
    tags=("fundamentals", "growth", "external"),
)
def fundamental_momentum(panel: pd.DataFrame, ctx: Context, period: int = 252) -> pd.DataFrame:
    """Year-on-year growth in revenue, earnings and margin.

    Fundamental momentum is distinct from price momentum and adds information
    to it -- the two disagree often enough to be worth measuring separately.
    """
    symbols = sorted(set(panel.index.get_level_values("symbol")))
    facts = _fetch_facts(ctx, symbols, CORE_CONCEPTS)
    f = _align_pit(facts, panel, ["revenue", "net_income", "operating_income"])

    def growth(col: str) -> pd.Series:
        s = f[col]
        prior = s.groupby(level="symbol", group_keys=False).shift(period)
        return safe_div(s - prior, prior.abs())

    margin = safe_div(f["operating_income"], f["revenue"])
    return pd.DataFrame(
        {
            "revenue_growth": growth("revenue"),
            "earnings_growth": growth("net_income"),
            "margin_trend": margin.groupby(level="symbol", group_keys=False).diff(period),
        },
        index=panel.index,
    )
