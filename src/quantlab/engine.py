"""The feature engine: schedules plugins over a panel and enforces hygiene."""
from __future__ import annotations

import dataclasses
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .config import FeatureRequest, settings
from .registry import FeaturePlugin, load_plugins, lookup_feature
from .schema import Currency, Security, iter_symbol_frames, panel_symbols

log = logging.getLogger(__name__)


@dataclasses.dataclass
class Context:
    """Everything a cross-sectional or externally-sourced feature may need."""

    securities: dict[str, Security] = dataclasses.field(default_factory=dict)
    currencies: dict[str, Currency] = dataclasses.field(default_factory=dict)
    benchmark: pd.Series | None = None          # benchmark close series
    frequency: str = "1d"
    price_column: str = "adj_close"
    extras: dict[str, Any] = dataclasses.field(default_factory=dict)
    _provider_cache: dict[str, Any] = dataclasses.field(default_factory=dict, repr=False)

    def sector_of(self, symbol: str) -> str:
        sec = self.securities.get(symbol)
        return (sec.sector if sec else "") or "UNKNOWN"

    def sectors(self, symbols: Sequence[str]) -> pd.Series:
        return pd.Series({s: self.sector_of(s) for s in symbols}, name="sector")

    def country_of(self, symbol: str) -> str:
        sec = self.securities.get(symbol)
        if sec and sec.country:
            return sec.country
        suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
        return {"L": "GB", "LON": "GB", "UK": "GB", "LSE": "GB"}.get(suffix, "US")

    def provider(self, name: str) -> Any:
        """Lazily instantiate a registered provider, cached per context."""
        if name not in self._provider_cache:
            from .data import get_provider

            self._provider_cache[name] = get_provider(name)
        return self._provider_cache[name]


@dataclasses.dataclass
class ComputeReport:
    """What ran, what it produced, and what went wrong."""

    computed: list[str] = dataclasses.field(default_factory=list)
    columns: list[str] = dataclasses.field(default_factory=list)
    failures: dict[str, str] = dataclasses.field(default_factory=dict)
    timings: dict[str, float] = dataclasses.field(default_factory=dict)
    coverage: dict[str, float] = dataclasses.field(default_factory=dict)

    def summary(self) -> str:
        lines = [f"{len(self.computed)} features -> {len(self.columns)} columns"]
        if self.failures:
            lines.append(f"{len(self.failures)} failed: " + ", ".join(sorted(self.failures)))
        slow = sorted(self.timings.items(), key=lambda kv: -kv[1])[:3]
        if slow:
            lines.append("slowest: " + ", ".join(f"{k} {v:.2f}s" for k, v in slow))
        return "\n".join(lines)


class FeatureEngine:
    def __init__(self, context: Context | None = None, *, max_workers: int | None = None,
                 on_error: str = "warn"):
        load_plugins()
        self.ctx = context or Context()
        self.max_workers = max_workers or settings().max_workers
        if on_error not in {"warn", "raise", "ignore"}:
            raise ValueError("on_error must be 'warn', 'raise' or 'ignore'")
        self.on_error = on_error

    # -- public API --------------------------------------------------------
    def compute(
        self,
        panel: pd.DataFrame,
        features: Iterable[str | Mapping[str, Any] | FeatureRequest],
        *,
        report: bool = False,
    ) -> pd.DataFrame | tuple[pd.DataFrame, ComputeReport]:
        """Add feature columns to a long (date, symbol) panel.

        Per-symbol features run in parallel across symbols; cross-sectional
        features run once over the whole panel, after all per-symbol features
        they might depend on.
        """
        requests = [f if isinstance(f, FeatureRequest) else FeatureRequest.parse(f) for f in features]
        out = panel.copy()
        rep = ComputeReport()

        plugins: list[tuple[FeatureRequest, FeaturePlugin]] = []
        for req in requests:
            try:
                plugins.append((req, lookup_feature(req.name)))
            except KeyError as exc:
                self._fail(rep, req.name, exc)

        per_symbol = [(r, p) for r, p in plugins if not p.spec.cross_sectional]
        cross = [(r, p) for r, p in plugins if p.spec.cross_sectional]

        for req, plug in per_symbol:
            t0 = time.perf_counter()
            try:
                block = self._run_per_symbol(out, req, plug)
            except Exception as exc:
                self._fail(rep, req.name, exc)
                continue
            out = self._merge(out, block)
            self._record(rep, req, block, time.perf_counter() - t0)

        for req, plug in cross:
            t0 = time.perf_counter()
            try:
                block = self._run_cross_sectional(out, req, plug)
            except Exception as exc:
                self._fail(rep, req.name, exc)
                continue
            out = self._merge(out, block)
            self._record(rep, req, block, time.perf_counter() - t0)

        return (out, rep) if report else out

    # -- internals ---------------------------------------------------------
    def _fail(self, rep: ComputeReport, name: str, exc: BaseException) -> None:
        rep.failures[name] = f"{type(exc).__name__}: {exc}"
        if self.on_error == "raise":
            raise exc
        if self.on_error == "warn":
            log.warning("feature %s failed: %s", name, exc)

    def _record(self, rep: ComputeReport, req: FeatureRequest, block: pd.DataFrame, dt: float) -> None:
        rep.computed.append(req.name)
        rep.timings[req.name] = dt
        for col in block.columns:
            rep.columns.append(col)
            rep.coverage[col] = float(block[col].notna().mean()) if len(block) else 0.0

    @staticmethod
    def _merge(panel: pd.DataFrame, block: pd.DataFrame) -> pd.DataFrame:
        if block.empty:
            return panel
        dupes = [c for c in block.columns if c in panel.columns]
        if dupes:
            panel = panel.drop(columns=dupes)
        return panel.join(block, how="left")

    def _rename(self, req: FeatureRequest, frame: pd.DataFrame, plug: FeaturePlugin) -> pd.DataFrame:
        """Apply the alias prefix and the parameter suffix convention."""
        if not req.alias:
            return frame
        outputs = plug.spec.resolved_outputs()
        if len(outputs) == 1:
            return frame.rename(columns={frame.columns[0]: req.alias})
        return frame.rename(columns={c: f"{req.alias}_{c}" for c in frame.columns})

    def _run_per_symbol(self, panel: pd.DataFrame, req: FeatureRequest, plug: FeaturePlugin) -> pd.DataFrame:
        params = {**dict(plug.spec.params), **req.params}
        missing = [c for c in plug.spec.inputs if c not in panel.columns]
        if missing:
            raise KeyError(f"{req.name}: panel is missing input columns {missing}")

        symbols = panel_symbols(panel)
        frames = dict(iter_symbol_frames(panel))

        def run_one(sym: str) -> tuple[str, pd.DataFrame]:
            df = frames[sym]
            result = plug.fn(df, **params)
            return sym, _as_frame(result, plug, df.index)

        if self.max_workers > 1 and len(symbols) > 1:
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                results = list(pool.map(run_one, symbols))
        else:
            results = [run_one(s) for s in symbols]

        parts = []
        for sym, block in results:
            block = block.copy()
            block["symbol"] = sym
            parts.append(block.set_index("symbol", append=True))
        if not parts:
            return pd.DataFrame(index=panel.index)
        combined = pd.concat(parts).sort_index()
        combined = self._apply_lag(combined, plug.spec.lag)
        return self._rename(req, combined.reindex(panel.index), plug)

    def _run_cross_sectional(self, panel: pd.DataFrame, req: FeatureRequest, plug: FeaturePlugin) -> pd.DataFrame:
        params = {**dict(plug.spec.params), **req.params}
        result = plug.fn(panel, self.ctx, **params)
        if isinstance(result, pd.Series):
            result = result.to_frame(plug.spec.resolved_outputs()[0])
        if not isinstance(result, pd.DataFrame):
            raise TypeError(f"{req.name}: cross-sectional feature must return a DataFrame")
        result = self._apply_lag(result, plug.spec.lag)
        return self._rename(req, result.reindex(panel.index), plug)

    @staticmethod
    def _apply_lag(frame: pd.DataFrame, lag: int) -> pd.DataFrame:
        """Shift a feature forward in time so it is only usable once known.

        This is the guardrail against look-ahead: any feature whose spec
        declares a publication delay is shifted by that many bars, per symbol.
        """
        if lag <= 0 or frame.empty:
            return frame
        if isinstance(frame.index, pd.MultiIndex) and "symbol" in frame.index.names:
            return frame.groupby(level="symbol", group_keys=False).shift(lag)
        return frame.shift(lag)


def _as_frame(result: Any, plug: FeaturePlugin, index: pd.Index) -> pd.DataFrame:
    outputs = plug.spec.resolved_outputs()
    if isinstance(result, pd.Series):
        return result.rename(outputs[0]).to_frame()
    if isinstance(result, pd.DataFrame):
        if list(result.columns) != list(outputs) and len(result.columns) == len(outputs):
            result = result.copy()
            result.columns = list(outputs)
        return result
    if np.isscalar(result):
        return pd.DataFrame({outputs[0]: result}, index=index)
    raise TypeError(f"{plug.name}: unsupported return type {type(result).__name__}")


def compute(
    panel: pd.DataFrame,
    features: Iterable[str | Mapping[str, Any] | FeatureRequest],
    *,
    context: Context | None = None,
    report: bool = False,
    on_error: str = "warn",
    max_workers: int | None = None,
) -> pd.DataFrame | tuple[pd.DataFrame, ComputeReport]:
    """Convenience wrapper around :class:`FeatureEngine`."""
    return FeatureEngine(context, max_workers=max_workers, on_error=on_error).compute(
        panel, features, report=report
    )
