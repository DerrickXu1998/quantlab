"""A third-party data provider. ~30 lines is all it takes."""
from __future__ import annotations

import pandas as pd

from quantlab.providers.base import DataProvider
from quantlab.registry import provider
from quantlab.schema import DataUnavailable


@provider("mybroker")
class MyBrokerProvider(DataProvider):
    """Template for wrapping your broker's or vendor's API.

    The framework handles caching, rate limiting, retries, schema validation
    and currency normalisation, so all you implement is one method. Use
    ``quantlab.http.HttpClient(self.name)`` for requests and it is rate
    limited and cached automatically.
    """

    name = "mybroker"
    supports = ("US", "LON")
    requires_key = True
    licence_note = "Whatever your vendor's terms say. Write it here; `quantlab sources` prints it."

    def __init__(self, api_key: str = "", base_url: str = "https://api.example.com", **opts):
        super().__init__(**opts)
        self.api_key = api_key
        self.base_url = base_url

    def to_native(self, symbol: str) -> str:
        return symbol.replace(".US", "").replace(".LON", ":LSE")

    def fetch_one(self, symbol: str, start: str, end: str, frequency: str = "1d") -> pd.DataFrame:
        # from quantlab.http import HttpClient
        # client = HttpClient(self.name, headers={"Authorization": f"Bearer {self.api_key}"})
        # payload = client.get_json(f"{self.base_url}/bars", params={...})
        # return pd.DataFrame(payload["bars"])  -> needs date index + OHLCV columns
        raise DataUnavailable("mybroker is a template; wire up fetch_one to your vendor")
