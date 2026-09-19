"""Volume, liquidity and microstructure proxies.

Liquidity is where an LSE + NYSE universe bites hardest: AIM small caps and
NYSE mega caps differ by six orders of magnitude in turnover. Anything you
trade needs a liquidity screen, and these are the ones that work on free daily
bars alone.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import indicator
from ._util import ema, log_returns, safe_div, sma, typical_price, zscore


@indicator("obv", inputs=("close", "volume"), tags=("volume",))
def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume: cumulative volume signed by the day's direction.

    The level is meaningless (it depends on where the series starts) -- read
    the slope, or its divergence from price.
    """
    direction = np.sign(df["close"].diff().fillna(0.0))
    return (direction * df["volume"]).fillna(0.0).cumsum()


@indicator("ad_line", tags=("volume",))
def ad_line(df: pd.DataFrame) -> pd.Series:
    """Accumulation/Distribution line (Chaikin)."""
    hl = df["high"] - df["low"]
    mfm = safe_div((df["close"] - df["low"]) - (df["high"] - df["close"]), hl).fillna(0.0)
    return (mfm * df["volume"]).fillna(0.0).cumsum()


@indicator("cmf", params={"period": 20}, min_periods=20, tags=("volume", "oscillator"))
def cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Chaikin Money Flow: volume-weighted close location, in [-1, 1]."""
    hl = df["high"] - df["low"]
    mfm = safe_div((df["close"] - df["low"]) - (df["high"] - df["close"]), hl).fillna(0.0)
    mfv = mfm * df["volume"]
    return safe_div(
        mfv.rolling(period, min_periods=period).sum(),
        df["volume"].rolling(period, min_periods=period).sum(),
    )


@indicator("mfi", params={"period": 14}, min_periods=15, tags=("volume", "oscillator"))
def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Money Flow Index -- RSI with volume weighting."""
    tp = typical_price(df["high"], df["low"], df["close"])
    raw = tp * df["volume"]
    up = raw.where(tp.diff() > 0, 0.0).rolling(period, min_periods=period).sum()
    dn = raw.where(tp.diff() < 0, 0.0).rolling(period, min_periods=period).sum()
    return 100.0 - 100.0 / (1.0 + safe_div(up, dn))


@indicator("vwap", params={"period": 20, "anchor": ""}, outputs=("vwap", "vwap_dist"), tags=("volume", "overlay"))
def vwap(df: pd.DataFrame, period: int = 20, anchor: str = "") -> pd.DataFrame:
    """Rolling or anchored VWAP, plus percent distance from it.

    ``anchor`` accepts a pandas period alias ('W', 'ME', 'QE', 'YE') to reset
    the accumulation -- anchored VWAP from an earnings date or a 52-week low is
    a far better reference level than the rolling version.
    """
    tp = typical_price(df["high"], df["low"], df["close"])
    pv = tp * df["volume"]
    if anchor:
        grp = df.index.to_period(anchor)
        num = pv.groupby(grp).cumsum()
        den = df["volume"].groupby(grp).cumsum()
    else:
        num = pv.rolling(period, min_periods=period).sum()
        den = df["volume"].rolling(period, min_periods=period).sum()
    v = safe_div(num, den)
    return pd.DataFrame({"vwap": v, "vwap_dist": safe_div(df["close"] - v, v)})


@indicator("volume_zscore", params={"period": 60}, inputs=("volume",), min_periods=60, tags=("volume", "event"))
def volume_zscore(df: pd.DataFrame, period: int = 60) -> pd.Series:
    """Volume surprise. The single best free proxy for "something happened"."""
    return zscore(np.log1p(df["volume"]), period)


@indicator("dollar_volume", params={"period": 20}, inputs=("close", "volume"), tags=("volume", "liquidity"))
def dollar_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Average traded value (price x volume) -- your primary liquidity screen.

    Units follow the price series, so normalise currency first if you are
    ranking NYSE against LSE.
    """
    return (df["close"] * df["volume"]).rolling(period, min_periods=1).mean()


@indicator("amihud_illiquidity", params={"period": 21}, inputs=("close", "volume"), min_periods=21, tags=("volume", "liquidity", "microstructure"))
def amihud(df: pd.DataFrame, period: int = 21) -> pd.Series:
    """Amihud illiquidity: |return| per unit of traded value, x1e6.

    Price impact per pound/dollar traded. High = thin. It is the most useful
    microstructure measure available without tick data, and it is what actually
    separates a tradeable AIM name from an untradeable one.
    """
    ret = df["close"].pct_change().abs()
    value = (df["close"] * df["volume"]).replace(0.0, np.nan)
    return (1e6 * safe_div(ret, value)).rolling(period, min_periods=period).mean()


@indicator("roll_spread", params={"period": 21}, inputs=("close",), min_periods=22, tags=("liquidity", "microstructure"))
def roll_spread(df: pd.DataFrame, period: int = 21) -> pd.Series:
    """Roll's effective spread estimator from serial covariance of returns.

    Only defined when that covariance is negative (bid-ask bounce); NaN
    otherwise, which is itself informative.
    """
    d = df["close"].diff()
    cov = d.rolling(period, min_periods=period).apply(
        lambda x: float(np.cov(x[:-1], x[1:], ddof=1)[0, 1]) if len(x) > 2 else np.nan, raw=True
    )
    return 2.0 * np.sqrt((-cov).where(cov < 0))


@indicator("corwin_schultz_spread", params={"period": 21}, inputs=("high", "low"), min_periods=22, tags=("liquidity", "microstructure"))
def corwin_schultz(df: pd.DataFrame, period: int = 21) -> pd.Series:
    """Corwin-Schultz high-low bid-ask spread estimator.

    Recovers an effective spread from daily highs and lows alone -- the closest
    you get to quote data on a free feed.
    """
    hi, lo = df["high"], df["low"]
    hi2 = pd.concat([hi, hi.shift(1)], axis=1).max(axis=1)
    lo2 = pd.concat([lo, lo.shift(1)], axis=1).min(axis=1)

    beta = np.log(safe_div(hi, lo)) ** 2 + np.log(safe_div(hi.shift(1), lo.shift(1))) ** 2
    gamma = np.log(safe_div(hi2, lo2)) ** 2
    k = 3.0 - 2.0 * np.sqrt(2.0)
    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    spread = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    return spread.clip(lower=0).rolling(period, min_periods=period).mean()


@indicator("force_index", params={"period": 13}, inputs=("close", "volume"), min_periods=14, tags=("volume",))
def force_index(df: pd.DataFrame, period: int = 13) -> pd.Series:
    """Elder's Force Index: price change x volume, smoothed."""
    return ema(df["close"].diff() * df["volume"], period)


@indicator("ease_of_movement", params={"period": 14}, min_periods=15, tags=("volume",))
def ease_of_movement(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """How far price moves per unit of volume."""
    mid_move = ((df["high"] + df["low"]) / 2).diff()
    box = safe_div(df["volume"] / 1e8, (df["high"] - df["low"]))
    return sma(safe_div(mid_move, box), period)


@indicator("volume_trend_confirm", params={"period": 20}, inputs=("close", "volume"), min_periods=21, tags=("volume", "quality"))
def volume_trend_confirm(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Correlation of returns with volume changes over the window.

    Positive means moves come on rising volume (confirmed); negative means the
    trend is running on fumes.
    """
    r = log_returns(df["close"])
    v = np.log1p(df["volume"]).diff()
    return r.rolling(period, min_periods=period).corr(v)


@indicator("turnover", params={"period": 20, "shares_outstanding": 0.0}, inputs=("volume",), tags=("volume", "liquidity", "requires-params"))
def turnover(df: pd.DataFrame, period: int = 20, shares_outstanding: float = 0.0) -> pd.Series:
    """Share turnover as a fraction of shares outstanding.

    Pass ``shares_outstanding`` from a fundamentals provider (SEC ``dei``
    facts, or Companies House). Without it this returns NaN rather than
    silently inventing a denominator.
    """
    if not shares_outstanding or shares_outstanding <= 0:
        return pd.Series(np.nan, index=df.index)
    return df["volume"].rolling(period, min_periods=1).mean() / float(shares_outstanding)
