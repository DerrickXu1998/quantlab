"""Pydantic v2 response models mirroring contracts/openapi.yaml exactly."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Dataset = Literal["sqlite", "warehouse"]
"""Which store answered. Two runs from different datasets are never directly
comparable, however identical their configuration."""


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    dataset: Dataset
    seeded: bool
    signal_count: int


class Instrument(BaseModel):
    symbol: str
    name: str
    currency: str
    # Synthetic-demo only: a generated instrument is built to follow a known
    # regime, which is what makes the demo assertable. Real ingested
    # instruments have no such label, so the field is nullable rather than
    # carrying a fabricated one.
    regime_profile: Literal["trending", "mean_reverting", "volatile", "mixed"] | None = None
    bar_count: int
    signal_count: int


class InstrumentList(BaseModel):
    total: int
    items: list[Instrument]


class PriceBar(BaseModel):
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class PriceBarList(BaseModel):
    total: int
    items: list[PriceBar]


class Signal(BaseModel):
    id: int
    symbol: str
    date: str
    rule_name: str
    rule_version: str
    parameters: dict[str, Any]
    direction: Literal["bullish", "bearish"]
    trigger_values: dict[str, Any]
    data_window_end: str


class SignalList(BaseModel):
    total: int
    items: list[Signal]


class Error(BaseModel):
    detail: str


# --- Model catalog and experiment runs (feature 005) -----------------------


class ParamSpec(BaseModel):
    name: str
    type: Literal["int", "float", "bool", "enum"]
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    choices: list[Any] | None = None
    description: str = ""


class Model(BaseModel):
    name: str
    version: str
    parameters: list[ParamSpec]
    lookback_days: int
    scale_class: Literal["scale_free", "price_scaled"]
    direction_semantics: str


class ModelList(BaseModel):
    total: int
    items: list[Model]


class RunRequest(BaseModel):
    model_name: str
    model_version: str | None = None
    parameters: dict[str, Any] = {}
    symbols: list[str]
    start_date: str
    end_date: str


class CorporateActionNotice(BaseModel):
    """A split or dividend inside a run's window. Reported, never applied:
    stored bars are unadjusted, so a split makes the series jump in a way that
    is an artefact rather than a market move."""

    instrument_id: int
    symbol: str
    ex_date: str
    action_type: Literal["split", "dividend"]
    split_ratio: float | None = None
    dividend: float | None = None


class RunCoverage(BaseModel):
    instruments_requested: int
    instruments_with_data: int
    instruments_full_warmup: int


class Run(BaseModel):
    id: str
    name: str | None = None
    model_name: str
    model_version: str
    parameters: dict[str, Any]
    symbols: list[str]
    start_date: str
    end_date: str
    status: Literal["completed", "failed"]
    error: str | None = None
    created_at: str
    signal_count: int
    coverage: RunCoverage
    dataset: Dataset
    instrument_ids: list[int] | None = None
    ingest_run_ids: list[int] | None = None
    corporate_actions: list[CorporateActionNotice] = []
    re_runnable: bool = True
    model_available: bool = True


class RunList(BaseModel):
    total: int
    items: list[Run]


class ExperimentSignal(BaseModel):
    symbol: str
    date: str
    direction: Literal["bullish", "bearish"]
    trigger_values: dict[str, Any]
    data_window_end: str


class RunDetail(Run):
    signals: list[ExperimentSignal]


class RunNameRequest(BaseModel):
    name: str


class EquityPoint(BaseModel):
    date: str
    value: float


class Trade(BaseModel):
    symbol: str
    entry_date: str
    entry_price: float
    exit_date: str | None = None
    exit_price: float
    return_pct: float
    open: bool


class PerformanceMetrics(BaseModel):
    total_return: float
    # Null rather than 0.0 when undefined: a fabricated zero would read as
    # "measured, and mediocre" instead of "not measurable".
    sharpe_ratio: float | None = None
    max_drawdown: float
    win_rate: float | None = None
    trade_count: int
    winning_trades: int
    losing_trades: int


class RunPerformance(BaseModel):
    run_id: str
    initial_capital: float
    equity: list[EquityPoint]
    benchmark: list[EquityPoint]
    metrics: PerformanceMetrics
    trades: list[Trade]
    # Carried in the payload so the caveats cannot be lost by a UI refactor.
    assumptions: list[str]
