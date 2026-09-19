"""Derived features: cross-sectional maths, regime detection, and the graceful
degradation of externally-sourced plugins when a source is unreachable."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import quantlab as ql
from quantlab.engine import Context
from quantlab.registry import DERIVED
from quantlab.schema import Security, concat_panel



def test_cs_zscore_is_centred_and_winsorized(panel, context):
    out = ql.compute(panel, [{"cs_zscore": {"column": "close", "winsor": 2.0}}], context=context)
    per_date = out.groupby(level="date")["cs_zscore"]
    assert abs(per_date.mean().mean()) < 1e-9
    assert out["cs_zscore"].abs().max() <= 2.0 + 1e-9


def test_cs_rank_is_uniform(panel, context):
    out = ql.compute(panel, [{"cs_rank": {"column": "volume"}}], context=context)
    r = out["cs_rank"].dropna()
    assert r.between(0, 1).all()
    assert sorted(out.groupby(level="date")["cs_rank"].first().unique()) != [1.0]


def test_sector_neutral_removes_sector_means(panel, context):
    out = ql.compute(panel, [{"sector_neutral": {"column": "close", "group": "sector"}}], context=context)
    frame = out.dropna(subset=["sector_neutral"]).copy()
    frame["sector"] = [context.sector_of(s) for s in frame.index.get_level_values("symbol")]
    dates = frame.index.get_level_values("date")
    means = frame.groupby([dates, frame["sector"]])["sector_neutral"].mean()
    # Groups of size 1 are NaN; groups of size >1 must be demeaned to zero.
    assert abs(means.dropna()).max() < 1e-9


def test_market_beta_recovers_a_known_beta():
    """Construct a name that is exactly 1.5x the market plus noise."""
    rng = np.random.default_rng(3)
    n = 600
    idx = pd.bdate_range("2021-01-04", periods=n, name="date")
    mkt = rng.normal(0.0003, 0.012, n)

    frames = {}
    for i, beta in enumerate([0.5, 1.0, 1.5, 2.0], start=1):
        r = beta * mkt + rng.normal(0, 0.002, n)
        close = 100 * np.exp(np.cumsum(r))
        frames[f"B{i}.US"] = pd.DataFrame(
            {"open": close, "high": close * 1.004, "low": close * 0.996,
             "close": close, "adj_close": close, "volume": 1e6},
            index=idx,
        )
    panel = concat_panel(frames)
    ctx = Context(securities={s: Security(s, country="US") for s in frames})

    out = ql.compute(panel, [{"market_beta": {"period": 400, "min_periods": 200}}], context=ctx)
    final = out.groupby(level="symbol")["market_beta"].last()

    # The benchmark is the equal-weight mean of the four, i.e. beta ~1.25x mkt,
    # so recovered betas are scaled by 1/1.25 but must keep the ordering and
    # the ratios.
    assert final["B4.US"] > final["B3.US"] > final["B2.US"] > final["B1.US"]
    ratio = final["B4.US"] / final["B1.US"]
    assert ratio == pytest.approx(4.0, rel=0.1), f"beta ratio {ratio:.3f}, expected ~4"

    r2 = out.groupby(level="symbol")["r2_market"].last()
    assert (r2 > 0.8).all(), "single-factor construction should fit tightly"


def test_idio_vol_is_lower_than_total_vol():
    rng = np.random.default_rng(8)
    n = 500
    idx = pd.bdate_range("2021-01-04", periods=n, name="date")
    mkt = rng.normal(0, 0.015, n)
    frames = {}
    for i in range(4):
        r = mkt + rng.normal(0, 0.004, n)
        c = 100 * np.exp(np.cumsum(r))
        frames[f"S{i}.US"] = pd.DataFrame(
            {"open": c, "high": c, "low": c, "close": c, "adj_close": c, "volume": 1e6}, index=idx
        )
    panel = concat_panel(frames)
    ctx = Context(securities={s: Security(s, country="US") for s in frames})
    out = ql.compute(panel, ["market_beta", {"realised_vol": {"period": 250}}], context=ctx)
    last = out.groupby(level="symbol").last()
    assert (last["idio_vol"] < last["realised_vol"]).all()


def test_breadth_endpoints():
    """All names above their MA -> breadth 1.0; all below -> 0.0."""
    n = 400
    idx = pd.bdate_range("2021-01-04", periods=n, name="date")
    up = np.linspace(100, 300, n)
    down = np.linspace(300, 100, n)

    def frame(series):
        return pd.DataFrame(
            {"open": series, "high": series, "low": series, "close": series,
             "adj_close": series, "volume": 1e6},
            index=idx,
        )

    rising = concat_panel({f"U{i}.US": frame(up * (1 + 0.01 * i)) for i in range(4)})
    falling = concat_panel({f"D{i}.US": frame(down * (1 + 0.01 * i)) for i in range(4)})
    ctx = Context()

    b_up = ql.compute(rising, [{"breadth": {"ma_period": 100}}], context=ctx)
    b_dn = ql.compute(falling, [{"breadth": {"ma_period": 100}}], context=ctx)
    assert b_up["breadth_above_ma"].dropna().iloc[-1] == pytest.approx(1.0)
    assert b_dn["breadth_above_ma"].dropna().iloc[-1] == pytest.approx(0.0)
    assert b_up["breadth_new_highs"].dropna().iloc[-1] > 0
    assert b_dn["breadth_new_highs"].dropna().iloc[-1] < 0


def test_market_regime_labels_are_valid(panel, context):
    out = ql.compute(panel, ["market_regime"], context=context)
    labels = out["regime_label"].dropna().unique()
    assert set(labels) <= {0.0, 1.0, 2.0, 3.0}
    assert out["market_vol_pct"].dropna().between(0, 1).all()
    # a market series is identical for every symbol on a given date
    per_date = out.groupby(level="date")["market_vol"].nunique()
    assert per_date.max() == 1


def test_dispersion_and_implied_correlation_bounds():
    """Perfectly correlated names -> rho near 1; independent names -> near 0."""
    rng = np.random.default_rng(12)
    n = 400
    idx = pd.bdate_range("2021-01-04", periods=n, name="date")
    common = rng.normal(0, 0.012, n)

    def build(rets):
        c = 100 * np.exp(np.cumsum(rets))
        return pd.DataFrame(
            {"open": c, "high": c, "low": c, "close": c, "adj_close": c, "volume": 1e6}, index=idx
        )

    same = concat_panel({f"C{i}.US": build(common) for i in range(5)})
    indep = concat_panel({f"I{i}.US": build(rng.normal(0, 0.012, n)) for i in range(5)})
    ctx = Context()

    rho_same = ql.compute(same, [{"dispersion": {"period": 60}}], context=ctx)["avg_pairwise_corr"].dropna()
    rho_indep = ql.compute(indep, [{"dispersion": {"period": 60}}], context=ctx)["avg_pairwise_corr"].dropna()

    assert rho_same.median() > 0.95
    assert abs(rho_indep.median()) < 0.3
    assert rho_same.median() > rho_indep.median()


def test_liquidity_tier_partitions_universe(panel, context):
    out = ql.compute(panel, [{"liquidity_tier": {"tiers": 5}}], context=context)
    tiers = out["liquidity_tier"].dropna()
    assert tiers.between(1, 5).all()
    assert out["adv_rank"].dropna().between(0, 1).all()


def test_relative_strength_sums_to_zero(panel, context):
    out = ql.compute(panel, [{"relative_strength": {"period": 20}}], context=context)
    per_date = out.dropna(subset=["relative_strength"]).groupby(level="date")["relative_strength"].mean()
    assert abs(per_date).max() < 1e-9


def test_seasonality_features(panel, context):
    out = ql.compute(panel, ["calendar", "turn_of_month"], context=context)
    assert out["day_of_week"].dropna().between(0, 4).all()
    assert set(out["turn_of_month"].dropna().unique()) <= {0.0, 1.0}
    assert out["trading_day_of_month"].dropna().min() == 1


def test_external_features_degrade_gracefully_offline(panel, context):
    """Offline, every externally-sourced feature must fail softly: reported in
    the report, never crashing the run, never producing wrong numbers."""
    external = [n for n, p in DERIVED.items() if "external" in p.spec.tags]
    assert external, "expected some externally-sourced derived features"

    out, report = ql.compute(panel, ["rsi", *external], context=context, report=True)
    assert "rsi" in out.columns, "an offline external source must not break the run"
    for name in external:
        produced = name in report.computed
        failed = name in report.failures
        assert produced or failed, f"{name} neither computed nor reported as failed"
        if produced:
            plug = DERIVED.get(name)
            for col in plug.spec.resolved_outputs():
                if col in out.columns:
                    assert out[col].notna().sum() == 0, f"{name} invented data while offline"


def test_short_squeeze_score_requires_its_inputs(panel, context):
    _, report = ql.compute(panel, ["short_squeeze_score"], context=context, report=True)
    assert "short_squeeze_score" in report.failures
    assert "net_short_pct" in report.failures["short_squeeze_score"]


def test_external_feature_specs_declare_a_lag():
    """Anything sourced from a filing or a published file must declare a lag,
    or the engine cannot protect you from look-ahead."""
    offenders = [
        n for n, p in DERIVED.items()
        if "external" in p.spec.tags and p.spec.lag < 1
    ]
    assert not offenders, f"external features with no publication lag: {offenders}"
