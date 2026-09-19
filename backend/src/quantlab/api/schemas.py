"""Pydantic v2 response models mirroring contracts/openapi.yaml exactly."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    seeded: bool
    signal_count: int


class Instrument(BaseModel):
    symbol: str
    name: str
    currency: str
    regime_profile: Literal["trending", "mean_reverting", "volatile", "mixed"]
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
