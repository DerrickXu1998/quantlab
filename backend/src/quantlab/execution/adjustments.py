"""Splits and dividends: adjusted prices for signals, events for execution.

Stored bars are unadjusted and stay that way -- they are what actually traded,
and restating hundreds of millions of rows every time a dividend goes ex would
also destroy them. Adjustment happens here, when a run reads them, and in two
different ways for two different consumers:

* **Signals** read back-adjusted bars. Every bar before an ex-date is scaled so
  the series is continuous across it: a 20-for-1 split no longer reads as a 95%
  crash to a moving average, and a dividend no longer as a small down day.
* **Execution** trades the raw prices and is told about each action as an
  event (:class:`ExecutionSimulator` applies them): a split multiplies the
  shares held, a dividend pays or charges cash. That is what a brokerage
  account experiences, and it keeps fills, stops and commissions at prices
  that actually traded.

Point-in-time: factors are anchored at the last bar supplied, which the runner
loads up to the run's end date, and only actions on or before that bar are
applied. A 2021 backtest therefore never sees a 2024 dividend -- unlike a
vendor's adjusted close, which is restated as of the day it was fetched.

Pure computation: no I/O, no wall clock (Constitution VI).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from quantlab.execution.bars import BarSeries, first_at_or_after

#: What a run may ask for. ``none`` is the behaviour that predates this module.
PRICE_ADJUSTMENT: tuple[str, ...] = ("split_dividend", "split", "none")


@dataclass(frozen=True)
class CorporateAction:
    ex_date: str
    #: "split" or "dividend".
    action_type: str
    #: New shares per old share: 20.0 for a 20-for-1 split, 0.1 for a 1-for-10
    #: reverse split. Spin-offs arrive from the vendor as a split with a small
    #: ratio (IBM's 2021 Kyndryl spin-off is ~1.046) and are applied the same
    #: way, which approximates receiving the spun-off shares.
    split_ratio: float | None = None
    #: Cash per share, in the currency and share count of the ex-date.
    dividend: float | None = None

    @property
    def is_split(self) -> bool:
        return self.action_type == "split" and bool(self.split_ratio) and self.split_ratio > 0

    @property
    def is_dividend(self) -> bool:
        return self.action_type != "split" and bool(self.dividend) and self.dividend > 0


@dataclass(frozen=True)
class AdjustedBar:
    """A bar as signals see it, plus the close that actually traded.

    ``raw_close`` is for anything that multiplies a price by a per-share figure
    as filed -- market cap from ``shares_outstanding`` in the valuation gates.
    Those filings are in the share count of their own day, so pairing them with
    a price restated for a later split would understate the cap by its ratio.
    """

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    raw_close: float


def raw_close(bar: Any) -> float:
    """The traded close of any bar, adjusted or not."""
    return float(getattr(bar, "raw_close", bar.close))


def applies(action: CorporateAction, mode: str) -> bool:
    """Whether ``mode`` adjusts for this action at all."""
    if mode == "split_dividend":
        return action.is_split or action.is_dividend
    if mode == "split":
        return action.is_split
    return False


def by_symbol(
    actions: list[dict] | None, mode: str, end: str | None = None
) -> dict[str, list[CorporateAction]]:
    """Group the backend's action rows by symbol, keeping what ``mode`` applies.

    Actions after ``end`` are dropped: a run must not be adjusted for an event
    that had not happened by its last session.
    """
    out: dict[str, list[CorporateAction]] = {}
    if mode == "none":
        return out
    for row in actions or []:
        action = CorporateAction(
            ex_date=str(row["ex_date"])[:10],
            action_type=row["action_type"],
            split_ratio=row.get("split_ratio"),
            dividend=row.get("dividend"),
        )
        if end is not None and action.ex_date > end:
            continue
        if applies(action, mode):
            out.setdefault(row["symbol"], []).append(action)
    for items in out.values():
        items.sort(key=lambda a: (a.ex_date, a.action_type))
    return out


def factors(bars: Any, actions: list[CorporateAction]) -> tuple[Any, Any]:
    """Per-bar multipliers that back-adjust ``bars`` for ``actions``.

    Returns ``(price, volume)``: adjusted price = raw x price[i], adjusted
    volume = raw x volume[i]. Both are 1.0 on and after the last action, so the
    final bar keeps the price that actually traded.

    A split with ratio r divides every earlier price by r and multiplies every
    earlier volume by r. A dividend D divides every earlier price by
    ``close_before / (close_before - D)`` -- the standard (CRSP) total-return
    factor, using the raw close of the session before the ex-date. A dividend
    with no earlier bar, or one at least as large as that close, is skipped
    rather than allowed to produce a zero or negative price.
    """
    n = len(bars)
    columnar = isinstance(bars, BarSeries)
    price = np.ones(n)
    volume = np.ones(n)
    if n and actions:
        for action in actions:
            # First bar on or after the ex-date; everything before it is
            # adjusted. For intraday bars that is the session's first bar.
            cut = first_at_or_after(bars, action.ex_date)
            if cut == 0 or cut >= n:
                # Nothing before it in this series, or not in force by the last bar.
                continue
            if action.is_split:
                ratio = float(action.split_ratio)
                price[:cut] /= ratio
                volume[:cut] *= ratio
            elif action.is_dividend:
                before = float(bars[cut - 1].close)
                dividend = float(action.dividend)
                if before <= 0 or dividend >= before:
                    continue
                price[:cut] *= (before - dividend) / before
    # Columns for a BarSeries; plain lists for a list of bars, as before.
    return (price, volume) if columnar else (price.tolist(), volume.tolist())


def adjust(bars: list[Any], actions: list[CorporateAction]) -> list[Any]:
    """``bars`` back-adjusted for ``actions``; the input is not modified.

    A series with nothing to adjust comes back as the same bars. One with
    anything to adjust comes back entirely as :class:`AdjustedBar`, so every
    bar in it answers ``raw_close`` the same way.
    """
    if isinstance(bars, BarSeries):
        if not actions:
            return bars
        price, volume = factors(bars, actions)
        if (price == 1.0).all() and (volume == 1.0).all():
            return bars
        return bars.scaled(price, volume)
    if not actions:
        return list(bars)
    price, volume = factors(bars, actions)
    if all(p == 1.0 for p in price) and all(v == 1.0 for v in volume):
        return list(bars)
    return [
        AdjustedBar(
            date=bar.date,
            open=float(bar.open) * p,
            high=float(bar.high) * p,
            low=float(bar.low) * p,
            close=float(bar.close) * p,
            volume=round(float(bar.volume) * v),
            raw_close=float(bar.close),
        )
        for bar, p, v in zip(bars, price, volume, strict=True)
    ]


def adjust_all(
    bars_by_symbol: dict[str, list[Any]], actions_by_symbol: dict[str, list[CorporateAction]]
) -> dict[str, list[Any]]:
    return {
        symbol: adjust(bars, actions_by_symbol.get(symbol, []))
        for symbol, bars in bars_by_symbol.items()
    }
