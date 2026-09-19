"""Universe contract: what counts as "all listed companies" on an exchange."""
from __future__ import annotations

import abc

import pandas as pd

from ..schema import Security


class UniverseSource(abc.ABC):
    name: str = "base"
    exchanges: tuple[str, ...] = ()
    licence_note: str = ""

    def __init__(self, **options):
        self.options = options

    @abc.abstractmethod
    def securities(self) -> list[Security]:
        """Return every security in the universe."""

    def symbols(self) -> list[str]:
        return [s.symbol for s in self.securities()]

    def to_frame(self) -> pd.DataFrame:
        rows = [
            {
                "symbol": s.symbol, "name": s.name, "exchange": s.exchange,
                "country": s.country, "currency": s.currency.value,
                "sector": s.sector, "isin": s.isin, "sedol": s.sedol,
                "cik": s.cik, "company_number": s.company_number, "active": s.active,
            }
            for s in self.securities()
        ]
        return pd.DataFrame(rows).set_index("symbol") if rows else pd.DataFrame()
