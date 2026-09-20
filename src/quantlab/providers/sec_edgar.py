"""SEC EDGAR -- US fundamentals and insider transactions.

The best free financial data source that exists, and the only one on this list
that is public domain and unambiguously safe to build on commercially. No API
key. Two rules matter:

  1. **10 requests/second**, enforced by IP.
  2. A **User-Agent identifying you with a contact email** is mandatory. Set
     ``SEC_USER_AGENT='Your Name you@example.com'``.

Scale strategy: do not loop 5,000 CIKs against ``companyconcept``. Use the
``frames`` endpoint (one concept, one period, every filer -- one request) for
cross-sectional pulls, and the nightly bulk ZIPs for history.
"""
from __future__ import annotations

import io
import logging
import zipfile
from typing import Any, Sequence

import pandas as pd

from ..config import settings
from ..registry import provider
from ..schema import Currency, DataUnavailable, Security
from .base import DataProvider

log = logging.getLogger(__name__)

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FRAMES = "https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/{unit}/CY{period}.json"
INSIDER_ZIP = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{year}q{q}_form345.zip"

# Canonical concept -> candidate us-gaap tags, most preferred first.
# Filers are inconsistent, so every concept needs a fallback chain.
CONCEPT_TAGS: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues", "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "shares_outstanding": ["CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"],
}


@provider("sec_edgar")
class SecEdgarProvider(DataProvider):
    name = "sec_edgar"
    supports = ("US",)
    requires_key = False
    licence_note = "US public domain. No restrictions. Requires a contact User-Agent and <=10 req/s."

    def __init__(self, **opts):
        super().__init__(**opts)
        from ..http import HttpClient

        self.client = HttpClient("sec_edgar", user_agent=settings().sec_user_agent())
        self._ticker_map: dict[str, int] | None = None

    # -- identifiers -------------------------------------------------------
    def ticker_to_cik(self) -> dict[str, int]:
        if self._ticker_map is None:
            raw = self.client.get_json(TICKER_MAP_URL, ttl=7 * 86400)
            self._ticker_map = {
                str(v["ticker"]).upper(): int(v["cik_str"]) for v in raw.values()
            }
        return self._ticker_map

    def cik_for(self, symbol: str) -> int:
        root = symbol.rsplit(".", 1)[0].upper() if "." in symbol else symbol.upper()
        cik = self.ticker_to_cik().get(root)
        if cik is None:
            raise DataUnavailable(f"sec_edgar: no CIK for {symbol}")
        return cik

    def fetch_one(self, symbol, start, end, frequency="1d"):
        raise DataUnavailable("sec_edgar does not provide price bars; use stooq or yahoo")

    def securities(self, symbols: Sequence[str]) -> dict[str, Security]:
        out = {}
        for s in symbols:
            try:
                out[s] = Security(symbol=s, country="US", currency=Currency.USD, cik=f"{self.cik_for(s):010d}")
            except DataUnavailable:
                continue
        return out

    # -- fundamentals ------------------------------------------------------
    def companyfacts(self, cik: int) -> dict[str, Any]:
        """Everything one filer ever tagged, one request per CIK."""
        return self.client.get_json(COMPANY_FACTS.format(cik=int(cik)), ttl=7 * 86400)

    def fundamentals(self, symbols: Sequence[str], concepts: Sequence[str], *, ctx: Any = None) -> pd.DataFrame:
        """Point-in-time fundamentals, indexed by (filed_date, symbol).

        The index is the **filing date** (``filed`` in the XBRL payload), not
        the fiscal period end. That is what makes the output safe to join onto
        a price panel without look-ahead.
        """
        rows: list[dict[str, Any]] = []
        for sym in symbols:
            try:
                cik = self.cik_for(sym)
                blob = self.companyfacts(cik)
            except Exception as exc:
                log.debug("sec_edgar: %s facts unavailable: %s", sym, exc)
                continue
            facts = blob.get("facts", {})
            merged: dict[pd.Timestamp, dict[str, float]] = {}
            for concept in concepts:
                for tag in CONCEPT_TAGS.get(concept, [concept]):
                    series = self._extract(facts, tag)
                    if series is None:
                        continue
                    for filed, value in series.items():
                        merged.setdefault(filed, {})[concept] = value
                    break
            for filed, values in merged.items():
                rows.append({"date": filed, "symbol": sym, **values})

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.groupby(["date", "symbol"]).last().sort_index()

    @staticmethod
    def _extract(facts: dict, tag: str) -> dict[pd.Timestamp, float] | None:
        for taxonomy in ("us-gaap", "dei", "ifrs-full"):
            node = facts.get(taxonomy, {}).get(tag)
            if not node:
                continue
            for unit_key, entries in node.get("units", {}).items():
                if unit_key not in {"USD", "shares", "USD/shares"}:
                    continue
                out: dict[pd.Timestamp, float] = {}
                for e in entries:
                    filed = e.get("filed")
                    val = e.get("val")
                    if filed is None or val is None:
                        continue
                    # Prefer annual (FY) figures; keep the latest filed value.
                    out[pd.Timestamp(filed)] = float(val)
                if out:
                    return out
        return None

    def frame(self, concept: str, period: str, unit: str = "USD") -> pd.DataFrame:
        """Cross-sectional pull: one concept, one period, every filer, one request.

        ``period`` is a frame label such as ``2025Q4I`` (instantaneous) or
        ``2025`` (annual duration). This is how you populate 5,000 names
        without 5,000 requests.
        """
        tag = CONCEPT_TAGS.get(concept, [concept])[0]
        blob = self.client.get_json(FRAMES.format(concept=tag, unit=unit, period=period), ttl=7 * 86400)
        data = blob.get("data", [])
        if not data:
            raise DataUnavailable(f"sec_edgar: empty frame {concept} {period}")
        df = pd.DataFrame(data)
        df["cik"] = df["cik"].astype(int)
        return df

    # -- insider transactions ---------------------------------------------
    def insider_transactions(
        self, symbols: Sequence[str], start: Any, end: Any, *, ctx: Any = None
    ) -> pd.DataFrame:
        """Form 3/4/5 transactions from the quarterly bulk datasets.

        Returns columns: ``date``, ``symbol``, ``owner``, ``shares``,
        ``is_acquisition``.
        """
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        cik_to_symbol: dict[int, str] = {}
        for s in symbols:
            try:
                cik_to_symbol[self.cik_for(s)] = s
            except DataUnavailable:
                continue
        if not cik_to_symbol:
            return pd.DataFrame()

        quarters = pd.period_range(start, end, freq="Q")
        frames: list[pd.DataFrame] = []
        for q in quarters:
            url = INSIDER_ZIP.format(year=q.year, q=q.quarter)
            try:
                blob = self.client.get(url, ttl=-1)
                frames.append(self._parse_insider_zip(blob, cik_to_symbol))
            except Exception as exc:
                log.debug("sec_edgar: insider %s unavailable: %s", q, exc)
        frames = [f for f in frames if f is not None and not f.empty]
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=True)
        return out[(out["date"] >= start) & (out["date"] <= end)]

    @staticmethod
    def _parse_insider_zip(blob: bytes, cik_to_symbol: dict[int, str]) -> pd.DataFrame:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = {n.lower(): n for n in zf.namelist()}
            if "nonderiv_trans.tsv" not in names or "reportingowner.tsv" not in names:
                return pd.DataFrame()
            trans = pd.read_csv(zf.open(names["nonderiv_trans.tsv"]), sep="\t", low_memory=False)
            owners = pd.read_csv(zf.open(names["reportingowner.tsv"]), sep="\t", low_memory=False)
            subs = pd.read_csv(zf.open(names["submission.tsv"]), sep="\t", low_memory=False)

        trans.columns = [c.upper() for c in trans.columns]
        owners.columns = [c.upper() for c in owners.columns]
        subs.columns = [c.upper() for c in subs.columns]

        subs["ISSUERCIK"] = pd.to_numeric(subs.get("ISSUERCIK"), errors="coerce")
        subs = subs[subs["ISSUERCIK"].isin(cik_to_symbol)]
        if subs.empty:
            return pd.DataFrame()

        merged = trans.merge(subs[["ACCESSION_NUMBER", "ISSUERCIK", "FILING_DATE"]], on="ACCESSION_NUMBER")
        merged = merged.merge(
            owners[["ACCESSION_NUMBER", "RPTOWNERCIK"]].drop_duplicates(), on="ACCESSION_NUMBER", how="left"
        )
        return pd.DataFrame(
            {
                "date": pd.to_datetime(merged["FILING_DATE"], errors="coerce", format="mixed"),
                "symbol": merged["ISSUERCIK"].map(cik_to_symbol),
                "owner": merged["RPTOWNERCIK"].astype(str),
                "shares": pd.to_numeric(merged.get("TRANS_SHARES"), errors="coerce").fillna(0.0),
                "is_acquisition": merged.get("TRANS_ACQUIRED_DISP_CD", "").astype(str).str.upper().eq("A"),
            }
        ).dropna(subset=["date", "symbol"])
