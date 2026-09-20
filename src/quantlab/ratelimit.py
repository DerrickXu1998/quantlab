"""Rate limiting and polite HTTP.

Free data sources are free because you agree not to hammer them. Every limit in
``DEFAULT_LIMITS`` is taken from the provider's published policy (see
docs/DATA_SOURCES.md); where a provider publishes nothing we pick a
deliberately conservative number rather than guessing high.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import pathlib
import random
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclasses.dataclass
class Limit:
    """A token bucket. ``rate`` tokens accrue per second, capped at ``burst``."""

    rate: float
    burst: float = 1.0
    daily_cap: int | None = None
    note: str = ""

    @classmethod
    def per_second(cls, n: float, **kw: Any) -> "Limit":
        return cls(rate=n, burst=max(1.0, n), **kw)

    @classmethod
    def per_minute(cls, n: float, **kw: Any) -> "Limit":
        return cls(rate=n / 60.0, burst=max(1.0, min(n, 10.0)), **kw)

    @classmethod
    def per_hour(cls, n: float, **kw: Any) -> "Limit":
        return cls(rate=n / 3600.0, burst=max(1.0, min(n, 5.0)), **kw)

    @classmethod
    def per_day(cls, n: float, **kw: Any) -> "Limit":
        return cls(rate=n / 86400.0, burst=1.0, daily_cap=int(n), **kw)

    @classmethod
    def per_window(cls, n: float, seconds: float, **kw: Any) -> "Limit":
        return cls(rate=n / seconds, burst=max(1.0, min(n, n / 4)), **kw)


# Published free-tier limits, as of 2026-09. Sources in docs/DATA_SOURCES.md.
DEFAULT_LIMITS: dict[str, Limit] = {
    # SEC states 10 requests/second and requires a descriptive User-Agent.
    "sec_edgar": Limit.per_second(9, note="SEC published limit is 10 req/s; we stay under"),
    # Companies House: 600 requests per 5-minute rolling window.
    "companies_house": Limit.per_window(600, 300, note="600 req / 5 min"),
    # OpenFIGI mapping: 25 req/min anonymous, 25 req/6s with a key. The
    # anonymous window rejects bursts, so keyless pacing is strictly one
    # request every 2.4s (burst=1), never 10-at-once.
    "openfigi": Limit(rate=25 / 60, burst=1, note="keyless 25 req/min; raise with OPENFIGI_API_KEY"),
    "openfigi_keyed": Limit.per_window(25, 6, note="25 req / 6 s with API key"),
    # Unpublished: be conservative. Yahoo 429s somewhere near 360 req/hour.
    "yahoo": Limit.per_minute(4, note="undocumented; community reports ~360/hr before 429"),
    # Stooq publishes nothing at all. Treat as a courtesy limit.
    "stooq": Limit.per_second(2, note="undocumented; courtesy limit"),
    "fred": Limit.per_minute(100, note="widely cited 120/min, unconfirmed officially"),
    "boe": Limit.per_second(1, note="undocumented; 300 series per request, so 1/s is plenty"),
    "finra": Limit.per_second(2, note="flat files; undocumented"),
    "fca": Limit.per_second(1, note="single daily file"),
    "default": Limit.per_second(1),
}


class TokenBucket:
    def __init__(self, limit: Limit, *, name: str = "", state_dir: pathlib.Path | None = None):
        self.limit = limit
        self.name = name
        self._tokens = float(limit.burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()
        self._state_path = (state_dir / f"{name}.quota.json") if (state_dir and name) else None
        self._day, self._used = self._load_quota()

    # -- daily quota persistence (survives process restarts) ----------------
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def _load_quota(self) -> tuple[str, int]:
        if not self._state_path or not self._state_path.exists():
            return self._today(), 0
        try:
            blob = json.loads(self._state_path.read_text())
            if blob.get("day") == self._today():
                return blob["day"], int(blob.get("used", 0))
        except Exception:
            pass
        return self._today(), 0

    def _save_quota(self) -> None:
        if not self._state_path:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({"day": self._day, "used": self._used}))
        except OSError:
            pass

    @property
    def remaining_today(self) -> int | None:
        if self.limit.daily_cap is None:
            return None
        return max(0, self.limit.daily_cap - self._used)

    def acquire(self, tokens: float = 1.0, *, timeout: float | None = None) -> None:
        """Block until `tokens` are available. Raises on daily cap exhaustion."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                if self.limit.daily_cap is not None:
                    if self._day != self._today():
                        self._day, self._used = self._today(), 0
                    if self._used + tokens > self.limit.daily_cap:
                        raise QuotaExhausted(
                            f"{self.name or 'source'}: daily cap of "
                            f"{self.limit.daily_cap} requests reached"
                        )
                now = time.monotonic()
                self._tokens = min(
                    self.limit.burst, self._tokens + (now - self._last) * self.limit.rate
                )
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    if self.limit.daily_cap is not None:
                        self._used += int(tokens)
                        self._save_quota()
                    return
                wait = (tokens - self._tokens) / self.limit.rate if self.limit.rate > 0 else 1.0
            if deadline is not None and time.monotonic() + wait > deadline:
                raise TimeoutError(f"{self.name}: rate limit wait exceeded timeout")
            time.sleep(min(wait, 5.0))


class QuotaExhausted(RuntimeError):
    pass


_BUCKETS: dict[str, TokenBucket] = {}
_BUCKET_LOCK = threading.Lock()


def bucket_for(name: str, *, state_dir: pathlib.Path | None = None) -> TokenBucket:
    with _BUCKET_LOCK:
        if name not in _BUCKETS:
            limit = DEFAULT_LIMITS.get(name, DEFAULT_LIMITS["default"])
            _BUCKETS[name] = TokenBucket(limit, name=name, state_dir=state_dir)
        return _BUCKETS[name]


def set_limit(name: str, limit: Limit) -> None:
    """Override a limit (e.g. after supplying an API key that raises it)."""
    with _BUCKET_LOCK:
        DEFAULT_LIMITS[name] = limit
        _BUCKETS.pop(name, None)


def retry(
    fn: Callable[[], Any],
    *,
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    give_up_on: tuple[type[BaseException], ...] = (QuotaExhausted,),
) -> Any:
    """Exponential backoff with full jitter."""
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except give_up_on:
            raise
        except retry_on as exc:
            last = exc
            if i == attempts - 1:
                break
            delay = min(max_delay, base_delay * (2**i))
            time.sleep(random.uniform(0, delay))
            log.debug("retry %d/%d after %s", i + 1, attempts, exc)
    assert last is not None
    raise last
