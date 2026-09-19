"""Engine scheduling, aliasing, lag enforcement and error isolation."""
from __future__ import annotations

import pandas as pd
import pytest

import quantlab as ql
from quantlab.config import FeatureRequest, PipelineConfig
from quantlab.registry import DERIVED, INDICATORS
from quantlab.schema import validate_bars, wide


def test_compute_adds_expected_columns(panel, context):
    out = ql.compute(panel, ["rsi", "atr", "macd"], context=context)
    for col in ("rsi", "atr", "macd", "macd_signal", "macd_hist"):
        assert col in out.columns
    assert len(out) == len(panel)
    assert list(out.index.names) == ["date", "symbol"]


def test_per_symbol_isolation(panel, context):
    """A feature must never leak values across symbols."""
    out = ql.compute(panel, ["rsi"], context=context)
    for sym in ("AAA.US", "DDD.LON"):
        one = panel.xs(sym, level="symbol")
        direct = INDICATORS.get("rsi").fn(one, 14)
        via_engine = out.xs(sym, level="symbol")["rsi"]
        pd.testing.assert_series_equal(direct, via_engine, check_names=False)


def test_first_rows_of_each_symbol_are_nan_not_borrowed(panel, context):
    """The classic groupby bug: symbol B warming up on symbol A's history."""
    out = ql.compute(panel, ["sma"], context=context)
    for sym in out.index.get_level_values("symbol").unique():
        head = out.xs(sym, level="symbol")["sma"].head(19)
        assert head.isna().all(), f"{sym} produced an SMA before 20 bars"


def test_parameters_and_alias(panel, context):
    out = ql.compute(
        panel,
        [{"rsi": {"period": 5, "as": "rsi_fast"}}, {"rsi": {"period": 30, "as": "rsi_slow"}}],
        context=context,
    )
    assert "rsi_fast" in out.columns and "rsi_slow" in out.columns
    fast = out["rsi_fast"].dropna()
    slow = out["rsi_slow"].dropna()
    assert fast.std() > slow.std(), "shorter RSI must be more volatile"


def test_alias_prefixes_multi_output_features(panel, context):
    out = ql.compute(panel, [{"macd": {"fast": 5, "slow": 20, "as": "m"}}], context=context)
    assert {"m_macd", "m_macd_signal", "m_macd_hist"} <= set(out.columns)


def test_failures_are_isolated_and_reported(panel, context):
    @ql.indicator("t_explodes", inputs=("close",))
    def explodes(df):
        raise RuntimeError("boom")

    try:
        out, report = ql.compute(panel, ["rsi", "t_explodes", "atr"], context=context, report=True)
        assert "rsi" in out.columns and "atr" in out.columns
        assert "t_explodes" in report.failures
        assert "boom" in report.failures["t_explodes"]
        assert report.computed == ["rsi", "atr"]
    finally:
        INDICATORS.unregister("t_explodes")


def test_on_error_raise(panel, context):
    @ql.indicator("t_explodes2", inputs=("close",))
    def explodes(df):
        raise RuntimeError("boom")

    try:
        with pytest.raises(RuntimeError, match="boom"):
            ql.compute(panel, ["t_explodes2"], context=context, on_error="raise")
    finally:
        INDICATORS.unregister("t_explodes2")


def test_missing_input_column_is_an_error(panel, context):
    @ql.indicator("t_needs_oi", inputs=("open_interest",))
    def needs_oi(df):
        return df["open_interest"]

    try:
        _, report = ql.compute(panel, ["t_needs_oi"], context=context, report=True)
        assert "open_interest" in report.failures["t_needs_oi"]
    finally:
        INDICATORS.unregister("t_needs_oi")


def test_lag_is_enforced_per_symbol(panel, context):
    """A declared publication lag must shift values forward, per symbol, with
    no bleed from one symbol's tail into the next symbol's head."""

    @ql.derived_feature("t_lagged", cross_sectional=True, lag=3, params={}, outputs=("t_lagged",))
    def lagged(panel_, ctx):
        return panel_["close"].to_frame("t_lagged")

    try:
        out = ql.compute(panel, ["t_lagged"], context=context)
        for sym in out.index.get_level_values("symbol").unique():
            got = out.xs(sym, level="symbol")["t_lagged"]
            want = panel.xs(sym, level="symbol")["close"].shift(3)
            pd.testing.assert_series_equal(got, want, check_names=False)
            assert got.head(3).isna().all()
    finally:
        DERIVED.unregister("t_lagged")


def test_cross_sectional_feature_sees_whole_panel(panel, context):
    out = ql.compute(panel, [{"cs_rank": {"column": "close"}}], context=context)
    per_date = out.groupby(level="date")["cs_rank"]
    assert per_date.max().dropna().max() == pytest.approx(1.0)
    assert per_date.nunique().max() == 5


def test_cross_sectional_runs_after_per_symbol(panel, context):
    """Ordering matters: a cross-sectional feature must be able to consume a
    column produced by a per-symbol feature in the same call."""
    out = ql.compute(panel, [{"cs_zscore": {"column": "rsi"}}, "rsi"], context=context)
    assert out["cs_zscore"].notna().sum() > 0
    z = out.dropna(subset=["cs_zscore"]).groupby(level="date")["cs_zscore"].mean()
    assert abs(z.mean()) < 1e-6, "z-scores should be centred per date"


def test_report_coverage_and_timings(panel, context):
    _, report = ql.compute(panel, ["rsi", "sma", "bollinger"], context=context, report=True)
    assert set(report.timings) == {"rsi", "sma", "bollinger"}
    assert 0.0 < report.coverage["rsi"] < 1.0   # NaN warmup
    assert "features" in report.summary()


def test_recompute_replaces_not_duplicates(panel, context):
    once = ql.compute(panel, ["rsi"], context=context)
    twice = ql.compute(once, ["rsi"], context=context)
    assert list(twice.columns).count("rsi") == 1


def test_feature_request_parsing():
    assert FeatureRequest.parse("rsi") == FeatureRequest("rsi")
    r = FeatureRequest.parse({"rsi": {"period": 7, "as": "r7"}})
    assert r.name == "rsi" and r.params == {"period": 7} and r.alias == "r7"
    r2 = FeatureRequest.parse({"name": "atr", "params": {"period": 20}})
    assert r2.name == "atr" and r2.params == {"period": 20}


def test_pipeline_config_round_trip(tmp_path):
    cfg_path = tmp_path / "p.yaml"
    cfg_path.write_text(
        "universe:\n  static:\n    watchlist: sample_uk\n"
        "providers: [stooq]\nstart: '2022-01-01'\n"
        "features:\n  - rsi\n  - atr: {period: 20}\n  - cs_rank: {column: close}\n"
    )
    cfg = PipelineConfig.from_yaml(cfg_path)
    assert cfg.universe == "static"
    assert cfg.universe_params == {"watchlist": "sample_uk"}
    assert [f.name for f in cfg.features] == ["rsi", "atr", "cs_rank"]
    assert cfg.features[1].params == {"period": 20}


def test_validate_bars_repairs_untidy_input():
    raw = pd.DataFrame(
        {
            "Date": ["2024-01-03", "2024-01-02", "2024-01-02", "2024-01-04"],
            "Open": [1, 2, 2.5, 3], "High": [2, 3, 3, 4],
            "Low ": [0.5, 1, 1, 2], "Close": [1.5, 2.5, 2.6, 3.5],
            "Volume": [10, 20, 21, 30],
        }
    )
    out = validate_bars(raw, symbol="X")
    assert list(out.columns[:5]) == ["open", "high", "low", "close", "volume"]
    assert "adj_close" in out.columns
    assert out.index.is_monotonic_increasing
    assert not out.index.duplicated().any()
    assert out.loc["2024-01-02", "close"] == 2.6   # last wins on duplicates


def test_validate_bars_rejects_missing_columns():
    from quantlab.schema import ProviderError

    with pytest.raises(ProviderError, match="missing required columns"):
        validate_bars(pd.DataFrame({"close": [1.0]}, index=pd.to_datetime(["2024-01-01"])))


def test_wide_pivot(panel):
    w = wide(panel, "close")
    assert w.shape[1] == 5
    assert w.index.is_monotonic_increasing
