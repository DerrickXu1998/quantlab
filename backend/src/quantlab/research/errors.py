"""Typed failures the API layer maps to responses.

Kept out of the route so the runner stays testable without HTTP (Constitution I)
and so the mapping from cause to status code lives in exactly one place.
"""

from __future__ import annotations


class ExperimentError(Exception):
    """Base for anything that prevents a run from being attempted."""


class UnknownModelError(ExperimentError):
    def __init__(self, model_name: str, model_version: str | None = None) -> None:
        self.model_name = model_name
        self.model_version = model_version
        target = f"{model_name} v{model_version}" if model_version else model_name
        super().__init__(f"unknown model: {target}")


class UnknownSymbolError(ExperimentError):
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols
        super().__init__(f"unknown symbol(s): {', '.join(sorted(symbols))}")


class ParameterValidationError(ExperimentError):
    """Carries the offending parameter so the UI can report against that field
    rather than as a form-level banner."""

    def __init__(self, parameter: str, message: str) -> None:
        self.parameter = parameter
        super().__init__(f"{parameter}: {message}")


class InvalidWindowError(ExperimentError):
    pass


class WindowTooShortError(ExperimentError):
    """The requested window is shorter than the model's lookback.

    Rejected rather than run, because a run that returns nothing is
    indistinguishable to a researcher from a model that found nothing.
    """

    def __init__(self, lookback_days: int, window_days: int) -> None:
        self.lookback_days = lookback_days
        self.window_days = window_days
        super().__init__(
            f"window of {window_days} calendar days is shorter than the model's "
            f"lookback of {lookback_days} bars; widen the date range"
        )


class SelectionTooLargeError(ExperimentError):
    def __init__(self, requested: int, limit: int) -> None:
        self.requested = requested
        self.limit = limit
        super().__init__(
            f"selection of {requested} instrument-days exceeds the limit of {limit}"
        )
