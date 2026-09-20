"""FCA net short positions -- free, keyless UK disclosed short interest.

The FCA publishes one Excel workbook of every disclosed net short position
in UK issuers, updated daily (``Historic Disclosures``), covering 2013 to
the present::

    Position Holder | Name of Share Issuer | ISIN | Net Short Position (%) | Position Date

Each row is one holder's position in one issuer on one date, at the 0.2%
disclosure threshold, on a T+2 basis. This *is* short interest -- real money
publicly committed to a view -- and it is genuinely informative, unlike
FINRA's short volume. A 0.0% row means a previously disclosed position fell
below the threshold; it is kept, not dropped.

The file is ISIN-keyed and the warehouse catalog carries no ISINs (OpenFIGI
does not return them), so the ingest bridges on the issuer name -- see
``quantlab.store.shorts``. The matching is deliberately conservative, like
``map_ch_companies``.
"""
from __future__ import annotations

import io
import logging

import pandas as pd

from ..registry import provider
from ..schema import DataUnavailable, ProviderError
from .base import DataProvider

log = logging.getLogger(__name__)

FCA_AGGREGATE_URL = "https://www.fca.org.uk/publication/data/short-positions-daily-update.xlsx"

COLUMN_NAMES = ("holder", "issuer_name", "isin", "net_short_pct", "position_date")


def _find_column(columns, *needles: str) -> str | None:
    """First column whose lower-cased name contains any needle."""
    lowered = {str(c).strip().lower(): c for c in columns}
    for needle in needles:
        hit = next((lowered[c] for c in lowered if needle in c), None)
        if hit is not None:
            return hit
    return None


def parse_positions(blob: bytes) -> pd.DataFrame:
    """The FCA workbook -> one row per (holder, issuer, position date).

    Columns are located by name fragment rather than position because the
    FCA re-labels them occasionally. Rows without an ISIN, a position date
    or a numeric percentage cannot be placed and are dropped. Needs
    openpyxl (``pip install quantlab[excel]``).
    """
    try:
        sheets = pd.read_excel(io.BytesIO(blob), sheet_name=None)
    except ImportError as exc:
        raise ProviderError(
            "reading the FCA file needs openpyxl: pip install quantlab[excel]"
        ) from exc

    frames = []
    for sheet in sheets.values():
        holder_col = _find_column(sheet.columns, "position holder", "holder")
        issuer_col = _find_column(sheet.columns, "share issuer", "issuer")
        isin_col = _find_column(sheet.columns, "isin")
        pct_col = _find_column(sheet.columns, "net short", "position (%)")
        date_col = _find_column(sheet.columns, "position date", "date")
        if not (holder_col and isin_col and pct_col and date_col):
            continue
        frame = pd.DataFrame(
            {
                "holder": sheet[holder_col].astype(str).str.strip(),
                "issuer_name": sheet[issuer_col].astype(str).str.strip() if issuer_col else "",
                "isin": sheet[isin_col].astype(str).str.strip().str.upper(),
                "net_short_pct": pd.to_numeric(sheet[pct_col], errors="coerce"),
                "position_date": pd.to_datetime(sheet[date_col], errors="coerce"),
            }
        )
        frames.append(frame)
    if not frames:
        raise ProviderError("fca: could not locate holder / ISIN / position columns in the file")

    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["net_short_pct", "position_date"])
    out = out[out["isin"].str.len() == 12]
    out = out[out["holder"] != ""]
    out["position_date"] = out["position_date"].dt.normalize()
    return out.reset_index(drop=True)


@provider("fca")
class FcaProvider(DataProvider):
    name = "fca"
    requires_key = False
    licence_note = (
        "FCA daily net short position disclosures, keyless xlsx, T+2, 0.2% threshold. "
        "Real short interest."
    )

    def __init__(self, **opts):
        super().__init__(**opts)
        from ..http import HttpClient

        self.client = HttpClient("fca")

    def fetch_one(self, symbol, start, end, frequency="1d"):
        raise DataUnavailable("fca provides net short position disclosures, not equity bars")

    def net_short_positions(self) -> pd.DataFrame:
        """The full historic disclosure workbook, one row per disclosure.

        The file is a single daily-refreshed snapshot, cached 12h. History
        reaches 2013, so a re-fetch is a full re-pull -- the fundamentals
        identity (holder in the accession) keeps re-runs idempotent.
        """
        blob = self.client.get(FCA_AGGREGATE_URL, ttl=12 * 3600)
        frame = parse_positions(blob)
        if frame.empty:
            raise DataUnavailable("fca: disclosure file parsed to zero rows")
        return frame
