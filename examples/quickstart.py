"""Five-minute tour. Run: python examples/quickstart.py"""
from __future__ import annotations

import quantlab as ql
from quantlab.data import save_panel

# 1. What's available? --------------------------------------------------------
inv = ql.describe()
print({k: len(v) for k, v in inv.items()})

# 2. Load a mixed NYSE + LSE panel -------------------------------------------
#    `return_context=True` also gives you securities, inferred currencies and a
#    record of which provider served each symbol.
panel, ctx = ql.load(
    ["JPM.US", "XOM.US", "HSBA.LON", "SHEL.LON", "AZN.LON"],
    start="2020-01-01",
    providers=["stooq", "yahoo"],   # fallback chain
    return_context=True,
)
print(panel.tail())
print("served by:", ctx.extras["provider_used"])
print("quote units:", {k: v.value for k, v in ctx.currencies.items()})

# 3. Compute features ---------------------------------------------------------
result, report = ql.compute(
    panel,
    [
        "rsi",
        {"rsi": {"period": 5, "as": "rsi_fast"}},     # same feature, twice, aliased
        "yang_zhang_vol",
        "natr",
        "amihud_illiquidity",
        "hurst",
        "momentum_12_1",
        {"market_beta": {"period": 252}},             # cross-sectional
        {"cs_zscore": {"column": "momentum_12_1", "as": "mom_z"}},
        "breadth",
    ],
    context=ctx,
    report=True,
)
print(report.summary())

# 4. Today's cross-section ----------------------------------------------------
latest = result.xs(result.index.get_level_values("date").max(), level="date")
print(latest[["close", "rsi", "yang_zhang_vol", "market_beta", "mom_z", "hurst"]].round(3))

# 5. Add your own indicator ---------------------------------------------------
@ql.indicator("my_signal", params={"fast": 10, "slow": 50}, inputs=("close",), tags=("custom",))
def my_signal(df, fast=10, slow=50):
    """Normalised fast/slow moving-average spread."""
    f = df["close"].rolling(fast).mean()
    s = df["close"].rolling(slow).mean()
    return (f - s) / s


print(ql.compute(panel, ["my_signal"], context=ctx)["my_signal"].dropna().tail())

# 6. Persist ------------------------------------------------------------------
print("saved to", save_panel(result, "features.parquet"))
