"""FRED (Federal Reserve Bank of St. Louis) -- free US macro series.

Needs a free API key (``FRED_API_KEY``). Note that much of FRED is
*redistributed* third-party data (OECD, BIS), whose own terms still apply --
the FRED wrapper being free does not make every series redistributable.
"""
from __future__ import annotations

import logging

import pandas as pd

from ..config import settings
from ..registry import provider
from ..schema import DataUnavailable, ProviderError
from .base import DataProvider

log = logging.getLogger(__name__)

BASE = "https://api.stlouisfed.org/fred/series/observations"


@provider("fred")
class FredProvider(DataProvider):
    name = "fred"
    requires_key = True
    licence_note = "Free key required. Some series carry third-party redistribution limits."

    def __init__(self, api_key: str = "", **opts):
        super().__init__(**opts)
        from ..http import HttpClient

        self.api_key = api_key or settings().fred_api_key
        self.client = HttpClient("fred")

    def fetch_one(self, symbol, start, end, frequency="1d"):
        raise DataUnavailable("fred provides macro series, not equity bars")

    def series(self, code: str, start, end="") -> pd.Series:
        if not self.api_key:
            raise ProviderError("FRED needs a free API key; set FRED_API_KEY")
        params = {
            "series_id": code,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": pd.Timestamp(start).strftime("%Y-%m-%d"),
        }
        if end:
            params["observation_end"] = pd.Timestamp(end).strftime("%Y-%m-%d")
        blob = self.client.get_json(BASE, params=params, ttl=12 * 3600)
        obs = blob.get("observations", [])
        if not obs:
            raise DataUnavailable(f"fred: no observations for {code}")
        df = pd.DataFrame(obs)
        s = pd.Series(
            pd.to_numeric(df["value"].replace(".", None), errors="coerce").to_numpy(),
            index=pd.to_datetime(df["date"]),
            name=code,
        )
        s.index.name = "date"
        return s

    def series_batch(self, codes: list[str], start, end="") -> pd.DataFrame:
        """FRED has no bulk endpoint: loop ``series`` per code.

        A series that simply has no data is logged and skipped, so one dead
        code does not cost the batch. A missing API key (ProviderError)
        propagates -- that failure is the operator's to fix, not a gap.
        """
        cols = {}
        for code in codes:
            try:
                cols[code] = self.series(code, start, end)
            except DataUnavailable as exc:
                log.warning("%s", exc)
        return pd.DataFrame(cols)
