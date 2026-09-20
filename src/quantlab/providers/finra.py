"""FINRA daily short sale volume -- free, keyless US short volume files.

One pipe-delimited flat file per trading day, published by ~18:00 ET on the
trade date and kept on the CDN for years (verified back to 2018-08 in
2026-09). This is short *volume*, not short *interest*: it counts shares
sold short intraday, most of which is market-making. 40-50% of total volume
is normal -- read the z-score, not the level.

File shape (one row per symbol, a bare record-count line at the end)::

    Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
    20260918|A|633386.346426|17|915680.398509|B,Q,N
    ...
    12315

Class shares use the exchange's slash spelling (``BRK/A``); volumes can be
fractional. An absent file (weekend, holiday, not yet published) comes back
as an HTTP 403, not a 404.
"""
from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from ..registry import provider
from ..schema import DataUnavailable, ProviderError
from .base import DataProvider

log = logging.getLogger(__name__)

CNMS_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"

_EXPECTED_FIELDS = 6


def parse_shvol(text: str) -> list[dict]:
    """One CNMSshvol file -> one dict per symbol row.

    The header, the trailing record-count line and any malformed row are
    skipped, never fatal -- the file is a vendor flat file, not a contract.
    Rows whose volumes are not numeric are dropped the same way.
    """
    rows: list[dict] = []
    for line in text.splitlines():
        fields = [f.strip() for f in line.split("|")]
        if len(fields) != _EXPECTED_FIELDS:
            # Header (starts "Date") and the numeric footer both land here.
            continue
        day, symbol, short, exempt, total, market = fields
        if day.lower() == "date" or not symbol:
            continue
        try:
            short_v, exempt_v, total_v = float(short), float(exempt), float(total)
        except ValueError:
            continue
        if len(day) == 8 and day.isdigit():
            trade_date = dt.date(int(day[:4]), int(day[4:6]), int(day[6:8]))
        else:
            continue
        rows.append(
            {
                "date": trade_date,
                "symbol": symbol,
                "short_volume": short_v,
                "short_exempt_volume": exempt_v,
                "total_volume": total_v,
                "market": market,
            }
        )
    return rows


@provider("finra")
class FinraProvider(DataProvider):
    name = "finra"
    requires_key = False
    licence_note = (
        "Official FINRA RegSHO daily files, keyless; no published rate limit. "
        "Short volume, not short interest."
    )

    def __init__(self, **opts):
        super().__init__(**opts)
        from ..http import HttpClient

        self.client = HttpClient("finra")

    def fetch_one(self, symbol, start, end, frequency="1d"):
        raise DataUnavailable("finra provides daily short volume files, not equity bars")

    def short_volume_day(self, day: str | dt.date) -> pd.DataFrame:
        """One trading day's short volume for every reported symbol.

        Raises ``DataUnavailable`` when no file exists for the day -- a
        weekend, a market holiday, or a file not yet published. That is the
        expected case, not an error. Historical files never change and are
        cached forever; today's file is cached 12h in case FINRA corrects it.
        """
        day = pd.Timestamp(day).date()
        url = CNMS_URL.format(date=day.strftime("%Y%m%d"))
        ttl = 12 * 3600 if day >= dt.datetime.now(dt.timezone.utc).date() else -1
        try:
            text = self.client.get_text(url, ttl=ttl)
        except ProviderError as exc:
            # The CDN answers a missing file with 403, not 404.
            if "HTTP 403" in str(exc) or "HTTP 404" in str(exc):
                raise DataUnavailable(f"finra: no short volume file for {day}") from exc
            raise
        rows = parse_shvol(text)
        if not rows:
            raise DataUnavailable(f"finra: empty short volume file for {day}")
        return pd.DataFrame(rows)
