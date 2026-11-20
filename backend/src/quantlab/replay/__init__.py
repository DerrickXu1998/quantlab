"""Historical replay: stream a stored run's window as if it were live.

A completed run's replay is *recorded* (``replay.recording``) when the run
finishes and only read afterwards: re-simulating it later would use today's
bars, which can have changed since the run executed. ``replay_events`` is what
produces that record (and reconstructs one, once, for a run that predates it).

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
    to_dict,
)
from quantlab.replay.portfolio import Fill, PortfolioSimulator, PositionSnapshot
from quantlab.replay.recording import RecordedReplay, playback, record

__all__ = [
    "Fill",
    "PortfolioSimulator",
    "PositionSnapshot",
    "RecordedReplay",
    "ReplayBar",
    "ReplayEquity",
    "ReplayFill",
    "ReplaySignal",
    "ReplaySummary",
    "load_replay_inputs",
    "playback",
    "record",
    "replay_events",
    "to_dict",
]
