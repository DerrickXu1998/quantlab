"""A single polite HTTP client: rate limited, cached, retried, offline-aware."""
from __future__ import annotations

import hashlib
import logging
import pathlib
import time
from typing import Any, Mapping

import requests

from .config import settings
from .ratelimit import QuotaExhausted, bucket_for, retry
from .schema import ProviderError

log = logging.getLogger(__name__)


class OfflineError(ProviderError):
    """Offline mode is on and the response was not in the cache."""


class HttpClient:
    def __init__(self, source: str, *, user_agent: str | None = None, headers: Mapping[str, str] | None = None):
        self.source = source
        st = settings()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent or st.user_agent,
                "Accept-Encoding": "gzip, deflate",
                **(headers or {}),
            }
        )
        self.bucket = bucket_for(source, state_dir=st.state_dir)
        self.cache_dir = st.cache_dir / source
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- cache -------------------------------------------------------------
    def _key(self, url: str, params: Mapping[str, Any] | None, body: Any) -> pathlib.Path:
        blob = repr((url, sorted((params or {}).items()), repr(body))).encode()
        return self.cache_dir / (hashlib.sha256(blob).hexdigest()[:32] + ".bin")

    def _read_cache(self, path: pathlib.Path, ttl: int | None) -> bytes | None:
        if not path.exists():
            return None
        ttl = settings().cache_ttl_seconds if ttl is None else ttl
        if ttl >= 0 and (time.time() - path.stat().st_mtime) > ttl:
            return None
        return path.read_bytes()

    # -- fetch -------------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        ttl: int | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return self._request("GET", url, params=params, ttl=ttl, timeout=timeout, headers=headers)

    def post_json(
        self,
        url: str,
        payload: Any,
        *,
        ttl: int | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return self._request(
            "POST", url, json_body=payload, ttl=ttl, timeout=timeout, headers=headers
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        ttl: int | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        st = settings()
        cache_path = self._key(url, params, json_body)
        cached = self._read_cache(cache_path, ttl)
        if cached is not None:
            return cached
        if st.offline:
            raise OfflineError(f"offline mode: {url} not in cache")

        def do() -> bytes:
            self.bucket.acquire()
            resp = self.session.request(
                method, url, params=params, json=json_body,
                timeout=timeout or st.http_timeout, headers=dict(headers or {}),
            )
            if resp.status_code == 429:
                raise ProviderError(f"{self.source}: HTTP 429 rate limited on {url}")
            if resp.status_code >= 400:
                raise ProviderError(
                    f"{self.source}: HTTP {resp.status_code} on {url}: {resp.text[:200]}"
                )
            return resp.content

        content = retry(do, attempts=4, give_up_on=(QuotaExhausted, OfflineError))
        try:
            cache_path.write_bytes(content)
        except OSError:
            pass
        return content

    def get_text(self, url: str, **kw: Any) -> str:
        return self.get(url, **kw).decode("utf-8", errors="replace")

    def get_json(self, url: str, **kw: Any) -> Any:
        import json

        return json.loads(self.get(url, **kw))
