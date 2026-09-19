"""Local CSV / Parquet provider.

Useful for three things: working offline, replaying a frozen dataset so a
backtest is reproducible, and as the shortest possible example of a provider.
"""
from __future__ import annotations

import pathlib

import pandas as pd

from ..config import settings
from ..registry import provider
from ..schema import DataUnavailable
from .base import DataProvider


@provider("csv")
class CsvProvider(DataProvider):
    name = "csv"
    licence_note = "Local files; whatever licence the source data carried."

    def __init__(self, directory: str | pathlib.Path = "", pattern: str = "{symbol}.csv", **opts):
        super().__init__(**opts)
        self.directory = pathlib.Path(directory or settings().data_dir / "csv").expanduser()
        self.pattern = pattern

    def fetch_one(self, symbol: str, start: str, end: str, frequency: str = "1d") -> pd.DataFrame:
        for suffix, reader in ((".csv", pd.read_csv), (".parquet", pd.read_parquet)):
            path = self.directory / self.pattern.format(symbol=symbol).replace(".csv", suffix)
            if path.exists():
                df = reader(path)
                break
        else:
            raise DataUnavailable(f"csv: no file for {symbol} in {self.directory}")

        if "date" in df.columns:
            df = df.set_index("date")
        df.index = pd.to_datetime(df.index)
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            df = df[df.index <= pd.Timestamp(end)]
        return df
