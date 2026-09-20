"""Historical replay: stream a stored run's window as if it were live.

Library logic, not route logic (Constitution I). The engine interleaves a
run's stored signals with the bars of its window in chronological order and
drives a PortfolioSimulator day by day, emitting typed events. Everything is a
pure function of the run record, its stored signals and the warehouse bars --
no I/O outside the loading seam, no wall-clock, no randomness (Constitution
VI). The signals arrive already stamped point-in-time, and the simulator only
ever transacts at the close of the signal date, so a replay can never see the
future either (Constitution VII).
"""

from quantlab.replay.engine import (
    ReplayBar,
    ReplayEquity,
    ReplayFill,
    ReplaySignal,
    ReplaySummary,
    load_replay_inputs,
    replay_events,
    replay_summary,
    to_dict,
)
from quantlab.replay.portfolio import Fill, PortfolioSimulator, PositionSnapshot

__all__ = [
    "Fill",
    "PortfolioSimulator",
    "PositionSnapshot",
    "ReplayBar",
    "ReplayEquity",
    "ReplayFill",
    "ReplaySignal",
    "ReplaySummary",
    "load_replay_inputs",
    "replay_events",
    "replay_summary",
    "to_dict",
]
