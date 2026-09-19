"""Provider contract.

A provider does one job: turn symbols and a date range into canonical bars, or
turn identifiers into fundamentals. Everything else -- caching, rate limiting,
retries, currency handling -- is the framework's job, so an adapter stays
short. The smallest useful provider is about 20 lines; see ``csvfile.py``.
"""
from __future__ import annotations

import abc
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Sequence

import pandas as pd

from ..config import settings
from ..schema import DataUnavailable, Security, empty_bars, validate_bars

log = logging.getLogger(__name__)


class DataProvider(abc.ABC):
    """Base class for every price/reference data source."""

    #: short id, must match the entry-point name
    name: str = "base"
    #: which exchange suffixes this provider can serve; empty means "any"
    supports: tuple[str, ...] = ()
    #: whether an API key is required
    requires_key: bool = False
    #: free-text note surfaced by `quantlab sources`
    licence_note: str = ""

    def __init__(self, **options: Any):
        self.options = options

    # -- required ----------------------------------------------------------
    @abc.abstractmethod
    def fetch_one(self, symbol: str, start: str, end: str, frequency: str = "1d") -> pd.DataFrame:
        """Return canonical bars for one symbol. Raise DataUnavailable if none."""

    # -- optional ----------------------------------------------------------
    def fetch(
        self,
        symbols: Sequence[str],
        start: str,
        end: str = "",
        frequency: str = "1d",
        *,
        max_workers: int | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch many symbols. Override if the source has a bulk endpoint."""
        workers = max_workers or settings().max_workers

        def one(sym: str) -> tuple[str, pd.DataFrame]:
            try:
                return sym, validate_bars(self.fetch_one(sym, start, end, frequency), symbol=sym)
            except DataUnavailable:
                return sym, empty_bars()
            except Exception as exc:
                log.warning("%s: %s failed: %s", self.name, sym, exc)
                return sym, empty_bars()

        if workers > 1 and len(symbols) > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                return dict(pool.map(one, symbols))
        return dict(one(s) for s in symbols)

    def securities(self, symbols: Sequence[str]) -> dict[str, Security]:
        """Reference data. Default: nothing known."""
        return {}

    def corporate_actions(self, symbol: str, start: str, end: str = "") -> pd.DataFrame:
        """Dividends and splits. Columns: date index, `dividend`, `split_ratio`."""
        raise NotImplementedError(f"{self.name} does not supply corporate actions")

    def fundamentals(self, symbols: Sequence[str], concepts: Sequence[str], *, ctx: Any = None) -> pd.DataFrame:
        """Point-in-time fundamentals indexed by (filed_date, symbol)."""
        raise NotImplementedError(f"{self.name} does not supply fundamentals")

    def to_native(self, symbol: str) -> str:
        """Map a canonical quantlab symbol to this vendor's convention."""
        return symbol

    def health(self) -> dict[str, Any]:
        """Cheap self-check used by `quantlab doctor`."""
        return {"provider": self.name, "requires_key": self.requires_key, "ok": True}


# Canonical suffix -> what each vendor calls it. Keeping this in one place is
# what lets you swap providers without rewriting your symbol lists.
SUFFIX_MAP: dict[str, dict[str, str]] = {
    "US":  {"stooq": "us",  "yahoo": "",    "sec_edgar": ""},
    "LON": {"stooq": "uk",  "yahoo": "L",   "companies_house": ""},
    "L":   {"stooq": "uk",  "yahoo": "L"},
}


def map_suffix(symbol: str, vendor: str) -> str:
    if "." not in symbol:
        return symbol
    root, suffix = symbol.rsplit(".", 1)
    mapped = SUFFIX_MAP.get(suffix.upper(), {}).get(vendor)
    if mapped is None:
        return symbol
    return f"{root}.{mapped}" if mapped else root
