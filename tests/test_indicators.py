"""Indicator correctness.

Where an indicator has an unambiguous textbook definition, it is checked
against an independently written reference implementation rather than against
its own output -- otherwise the test only proves the code is self-consistent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.indicators import _util
from quantlab.registry import INDICATORS

from conftest import make_bars


# --------------------------------------------------------------------------
# Reference implementations, written from the definitions, not from the code
# under test.
# --------------------------------------------------------------------------

def ref_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = np.full(len(close), np.nan)
    avg_loss = np.full(len(close), np.nan)
    ups, downs = gain.to_numpy(), loss.to_numpy()
    avg_gain[period] = np.nanmean(ups[1 : period + 1])
    avg_loss[period] = np.nanmean(downs[1 : period + 1])
    for i in range(period + 1, len(close)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + ups[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + downs[i]) / period
    rs = avg_gain / np.where(avg_loss == 0, np.nan, avg_loss)
    out = 100.0 - 100.0 / (1.0 + rs)
    return pd.Series(out, index=close.index)


def ref_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1
    ).max(axis=1).to_numpy()
    out = np.full(len(tr), np.nan)
    out[period] = np.nanmean(tr[1 : period + 1])
    for i in range(period + 1, len(tr)):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return pd.Series(out, index=df.index)


def test_rsi_matches_reference(bars):
    got = INDICATORS.get("rsi").fn(bars, period=14)
    want = ref_rsi(bars["close"], 14)
    common = got.notna() & want.notna()
    assert common.sum() > 400
    np.testing.assert_allclose(got[common], want[common], rtol=1e-9)


def test_rsi_bounds_and_extremes():
    up = pd.DataFrame({"close": np.arange(1.0, 60.0)})
    rsi = INDICATORS.get("rsi").fn(up, period=14).dropna()
    assert (rsi > 99.99).all(), "monotonic rise must pin RSI at 100"

    down = pd.DataFrame({"close": np.arange(60.0, 1.0, -1.0)})
    rsi_d = INDICATORS.get("rsi").fn(down, period=14).dropna()
    assert (rsi_d < 0.01).all(), "monotonic fall must pin RSI at 0"


def test_atr_matches_reference(bars):
    got = INDICATORS.get("atr").fn(bars, period=14)
    want = ref_atr(bars, 14)
    common = got.notna() & want.notna()
    assert common.sum() > 400
    np.testing.assert_allclose(got[common], want[common], rtol=1e-9)


def test_wilder_is_not_sma(bars):
    """Guard against the classic bug of smoothing RSI/ATR with an SMA."""
    w = _util.wilder(bars["close"], 14).dropna()
    s = _util.sma(bars["close"], 14).dropna()
    assert not np.allclose(w.iloc[-50:], s.iloc[-50:])


def test_sma_and_ema_known_values():
    s = pd.Series([1.0, 2, 3, 4, 5])
    np.testing.assert_allclose(_util.sma(s, 3).dropna(), [2.0, 3.0, 4.0])
    ema = _util.ema(s, 3).dropna()
    # alpha = 2/(3+1) = 0.5, seeded on the 3rd observation
    assert ema.iloc[0] == pytest.approx(2.25)


def test_macd_histogram_identity(bars):
    out = INDICATORS.get("macd").fn(bars, 12, 26, 9)
    np.testing.assert_allclose(
        out["macd_hist"].dropna(), (out["macd"] - out["macd_signal"]).dropna(), rtol=1e-12
    )


def test_bollinger_geometry(bars):
    bb = INDICATORS.get("bollinger").fn(bars, 20, 2.0).dropna()
    assert (bb["bb_upper"] > bb["bb_mid"]).all()
    assert (bb["bb_mid"] > bb["bb_lower"]).all()
    # %B is the normalised position within the bands
    pctb = (bars["close"] - bb["bb_lower"]) / (bb["bb_upper"] - bb["bb_lower"])
    np.testing.assert_allclose(bb["bb_pctb"], pctb.loc[bb.index], rtol=1e-10)


def test_adx_components_bounded(bars):
    out = INDICATORS.get("adx").fn(bars, 14).dropna()
    assert len(out) > 400
    for col in ("adx", "di_plus", "di_minus"):
        assert out[col].between(0, 100).all(), f"{col} escaped [0,100]"


def test_stochastic_and_williams_ranges(bars):
    st = INDICATORS.get("stoch").fn(bars).dropna()
    assert st["stoch_k"].between(-0.001, 100.001).all()
    wr = INDICATORS.get("williams_r").fn(bars).dropna()
    assert wr.between(-100.001, 0.001).all()


def test_aroon_endpoints():
    """A strictly rising series pins Aroon Up at 100 and Aroon Down at 0."""
    n = 60
    df = pd.DataFrame(
        {"high": np.arange(1.0, n + 1), "low": np.arange(1.0, n + 1), "close": np.arange(1.0, n + 1)}
    )
    out = INDICATORS.get("aroon").fn(df, 25).dropna()
    assert out["aroon_up"].iloc[-1] == pytest.approx(100.0)
    assert out["aroon_down"].iloc[-1] == pytest.approx(0.0)
    assert out["aroon_osc"].iloc[-1] == pytest.approx(100.0)


def test_volatility_estimators_agree_in_magnitude(bars):
    """Different estimators, same underlying process: they should be within a
    factor of ~2 of each other, and all positive."""
    names = ["realised_vol", "parkinson_vol", "garman_klass_vol",
             "rogers_satchell_vol", "yang_zhang_vol"]
    finals = {}
    for n in names:
        s = INDICATORS.get(n).fn(bars, period=60).dropna()
        assert len(s) > 300, n
        assert (s > 0).all(), f"{n} produced non-positive volatility"
        finals[n] = float(s.iloc[-1])
    lo, hi = min(finals.values()), max(finals.values())
    assert hi / lo < 2.5, f"estimators disagree wildly: {finals}"


def test_yang_zhang_reacts_to_gaps():
    """Yang-Zhang must price overnight gaps that Parkinson ignores."""
    base = make_bars(n=300, seed=11, vol=0.01)
    gapped = base.copy()
    # Inject large overnight gaps without changing the intraday range.
    shift = np.where(np.arange(len(gapped)) % 5 == 0, 1.05, 1.0)
    for col in ("open", "high", "low", "close", "adj_close"):
        gapped[col] = gapped[col] * np.cumprod(shift)

    yz_base = INDICATORS.get("yang_zhang_vol").fn(base, period=60).dropna().iloc[-1]
    yz_gap = INDICATORS.get("yang_zhang_vol").fn(gapped, period=60).dropna().iloc[-1]
    park_base = INDICATORS.get("parkinson_vol").fn(base, period=60).dropna().iloc[-1]
    park_gap = INDICATORS.get("parkinson_vol").fn(gapped, period=60).dropna().iloc[-1]

    assert yz_gap > yz_base * 1.5, "Yang-Zhang ignored injected gaps"
    assert park_gap == pytest.approx(park_base, rel=0.05), "Parkinson should be gap-blind"


def test_hurst_discriminates_regimes():
    """The whole point of Hurst: trending > 0.5 > mean-reverting."""
    rng = np.random.default_rng(42)
    n = 1200

    # Persistent: AR(1) returns with positive autocorrelation. A random walk
    # *with drift* would not do -- the estimator differences out the drift, so
    # it correctly reports H ~ 0.5 for one. Persistence has to be in the
    # autocorrelation, not the mean.
    eps = rng.normal(0, 0.008, n)
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = 0.45 * r[i - 1] + eps[i]
    trend = pd.DataFrame({"close": 100 * np.exp(np.cumsum(r))})

    noise = rng.normal(0, 0.01, n)
    revert = pd.DataFrame({"close": 100 * np.exp(np.cumsum(noise - 0.6 * np.roll(noise, 1)))})

    h_trend = INDICATORS.get("hurst").fn(trend, period=300).dropna().mean()
    h_revert = INDICATORS.get("hurst").fn(revert, period=300).dropna().mean()
    assert h_trend > 0.55, f"trending series gave H={h_trend:.3f}"
    assert h_revert < 0.45, f"mean-reverting series gave H={h_revert:.3f}"
    assert h_trend > h_revert


def test_efficiency_ratio_endpoints():
    straight = pd.DataFrame({"close": np.arange(1.0, 100.0)})
    er = INDICATORS.get("efficiency_ratio").fn(straight, 20).dropna()
    np.testing.assert_allclose(er, 1.0, rtol=1e-9)

    zigzag = pd.DataFrame({"close": 100 + np.tile([0.0, 1.0], 50)})
    er_z = INDICATORS.get("efficiency_ratio").fn(zigzag, 20).dropna()
    assert (er_z < 0.2).all()


def test_half_life_recovers_known_ou():
    """Simulate an OU process with a known half-life and check we recover it."""
    rng = np.random.default_rng(5)
    n, theta = 4000, 0.10           # true half-life = ln(2)/0.10 ~= 6.93 bars
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = x[i - 1] - theta * x[i - 1] + rng.normal(0, 0.01)
    df = pd.DataFrame({"close": 100 * np.exp(x)})
    hl = INDICATORS.get("half_life").fn(df, period=500).dropna()
    expected = np.log(2) / theta
    assert abs(hl.median() - expected) < expected * 0.5, f"got {hl.median():.2f}, want ~{expected:.2f}"


def test_drawdown_properties(bars):
    out = INDICATORS.get("drawdown").fn(bars)
    assert (out["drawdown"] <= 1e-12).all()
    assert out["drawdown"].min() < -0.01
    assert (out["drawdown_duration"] >= 0).all()
    # at a new peak, drawdown is zero and duration resets
    at_peak = out["drawdown"] > -1e-12
    assert (out.loc[at_peak, "drawdown_duration"] == 0).all()


def test_amihud_is_higher_for_illiquid():
    liquid = make_bars(seed=9)
    illiquid = liquid.copy()
    illiquid["volume"] = illiquid["volume"] / 1000.0
    a_l = INDICATORS.get("amihud_illiquidity").fn(liquid).dropna().median()
    a_i = INDICATORS.get("amihud_illiquidity").fn(illiquid).dropna().median()
    assert a_i > a_l * 100


def test_no_indicator_looks_ahead(bars):
    """Truncating history must not change values computed earlier.

    This is the test that catches accidental look-ahead, which is the only
    bug class in an indicator library that silently makes you money on paper
    and loses it live.
    """
    cutoff = 380
    skip = {"ichimoku"}  # documented: emits chikou, a deliberate forward shift
    failures = []
    for name, plug in INDICATORS.items():
        if name in skip or plug.spec.cross_sectional:
            continue
        try:
            full = plug.fn(bars, **plug.spec.params)
            part = plug.fn(bars.iloc[:cutoff], **plug.spec.params)
        except Exception:
            continue
        full = full.to_frame() if isinstance(full, pd.Series) else full
        part = part.to_frame() if isinstance(part, pd.Series) else part
        for col in part.columns:
            a = full[col].iloc[:cutoff]
            b = part[col]
            mask = a.notna() & b.notna()
            if mask.sum() == 0:
                continue
            if not np.allclose(a[mask], b[mask], rtol=1e-6, atol=1e-8):
                failures.append(f"{name}.{col}")
    assert not failures, f"look-ahead detected in: {failures}"


def test_every_indicator_runs_and_is_shaped_correctly(bars):
    bad = []
    for name, plug in INDICATORS.items():
        # `requires-params` features (e.g. turnover needs shares outstanding)
        # correctly return all-NaN without their external input.
        if plug.spec.cross_sectional or "requires-params" in plug.spec.tags:
            continue
        try:
            out = plug.fn(bars, **plug.spec.params)
        except Exception as exc:
            bad.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        frame = out.to_frame() if isinstance(out, pd.Series) else out
        if len(frame) != len(bars):
            bad.append(f"{name}: returned {len(frame)} rows, expected {len(bars)}")
        expected = plug.spec.resolved_outputs()
        if isinstance(out, pd.DataFrame) and len(out.columns) != len(expected):
            bad.append(f"{name}: {len(out.columns)} columns, spec declares {len(expected)}")
        if frame.notna().sum().sum() == 0:
            bad.append(f"{name}: produced all NaN")
    assert not bad, "\n".join(bad)


def test_indicators_handle_short_and_degenerate_input():
    tiny = make_bars(n=3, seed=2)
    flat = make_bars(n=120, seed=2)
    for col in ("open", "high", "low", "close", "adj_close"):
        flat[col] = 50.0
    for name, plug in INDICATORS.items():
        if plug.spec.cross_sectional:
            continue
        for frame in (tiny, flat):
            try:
                plug.fn(frame, **plug.spec.params)
            except Exception as exc:
                pytest.fail(f"{name} raised on degenerate input: {type(exc).__name__}: {exc}")
