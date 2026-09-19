"""Stooq -- the free-data backbone.

Why it goes first: no key, no registration, no symbol cap, deep daily history,
and -- uniquely among genuinely free sources -- it covers **both** US (``.us``)
and UK (``.uk``) listings from the same endpoint.

Caveats you should take seriously:
  * Stooq publishes no rate limit and no terms of use. Treat access as a
    courtesy, not a right; the default limiter here is deliberately gentle.
  * Coverage of thin AIM names is patchy and occasionally has bad ticks.
  * London prices come back in pence (GBX). ``quantlab.fx`` handles the
    conversion -- do not skip it.
"""
from __future__ import annotations

import io

import pandas as pd

from ..registry import provider
from ..schema import Currency, DataUnavailable, Security
from .base import DataProvider, map_suffix

BASE = "https://stooq.com/q/d/l/"
INTERVAL = {"1d": "d", "1wk": "w", "1mo": "m", "1h": "60", "5m": "5"}


@provider("stooq")
class StooqProvider(DataProvider):
    name = "stooq"
    supports = ("US", "LON", "L", "UK")
    requires_key = False
    licence_note = (
        "No published terms or rate limit. Personal research use; do not redistribute."
    )

    def __init__(self, **opts):
        super().__init__(**opts)
        from ..http import HttpClient

        self.client = HttpClient("stooq")

    def to_native(self, symbol: str) -> str:
        return map_suffix(symbol, "stooq").lower()

    def fetch_one(self, symbol: str, start: str, end: str, frequency: str = "1d") -> pd.DataFrame:
        params = {"s": self.to_native(symbol), "i": INTERVAL.get(frequency, "d")}
        if start:
            params["d1"] = pd.Timestamp(start).strftime("%Y%m%d")
        if end:
            params["d2"] = pd.Timestamp(end).strftime("%Y%m%d")

        text = self.client.get_text(BASE, params=params)
        head = text[:64].lstrip().lower()
        if not head.startswith("date") or "no data" in head:
            raise DataUnavailable(f"stooq: no data for {symbol}")

        df = pd.read_csv(io.StringIO(text))
        df.columns = [c.strip().lower() for c in df.columns]
        if "date" not in df.columns:
            raise DataUnavailable(f"stooq: unexpected payload for {symbol}")
        df = df.set_index(pd.to_datetime(df["date"])).drop(columns=["date"])
        # Stooq's close is already split/dividend adjusted.
        df["adj_close"] = df["close"]
        return df

    def securities(self, symbols):
        out = {}
        for s in symbols:
            suffix = s.rsplit(".", 1)[-1].upper() if "." in s else ""
            is_uk = suffix in {"LON", "L", "UK"}
            out[s] = Security(
                symbol=s,
                exchange="XLON" if is_uk else "XNYS",
                country="GB" if is_uk else "US",
                currency=Currency.GBX if is_uk else Currency.USD,
            )
        return out
