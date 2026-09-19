"""The US listed universe from Nasdaq Trader's symbol directory files.

``otherlisted.txt`` carries NYSE, NYSE American, NYSE Arca and CBOE listings;
``nasdaqlisted.txt`` carries Nasdaq. Both are pipe-delimited, updated daily and
free. This is the official-ish route to a full US universe -- nyse.com's own
listings directory is a JavaScript UI with no export.

The files include test issues, ETFs and non-common-stock lines. Filtering is
on by default because a "universe" full of warrants and preferreds will quietly
wreck your cross-sectional statistics.
"""
from __future__ import annotations

import io
import logging

import pandas as pd

from ..registry import universe
from ..schema import Currency, ProviderError, Security
from .base import UniverseSource

log = logging.getLogger(__name__)

BASE = "https://www.nasdaqtrader.com/dynamic/symdir/"
FILES = {"other": BASE + "otherlisted.txt", "nasdaq": BASE + "nasdaqlisted.txt"}

# Exchange letter codes used in otherlisted.txt
EXCHANGE_NAMES = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "CBOE BZX", "V": "IEX"}


@universe("nasdaqtrader")
class NasdaqTraderUniverse(UniverseSource):
    name = "nasdaqtrader"
    exchanges = ("XNYS", "XNAS", "ARCX")
    licence_note = "Public symbol directory files. No key; no stated restrictions."

    def __init__(
        self,
        exchanges: tuple[str, ...] = ("N",),
        include_nasdaq: bool = False,
        common_stock_only: bool = True,
        exclude_test_issues: bool = True,
        **opts,
    ):
        super().__init__(**opts)
        self.exchange_codes = tuple(exchanges)
        self.include_nasdaq = include_nasdaq
        self.common_stock_only = common_stock_only
        self.exclude_test_issues = exclude_test_issues

    def _read(self, url: str) -> pd.DataFrame:
        from ..http import HttpClient

        text = HttpClient("default").get_text(url, ttl=86400)
        lines = [ln for ln in text.splitlines() if ln and not ln.startswith("File Creation Time")]
        df = pd.read_csv(io.StringIO("\n".join(lines)), sep="|")
        df.columns = [c.strip() for c in df.columns]
        return df

    def securities(self) -> list[Security]:
        out: list[Security] = []

        try:
            other = self._read(FILES["other"])
        except Exception as exc:
            raise ProviderError(f"nasdaqtrader: could not read otherlisted.txt: {exc}") from exc

        if "Exchange" in other.columns and self.exchange_codes:
            other = other[other["Exchange"].isin(self.exchange_codes)]
        out += self._rows_to_securities(other, symbol_col="ACT Symbol", name_col="Security Name")

        if self.include_nasdaq:
            try:
                nas = self._read(FILES["nasdaq"])
                out += self._rows_to_securities(nas, symbol_col="Symbol", name_col="Security Name")
            except Exception as exc:
                log.warning("nasdaqtrader: nasdaqlisted.txt unavailable: %s", exc)

        return out

    def _rows_to_securities(self, df: pd.DataFrame, symbol_col: str, name_col: str) -> list[Security]:
        if symbol_col not in df.columns:
            return []
        if self.exclude_test_issues and "Test Issue" in df.columns:
            df = df[df["Test Issue"].astype(str).str.upper() != "Y"]
        if "ETF" in df.columns and self.common_stock_only:
            df = df[df["ETF"].astype(str).str.upper() != "Y"]
        if self.common_stock_only:
            name = df[name_col].astype(str).str.lower()
            drop = name.str.contains(
                r"warrant|preferred|depositary|right|unit|notes? due|%\s", regex=True, na=False
            )
            df = df[~drop]
            # Five-character symbols ending in a class letter are usually not
            # ordinary common stock on these files.
            df = df[~df[symbol_col].astype(str).str.contains(r"[\$\.\^]", regex=True, na=False)]

        exch_col = df["Exchange"] if "Exchange" in df.columns else None
        securities = []
        for i, (_, row) in enumerate(df.iterrows()):
            sym = str(row[symbol_col]).strip()
            if not sym:
                continue
            code = str(exch_col.iloc[i]) if exch_col is not None else "N"
            securities.append(
                Security(
                    symbol=f"{sym}.US",
                    name=str(row.get(name_col, "")).strip(),
                    exchange=EXCHANGE_NAMES.get(code, "NASDAQ"),
                    country="US",
                    currency=Currency.USD,
                )
            )
        return securities
