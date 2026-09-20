"""UK Companies House -- the only free, official, bulk UK fundamentals source.

Two surfaces:
  * **REST API** (free key, 600 requests / 5 minutes): company profile, filing
    history, officers, PSC.
  * **Free Accounts Data Product** (no key): daily ZIPs of electronically
    filed accounts as iXBRL. Files are retained for 60 days, so backfill early
    and keep your own archive.

Honest limitations, because they shape what you can build:
  * Many LSE issuers are incorporated in Jersey, Guernsey, Ireland or the Isle
    of Man and simply are not here.
  * Accounts follow a statutory calendar, not a market reporting calendar, so
    they lag and are coarser than US quarterly filings.
  * Nothing in the data carries a ticker. You must build the
    company-number -> SEDOL/ISIN -> ticker bridge yourself (OpenFIGI helps).
"""
from __future__ import annotations

import base64
import datetime as dt
import logging
import re
from typing import Any, Sequence

import pandas as pd

from ..config import settings
from ..registry import provider
from ..schema import Currency, DataUnavailable, ProviderError, Security
from .base import DataProvider

log = logging.getLogger(__name__)

API_BASE = "https://api.company-information.service.gov.uk"
BULK_INDEX = "https://download.companieshouse.gov.uk/en_accountsdata.html"

# Common UK-GAAP / IFRS iXBRL tags mapped onto quantlab's canonical concepts.
UK_TAGS: dict[str, list[str]] = {
    "revenue": ["Turnover", "Revenue", "TurnoverRevenue"],
    "net_income": ["ProfitLoss", "ProfitLossForPeriod"],
    "operating_income": ["OperatingProfitLoss"],
    "gross_profit": ["GrossProfitLoss"],
    "total_assets": ["TotalAssets", "Assets"],
    "total_liabilities": ["Liabilities", "TotalLiabilities"],
    "equity": ["Equity", "ShareholderFunds"],
    "cash": ["CashBankOnHand", "CashAndCashEquivalents"],
    "current_assets": ["CurrentAssets"],
    "current_liabilities": ["CreditorsDueWithinOneYear", "CurrentLiabilities"],
    "long_term_debt": ["CreditorsDueAfterOneYear"],
    "shares_outstanding": ["NumberSharesIssued", "NumberSharesAllotted"],
}


@provider("companies_house")
class CompaniesHouseProvider(DataProvider):
    name = "companies_house"
    supports = ("LON", "L")
    requires_key = True
    licence_note = (
        "Crown copyright, normally Open Government Licence -- confirm the current "
        "terms on the Companies House site before commercial use."
    )

    def __init__(self, api_key: str = "", **opts):
        super().__init__(**opts)
        from ..http import HttpClient

        self.api_key = api_key or settings().companies_house_key
        headers = {}
        if self.api_key:
            token = base64.b64encode(f"{self.api_key}:".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        self.client = HttpClient("companies_house", headers=headers)

    def _require_key(self) -> None:
        if not self.api_key:
            raise ProviderError(
                "Companies House needs a free API key. Register at "
                "developer.company-information.service.gov.uk and set "
                "COMPANIES_HOUSE_API_KEY."
            )

    def fetch_one(self, symbol, start, end, frequency="1d"):
        raise DataUnavailable("companies_house does not provide price bars; use stooq or yahoo")

    # -- reference ---------------------------------------------------------
    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        self._require_key()
        blob = self.client.get_json(
            f"{API_BASE}/search/companies", params={"q": query, "items_per_page": limit}, ttl=30 * 86400
        )
        return blob.get("items", [])

    def profile(self, company_number: str) -> dict[str, Any]:
        self._require_key()
        return self.client.get_json(f"{API_BASE}/company/{company_number}", ttl=7 * 86400)

    def filing_history(self, company_number: str, category: str = "accounts", limit: int = 50) -> pd.DataFrame:
        """Filing history -- the source of point-in-time filing dates for the UK."""
        self._require_key()
        blob = self.client.get_json(
            f"{API_BASE}/company/{company_number}/filing-history",
            params={"category": category, "items_per_page": limit},
            ttl=86400,
        )
        items = blob.get("items", [])
        if not items:
            return pd.DataFrame()
        df = pd.DataFrame(items)
        for col in ("date", "action_date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        return df

    def securities(self, symbols: Sequence[str]) -> dict[str, Security]:
        out: dict[str, Security] = {}
        for s in symbols:
            out[s] = Security(symbol=s, exchange="XLON", country="GB", currency=Currency.GBX)
        return out

    # -- fundamentals ------------------------------------------------------
    def fundamentals(self, symbols: Sequence[str], concepts: Sequence[str], *, ctx: Any = None) -> pd.DataFrame:
        """Parse filed iXBRL accounts into canonical concepts.

        Requires each symbol to carry a ``company_number`` in the context's
        securities map -- resolve it once with :meth:`search` and cache it.
        Returns an empty frame (not an error) when the mapping is missing, so a
        mixed NYSE/LSE pipeline still runs.
        """
        securities = getattr(ctx, "securities", {}) or {}
        pairs = [
            (s, securities[s].company_number)
            for s in symbols
            if s in securities and getattr(securities[s], "company_number", "")
        ]
        if not pairs:
            log.info(
                "companies_house: no company numbers resolved for %d symbols; "
                "populate Security.company_number to enable UK fundamentals",
                len(symbols),
            )
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []
        for symbol, number in pairs:
            try:
                history = self.filing_history(number, category="accounts")
            except Exception as exc:
                log.warning("companies_house: filing history for %s failed: %s", symbol, exc)
                continue
            for _, item in history.iterrows():
                doc = (item.get("links") or {}).get("document_metadata")
                if not doc:
                    continue
                try:
                    content = self.client.get(f"{doc}/content", ttl=-1, headers={"Accept": "application/xhtml+xml"})
                except Exception as exc:
                    log.debug("companies_house: document fetch failed: %s", exc)
                    continue
                values = parse_ixbrl(content.decode("utf-8", errors="replace"), concepts)
                if values:
                    rows.append({"date": item["date"], "symbol": symbol, **values})

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.groupby(["date", "symbol"]).last().sort_index()


_IX_RE = re.compile(
    r'<ix:nonFraction[^>]*name="[^:"]*:(?P<tag>[A-Za-z0-9_]+)"[^>]*>(?P<value>[^<]*)</ix:nonFraction>',
    re.IGNORECASE,
)
_SCALE_RE = re.compile(r'scale="(-?\d+)"')
_SIGN_RE = re.compile(r'sign="(-)"')


def parse_ixbrl(document: str, concepts: Sequence[str]) -> dict[str, float]:
    """Minimal iXBRL numeric extractor.

    Deliberately regex-based rather than a full XBRL processor: Companies House
    filings are small, the tags we want are few, and a full processor is a
    heavy dependency for a handful of numbers. Swap in ``arelle`` here if you
    need contexts, dimensions and full validation.
    """
    return {concept: value for concept, (_, value) in parse_ixbrl_facts(document, concepts).items()}


def parse_ixbrl_facts(document: str, concepts: Sequence[str]) -> dict[str, tuple[str, float]]:
    """Like :func:`parse_ixbrl`, but keeps the raw tag: concept -> (tag, value).

    The fundamentals table stores the tag as filed, so the warehouse ingest
    needs the tag name back; the namespace prefix is still dropped (the regex
    cannot resolve it), so the tag alone is what lands in ``fundamentals.tag``.
    """
    wanted: dict[str, str] = {}
    for concept in concepts:
        for tag in UK_TAGS.get(concept, [concept]):
            wanted[tag.lower()] = concept

    out: dict[str, tuple[str, float]] = {}
    for match in _IX_RE.finditer(document):
        tag = match.group("tag")
        concept = wanted.get(tag.lower())
        if concept is None or concept in out:
            continue
        raw = match.group("value").replace(",", "").replace("\xa0", "").strip()
        if not raw or raw in {"-", "—"}:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        attrs = match.group(0)
        scale = _SCALE_RE.search(attrs)
        if scale:
            value *= 10 ** int(scale.group(1))
        if _SIGN_RE.search(attrs):
            value = -value
        out[concept] = (tag, value)
    return out


_PERIOD_RE = re.compile(
    r'<ix:nonNumeric[^>]*name="[^:"]*:(?P<tag>EndDateForPeriodCoveredByReport|BalanceSheetDate)"[^>]*>'
    r"(?P<value>[^<]*)</ix:nonNumeric>",
    re.IGNORECASE,
)


def parse_ixbrl_period_end(document: str) -> dt.date | None:
    """The statutory period end of an iXBRL accounts document, if findable.

    Companies House filings tag it as ``EndDateForPeriodCoveredByReport`` (or
    ``BalanceSheetDate`` for a balance-sheet-only document). Returns None when
    neither parses -- the caller decides on the fallback, not this function.
    """
    for match in _PERIOD_RE.finditer(document):
        raw = match.group("value").strip()
        ts = pd.to_datetime(raw, errors="coerce", format="%Y-%m-%d")
        if pd.isna(ts):
            # Human-spelled dates ("31 December 2023") appear in older filings.
            ts = pd.to_datetime(raw, errors="coerce", dayfirst=True)
        if pd.notna(ts):
            return ts.date()
    return None
