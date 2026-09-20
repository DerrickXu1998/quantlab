"""Strategies: several signals, combined, with execution criteria attached.

The unit a user actually onboards. ``signals`` says what fires, ``execution``
says what a firing does, and this package is the contract between them.
"""

from __future__ import annotations

from quantlab.strategy.compose import CompositionStats, compose
from quantlab.strategy.spec import (
    COMBINE_LOGIC,
    StrategyComponent,
    StrategySpec,
    StrategyValidationError,
    promote_legacy,
)
from quantlab.strategy.templates import TEMPLATE_IDS, catalogue, template

__all__ = [
    "COMBINE_LOGIC",
    "TEMPLATE_IDS",
    "CompositionStats",
    "StrategyComponent",
    "StrategySpec",
    "StrategyValidationError",
    "catalogue",
    "compose",
    "promote_legacy",
    "template",
]
