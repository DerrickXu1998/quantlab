"""Deterministic synthetic fixtures. No network, no vendor data."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import quantlab as ql
from quantlab.schema import Currency, Security, concat_panel


def make_bars(
    n: int = 500,
    seed: int = 7,
    start: str = "2021-01-04",
    price0: float = 100.0,
    drift: float = 0.0003,
    vol: float = 0.018,
) -> pd.DataFrame:
    """A geometric random walk with a plausible OHLC bar built around it."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n, name="date")
    rets = rng.normal(drift, vol, n)
    close = price0 * np.exp(np.cumsum(rets))

    intraday = np.abs(rng.normal(0, vol * 0.6, n))
    open_ = close * np.exp(rng.normal(0, vol * 0.4, n))
    high = np.maximum(open_, close) * (1 + intraday)
    low = np.minimum(open_, close) * (1 - intraday)
    volume = rng.lognormal(13.5, 0.6, n).round()

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "adj_close": close, "volume": volume},
        index=idx,
    )


@pytest.fixture(scope="session", autouse=True)
def _offline(tmp_path_factory):
    ql.configure(root=tmp_path_factory.mktemp("quantlab_home"), offline=True, max_workers=2)
    ql.load_plugins()


@pytest.fixture
def bars() -> pd.DataFrame:
    return make_bars()


@pytest.fixture
def panel() -> pd.DataFrame:
    frames = {
        "AAA.US": make_bars(seed=1, price0=120.0),
        "BBB.US": make_bars(seed=2, price0=45.0, drift=-0.0002),
        "CCC.US": make_bars(seed=3, price0=310.0, vol=0.028),
        "DDD.LON": make_bars(seed=4, price0=850.0),   # pence
        "EEE.LON": make_bars(seed=5, price0=2400.0),  # pence
    }
    return concat_panel(frames)


@pytest.fixture
def context() -> ql.__class__:
    from quantlab.engine import Context

    secs = {
        "AAA.US": Security("AAA.US", sector="Tech", country="US", currency=Currency.USD),
        "BBB.US": Security("BBB.US", sector="Tech", country="US", currency=Currency.USD),
        "CCC.US": Security("CCC.US", sector="Energy", country="US", currency=Currency.USD),
        "DDD.LON": Security("DDD.LON", sector="Energy", country="GB", currency=Currency.GBX, isin="GB0000000001"),
        "EEE.LON": Security("EEE.LON", sector="Banks", country="GB", currency=Currency.GBX, isin="GB0000000002"),
    }
    return Context(securities=secs)
