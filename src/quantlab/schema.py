"""Core data contracts shared by every provider, indicator and derived feature."""
from __future__ import annotations

import dataclasses
import enum
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

# ---------------------------------------------------------------------------
# Canonical bar schema
# ---------------------------------------------------------------------------
# Every provider MUST return a DataFrame with a DatetimeIndex named "date"
# (timezone-naive, session date) and at least these columns. Extra columns are
# preserved and carried through the feature engine untouched.
OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
BAR_COLUMNS: tuple[str, ...] = OHLCV_COLUMNS + ("adj_close",)


class Frequency(str, enum.Enum):
    DAILY = "1d"
    WEEKLY = "1wk"
    MONTHLY = "1mo"
    HOURLY = "1h"
    MINUTE_5 = "5m"

    @property
    def pandas_rule(self) -> str:
        return {"1d": "B", "1wk": "W-FRI", "1mo": "ME", "1h": "h", "5m": "5min"}[self.value]


class Currency(str, enum.Enum):
    USD = "USD"
    GBP = "GBP"
    GBX = "GBX"   # pence -- the London trap
    EUR = "EUR"

    @property
    def is_minor_unit(self) -> bool:
        """True when quoted in 1/100ths of the major unit (London pence)."""
        return self is Currency.GBX


@dataclasses.dataclass(frozen=True, slots=True)
class Security:
    """One tradeable line. `symbol` is quantlab's canonical id, not a vendor's."""

    symbol: str                 # canonical: "AAPL.US", "HSBA.LON"
    name: str = ""
    exchange: str = ""          # "XNYS", "XLON", "XNAS"
    country: str = ""           # ISO-2
    currency: Currency = Currency.USD
    sector: str = ""
    industry: str = ""
    isin: str = ""
    sedol: str = ""
    cik: str = ""               # SEC identifier (US)
    company_number: str = ""    # Companies House identifier (UK)
    figi: str = ""
    active: bool = True
    meta: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def suffix(self) -> str:
        return self.symbol.rsplit(".", 1)[-1] if "." in self.symbol else ""

    @property
    def root(self) -> str:
        return self.symbol.rsplit(".", 1)[0] if "." in self.symbol else self.symbol


@dataclasses.dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Declarative description of a computed column.

    The engine uses this to (a) validate inputs are present, (b) topologically
    order computation, (c) enforce point-in-time correctness via `lag`.
    """

    name: str
    kind: str                       # "indicator" | "derived"
    inputs: tuple[str, ...] = OHLCV_COLUMNS
    outputs: tuple[str, ...] = ()   # defaults to (name,)
    params: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    min_periods: int = 1
    cross_sectional: bool = False   # needs the whole panel, not one symbol
    lag: int = 0                    # bars of delay before the value is usable
    description: str = ""
    tags: tuple[str, ...] = ()

    def resolved_outputs(self) -> tuple[str, ...]:
        return self.outputs or (self.name,)


class DataUnavailable(RuntimeError):
    """Provider reached but has no data for this request (not an outage)."""


class ProviderError(RuntimeError):
    """Provider failed: network, auth, parse, or rate limit exhaustion."""


def empty_bars() -> pd.DataFrame:
    idx = pd.DatetimeIndex([], name="date")
    return pd.DataFrame({c: pd.Series(dtype="float64") for c in BAR_COLUMNS}, index=idx)


def validate_bars(df: pd.DataFrame, *, symbol: str = "") -> pd.DataFrame:
    """Coerce a provider's output into the canonical bar schema.

    Raises ProviderError on anything structurally wrong; silently repairs the
    things that are merely untidy (column case, index name, sort order, dupes).
    """
    if df is None:
        raise ProviderError(f"{symbol}: provider returned None")
    if not isinstance(df, pd.DataFrame):
        raise ProviderError(f"{symbol}: provider returned {type(df).__name__}, expected DataFrame")
    if df.empty:
        return empty_bars()

    out = df.copy()
    out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]

    if not isinstance(out.index, pd.DatetimeIndex):
        for cand in ("date", "datetime", "timestamp"):
            if cand in out.columns:
                out = out.set_index(cand)
                break
        out.index = pd.to_datetime(out.index, errors="coerce", utc=False)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    out.index.name = "date"

    missing = [c for c in OHLCV_COLUMNS if c not in out.columns]
    if missing:
        raise ProviderError(f"{symbol}: missing required columns {missing}")

    if "adj_close" not in out.columns:
        out["adj_close"] = out["close"]

    for c in BAR_COLUMNS:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    out = out[~out.index.isna()]
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def concat_panel(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Stack per-symbol frames into a long panel indexed by (date, symbol)."""
    parts = []
    for sym, df in frames.items():
        if df is None or df.empty:
            continue
        d = df.copy()
        d["symbol"] = sym
        parts.append(d)
    if not parts:
        return pd.DataFrame(
            index=pd.MultiIndex.from_arrays(
                [pd.DatetimeIndex([], name="date"), pd.Index([], name="symbol", dtype=object)]
            )
        )
    panel = pd.concat(parts, axis=0)
    panel = panel.set_index("symbol", append=True).sort_index()
    return panel


def panel_symbols(panel: pd.DataFrame) -> list[str]:
    return sorted(panel.index.get_level_values("symbol").unique().tolist())


def iter_symbol_frames(panel: pd.DataFrame) -> Iterable[tuple[str, pd.DataFrame]]:
    """Yield (symbol, single-index frame) pairs from a long panel."""
    for sym, chunk in panel.groupby(level="symbol", sort=True):
        yield str(sym), chunk.droplevel("symbol")


def wide(panel: pd.DataFrame, column: str) -> pd.DataFrame:
    """Pivot one column of a long panel to date x symbol."""
    if panel.empty:
        return pd.DataFrame()
    return panel[column].unstack("symbol").sort_index()


def dedupe(seq: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
