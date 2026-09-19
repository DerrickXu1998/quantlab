"""Currency and unit normalisation.

The single most common silent bug in cross-listed NYSE/LSE analytics is the
London pence problem: most LSE lines quote in GBX (pence), a few in GBP, and
some in USD or EUR. Mixing them produces price ratios off by 100x, which
quietly poisons every cross-sectional factor downstream.

quantlab therefore keeps prices in their *native* quote unit and records the
unit explicitly, then converts only at the point where cross-currency
comparison is actually needed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import Currency, Security

# Heuristic threshold: a London line trading above this in "pounds" is almost
# certainly quoted in pence. Used only when metadata does not tell us.
GBX_PRICE_HEURISTIC = 25.0

MINOR_UNIT_DIVISOR = {Currency.GBX: 100.0}


def infer_quote_currency(symbol: str, bars: pd.DataFrame, declared: Currency | None = None) -> Currency:
    """Best-effort determination of the quote unit for a price series."""
    if declared is not None and declared is not Currency.GBP:
        return declared
    suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
    if suffix in {"L", "LON", "LSE", "UK"}:
        if bars is None or bars.empty:
            return Currency.GBX
        median = float(pd.to_numeric(bars["close"], errors="coerce").median())
        if not np.isfinite(median):
            return Currency.GBX
        return Currency.GBX if median > GBX_PRICE_HEURISTIC else Currency.GBP
    return declared or Currency.USD


def to_major_units(bars: pd.DataFrame, currency: Currency) -> pd.DataFrame:
    """GBX -> GBP. Volume and any non-price column is left alone."""
    div = MINOR_UNIT_DIVISOR.get(currency)
    if not div:
        return bars
    out = bars.copy()
    for col in ("open", "high", "low", "close", "adj_close", "vwap"):
        if col in out.columns:
            out[col] = out[col] / div
    return out


def convert(
    bars: pd.DataFrame,
    from_ccy: Currency,
    to_ccy: Currency,
    rates: pd.Series | float,
) -> pd.DataFrame:
    """Convert price columns. `rates` is units of `to_ccy` per 1 unit of `from_ccy`."""
    out = to_major_units(bars, from_ccy)
    base = Currency.GBP if from_ccy is Currency.GBX else from_ccy
    if base is to_ccy:
        return out
    if isinstance(rates, pd.Series):
        r = rates.reindex(out.index).ffill()
    else:
        r = pd.Series(float(rates), index=out.index)
    for col in ("open", "high", "low", "close", "adj_close", "vwap"):
        if col in out.columns:
            out[col] = out[col] * r
    return out


def normalise_panel(
    frames: dict[str, pd.DataFrame],
    securities: dict[str, Security] | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, Currency]]:
    """Put every symbol into major units and report what each was quoted in."""
    securities = securities or {}
    out: dict[str, pd.DataFrame] = {}
    units: dict[str, Currency] = {}
    for sym, df in frames.items():
        declared = securities[sym].currency if sym in securities else None
        ccy = infer_quote_currency(sym, df, declared)
        units[sym] = ccy
        out[sym] = to_major_units(df, ccy)
    return out, units
