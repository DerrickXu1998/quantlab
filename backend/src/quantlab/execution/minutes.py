"""Minute bars for execution: what happens between the open and the close.

Signals are daily. With ``intraday_resolution="minute"`` the engine consults
one session's minute bars only where they change an answer the daily bar
cannot give -- which of a stop and a target was crossed first, at what time,
and the session's real volume-weighted price. Opens and closes stay the daily
bar's: they are auction prices, and the minute feed's first and last prints
are not (measured: IEX's first print sits a median 0.17% from the official
open).

The engine never does I/O. It is handed a :data:`MinuteSource` -- a callable
from (symbol, date) to that session's bars -- and the runner supplies one that
reads the warehouse lazily, a symbol-month at a time, so a run touches only
the sessions an order or a protective level actually lands in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MinuteBar:
    """One minute of one session. ``time`` is exchange-local, ``HH:MM``."""

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


#: (symbol, ISO date) -> that session's minute bars, ascending; empty when the
#: store has none for it.
MinuteSource = Callable[[str, str], list[MinuteBar]]


def vwap(minutes: list[MinuteBar]) -> float | None:
    """Volume-weighted average of each minute's typical price.

    Only the minutes' relative volumes matter, so a feed that sees a fraction
    of all trading (IEX) still gives the session's shape. A session with no
    volume at all averages the typical prices evenly; no minutes, no answer.
    """
    if not minutes:
        return None
    typical = [(m.high + m.low + m.close) / 3.0 for m in minutes]
    volume = sum(m.volume for m in minutes)
    if volume <= 0:
        return sum(typical) / len(typical)
    return sum(t * m.volume for t, m in zip(typical, minutes, strict=True)) / volume


class MonthlyMinuteCache:
    """A :data:`MinuteSource` over a store, loading one symbol-month per miss.

    A month of one symbol is ~8,000 rows: small enough to stay well inside
    the bar store's per-query memory cap, large enough that a position held
    for weeks costs one read rather than one per session.
    ``load(symbol, first_day, last_day)`` returns ``{date: [MinuteBar, ...]}``.
    """

    def __init__(self, load: Callable[[str, str, str], dict[str, list[MinuteBar]]]) -> None:
        self._load = load
        self._months: dict[tuple[str, str], dict[str, list[MinuteBar]]] = {}

    def __call__(self, symbol: str, date: str) -> list[MinuteBar]:
        month = date[:7]
        key = (symbol, month)
        if key not in self._months:
            self._months[key] = self._load(symbol, f"{month}-01", _month_end(month))
        return self._months[key].get(date, [])


def source_for(backend: Any, config: Any) -> MinuteSource | None:
    """The minute source a run under ``config`` needs, or None for daily runs."""
    if getattr(config, "intraday_resolution", "daily") != "minute":
        return None
    return MonthlyMinuteCache(backend.minute_bars)


def _month_end(month: str) -> str:
    year, number = (int(part) for part in month.split("-"))
    if number == 12:
        return f"{year}-12-31"
    from datetime import date, timedelta

    return (date(year, number + 1, 1) - timedelta(days=1)).isoformat()
