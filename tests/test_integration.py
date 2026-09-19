"""End-to-end: CLI, YAML pipeline, third-party plugin, storage round trip."""
from __future__ import annotations

import subprocess
import sys

import pytest

import quantlab as ql
from quantlab.data import load_panel


@pytest.fixture(scope="module")
def csv_universe(tmp_path_factory):
    """A frozen ten-name NYSE + LSE dataset on disk."""
    sys.path.insert(0, str(tmp_path_factory.getbasetemp().parent))
    from conftest import make_bars

    d = tmp_path_factory.mktemp("csvdata")
    spec = {
        "JPM.US": (150.0, 0.016), "XOM.US": (105.0, 0.019), "KO.US": (60.0, 0.011),
        "PG.US": (155.0, 0.012), "BA.US": (200.0, 0.026),
        "HSBA.LON": (650.0, 0.015), "SHEL.LON": (2750.0, 0.017),
        "AZN.LON": (11500.0, 0.014), "BP.LON": (470.0, 0.020), "ULVR.LON": (4200.0, 0.011),
    }
    for i, (sym, (p0, vol)) in enumerate(spec.items()):
        make_bars(n=900, seed=200 + i, price0=p0, vol=vol, start="2022-01-03").to_csv(d / f"{sym}.csv")
    return d, list(spec)


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "quantlab.cli", *args],
        capture_output=True, text=True, timeout=300,
        env={**__import__("os").environ, "QUANTLAB_OFFLINE": "1"},
    )


def test_cli_list_and_sources_and_doctor():
    for args in (["list", "indicators"], ["sources"], ["doctor"], ["list", "--json"]):
        r = _cli(*args)
        assert r.returncode == 0, f"{args} failed: {r.stderr[-500:]}"
        assert r.stdout.strip()

    assert "rsi" in _cli("list", "indicators").stdout
    sources = _cli("sources").stdout
    assert "stooq" in sources and "sec_edgar" in sources
    # every source must state its licence position
    assert "personal research" in sources.lower() or "public domain" in sources.lower()


def test_cli_rejects_unknown_feature():
    r = _cli("compute", "--features", "not_a_real_feature", "--symbols", "AAA.US")
    assert r.returncode != 0 or "unknown" in (r.stdout + r.stderr).lower()


def test_yaml_pipeline_end_to_end(csv_universe, tmp_path):
    """The full path: YAML -> universe -> provider -> fx -> engine -> parquet."""
    d, symbols = csv_universe
    cfg = tmp_path / "p.yaml"
    out = tmp_path / "features.parquet"
    cfg.write_text(
        f"""
universe:
  static:
    symbols: {symbols}
providers: [csv]
provider_options:
  csv:
    directory: {d}
start: "2022-01-03"
normalise_currency: true
features:
  - rsi: {{period: 14}}
  - natr: {{period: 14}}
  - yang_zhang_vol: {{period: 20}}
  - amihud_illiquidity: {{period: 21}}
  - hurst: {{period: 150}}
  - momentum_12_1: {{}}
  - market_beta: {{period: 252}}
  - liquidity_tier: {{tiers: 5}}
  - breadth: {{ma_period: 200}}
  - dispersion: {{period: 20}}
  - cs_zscore: {{column: momentum_12_1, as: mom_z}}
"""
    )
    r = _cli("run", str(cfg), "--out", str(out))
    assert r.returncode == 0, r.stderr[-2000:]
    assert "failed" not in r.stderr.lower() or "0 failed" in r.stderr

    df = load_panel(out)
    assert df.index.get_level_values("symbol").nunique() == 10
    for col in ("rsi", "natr", "yang_zhang_vol", "hurst", "market_beta", "mom_z", "liquidity_tier"):
        assert col in df.columns, col
        assert df[col].notna().sum() > 0, f"{col} is entirely empty"

    # LSE prices must have come back as pounds, not pence
    lse_mean = df.loc[df.index.get_level_values("symbol").str.endswith(".LON"), "close"].mean()
    us_mean = df.loc[df.index.get_level_values("symbol").str.endswith(".US"), "close"].mean()
    assert lse_mean < us_mean * 3, f"LSE mean {lse_mean:.0f} looks like pence, not pounds"

    # cross-sectional features must be identical across symbols on a date
    assert df.groupby(level="date")["breadth_above_ma"].nunique().max() == 1
    assert df["liquidity_tier"].dropna().between(1, 5).all()


def test_third_party_plugin_is_discovered_and_usable(panel, context):
    """The example plugin ships as a real distribution; entry points must work."""
    pytest.importorskip("quantlab_myfactors")
    ql.load_plugins(force=True)

    for name in ("vwap_reversion", "range_position"):
        assert name in ql.INDICATORS, f"{name} not discovered via entry points"
    assert "regime_scaled_momentum" in ql.DERIVED
    assert "mybroker" in ql.PROVIDERS

    out = ql.compute(
        panel, ["vwap_reversion", "range_position", "regime_scaled_momentum"], context=context
    )
    for col in ("vwap_reversion", "range_pos", "range_width", "regime_scaled_momentum"):
        assert col in out.columns
        assert out[col].notna().sum() > 0

    # a third-party cross-sectional feature really does see the whole panel
    assert out.groupby(level="date")["regime_scaled_momentum"].nunique().max() > 1


def test_third_party_can_override_a_builtin(bars):
    """Deliberate override must work; accidental collision must not."""
    from quantlab.registry import DuplicatePlugin

    original = ql.INDICATORS.get("natr")
    origin = ql.INDICATORS.origin("natr")
    try:
        with pytest.raises(DuplicatePlugin):
            @ql.indicator("natr", inputs=("close",))
            def clash(df, period=14):
                return df["close"] * 0

        @ql.indicator("natr", inputs=("close",), override=True)
        def replacement(df, period=14):
            return df["close"] * 0 + 7.0

        assert ql.INDICATORS.get("natr").fn(bars).iloc[0] == 7.0
    finally:
        ql.INDICATORS.unregister("natr")
        ql.INDICATORS.register("natr", original, origin=origin)


def test_documented_feature_counts_are_accurate():
    """The README makes numeric claims. Keep them true."""
    import pathlib
    import re

    ql.load_plugins()
    readme = (pathlib.Path(__file__).parent.parent / "README.md").read_text()
    claimed = re.search(r"(\d+) technical indicators, (\d+) derived", readme)
    assert claimed, "README no longer states feature counts"

    # Builtins only -- the example plugin may or may not be installed.
    builtin_ind = [n for n, p in ql.INDICATORS.items() if p.fn.__module__.startswith("quantlab.")]
    builtin_der = [n for n, p in ql.DERIVED.items() if p.fn.__module__.startswith("quantlab.")]
    assert len(builtin_ind) == int(claimed.group(1)), f"README says {claimed.group(1)}, found {len(builtin_ind)}"
    assert len(builtin_der) == int(claimed.group(2)), f"README says {claimed.group(2)}, found {len(builtin_der)}"


def test_every_feature_has_a_description():
    """A registry you cannot browse is a registry nobody uses."""
    ql.load_plugins()
    missing = [
        name for name, p in ql.all_features().items()
        if len((p.spec.description or "").strip()) < 20
    ]
    assert not missing, f"features with no usable description: {missing}"


def test_every_provider_states_its_licence_position():
    ql.load_plugins()
    silent = [n for n, cls in ql.PROVIDERS.items() if not getattr(cls, "licence_note", "").strip()]
    assert not silent, f"providers with no licence note: {silent}"
