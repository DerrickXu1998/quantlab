"""OpenFIGI -- free identifier mapping, and the keystone of a NYSE+LSE join.

Nothing else ties a Stooq ``.uk`` symbol, a Yahoo ``.L`` symbol, an FCA short
position ISIN and a Companies House company number to the same instrument.
Free without limits; an optional free key raises throughput from 25 req/min
(10 jobs each) to 25 req/6s (100 jobs each) -- about 25,000 mappings a minute,
so a 5,000-name universe resolves in seconds.

Known asymmetry: ISIN and SEDOL work well as *inputs*. The response carries
FIGI, ticker, name, exchange code and security type -- not ISIN. Plan your
identifier graph around ISIN/SEDOL -> FIGI -> ticker, not the reverse.
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

import pandas as pd

from ..config import settings
from ..ratelimit import Limit, set_limit
from ..registry import provider
from ..schema import DataUnavailable
from .base import DataProvider

log = logging.getLogger(__name__)

MAPPING_URL = "https://api.openfigi.com/v3/mapping"
SEARCH_URL = "https://api.openfigi.com/v3/search"

EXCHANGE_CODES = {"US": ["US"], "GB": ["LN"]}


@provider("openfigi")
class OpenFigiProvider(DataProvider):
    name = "openfigi"
    requires_key = False
    licence_note = "Free, no usage limits stated. Optional free key raises throughput 10x."

    def __init__(self, api_key: str = "", **opts):
        super().__init__(**opts)
        from ..http import HttpClient

        self.api_key = api_key or settings().openfigi_api_key
        headers = {"Content-Type": "application/json"}
        bucket = "openfigi"
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key
            bucket = "openfigi_keyed"
            set_limit("openfigi", Limit.per_window(25, 6, note="keyed"))
        self.jobs_per_request = 100 if self.api_key else 10
        self.client = HttpClient(bucket, headers=headers)

    def fetch_one(self, symbol, start, end, frequency="1d"):
        raise DataUnavailable("openfigi maps identifiers; it has no price data")

    def map_identifiers(self, jobs: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Map a batch of identifier jobs, chunked to the per-request limit."""
        results: list[list[dict[str, Any]]] = []
        for i in range(0, len(jobs), self.jobs_per_request):
            chunk = list(jobs[i : i + self.jobs_per_request])
            blob = self.client.post_json(MAPPING_URL, chunk, ttl=30 * 86400)
            import json

            payload = json.loads(blob) if isinstance(blob, (bytes, bytearray)) else blob
            for entry in payload:
                results.append(entry.get("data", []) if isinstance(entry, dict) else [])
        return results

    def resolve_tickers(self, symbols: Sequence[str]) -> pd.DataFrame:
        """Canonical symbol -> FIGI, name, security type, exchange code."""
        jobs = []
        for s in symbols:
            root = s.rsplit(".", 1)[0] if "." in s else s
            suffix = s.rsplit(".", 1)[-1].upper() if "." in s else "US"
            exch = "LN" if suffix in {"LON", "L", "UK"} else "US"
            jobs.append({"idType": "TICKER", "idValue": root, "exchCode": exch})

        rows = []
        for symbol, data in zip(symbols, self.map_identifiers(jobs)):
            best = data[0] if data else {}
            rows.append(
                {
                    "symbol": symbol,
                    "figi": best.get("figi", ""),
                    "name": best.get("name", ""),
                    "security_type": best.get("securityType", ""),
                    "exch_code": best.get("exchCode", ""),
                    "composite_figi": best.get("compositeFIGI", ""),
                }
            )
        return pd.DataFrame(rows).set_index("symbol")

    def resolve_isins(self, isins: Sequence[str]) -> pd.DataFrame:
        """ISIN -> ticker. This direction is the reliable one."""
        jobs = [{"idType": "ID_ISIN", "idValue": i} for i in isins]
        rows = []
        for isin, data in zip(isins, self.map_identifiers(jobs)):
            best = data[0] if data else {}
            rows.append(
                {
                    "isin": isin,
                    "ticker": best.get("ticker", ""),
                    "figi": best.get("figi", ""),
                    "exch_code": best.get("exchCode", ""),
                    "name": best.get("name", ""),
                }
            )
        return pd.DataFrame(rows).set_index("isin")

    def resolve_sedols(self, sedols: Sequence[str]) -> pd.DataFrame:
        """SEDOL -> ticker. The UK-native identifier; use it for LSE names."""
        jobs = [{"idType": "ID_SEDOL", "idValue": s} for s in sedols]
        rows = []
        for sedol, data in zip(sedols, self.map_identifiers(jobs)):
            best = data[0] if data else {}
            rows.append({"sedol": sedol, "ticker": best.get("ticker", ""), "figi": best.get("figi", "")})
        return pd.DataFrame(rows).set_index("sedol")
