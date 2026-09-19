"""Insider transactions from SEC Form 3/4/5 bulk datasets (US only).

The UK equivalent (PDMR dealings under MAR Article 19) is published only via
RNS, with no free structured feed -- see docs/DATA_SOURCES.md. That asymmetry
is worth knowing before you build a strategy that assumes symmetry.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..engine import Context
from ..indicators._util import safe_div
from ..registry import derived

log = logging.getLogger(__name__)


@derived(
    "insider_activity",
    cross_sectional=True,
    params={"window": 90, "min_transactions": 1},
    outputs=("insider_net_shares", "insider_buy_ratio", "insider_transaction_count", "insider_cluster_buy"),
    lag=2,
    tags=("insider", "alternative-data", "us", "external"),
)
def insider_activity(panel: pd.DataFrame, ctx: Context, window: int = 90, min_transactions: int = 1) -> pd.DataFrame:
    """Rolling insider buying and selling from Form 4 filings.

    Signal notes worth respecting:

    * **Sales are mostly noise.** Insiders sell for liquidity, tax and 10b5-1
      plans. Buys are the informative side, which is why ``insider_buy_ratio``
      is separated from net shares.
    * **Clusters beat individuals.** Several distinct insiders buying inside
      the same window is the documented effect; one director topping up is not.
      ``insider_cluster_buy`` counts distinct buyers.
    * ``lag=2`` reflects the two-business-day Form 4 filing deadline.
    """
    if panel.empty:
        return pd.DataFrame(index=panel.index)

    symbols = sorted(set(panel.index.get_level_values("symbol")))
    us = [s for s in symbols if ctx.country_of(s) == "US"]
    empty = pd.DataFrame(
        index=panel.index,
        columns=["insider_net_shares", "insider_buy_ratio",
                 "insider_transaction_count", "insider_cluster_buy"],
        dtype=float,
    )
    if not us:
        return empty

    dates = panel.index.get_level_values("date")
    try:
        tx = ctx.provider("sec_edgar").insider_transactions(
            us, start=dates.min(), end=dates.max(), ctx=ctx
        )
    except Exception as exc:
        log.warning("insider data unavailable: %s", exc)
        return empty
    if tx is None or tx.empty:
        return empty

    # tx columns: date, symbol, owner, shares, is_acquisition
    tx = tx.copy()
    tx["signed"] = np.where(tx["is_acquisition"], tx["shares"], -tx["shares"])
    tx["is_buy"] = tx["is_acquisition"].astype(float)

    daily = tx.groupby(["date", "symbol"]).agg(
        net=("signed", "sum"),
        buys=("is_buy", "sum"),
        n=("signed", "size"),
        buyers=("owner", lambda s: s[tx.loc[s.index, "is_acquisition"]].nunique()),
    )

    out = daily.reindex(panel.index).fillna(0.0)
    grp = out.groupby(level="symbol", group_keys=False)
    rolled = pd.DataFrame(
        {
            "insider_net_shares": grp["net"].transform(lambda s: s.rolling(window, min_periods=1).sum()),
            "insider_transaction_count": grp["n"].transform(lambda s: s.rolling(window, min_periods=1).sum()),
            "_buys": grp["buys"].transform(lambda s: s.rolling(window, min_periods=1).sum()),
            "insider_cluster_buy": grp["buyers"].transform(lambda s: s.rolling(window, min_periods=1).max()),
        }
    )
    rolled["insider_buy_ratio"] = safe_div(rolled["_buys"], rolled["insider_transaction_count"])
    rolled = rolled.where(rolled["insider_transaction_count"] >= min_transactions)
    return rolled[
        ["insider_net_shares", "insider_buy_ratio", "insider_transaction_count", "insider_cluster_buy"]
    ]
