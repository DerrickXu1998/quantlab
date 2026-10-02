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

    def __init__(self, parameter: str, message: str, *, qualified: bool = False) -> None:
        self.parameter = parameter
        # A qualified message already says what it is about -- a strategy
        # error names its own path -- so prefixing the field again would read
        # "fast: components[0].parameters.fast: ..." or, with no path at all,
        # repeat the whole sentence twice.
        super().__init__(message if qualified else f"{parameter}: {message}")


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


class IntradaySelectionTooLargeError(SelectionTooLargeError):
    """An intraday run past the bar budget, refused before anything is read."""

    def __init__(self, requested: int, limit: int, frequency: str) -> None:
        ExperimentError.__init__(
            self,
            f"about {requested:,} {frequency} bars exceeds the limit of {limit:,} per run; "
            "use a coarser frequency, fewer symbols or a shorter window",
        )
        self.requested = requested
        self.limit = limit
        self.frequency = frequency


class IntradayBusyError(ExperimentError):
    """Another intraday run holds this worker's slot; try again shortly."""

    def __init__(self) -> None:
        super().__init__(
            "another intraday run is in progress on this server; try again in a minute"
        )


class DatasetUnsupportedError(ExperimentError):
    """The resolved rule needs data the active dataset does not hold.

    A fundamental-condition rule against the synthetic demo is the case this
    exists for: the demo has no filings, so every gate would read shut and the
    run would look like a strategy that simply never fired. A refusal names the
    cause; an empty result hides it.
    """

    def __init__(self, requirement: str, dataset: str) -> None:
        self.requirement = requirement
        self.dataset = dataset
        super().__init__(
            f"model requires {requirement}, which the {dataset} dataset does not have"
        )


class NoFactCoverageError(ExperimentError):
    """None of the selection has filed anything the run's rules read.

    The warehouse counterpart of :class:`DatasetUnsupportedError`: the store
    has fundamentals, just none for these names by the window's end -- a
    UK-only selection against a valuation filter, say (docs/ROADMAP.md, data
    gaps). Refused for the same reason: an empty result would hide the cause.
    """

    def __init__(self, concepts: list[str], instruments: int, end_date: str) -> None:
        self.concepts = list(concepts)
        self.instruments = instruments
        self.end_date = end_date
        super().__init__(
            f"none of the {instruments} selected instruments has any filing for "
            f"{', '.join(concepts)} on or before {end_date}, so every fundamental "
            "gate in this strategy would stay shut"
        )
