"""Loading: universes, providers, fallback, storage."""
from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

import pandas as pd

from .config import PipelineConfig, settings
from .engine import Context
from .fx import normalise_panel
from .registry import PROVIDERS, UNIVERSES, load_plugins
from .schema import Currency, Security, concat_panel

log = logging.getLogger(__name__)


def get_provider(name: str, **options: Any):
    load_plugins()
    cls = PROVIDERS.get(name)
    return cls(**options)


def get_universe(name: str, **options: Any):
    load_plugins()
    cls = UNIVERSES.get(name)
    return cls(**options)


def load_universe(name: str = "static", **options: Any) -> list[Security]:
    return get_universe(name, **options).securities()


def load(
    symbols: Sequence[str] | None = None,
    *,
    start: str = "2015-01-01",
    end: str = "",
    frequency: str = "1d",
    providers: Sequence[str] = ("stooq",),
    provider_options: Mapping[str, Mapping[str, Any]] | None = None,
    universe: str = "",
    universe_params: Mapping[str, Any] | None = None,
    securities: Mapping[str, Security] | None = None,
    normalise_currency: bool = True,
    max_workers: int | None = None,
    return_context: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, Context]:
    """Load a price panel, trying each provider in turn for missing symbols.

    The fallback chain is the point: free sources break, and a pipeline that
    dies because Yahoo changed an endpoint is not a pipeline. Symbols a
    provider fails on are simply retried against the next one.
    """
    load_plugins()
    sec_map: dict[str, Security] = dict(securities or {})

    if universe:
        uni = get_universe(universe, **(universe_params or {}))
        uni_secs = uni.securities()
        sec_map.update({s.symbol: s for s in uni_secs})
        symbols = list(symbols or []) + [s.symbol for s in uni_secs]
    if not symbols:
        raise ValueError("load() needs `symbols` or a `universe`")

    remaining = list(dict.fromkeys(symbols))
    frames: dict[str, pd.DataFrame] = {}
    used: dict[str, str] = {}

    for prov_name in providers:
        if not remaining:
            break
        try:
            prov = get_provider(prov_name, **dict((provider_options or {}).get(prov_name, {})))
        except Exception as exc:
            log.warning("provider %s unavailable: %s", prov_name, exc)
            continue
        log.info("fetching %d symbols from %s", len(remaining), prov_name)
        got = prov.fetch(remaining, start, end, frequency, max_workers=max_workers)
        still: list[str] = []
        for sym in remaining:
            df = got.get(sym)
            if df is None or df.empty:
                still.append(sym)
            else:
                frames[sym] = df
                used[sym] = prov_name
        if len(still) == len(remaining):
            log.warning("provider %s returned nothing for %d symbols", prov_name, len(still))
        remaining = still

    if remaining:
        log.warning("no data for %d symbols: %s", len(remaining), ", ".join(remaining[:10]))
    if not frames:
        log.error(
            "no provider returned data for any of %d symbols (tried: %s). "
            "Everything downstream will be empty -- check connectivity, symbol "
            "suffixes (.US / .LON) and provider options.",
            len(symbols), ", ".join(providers),
        )

    currencies: dict[str, Currency] = {}
    if normalise_currency:
        frames, currencies = normalise_panel(frames, sec_map)

    panel = concat_panel(frames)
    ctx = Context(
        securities=sec_map,
        currencies=currencies,
        frequency=frequency,
        extras={"provider_used": used, "missing": remaining},
    )
    return (panel, ctx) if return_context else panel


def run_pipeline(config: PipelineConfig, *, report: bool = False):
    """Load + compute in one call, driven by a YAML config."""
    from .engine import FeatureEngine

    panel, ctx = load(
        start=config.start,
        end=config.end,
        frequency=config.frequency,
        providers=config.providers,
        provider_options=config.provider_options,
        universe=config.universe,
        universe_params=config.universe_params,
        normalise_currency=config.normalise_currency,
        max_workers=config.max_workers,
        return_context=True,
    )
    ctx.price_column = config.price_column
    engine = FeatureEngine(ctx, max_workers=config.max_workers)
    return engine.compute(panel, config.features, report=report)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def save_panel(panel: pd.DataFrame, path: str | Any = "", *, partition_by_symbol: bool = False) -> str:
    """Write a panel to Parquet. Partitioned layout scales to a full universe."""
    import pathlib

    target = pathlib.Path(path) if path else settings().data_dir / "panel.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = panel.reset_index()
    if partition_by_symbol:
        frame.to_parquet(target, partition_cols=["symbol"], index=False)
    else:
        frame.to_parquet(target, index=False)
    return str(target)


def load_panel(path: str | Any = "") -> pd.DataFrame:
    import pathlib

    target = pathlib.Path(path) if path else settings().data_dir / "panel.parquet"
    frame = pd.read_parquet(target)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index(["date", "symbol"]).sort_index()
