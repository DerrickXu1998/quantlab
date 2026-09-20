"""The LSE listed universe.

This is the weakest link in the whole free-data story and it is worth being
straight about why: the London Stock Exchange's reports hub is a JavaScript
application, the old ``instrumentlist.xls`` URL is no longer dependable, and
LSEG sells the instrument reference data as a product. There is no stable,
documented, free endpoint that returns "every LSE-listed company".

So this source tries three routes in order and tells you which one it used:

1. ``path=`` -- a file you downloaded yourself from the LSE reports page.
   Boring, manual, and by far the most reliable. Recommended for production.
2. ``url=`` -- a direct link you supply, if you find a working one.
3. A bundled FTSE 350 fallback list, so the package works out of the box.

If you only need the liquid end of the market, route 3 is honestly fine: the
long AIM tail is exactly where free price data is least trustworthy anyway.
"""
from __future__ import annotations

import io
import logging
import pathlib

import pandas as pd

from ..registry import universe
from ..schema import Currency, Security
from .base import UniverseSource

log = logging.getLogger(__name__)

LSE_REPORTS_PAGE = "https://www.londonstockexchange.com/reports?tab=instruments"

# A pragmatic, hand-maintained fallback: large and mid-cap London lines that
# every free source covers. Not the full universe -- see the module docstring.
FTSE_CORE = [
    "AAL", "ABF", "ADM", "ANTO", "AUTO", "AV", "AZN", "BA", "BARC",
    "BATS", "BEZ", "BKG", "BNZL", "BP", "BRBY", "BT.A", "BTRW", "CCH", "CNA",
    "CPG", "CRDA", "CTEC", "DCC", "DGE", "DPLM", "EDV", "ENT", "EXPN", "FCIT",
    "FRAS", "FRES", "GAW", "GLEN", "GSK", "HIK", "HLMA", "HLN", "HSBA", "HSX", "HWDN",
    "IAG", "ICG", "IHG", "III", "IMB", "IMI", "INF", "ITRK", "JD", "KGF",
    "LAND", "LGEN", "LLOY", "LMP", "LSEG", "MKS", "MNDI", "MNG", "MRO", "NG",
    "NWG", "NXT", "PRU", "PSH", "PSN", "PSON", "REL", "RIO", "RKT",
    "RMV", "RR", "RTO", "SBRY", "SDLF", "SDR", "SGE", "SGRO", "SHEL", "SMIN",
    "SMT", "SN", "SPX", "SSE", "STAN", "STJ", "SVT", "TSCO", "TW", "ULVR", "UTG",
    "UU", "VOD", "WEIR", "WPP", "WTB",
]
# Refreshed 2026-09:
#   BDEV -> BTRW  Barratt became Barratt Redrow after the Redrow merger
#   PHNX -> SDLF  Phoenix Group renamed to Standard Life plc (ticker SDLF) in Mar 2026
#   SMDS dropped  DS Smith was acquired by International Paper
#   AHT  dropped  Ashtead moved its primary listing to NYSE; the London line is gone
# GAW and STJ added to keep the list at 95 liquid names.


@universe("lse")
class LseUniverse(UniverseSource):
    name = "lse"
    exchanges = ("XLON",)
    licence_note = (
        "No stable free endpoint for the full LSE instrument list. Download the "
        "issuer/instrument file from londonstockexchange.com/reports and pass path=."
    )

    def __init__(
        self,
        path: str | pathlib.Path = "",
        url: str = "",
        segment: str = "",
        include_aim: bool = True,
        **opts,
    ):
        super().__init__(**opts)
        self.path = pathlib.Path(path).expanduser() if path else None
        self.url = url
        self.segment = segment
        self.include_aim = include_aim
        self.source_used = ""

    def securities(self) -> list[Security]:
        if self.path and self.path.exists():
            self.source_used = f"file:{self.path.name}"
            return self._from_frame(_read_any(self.path.read_bytes(), self.path.suffix))
        if self.url:
            from ..http import HttpClient

            try:
                blob = HttpClient("default").get(self.url, ttl=7 * 86400)
                self.source_used = f"url:{self.url}"
                return self._from_frame(_read_any(blob, pathlib.Path(self.url).suffix))
            except Exception as exc:
                log.warning("lse: supplied url failed (%s); falling back to bundled list", exc)

        self.source_used = "fallback:ftse_core"
        log.info(
            "lse: using the bundled FTSE core list (%d names). For the full universe, "
            "download the instrument list from %s and pass path=.",
            len(FTSE_CORE), LSE_REPORTS_PAGE,
        )
        return [
            Security(symbol=f"{t}.LON", exchange="XLON", country="GB", currency=Currency.GBX)
            for t in FTSE_CORE
        ]

    def _from_frame(self, df: pd.DataFrame) -> list[Security]:
        cols = {str(c).strip().lower(): c for c in df.columns}

        def pick(*candidates: str) -> str | None:
            for want in candidates:
                for key, original in cols.items():
                    if want in key:
                        return original
            return None

        tidm = pick("tidm", "mnemonic", "ticker", "symbol")
        name = pick("company name", "issuer name", "name")
        isin = pick("isin")
        sector = pick("icb sector", "sector")
        market = pick("market", "segment")
        if tidm is None:
            raise ValueError(
                "lse: could not find a TIDM/ticker column in the supplied file; "
                f"columns were {list(df.columns)[:12]}"
            )

        if market and not self.include_aim:
            df = df[~df[market].astype(str).str.upper().str.contains("AIM", na=False)]
        if market and self.segment:
            df = df[df[market].astype(str).str.contains(self.segment, case=False, na=False)]

        out = []
        for _, row in df.iterrows():
            t = str(row[tidm]).strip().upper()
            if not t or t in {"NAN", "-"}:
                continue
            out.append(
                Security(
                    symbol=f"{t}.LON",
                    name=str(row[name]).strip() if name else "",
                    exchange="XLON",
                    country="GB",
                    currency=Currency.GBX,
                    sector=str(row[sector]).strip() if sector else "",
                    isin=str(row[isin]).strip().upper() if isin else "",
                )
            )
        return out


def _read_any(blob: bytes, suffix: str) -> pd.DataFrame:
    suffix = suffix.lower()
    if suffix in {".xls", ".xlsx", ".xlsm"}:
        try:
            sheets = pd.read_excel(io.BytesIO(blob), sheet_name=None)
        except ImportError as exc:
            raise ImportError("reading LSE Excel files needs openpyxl: pip install 'quantlab[excel]'") from exc
        # The instrument list usually lives on the widest sheet.
        return max(sheets.values(), key=lambda d: d.shape[1])
    text = blob.decode("utf-8", errors="replace")
    sep = "\t" if "\t" in text.splitlines()[0] else ","
    return pd.read_csv(io.StringIO(text), sep=sep)
