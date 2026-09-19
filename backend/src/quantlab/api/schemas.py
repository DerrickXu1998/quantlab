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
