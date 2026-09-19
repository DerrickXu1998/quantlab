"""Short-selling features from two free official sources.

* **FINRA daily short sale volume** (US) -- flat text files, published by
  ~18:00 ET on the trade date. This is short *volume*, not short *interest*:
  it counts shares sold short intraday, most of which is market-making. The
  useful signal is the ratio and its deviation from its own norm.
* **FCA net short positions** (UK) -- the daily aggregated file of disclosed
  net short positions, on a T+2 basis with a 0.2% disclosure threshold. This
  *is* short interest, and it is genuinely informative: it is real money
  publicly committed to a view.

Both are lagged in their specs so the engine cannot look ahead.
"""
from __future__ import annotations

import datetime as dt
import io
import logging

import numpy as np
import pandas as pd

from ..engine import Context
from ..indicators._util import safe_div, zscore
from ..registry import derived
from ..schema import ProviderError

log = logging.getLogger(__name__)

FINRA_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
FCA_AGGREGATE_URL = "https://www.fca.org.uk/publication/data/short-positions-daily-update.xlsx"


def _finra_frame(ctx: Context, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Download and stack FINRA daily short volume files for a date range."""
    from ..http import HttpClient

    client = HttpClient("finra")
    rows: list[pd.DataFrame] = []
    for day in pd.bdate_range(start, end):
        url = FINRA_URL.format(date=day.strftime("%Y%m%d"))
        try:
            text = client.get_text(url, ttl=-1)  # historical files never change
        except Exception as exc:
            log.debug("finra %s unavailable: %s", day.date(), exc)
            continue
        try:
            df = pd.read_csv(io.StringIO(text), sep="|")
        except Exception:
            continue
        df = df[[c for c in df.columns if not c.startswith("Unnamed")]]
        if "Symbol" not in df.columns:
            continue
        df["date"] = day.normalize()
        rows.append(df)
    if not rows:
        raise ProviderError("FINRA: no short volume files retrieved for the requested range")
    out = pd.concat(rows, ignore_index=True)
    out.columns = [c.strip().lower() for c in out.columns]
    return out


@derived(
    "finra_short_volume",
    cross_sectional=True,
    params={"zscore_period": 60},
    outputs=("short_volume_ratio", "short_volume_z", "short_exempt_ratio"),
    lag=1,
    tags=("shorts", "alternative-data", "us", "external"),
)
def finra_short_volume(panel: pd.DataFrame, ctx: Context, zscore_period: int = 60) -> pd.DataFrame:
    """Short volume as a fraction of total reported volume, plus its z-score.

    Interpret the *level* cautiously (40-50% is normal and mostly market
    making); interpret the *z-score* as a crowding signal.
    """
    if panel.empty:
        return pd.DataFrame(index=panel.index)
    dates = panel.index.get_level_values("date")
    raw = _finra_frame(ctx, dates.min(), dates.max())

    raw["symbol"] = raw["symbol"].astype(str).str.upper() + ".US"
    raw = raw.set_index(["date", "symbol"]).sort_index()

    total = raw.get("totalvolume")
    short = raw.get("shortvolume")
    exempt = raw.get("shortexemptvolume", pd.Series(0.0, index=raw.index))
    if total is None or short is None:
        raise ProviderError("FINRA: unexpected file layout")

    ratio = safe_div(short.astype(float), total.astype(float)).rename("short_volume_ratio")
    ex_ratio = safe_div(exempt.astype(float), total.astype(float)).rename("short_exempt_ratio")

    out = pd.concat([ratio, ex_ratio], axis=1).reindex(panel.index)
    out["short_volume_z"] = out.groupby(level="symbol", group_keys=False)["short_volume_ratio"].transform(
        lambda s: zscore(s.ffill(limit=3), zscore_period)
    )
    return out[["short_volume_ratio", "short_volume_z", "short_exempt_ratio"]]


@derived(
    "fca_short_interest",
    cross_sectional=True,
    params={"change_period": 21},
    outputs=("net_short_pct", "net_short_change", "short_holder_count"),
    lag=2,
    tags=("shorts", "alternative-data", "uk", "external"),
)
def fca_short_interest(panel: pd.DataFrame, ctx: Context, change_period: int = 21) -> pd.DataFrame:
    """Disclosed net short positions for UK issuers, from the FCA daily file.

    Matched on ISIN, so the securities in your context need ISINs populated
    (OpenFIGI will do it). ``lag=2`` reflects the FCA's T+2 publication basis.
    """
    from ..http import HttpClient

    if panel.empty:
        return pd.DataFrame(index=panel.index)

    client = HttpClient("fca")
    blob = client.get(FCA_AGGREGATE_URL, ttl=12 * 3600)
    try:
        sheets = pd.read_excel(io.BytesIO(blob), sheet_name=None)
    except ImportError as exc:  # openpyxl missing
        raise ProviderError("reading the FCA file needs openpyxl: pip install quantlab[excel]") from exc

    frames = []
    for name, sheet in sheets.items():
        cols = {str(c).strip().lower(): c for c in sheet.columns}
        isin_col = next((cols[c] for c in cols if "isin" in c), None)
        pct_col = next((cols[c] for c in cols if "net short" in c or "position" in c), None)
        date_col = next((cols[c] for c in cols if "date" in c), None)
        if not (isin_col and pct_col):
            continue
        f = pd.DataFrame(
            {
                "isin": sheet[isin_col].astype(str).str.strip().str.upper(),
                "net_short_pct": pd.to_numeric(sheet[pct_col], errors="coerce"),
                "date": pd.to_datetime(sheet[date_col], errors="coerce")
                if date_col
                else pd.Timestamp(dt.date.today()),
            }
        )
        frames.append(f.dropna(subset=["isin"]))
    if not frames:
        raise ProviderError("FCA: could not locate ISIN / position columns in the published file")

    fca = pd.concat(frames, ignore_index=True)
    agg = fca.groupby(["date", "isin"]).agg(
        net_short_pct=("net_short_pct", "sum"), short_holder_count=("net_short_pct", "size")
    )

    isin_to_symbol = {
        sec.isin.upper(): sym for sym, sec in ctx.securities.items() if getattr(sec, "isin", "")
    }
    if not isin_to_symbol:
        log.warning("fca_short_interest: no ISINs in context; returning empty")
        return pd.DataFrame(index=panel.index, columns=["net_short_pct", "net_short_change", "short_holder_count"], dtype=float)

    agg = agg.reset_index()
    agg["symbol"] = agg["isin"].map(isin_to_symbol)
    agg = agg.dropna(subset=["symbol"]).set_index(["date", "symbol"]).sort_index()

    out = agg[["net_short_pct", "short_holder_count"]].reindex(panel.index)
    out = out.groupby(level="symbol", group_keys=False).ffill(limit=10)
    out["net_short_change"] = out.groupby(level="symbol", group_keys=False)["net_short_pct"].diff(
        change_period
    )
    return out[["net_short_pct", "net_short_change", "short_holder_count"]]


@derived(
    "short_squeeze_score",
    cross_sectional=True,
    params={"vol_period": 20},
    outputs=("short_squeeze_score",),
    tags=("shorts", "composite"),
)
def short_squeeze_score(panel: pd.DataFrame, ctx: Context, vol_period: int = 20) -> pd.DataFrame:
    """Composite squeeze pressure: crowding x illiquidity x momentum.

    Requires ``net_short_pct`` (UK) or ``short_volume_z`` (US) and
    ``amihud_illiquidity`` to already be in the panel -- compute those first.
    A worked example of how to compose derived features into a score.
    """
    have_short = "net_short_pct" in panel.columns or "short_volume_z" in panel.columns
    if not have_short:
        raise KeyError(
            "short_squeeze_score needs 'net_short_pct' or 'short_volume_z' in the panel; "
            "run fca_short_interest / finra_short_volume first"
        )
    crowding = panel.get("net_short_pct")
    if crowding is None:
        crowding = panel["short_volume_z"]
    illiq = panel.get("amihud_illiquidity", pd.Series(np.nan, index=panel.index))
    mom = panel["close"].groupby(level="symbol", group_keys=False).pct_change(vol_period)

    def cs_rank(s: pd.Series) -> pd.Series:
        return s.groupby(level="date", group_keys=False).rank(pct=True)

    score = (cs_rank(crowding) * 0.5 + cs_rank(illiq) * 0.25 + cs_rank(mom) * 0.25)
    return score.to_frame("short_squeeze_score")
