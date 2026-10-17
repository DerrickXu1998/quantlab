"""Roll ticks into closed 1-minute bars.

IBKR's ``reqMktData`` sends throttled snapshots (~250 ms for US stocks), not
every trade, so a rolled minute's high and low can fall inside the true ones.
That is fine for what these are for -- drawing today's chart -- and why they
are marked ``kind = 'rolled'`` and never read by a backtest.

The first minute after a line opens is dropped: it saw only the ticks since
the subscription, and the backfill already holds IBKR's own (fuller) bar for
it. Volume is the difference of IBKR's cumulative session volume.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Open:
    start: int  # unix seconds of the minute's start
    open: float
    high: float
    low: float
    close: float
    volume_at_start: float | None
    volume_now: float | None


def minute_of(ts: float) -> int:
    return int(ts // 60) * 60


class MinuteRoller:
    """One symbol's forming minute; emits the minute when it closes."""

    def __init__(self) -> None:
        self._open: _Open | None = None
        self._first_minute: int | None = None
        self._last_volume: float | None = None

    def add(self, price: float, cumulative_volume: float | None, ts: float) -> dict | None:
        """Fold one tick in. Returns the previous minute if this tick closed it."""
        start = minute_of(ts)
        if self._first_minute is None:
            self._first_minute = start
        closed = None
        if self._open is not None and start > self._open.start:
            closed = self._close()
        if self._open is None:
            # The new minute starts where the last one ended, when that is known.
            base = self._last_volume if self._last_volume is not None else cumulative_volume
            self._open = _Open(start, price, price, price, price, base, cumulative_volume)
        elif start == self._open.start:
            bar = self._open
            bar.high = max(bar.high, price)
            bar.low = min(bar.low, price)
            bar.close = price
            if cumulative_volume is not None:
                bar.volume_now = cumulative_volume
        return closed

    def flush(self, now: float) -> dict | None:
        """Close the open minute once the clock has passed it, ticks or not."""
        if self._open is not None and minute_of(now) > self._open.start:
            return self._close()
        return None

    def _close(self) -> dict | None:
        bar, self._open = self._open, None
        assert bar is not None
        if bar.volume_now is not None:
            self._last_volume = bar.volume_now
        if bar.start == self._first_minute:
            return None
        volume = 0
        if bar.volume_now is not None and bar.volume_at_start is not None:
            volume = max(0, int(bar.volume_now - bar.volume_at_start))
        return {
            "start": bar.start,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": volume,
        }
