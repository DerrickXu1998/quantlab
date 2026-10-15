"""Which symbols get one of the account's market-data lines.

A lease is one consumer's claim on a symbol (live_subscriptions); a line is
what IBKR actually streams. Many leases on one symbol share one line. When
there are more symbols than lines, deployed strategies win over people
looking at charts, and among equals the earliest request wins -- so a chart
opened later cannot evict one already streaming.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Lease:
    subscription_id: int
    instrument_id: int
    symbol: str
    consumer: str  # 'deployment' | 'market'
    requested_at: datetime


@dataclass
class Plan:
    #: Symbols to stream, in priority order.
    lines: list[str] = field(default_factory=list)
    #: Symbols leased but left without a line.
    over_budget: set[str] = field(default_factory=set)


def plan_lines(leases: Iterable[Lease], max_lines: int, streaming: Iterable[str] = ()) -> Plan:
    """The symbols to stream within ``max_lines``.

    A symbol already ``streaming`` keeps its place ahead of newcomers of the
    same rank, so the plan does not churn lines every time a lease arrives.
    """
    current = set(streaming)
    best: dict[str, tuple] = {}
    for lease in leases:
        rank = (
            0 if lease.consumer == "deployment" else 1,
            0 if lease.symbol in current else 1,
            lease.requested_at,
            lease.symbol,
        )
        if lease.symbol not in best or rank < best[lease.symbol]:
            best[lease.symbol] = rank
    ordered = sorted(best, key=lambda symbol: best[symbol])
    keep = max(0, max_lines)
    return Plan(lines=ordered[:keep], over_budget=set(ordered[keep:]))


def diff(streaming: Iterable[str], wanted: Iterable[str]) -> tuple[list[str], list[str]]:
    """(to_open, to_close), each sorted."""
    now, then = set(streaming), set(wanted)
    return sorted(then - now), sorted(now - then)
