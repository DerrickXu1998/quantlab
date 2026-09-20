"""Execution: the layer that turns a strategy's decisions into trades.

Kept separate from ``signals`` (what to do) and from ``research`` (how it did)
because the three change for different reasons. A new indicator is a signals
change; a new stop type is an execution change; a new statistic is a research
change, and none of them should force the other two to be re-tested.
"""

from __future__ import annotations

from quantlab.execution.config import (
    BPS,
    DEFAULT_EXECUTION,
    EXIT_REASONS,
    FILL_TIMING,
    INITIAL_CAPITAL,
    POSITION_SIZING,
    ExecutionConfig,
)
from quantlab.execution.engine import (
    DayState,
    Decision,
    EquityPoint,
    ExecutedTrade,
    ExecutionResult,
    ExecutionSimulator,
    ExecutionSummary,
    Fill,
    simulate,
)

__all__ = [
    "BPS",
    "DEFAULT_EXECUTION",
    "EXIT_REASONS",
    "FILL_TIMING",
    "INITIAL_CAPITAL",
    "POSITION_SIZING",
    "DayState",
    "Decision",
    "EquityPoint",
    "ExecutedTrade",
    "ExecutionConfig",
    "ExecutionResult",
    "ExecutionSimulator",
    "ExecutionSummary",
    "Fill",
    "simulate",
]
