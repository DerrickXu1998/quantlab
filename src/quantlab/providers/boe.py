"""Bank of England Interactive Database -- free, keyless UK rates and FX.

One documented CSV endpoint, up to 300 series per request, no registration.
This is where ``gbp_usd`` comes from, which you need the moment you rank an
LSE name against a NYSE one.
"""
from __future__ import annotations

import io

import pandas as pd

from ..registry import provider
from ..schema import DataUnavailable
from .base import DataProvider

CSV_URL = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"

COMMON_SERIES = {
    "IUDBEDR": "Official Bank Rate",
    "XUDLUSS": "GBP/USD daily spot",
    "XUDLERS": "GBP/EUR daily spot",
    "IUDSNPY": "10y gilt yield",
    "LPMVWYR": "M4 money supply growth",
}


@provider("boe")
class BoeProvider(DataProvider):
    name = "boe"
    requires_key = False
    licence_note = "Freely reusable with attribution; no documented rate limit. Be polite."

    def __init__(self, **opts):
        super().__init__(**opts)
        from ..http import HttpClient

        self.client = HttpClient("boe")

    def fetch_one(self, symbol, start, end, frequency="1d"):
        raise DataUnavailable("boe provides macro series, not equity bars")

    def series_batch(self, codes: list[str], start, end="") -> pd.DataFrame:
        """Up to 300 series in one request, returned as a date-indexed frame."""
        if len(codes) > 300:
            raise ValueError("BoE accepts at most 300 series codes per request")
        params = {
            "csv.x": "yes",
            "Datefrom": pd.Timestamp(start).strftime("%d/%b/%Y"),
            "Dateto": pd.Timestamp(end).strftime("%d/%b/%Y") if end else "now",
            "SeriesCodes": ",".join(codes),
            "UsingCodes": "Y",
            "CSVF": "TN",
            "VPD": "Y",
        }
        text = self.client.get_text(CSV_URL, params=params, ttl=12 * 3600)
        if "DATE" not in text.upper()[:200]:
            raise DataUnavailable(f"boe: unexpected payload for {codes}")
        df = pd.read_csv(io.StringIO(text))
        date_col = df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col], format="%d %b %Y", errors="coerce")
        df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
        df.index.name = "date"
        return df.apply(pd.to_numeric, errors="coerce")

    def series(self, code: str, start, end="") -> pd.Series:
        frame = self.series_batch([code], start, end)
        if code not in frame.columns:
            if frame.shape[1] == 1:
                return frame.iloc[:, 0].rename(code)
            raise DataUnavailable(f"boe: series {code} not in response")
        return frame[code]

    def gbp_usd(self, start, end="") -> pd.Series:
        return self.series("XUDLUSS", start, end)
