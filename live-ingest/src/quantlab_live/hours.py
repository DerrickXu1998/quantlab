"""Is the regular session open? From IBKR's own trading hours.

``ContractDetails.liquidHours`` lists sessions in the contract's time zone,
holidays and half-days included::

    20261015:0930-20261015:1600;20261016:0930-20261016:1600;20261017:CLOSED

Reading the exchange's calendar from IBKR means quantlab keeps no holiday
table of its own to fall out of date.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

#: IBKR's legacy zone ids, as ContractDetails.timeZoneId reports them.
_ZONES = {"US/Eastern": "America/New_York", "EST5EDT": "America/New_York"}


def sessions(liquid_hours: str, time_zone_id: str) -> list[tuple[datetime, datetime]]:
    """Every open interval in ``liquid_hours``, as aware datetimes."""
    zone = ZoneInfo(_ZONES.get(time_zone_id, time_zone_id or "America/New_York"))
    out: list[tuple[datetime, datetime]] = []
    for part in liquid_hours.split(";"):
        part = part.strip()
        if not part or part.endswith("CLOSED") or "-" not in part:
            continue
        start, end = part.split("-", 1)
        try:
            opened = datetime.strptime(start, "%Y%m%d:%H%M").replace(tzinfo=zone)
            closed = datetime.strptime(end, "%Y%m%d:%H%M").replace(tzinfo=zone)
        except ValueError:
            continue
        out.append((opened, closed))
    return out


def market_state(liquid_hours: str, time_zone_id: str, now: datetime) -> str:
    """``open`` inside a listed session, else ``closed``."""
    return (
        "open" if any(a <= now < b for a, b in sessions(liquid_hours, time_zone_id)) else "closed"
    )
