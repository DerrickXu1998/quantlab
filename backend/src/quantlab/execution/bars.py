"""Intraday bars, stored as columns rather than objects.

A daily run holds a few thousand bars per symbol and can afford one Python
object each. An intraday one cannot: 2M bars as objects measured ~550 MB, past
what a backend worker may use. :class:`BarSeries` keeps the same OHLCV in NumPy
arrays (~48 B a bar) and hands out a small :class:`SeriesBar` only when a rule
or the engine asks for one, so every rule written against ``bars[i].close``
runs unchanged.

Keys. A bar's ``date`` is its exchange-local start, ``YYYY-MM-DDTHH:MM``.
It sorts with the daily ``YYYY-MM-DD`` keys and against ex-dates as strings,
so splits, dividends and decisions line up without special cases. Daily data
read from an intraday bar -- fundamentals, macro series -- is taken as of the
previous session (:func:`as_of_day`): a daily close is not known at 09:30.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date, timedelta
from typing import Any

import numpy as np

#: Signal bar frequencies, and how many bars a regular session holds. The 1h
#: buckets are clock hours, so the first is the half hour 09:30-10:00.
BAR_FREQUENCIES: tuple[str, ...] = ("1d", "1h", "15m", "5m")
BARS_PER_SESSION: dict[str, int] = {"1d": 1, "1h": 7, "15m": 26, "5m": 78}
SESSIONS_PER_YEAR = 252


def is_intraday(frequency: str) -> bool:
    return frequency != "1d"


def as_of_day(key: str) -> str:
    """The last date whose *daily* data a bar keyed ``key`` may read.

    A daily bar is evaluated at its close, so it sees its own date. An
    intraday bar is evaluated during the session, before that day's close or
    any filing dated that day could be known, so it sees the previous date.
    """
    if len(key) <= 10:
        return key
    return (date.fromisoformat(key[:10]) - timedelta(days=1)).isoformat()


class SeriesBar:
    """One bar of a :class:`BarSeries`, made on demand."""

    __slots__ = ("close", "date", "high", "low", "open", "raw_close", "volume")

    def __init__(self, key, o, h, lo, c, v, raw):
        self.date = key
        self.open = o
        self.high = h
        self.low = lo
        self.close = c
        self.volume = v
        self.raw_close = raw

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"SeriesBar({self.date} o={self.open} h={self.high} l={self.low} c={self.close})"


class BarSeries(Sequence):
    """One instrument's bars as columns: ``stamps`` and float64
    ``open/high/low/close``, int64 ``volume``.

    ``stamps`` are datetime64[m] (exchange-local bar starts) for intraday bars
    and datetime64[D] for daily ones, so a bar's key is ``YYYY-MM-DDTHH:MM``
    or ``YYYY-MM-DD`` -- exactly the key a row-wise bar of either kind has.

    ``raw_close`` is the traded close when the prices have been back-adjusted
    (``adjustments.adjust``); otherwise it is ``close`` itself.
    """

    __slots__ = ("close", "high", "low", "open", "raw_close", "stamps", "volume")

    def __init__(self, stamps, open_, high, low, close, volume, raw_close=None):
        stamps = np.asarray(stamps)
        self.stamps = stamps if stamps.dtype.kind == "M" else stamps.astype("datetime64[m]")
        self.open = np.asarray(open_, dtype=float)
        self.high = np.asarray(high, dtype=float)
        self.low = np.asarray(low, dtype=float)
        self.close = np.asarray(close, dtype=float)
        self.volume = np.asarray(volume, dtype=np.int64)
        self.raw_close = self.close if raw_close is None else np.asarray(raw_close, dtype=float)

    def __len__(self) -> int:
        return len(self.stamps)

    def key(self, i: int) -> str:
        return str(self.stamps[i])

    def __getitem__(self, i: Any) -> Any:
        if isinstance(i, slice):
            return BarSeries(
                self.stamps[i], self.open[i], self.high[i], self.low[i],
                self.close[i], self.volume[i], self.raw_close[i],
            )
        return SeriesBar(
            str(self.stamps[i]),
            float(self.open[i]),
            float(self.high[i]),
            float(self.low[i]),
            float(self.close[i]),
            int(self.volume[i]),
            float(self.raw_close[i]),
        )

    def __iter__(self) -> Iterator[SeriesBar]:
        for i in range(len(self)):
            yield self[i]

    def column(self, name: str) -> np.ndarray:
        return getattr(self, name)

    def scaled(self, price: np.ndarray, volume: np.ndarray) -> BarSeries:
        """Prices x ``price``, volume x ``volume``; the traded close is kept."""
        return BarSeries(
            self.stamps,
            self.open * price,
            self.high * price,
            self.low * price,
            self.close * price,
            np.rint(self.volume * volume).astype(np.int64),
            self.raw_close,
        )

    def within(self, start: str | None, end: str | None) -> BarSeries:
        """Bars whose session date is in [start, end]."""
        days = self.stamps.astype("datetime64[D]")
        mask = np.ones(len(self), dtype=bool)
        if start is not None:
            mask &= days >= np.datetime64(start[:10])
        if end is not None:
            mask &= days <= np.datetime64(end[:10])
        return self._take(np.flatnonzero(mask)) if not mask.all() else self

    def sessions(self) -> list[SeriesBar]:
        """One daily bar per session: first open, high, low, last close.

        For whatever is measured per session -- the buy-and-hold benchmark
        beside an equity curve that is itself one mark per session.
        """
        n = len(self)
        if not n:
            return []
        days = self.stamps.astype("datetime64[D]")
        starts = np.concatenate([[0], np.flatnonzero(days[1:] != days[:-1]) + 1])
        ends = np.concatenate([starts[1:], [n]]) - 1
        high = np.maximum.reduceat(self.high, starts)
        low = np.minimum.reduceat(self.low, starts)
        volume = np.add.reduceat(self.volume, starts)
        return [
            SeriesBar(
                str(days[s]),
                float(self.open[s]),
                float(high[k]),
                float(low[k]),
                float(self.close[e]),
                int(volume[k]),
                float(self.raw_close[e]),
            )
            for k, (s, e) in enumerate(zip(starts.tolist(), ends.tolist(), strict=True))
        ]

    def _take(self, index: np.ndarray) -> BarSeries:
        return BarSeries(
            self.stamps[index], self.open[index], self.high[index], self.low[index],
            self.close[index], self.volume[index], self.raw_close[index],
        )


def column(bars: Sequence[Any], name: str) -> np.ndarray:
    """One OHLCV field of any bar sequence as a float array."""
    if isinstance(bars, BarSeries):
        return bars.column(name).astype(float)
    return np.array([getattr(b, name) for b in bars], dtype=float)


def unit_of(bars: BarSeries) -> str:
    """``"m"`` for intraday stamps, ``"D"`` for daily."""
    return np.datetime_data(bars.stamps.dtype)[0]


def first_at_or_after(bars: Sequence[Any], day: str) -> int:
    """Index of the first bar on or after ``day`` (a date), any frequency."""
    if isinstance(bars, BarSeries):
        boundary = np.datetime64(day[:10]).astype(bars.stamps.dtype)
        return int(np.searchsorted(bars.stamps, boundary, side="left"))
    from bisect import bisect_left

    return bisect_left([b.date for b in bars], day)
