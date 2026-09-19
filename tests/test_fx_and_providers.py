"""Currency/unit handling and the provider contract.

The GBp trap gets its own test file because it is the bug that silently
corrupts every cross-sectional number in a mixed NYSE/LSE universe.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import quantlab as ql
from quantlab import fx
from quantlab.data import get_provider, get_universe, load, load_panel, save_panel
from quantlab.schema import Currency, DataUnavailable

from conftest import make_bars


# --------------------------------------------------------------------------
# Currency / units
# --------------------------------------------------------------------------

def test_infers_pence_for_london_lines():
    pence = make_bars(price0=850.0)
    assert fx.infer_quote_currency("HSBA.LON", pence) is Currency.GBX
    assert fx.infer_quote_currency("BP.L", pence) is Currency.GBX
    # A genuinely low-priced London line quoted in pounds
    pounds = make_bars(price0=4.0)
    assert fx.infer_quote_currency("XYZ.LON", pounds) is Currency.GBP


def test_us_lines_are_never_treated_as_pence():
    assert fx.infer_quote_currency("AAPL.US", make_bars(price0=850.0)) is Currency.USD


def test_declared_currency_beats_the_heuristic():
    cheap = make_bars(price0=3.0)
    assert fx.infer_quote_currency("ABC.LON", cheap, declared=Currency.GBX) is Currency.GBX


def test_to_major_units_divides_prices_not_volume():
    bars = make_bars(price0=850.0)
    out = fx.to_major_units(bars, Currency.GBX)
    np.testing.assert_allclose(out["close"], bars["close"] / 100.0)
    np.testing.assert_allclose(out["high"], bars["high"] / 100.0)
    np.testing.assert_allclose(out["volume"], bars["volume"])


def test_usd_bars_pass_through_untouched():
    bars = make_bars()
    pd.testing.assert_frame_equal(fx.to_major_units(bars, Currency.USD), bars)


def test_convert_applies_a_rate_series():
    bars = make_bars(price0=850.0)
    rate = pd.Series(1.27, index=bars.index)
    out = fx.convert(bars, Currency.GBX, Currency.USD, rate)
    np.testing.assert_allclose(out["close"], bars["close"] / 100.0 * 1.27)


def test_normalise_panel_makes_markets_comparable():
    """Without normalisation, an 850p LSE line looks 10x a $85 NYSE line."""
    frames = {"AAA.US": make_bars(price0=85.0), "BBB.LON": make_bars(price0=850.0)}
    raw_ratio = frames["BBB.LON"]["close"].mean() / frames["AAA.US"]["close"].mean()
    assert raw_ratio > 9

    normalised, units = fx.normalise_panel(frames)
    assert units["BBB.LON"] is Currency.GBX and units["AAA.US"] is Currency.USD
    fixed = normalised["BBB.LON"]["close"].mean() / normalised["AAA.US"]["close"].mean()
    assert 0.05 < fixed < 0.2, "pence should have been converted to pounds"


def test_ratio_indicators_are_unit_invariant():
    """Any well-built indicator must be identical in pence and in pounds.
    If one is not, it is not safe to use cross-sectionally."""
    pence = make_bars(price0=850.0, seed=21)
    pounds = fx.to_major_units(pence, Currency.GBX)

    for name in ("rsi", "natr", "bb_pctb_check", "efficiency_ratio", "price_percentile"):
        if name == "bb_pctb_check":
            a = ql.INDICATORS.get("bollinger").fn(pence)["bb_pctb"]
            b = ql.INDICATORS.get("bollinger").fn(pounds)["bb_pctb"]
        else:
            plug = ql.INDICATORS.get(name)
            a = plug.fn(pence, **plug.spec.params)
            b = plug.fn(pounds, **plug.spec.params)
        mask = a.notna() & b.notna()
        assert mask.sum() > 100, name
        np.testing.assert_allclose(a[mask], b[mask], rtol=1e-8, err_msg=f"{name} is unit-dependent")


def test_raw_atr_is_unit_dependent_by_design():
    """The counter-example, documented: use natr, not atr, across markets."""
    pence = make_bars(price0=850.0, seed=21)
    pounds = fx.to_major_units(pence, Currency.GBX)
    a = ql.INDICATORS.get("atr").fn(pence).dropna()
    b = ql.INDICATORS.get("atr").fn(pounds).dropna()
    np.testing.assert_allclose(a, b * 100.0, rtol=1e-8)


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

def test_symbol_mapping_per_vendor():
    from quantlab.providers.base import map_suffix

    assert map_suffix("AAPL.US", "stooq") == "AAPL.us"
    assert map_suffix("HSBA.LON", "stooq") == "HSBA.uk"
    assert map_suffix("HSBA.LON", "yahoo") == "HSBA.L"   # London suffix on Yahoo
    assert map_suffix("AAPL.US", "yahoo") == "AAPL"      # US lines carry no suffix


def test_stooq_native_symbols():
    p = get_provider("stooq")
    assert p.to_native("AAPL.US") == "aapl.us"
    assert p.to_native("HSBA.LON") == "hsba.uk"


def test_yahoo_native_symbols():
    pytest.importorskip("yfinance")
    p = get_provider("yahoo")
    assert p.to_native("HSBA.LON") == "HSBA.L"


def test_csv_provider_round_trip(tmp_path):
    bars = make_bars(n=120)
    d = tmp_path / "csv"
    d.mkdir()
    bars.to_csv(d / "TEST.US.csv")

    prov = get_provider("csv", directory=d)
    got = prov.fetch(["TEST.US", "MISSING.US"], start="2021-01-01")
    assert len(got["TEST.US"]) == 120
    assert got["MISSING.US"].empty, "a missing symbol must return empty, not raise"


def test_load_falls_back_between_providers(tmp_path, monkeypatch):
    """The whole point of the fallback chain: provider 1 dies, provider 2 covers."""
    from quantlab.providers.base import DataProvider
    from quantlab.registry import PROVIDERS

    @ql.provider("t_dead")
    class Dead(DataProvider):
        name = "t_dead"

        def fetch_one(self, symbol, start, end, frequency="1d"):
            raise DataUnavailable("always down")

    d = tmp_path / "csv2"
    d.mkdir()
    make_bars(n=60).to_csv(d / "AAA.US.csv")

    @ql.provider("t_backup")
    class Backup(DataProvider):
        name = "t_backup"

        def fetch_one(self, symbol, start, end, frequency="1d"):
            path = d / f"{symbol}.csv"
            if not path.exists():
                raise DataUnavailable(symbol)
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            return df

    try:
        panel, ctx = load(["AAA.US"], providers=["t_dead", "t_backup"], return_context=True)
        assert len(panel) == 60
        assert ctx.extras["provider_used"]["AAA.US"] == "t_backup"
        assert ctx.extras["missing"] == []
    finally:
        PROVIDERS.unregister("t_dead")
        PROVIDERS.unregister("t_backup")


def test_load_reports_symbols_no_provider_could_supply(tmp_path):
    from quantlab.providers.base import DataProvider
    from quantlab.registry import PROVIDERS

    @ql.provider("t_empty")
    class Empty(DataProvider):
        name = "t_empty"

        def fetch_one(self, symbol, start, end, frequency="1d"):
            raise DataUnavailable(symbol)

    try:
        panel, ctx = load(["NOPE.US"], providers=["t_empty"], return_context=True)
        assert panel.empty
        assert ctx.extras["missing"] == ["NOPE.US"]
    finally:
        PROVIDERS.unregister("t_empty")


def test_price_only_providers_refuse_bars_clearly():
    for name in ("sec_edgar", "boe", "fred", "openfigi"):
        try:
            prov = get_provider(name)
        except Exception:
            continue
        with pytest.raises(DataUnavailable):
            prov.fetch_one("AAPL.US", "2024-01-01", "2024-02-01")


def test_offline_http_client_raises_rather_than_fetching():
    from quantlab.http import HttpClient, OfflineError

    client = HttpClient("stooq")
    with pytest.raises(OfflineError):
        client.get("https://stooq.com/q/d/l/", params={"s": "aapl.us"})


# --------------------------------------------------------------------------
# Universes
# --------------------------------------------------------------------------

def test_static_universe_watchlists():
    uni = get_universe("static", watchlist="sample")
    secs = uni.securities()
    assert len(secs) == 16
    us = [s for s in secs if s.country == "US"]
    gb = [s for s in secs if s.country == "GB"]
    assert len(us) == 8 and len(gb) == 8
    assert all(s.currency is Currency.GBX for s in gb)


def test_static_universe_from_csv(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("symbol,name,sector\nAAA.US,Alpha,Tech\nBBB.LON,Beta,Banks\n")
    secs = get_universe("static", path=p).securities()
    assert [s.symbol for s in secs] == ["AAA.US", "BBB.LON"]
    assert secs[1].country == "GB" and secs[1].currency is Currency.GBX


def test_lse_universe_falls_back_and_says_so():
    uni = get_universe("lse")
    secs = uni.securities()
    assert len(secs) > 50
    assert uni.source_used == "fallback:ftse_core"
    assert all(s.symbol.endswith(".LON") for s in secs)


def test_lse_universe_parses_a_supplied_instrument_file(tmp_path):
    p = tmp_path / "instruments.csv"
    p.write_text(
        "Company Name,TIDM,ISIN,ICB Sector,Market\n"
        "Tesco PLC,TSCO,GB0008847096,Food Retail,Main Market\n"
        "Some AIM Co,AIMC,GB0000000009,Software,AIM\n"
    )
    secs = get_universe("lse", path=p).securities()
    assert [s.symbol for s in secs] == ["TSCO.LON", "AIMC.LON"]
    assert secs[0].isin == "GB0008847096"
    assert secs[0].sector == "Food Retail"

    main_only = get_universe("lse", path=p, include_aim=False).securities()
    assert [s.symbol for s in main_only] == ["TSCO.LON"]


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def test_panel_round_trips_through_parquet(panel, tmp_path):
    out = save_panel(panel, tmp_path / "p.parquet")
    back = load_panel(out)
    pd.testing.assert_frame_equal(panel, back, check_freq=False)


def test_rate_limiter_blocks_and_respects_daily_cap(tmp_path):
    import time

    from quantlab.ratelimit import Limit, QuotaExhausted, TokenBucket

    bucket = TokenBucket(Limit.per_second(50, ), name="t_fast")
    t0 = time.monotonic()
    for _ in range(60):
        bucket.acquire()
    assert time.monotonic() - t0 > 0.1, "limiter did not slow anything down"

    capped = TokenBucket(Limit(rate=100.0, burst=10, daily_cap=3), name="t_cap", state_dir=tmp_path)
    for _ in range(3):
        capped.acquire()
    with pytest.raises(QuotaExhausted, match="daily cap of 3"):
        capped.acquire()


def test_daily_quota_survives_a_restart(tmp_path):
    from quantlab.ratelimit import Limit, QuotaExhausted, TokenBucket

    limit = Limit(rate=100.0, burst=10, daily_cap=2)
    first = TokenBucket(limit, name="t_persist", state_dir=tmp_path)
    first.acquire()
    first.acquire()

    second = TokenBucket(limit, name="t_persist", state_dir=tmp_path)  # "restart"
    with pytest.raises(QuotaExhausted):
        second.acquire()
