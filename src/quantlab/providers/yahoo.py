"""Yahoo Finance via the ``yfinance`` package.

The complement to Stooq, and the reason both are worth having:

  * Best free LSE coverage (``.L`` suffix), including AIM.
  * The only free source of **UK corporate actions** -- dividends and splits
    for London lines, which SEC/Companies House do not give you.
  * Rich reference metadata (sector, industry, shares outstanding).

And the reason it is second, not first: the endpoint is unofficial, Yahoo's
terms describe personal use only, throttling is undocumented and changes, and
the library breaks periodically. Design for it to fail -- ``quantlab.data``
falls back to the next provider automatically.
"""
from __future__ import annotations

import logging

import pandas as pd

from ..registry import provider
from ..schema import Currency, DataUnavailable, ProviderError, Security
from ..ratelimit import bucket_for
from .base import DataProvider, map_suffix

log = logging.getLogger(__name__)


@provider("yahoo")
class YahooProvider(DataProvider):
    name = "yahoo"
    supports = ("US", "LON", "L")
    requires_key = False
    licence_note = (
        "Unofficial endpoint. Yahoo's terms describe personal use only; "
        "no redistribution, no commercial use, no SLA."
    )

    def __init__(self, **opts):
        super().__init__(**opts)
        try:
            import yfinance  # noqa: F401
        except ImportError as exc:
            raise ProviderError(
                "the yahoo provider needs yfinance: pip install 'quantlab[yahoo]'"
            ) from exc
        self.bucket = bucket_for("yahoo")

    def to_native(self, symbol: str) -> str:
        return map_suffix(symbol, "yahoo")

    def fetch_one(self, symbol: str, start: str, end: str, frequency: str = "1d") -> pd.DataFrame:
        import yfinance as yf

        self.bucket.acquire()
        t = yf.Ticker(self.to_native(symbol))
        df = t.history(start=start or None, end=end or None, interval=frequency, auto_adjust=False)
        if df is None or df.empty:
            raise DataUnavailable(f"yahoo: no data for {symbol}")
        df = df.rename(columns={c: str(c).lower().replace(" ", "_") for c in df.columns})
        if "adj_close" not in df.columns and "close" in df.columns:
            df["adj_close"] = df["close"]
        return df

    def fetch(self, symbols, start, end="", frequency="1d", *, max_workers=None):
        """Yahoo has a genuine bulk endpoint; use it rather than N requests."""
        import yfinance as yf

        from ..schema import empty_bars, validate_bars

        native = {self.to_native(s): s for s in symbols}
        out: dict[str, pd.DataFrame] = {s: empty_bars() for s in symbols}
        chunk_size = int(self.options.get("chunk_size", 200))
        tickers = list(native)
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i : i + chunk_size]
            self.bucket.acquire()
            try:
                raw = yf.download(
                    chunk, start=start or None, end=end or None, interval=frequency,
                    auto_adjust=False, progress=False, group_by="ticker", threads=True,
                )
            except Exception as exc:
                log.warning("yahoo bulk download failed for %d tickers: %s", len(chunk), exc)
                continue
            for tkr in chunk:
                try:
                    sub = raw[tkr] if isinstance(raw.columns, pd.MultiIndex) else raw
                    sub = sub.rename(columns={c: str(c).lower().replace(" ", "_") for c in sub.columns})
                    sub = sub.dropna(how="all")
                    if sub.empty:
                        continue
                    if "adj_close" not in sub.columns:
                        sub["adj_close"] = sub["close"]
                    out[native[tkr]] = validate_bars(sub, symbol=native[tkr])
                except Exception as exc:
                    log.debug("yahoo: %s unusable: %s", tkr, exc)
        return out

    def corporate_actions(self, symbol: str, start: str, end: str = "") -> pd.DataFrame:
        """Dividends and splits. The only free source of these for LSE names."""
        import yfinance as yf

        self.bucket.acquire()
        actions = yf.Ticker(self.to_native(symbol)).actions
        if actions is None or actions.empty:
            return pd.DataFrame(columns=["dividend", "split_ratio"])
        actions = actions.rename(
            columns={"Dividends": "dividend", "Stock Splits": "split_ratio"}
        )
        actions.index = pd.to_datetime(actions.index).tz_localize(None)
        if start:
            actions = actions[actions.index >= pd.Timestamp(start)]
        if end:
            actions = actions[actions.index <= pd.Timestamp(end)]
        return actions

    def securities(self, symbols):
        import yfinance as yf

        out: dict[str, Security] = {}
        for s in symbols:
            self.bucket.acquire()
            try:
                info = yf.Ticker(self.to_native(s)).get_info() or {}
            except Exception as exc:
                log.debug("yahoo info failed for %s: %s", s, exc)
                info = {}
            ccy = str(info.get("currency", "")).upper()
            out[s] = Security(
                symbol=s,
                name=info.get("longName", "") or info.get("shortName", ""),
                exchange=info.get("exchange", ""),
                country="GB" if ccy in {"GBP", "GBX", "GBP PENCE"} else info.get("country", "US")[:2].upper(),
                currency=Currency.GBX if ccy in {"GBX", "GBP PENCE"} else Currency(ccy) if ccy in Currency._value2member_map_ else Currency.USD,
                sector=info.get("sector", ""),
                industry=info.get("industry", ""),
                meta={"shares_outstanding": info.get("sharesOutstanding")},
            )
        return out
