"""Point-in-time transforms over stored fundamental facts (feature 008).

Pure functions, no I/O (Constitutions I and VI): storage returns raw facts
(``quantlab.storage.warehouse.get_fundamental_facts``), and this module is
where ``filed_at`` becomes a visibility rule -- a fact is knowable from its
filing date onwards, never from the fiscal ``period_end`` it describes. That
asymmetry is the whole reason the table exists; a reader that filters on
period_end sees December's earnings in December, weeks before the filing.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any

#: Derived concepts are computed at read time from stored concepts, never
#: stored: a stored copy could drift from its inputs.
#: key -> (provider, numerator concept, denominator concept).
DERIVED_CONCEPTS: dict[str, tuple[str, str, str]] = {
    "short_volume_ratio": ("finra", "short_volume", "total_volume"),
}

TRANSFORMS: tuple[str, ...] = ("raw", "raw_facts", "yoy_growth")


def _parse(value: str) -> _date:
    return _date.fromisoformat(value)


def fetch_facts(
    store, symbol: str, concept: str, *, start: str | None = None
) -> tuple[list[dict], str]:
    """Facts for a concept, synthesizing derived ones from their stored inputs.

    Returns ``(facts, base_provenance)``. Facts are dicts with ``value``,
    ``period_start``, ``period_end``, ``filed_at``, ``provider``, ``unit`` and
    ``holder`` (None except for per-holder filings such as FCA short positions).
    ``start`` bounds the read to facts filed on or after that date (the
    runner's warm-up bound; facts earlier than it cannot affect a signal in
    the window).
    """
    if concept in DERIVED_CONCEPTS:
        provider, numerator, denominator = DERIVED_CONCEPTS[concept]
        facts = ratio_facts(
            store.get_fundamental_facts(symbol, numerator, start=start),
            store.get_fundamental_facts(symbol, denominator, start=start),
        )
        return facts, f"{provider} {numerator} / {denominator}, aligned per trade date"
    facts = store.get_fundamental_facts(symbol, concept, start=start)
    base = f"{facts[0]['provider']} facts as filed" if facts else "no stored facts"
    return facts, base


def ratio_facts(numerator_facts: list[dict], denominator_facts: list[dict]) -> list[dict]:
    """Synthesize per-date ratio facts (e.g. finra short_volume / total_volume).

    Both inputs are daily rows keyed by the trade date (filed_at == period_end),
    so alignment is exact. A date present on only one side is dropped, and a
    zero denominator is skipped rather than answered with inf.
    """
    denominator = {f["filed_at"]: f["value"] for f in denominator_facts}
    out: list[dict] = []
    for fact in numerator_facts:
        total = denominator.get(fact["filed_at"])
        if not total:
            continue
        out.append(
            {
                "value": fact["value"] / total,
                "period_start": fact["period_start"],
                "period_end": fact["period_end"],
                "filed_at": fact["filed_at"],
                "provider": fact["provider"],
                "unit": "ratio",
                "holder": None,
            }
        )
    return out


def as_of_series(
    facts: list[dict], *, start: str | None = None, end: str | None = None
) -> list[dict]:
    """The point-in-time series: on each date, what was knowable by then.

    Emits a step series at filing dates. Facts carrying a ``holder`` (FCA
    short positions) are aggregated per holder first -- each holder's latest
    filing as of the date persists until they file again -- then summed across
    holders. Without holders, the latest filing on or before the date wins.

    With ``start``, an opening point is emitted at ``start`` carrying the
    value knowable as of that date (the latest filing before it), so a windowed
    read does not silently start from the first filing inside the window.
    """
    per_holder = any(fact.get("holder") for fact in facts)
    points: list[dict] = []
    if per_holder:
        latest_by_holder: dict[str, float] = {}
        for day in sorted({fact["filed_at"] for fact in facts}):
            for fact in facts:
                if fact["filed_at"] == day:
                    latest_by_holder[fact["holder"]] = fact["value"]
            points.append({"date": day, "value": sum(latest_by_holder.values())})
    else:
        for day in sorted({fact["filed_at"] for fact in facts}):
            day_facts = [fact for fact in facts if fact["filed_at"] == day]
            # The last row of the day, in fetch order: a deterministic winner
            # when one date carries several filings of the same concept.
            points.append({"date": day, "value": day_facts[-1]["value"]})

    in_window = [
        point
        for point in points
        if (start is None or point["date"] >= start) and (end is None or point["date"] <= end)
    ]
    if start is not None:
        earlier = [point for point in points if point["date"] < start]
        if earlier and (not in_window or in_window[0]["date"] != start):
            in_window.insert(0, {"date": start, "value": earlier[-1]["value"]})
    return in_window


def yoy_growth(points: list[dict]) -> list[dict]:
    """Year-over-year change of an as-of series: value(d) / value(d-1y) - 1.

    The base is the series' as-of value one year earlier -- a step lookup, not
    a calendar guess. Points with no base a year back, or a zero base, are
    dropped rather than answered with a fabricated number.
    """
    out: list[dict] = []
    for point in points:
        day = _parse(point["date"])
        try:
            target = day.replace(year=day.year - 1)
        except ValueError:  # Feb 29 -> Feb 28
            target = day.replace(year=day.year - 1, day=28)
        base = None
        for candidate in points:
            if candidate["date"] <= target.isoformat():
                base = candidate["value"]
            else:
                break
        if not base:
            continue
        out.append({"date": point["date"], "value": point["value"] / base - 1.0})
    return out


def build_series(
    symbol: str,
    concept: str,
    transform: str,
    facts: list[dict],
    base_provenance: str,
    *,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """The series response payload for one transform over one concept's facts.

    ``point_in_time`` is true for every transform, including raw_facts: raw
    rows are still stamped at filed_at, and the flag is the UI's cue that
    period_end must never be used as a visibility axis. The provenance string
    says exactly how the numbers were produced, so it travels with them.
    """
    if any(fact.get("holder") for fact in facts):
        base_provenance += "; per-holder filings summed across holders per date"

    if transform == "raw_facts":
        items = [
            fact
            for fact in facts
            if (start is None or fact["filed_at"] >= start)
            and (end is None or fact["filed_at"] <= end)
        ]
        provenance = f"{base_provenance}; rows as filed, ascending by filed_at"
    elif transform == "raw":
        items = as_of_series(facts, start=start, end=end)
        provenance = (
            f"{base_provenance}; as-of by filed_at: a fact is knowable from its "
            "filing date, latest filing wins"
        )
    elif transform == "yoy_growth":
        items = yoy_growth(as_of_series(facts, start=None, end=end))
        if start is not None:
            items = [point for point in items if point["date"] >= start]
        provenance = f"{base_provenance}; year-over-year change of the filed_at as-of series"
    else:
        raise ValueError(f"unknown transform {transform!r}; expected one of {TRANSFORMS}")

    return {
        "symbol": symbol,
        "concept": concept,
        "transform": transform,
        "point_in_time": True,
        "provenance": provenance,
        "total": len(items),
        "items": items,
    }
