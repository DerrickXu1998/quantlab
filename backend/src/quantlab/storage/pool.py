"""Bounded, reusable connections to the warehouse (feature 007).

Why this exists: the API used to open a fresh Postgres connection and a fresh
ClickHouse client per request. Measured in-container that is 9.86 ms and
6.76 ms of setup respectively -- 62x and 7x the cost of the queries themselves
-- and, worse, it makes the number of connections the API demands grow with
instance count against a catalog whose max_connections is 100. A handful of
autoscaled instances exhaust the budget and requests that were perfectly valid
start being refused.

Why a pool of clients rather than one shared client: clickhouse_connect's
Client carries no lock and exposes mutable per-instance state (`database`), so
it is not safe to share between threads. FastAPI runs this project's
synchronous handlers on a thread pool, so sharing one would be a data race. The
HTTP layer underneath is already pooled by urllib3, but that pool is
`block=False`, so it bounds nothing -- the ceiling has to be enforced here.

Postgres gets psycopg_pool instead of this class: its pool already implements
liveness checking and, critically, resets session state and rolls back an open
transaction when a connection is returned. Hand-writing that is the kind of
thing that looks fine until a half-finished transaction leaks into someone
else's request.
"""

from __future__ import annotations

import os
import queue
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from quantlab.logging import get_logger

logger = get_logger(__name__)

#: Well under Starlette's thread-pool size on purpose: the ceiling, not the
#: thread count, is what should bound connections. With a 100-connection
#: catalog budget this supports a dozen instances with headroom for migrations.
DEFAULT_POOL_MAX = 5

#: Seconds a request waits for a connection before failing. Long enough to ride
#: out a burst, short enough that exhaustion surfaces as an error rather than a
#: hang nobody can diagnose.
DEFAULT_POOL_TIMEOUT = 10.0


class PoolTimeout(RuntimeError):
    """No connection became available within the configured wait."""


#: Failures that make a connection itself suspect, as opposed to failures of the
#: work it was carrying. A handler raising ValueError says nothing about the
#: socket, and discarding a healthy connection every time business logic fails
#: would churn the pool for no reason -- FR-006 requires it be returned.
CONNECTION_FAILURES = (ConnectionError, OSError, EOFError, TimeoutError)


@dataclass(frozen=True)
class PoolConfig:
    pg_max: int
    ch_max: int
    timeout: float


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        if raw:
            logger.warning("pool_config_invalid", extra={"setting": name, "value": raw})
        return default
    if value < 1:
        logger.warning("pool_config_invalid", extra={"setting": name, "value": raw})
        return default
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        if raw:
            logger.warning("pool_config_invalid", extra={"setting": name, "value": raw})
        return default
    if value <= 0:
        logger.warning("pool_config_invalid", extra={"setting": name, "value": raw})
        return default
    return value


def pool_config() -> PoolConfig:
    """Resolve pool settings from the environment.

    A bad value falls back to the default with a warning rather than refusing to
    start. These are tuning knobs, not correctness settings, and turning a typo
    in one into an outage would be the wrong trade.
    """
    return PoolConfig(
        pg_max=_positive_int("QUANTLAB_PG_POOL_MAX", DEFAULT_POOL_MAX),
        ch_max=_positive_int("QUANTLAB_CH_POOL_MAX", DEFAULT_POOL_MAX),
        timeout=_positive_float("QUANTLAB_POOL_TIMEOUT", DEFAULT_POOL_TIMEOUT),
    )


class ClientPool:
    """A bounded pool of ClickHouse clients, one holder at a time.

    Clients are created lazily up to ``max_size`` and only when none is idle, so
    a process that never touches the bar store never builds one -- which is what
    keeps application startup free of any network call.
    """

    def __init__(
        self,
        factory: Callable[[], Any],
        *,
        max_size: int = DEFAULT_POOL_MAX,
        timeout: float = DEFAULT_POOL_TIMEOUT,
        name: str = "clickhouse",
    ) -> None:
        self._factory = factory
        self._max_size = max_size
        self._timeout = timeout
        self._name = name
        self._idle: queue.LifoQueue = queue.LifoQueue()
        # Permits, not clients: a permit is taken before a client is created, so
        # the ceiling bounds construction and not merely checkout.
        self._permits = threading.BoundedSemaphore(max_size)
        self._all: list[Any] = []
        self._guard = threading.Lock()
        self._closed = False

    def _discard(self, client: Any) -> None:
        try:
            client.close()
        except Exception:  # noqa: BLE001 -- a client we are throwing away
            pass
        with self._guard:
            if client in self._all:
                self._all.remove(client)

    def _healthy(self, client: Any) -> bool:
        try:
            client.ping()
        except Exception:  # noqa: BLE001 -- any failure means do not serve it
            return False
        return True

    @contextmanager
    def acquire(self) -> Iterator[Any]:
        """Check out a client, guaranteed returned on every exit path."""
        if not self._permits.acquire(timeout=self._timeout):
            logger.warning(
                "pool_exhausted",
                extra={"pool": self._name, "max_size": self._max_size, "timeout": self._timeout},
            )
            raise PoolTimeout(
                f"no {self._name} connection available within {self._timeout}s "
                f"(ceiling {self._max_size}); raise QUANTLAB_CH_POOL_MAX or reduce concurrency"
            )

        client = None
        try:
            # An idle client may have died while parked -- an idle timeout, or a
            # database restart. Replace it rather than hand out a corpse.
            while client is None:
                try:
                    candidate = self._idle.get_nowait()
                except queue.Empty:
                    break
                if self._healthy(candidate):
                    client = candidate
                else:
                    logger.info("pool_client_replaced", extra={"pool": self._name})
                    self._discard(candidate)

            if client is None:
                client = self._factory()
                with self._guard:
                    self._all.append(client)

            reusable = True
            try:
                yield client
            except CONNECTION_FAILURES:
                # The connection is suspect; returning it would spread one
                # failure across the next several requests.
                reusable = False
                raise
            except Exception:
                # The work failed, not the connection. Return it (FR-006).
                raise
            finally:
                if reusable and not self._closed:
                    self._idle.put(client)
                else:
                    self._discard(client)
        finally:
            self._permits.release()

    def close(self) -> None:
        """Release every client. Idempotent."""
        self._closed = True
        with self._guard:
            clients = list(self._all)
            self._all.clear()
        for client in clients:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        while True:
            try:
                self._idle.get_nowait()
            except queue.Empty:
                break
