"""A universe you define yourself: a list, a CSV, or a named watchlist.

Always available, never breaks, and the right choice for development. The
built-in samples are small, liquid, well-covered names on each exchange.
"""
from __future__ import annotations

import pathlib
from typing import Sequence

import pandas as pd

from ..registry import universe
from ..schema import Currency, Security
from .base import UniverseSource

# Deliberately short, liquid and well-covered by the free sources -- good for
# smoke tests and for checking a provider is alive.
SAMPLE_NYSE = ["JPM.US", "JNJ.US", "XOM.US", "PG.US", "KO.US", "WMT.US", "CVX.US", "BA.US"]
SAMPLE_LSE = ["HSBA.LON", "SHEL.LON", "AZN.LON", "ULVR.LON", "BP.LON", "GSK.LON", "RIO.LON", "BATS.LON"]

WATCHLISTS = {
    "sample": SAMPLE_NYSE + SAMPLE_LSE,
    "sample_us": SAMPLE_NYSE,
    "sample_uk": SAMPLE_LSE,
}


@universe("static")
class StaticUniverse(UniverseSource):
    name = "static"
    licence_note = "Yours."

    def __init__(self, symbols: Sequence[str] | None = None, watchlist: str = "",
                 path: str | pathlib.Path = "", **opts):
        super().__init__(**opts)
        self._symbols = list(symbols or [])
        self.watchlist = watchlist
        self.path = pathlib.Path(path).expanduser() if path else None

    def securities(self) -> list[Security]:
        if self.path and self.path.exists():
            df = pd.read_csv(self.path)
            col = "symbol" if "symbol" in df.columns else df.columns[0]
            return [
                Security(
                    symbol=str(r[col]),
                    name=str(r.get("name", "")),
                    sector=str(r.get("sector", "")),
                    isin=str(r.get("isin", "")),
                    country=str(r.get("country", "")) or _country(str(r[col])),
                    currency=_currency(str(r[col])),
                )
                for _, r in df.iterrows()
            ]
        syms = self._symbols or WATCHLISTS.get(self.watchlist or "sample", [])
        return [
            Security(symbol=s, country=_country(s), currency=_currency(s),
                     exchange="XLON" if _country(s) == "GB" else "XNYS")
            for s in syms
        ]


def _country(symbol: str) -> str:
    suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
    return "GB" if suffix in {"LON", "L", "UK"} else "US"


def _currency(symbol: str) -> Currency:
    return Currency.GBX if _country(symbol) == "GB" else Currency.USD
