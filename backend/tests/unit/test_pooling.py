"""Bounded, reusable warehouse connections (feature 007).

The behaviour under test is concurrency, so most of these run real threads. A
pool that passes single-threaded and fails under load is the failure this
feature exists to prevent, and asserting the ceiling without contending for it
would prove nothing.

The fake client stands in for clickhouse_connect's Client: the pool must not
know what it is holding, and the tests must not need a database.
"""

from __future__ import annotations

import threading
import time

import pytest

from quantlab.storage import pool as pool_module

# --- Configuration ---------------------------------------------------------


def test_defaults_when_nothing_is_configured(monkeypatch):
    for var in ("QUANTLAB_PG_POOL_MAX", "QUANTLAB_CH_POOL_MAX", "QUANTLAB_POOL_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)

    config = pool_module.pool_config()

    assert config.pg_max == 5
    assert config.ch_max == 5
    assert config.timeout == 10.0


def test_the_environment_overrides_the_defaults(monkeypatch):
    monkeypatch.setenv("QUANTLAB_PG_POOL_MAX", "12")
    monkeypatch.setenv("QUANTLAB_CH_POOL_MAX", "3")
    monkeypatch.setenv("QUANTLAB_POOL_TIMEOUT", "2.5")

    config = pool_module.pool_config()

    assert (config.pg_max, config.ch_max, config.timeout) == (12, 3, 2.5)


@pytest.mark.parametrize("bad", ["nonsense", "0", "-4", ""])
def test_an_unusable_value_falls_back_rather_than_refusing_to_start(monkeypatch, bad):
    """These are tuning knobs, not correctness settings. A typo in one should
    not turn into an outage."""
    monkeypatch.setenv("QUANTLAB_PG_POOL_MAX", bad)

    assert pool_module.pool_config().pg_max == 5


# --- The ClickHouse client pool --------------------------------------------


class FakeClient:
    """Stands in for clickhouse_connect's Client, which cannot be shared
    between threads and so must be handed to exactly one caller at a time."""

    def __init__(self, index: int) -> None:
        self.index = index
        self.closed = False
        self.alive = True
        self.pings = 0

    def ping(self) -> bool:
        self.pings += 1
        if not self.alive:
            raise ConnectionError("clickhouse is gone")
        return True

    def close(self) -> None:
        self.closed = True


def make_pool(size: int = 2, timeout: float = 1.0):
    created: list[FakeClient] = []

    def factory() -> FakeClient:
        client = FakeClient(len(created))
        created.append(client)
        return client

    return pool_module.ClientPool(factory, max_size=size, timeout=timeout), created


def test_a_second_acquire_reuses_the_first_client(monkeypatch):
    pool, created = make_pool()

    with pool.acquire() as first:
        first_id = id(first)
    with pool.acquire() as second:
        assert id(second) == first_id

    assert len(created) == 1, "a reused pool must not construct a second client"


def test_the_ceiling_is_never_exceeded_under_contention():
    pool, created = make_pool(size=3)
    peak = 0
    live = 0
    guard = threading.Lock()
    start = threading.Barrier(12)

    def worker():
        nonlocal peak, live
        start.wait()
        for _ in range(20):
            with pool.acquire():
                with guard:
                    live += 1
                    peak = max(peak, live)
                time.sleep(0.001)
                with guard:
                    live -= 1

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert peak <= 3, f"{peak} clients were checked out at once, ceiling is 3"
    assert len(created) <= 3, f"{len(created)} clients constructed, ceiling is 3"


def test_a_client_is_held_by_exactly_one_caller_at_a_time():
    """The thread-safety requirement, not an optimisation: clickhouse_connect's
    Client carries mutable per-instance state and no lock."""
    pool, _ = make_pool(size=3)
    holders: dict[int, int] = {}
    conflicts: list[str] = []
    guard = threading.Lock()
    start = threading.Barrier(9)

    def worker(me: int):
        start.wait()
        for _ in range(25):
            with pool.acquire() as client:
                with guard:
                    if id(client) in holders:
                        conflicts.append(f"client held by {holders[id(client)]} and {me}")
                    holders[id(client)] = me
                time.sleep(0.0005)
                with guard:
                    holders.pop(id(client), None)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert conflicts == [], conflicts


def test_a_client_is_returned_when_the_caller_raises():
    pool, created = make_pool(size=1)

    with pytest.raises(RuntimeError):
        with pool.acquire():
            raise RuntimeError("handler blew up")

    # If it were not returned, this would time out instead.
    with pool.acquire() as client:
        assert client is created[0]


def test_exhaustion_fails_within_the_timeout_rather_than_hanging():
    pool, _ = make_pool(size=1, timeout=0.2)

    with pool.acquire():
        started = time.perf_counter()
        with pytest.raises(pool_module.PoolTimeout):
            with pool.acquire():
                pass
        waited = time.perf_counter() - started

    assert waited < 2.0, f"waited {waited:.2f}s on a 0.2s timeout"


def test_a_dead_client_is_replaced_rather_than_served():
    pool, created = make_pool(size=1)

    with pool.acquire() as client:
        pass
    created[0].alive = False

    with pool.acquire() as client:
        assert client is not created[0], "a client failing ping() must not be served"
        assert len(created) == 2
    assert created[0].closed, "the dead client should have been closed"


def test_a_client_that_errors_is_not_returned_to_the_pool():
    """A connection error means the client is suspect; reusing it would spread
    one failed request across the next several."""
    pool, created = make_pool(size=2)

    with pytest.raises(ConnectionError):
        with pool.acquire() as client:
            raise ConnectionError("connection reset by peer")

    with pool.acquire() as client:
        assert client is not created[0]


def test_closing_the_pool_closes_every_client():
    pool, created = make_pool(size=2)

    with pool.acquire():
        with pool.acquire():
            pass
    pool.close()

    assert all(c.closed for c in created), "pool.close() must release every client"


# --- Observability ---------------------------------------------------------


def test_exhaustion_is_logged_so_it_is_visible_before_it_hurts(caplog):
    """A deployment approaching its ceiling should be readable in the logs.
    Waiting for user-facing refusals to appear is too late."""
    pool, _ = make_pool(size=1, timeout=0.1)

    with caplog.at_level("WARNING"):
        with pool.acquire():
            with pytest.raises(pool_module.PoolTimeout):
                with pool.acquire():
                    pass

    assert any(r.message == "pool_exhausted" for r in caplog.records)


def test_replacing_a_dead_client_is_logged(caplog):
    pool, created = make_pool(size=1)

    with pool.acquire():
        pass
    created[0].alive = False

    with caplog.at_level("INFO"):
        with pool.acquire():
            pass

    assert any(r.message == "pool_client_replaced" for r in caplog.records)


def test_a_successful_acquisition_is_not_logged(caplog):
    """Per-request logging of a normal checkout is noise at this volume."""
    pool, _ = make_pool(size=2)

    with caplog.at_level("INFO"):
        for _ in range(5):
            with pool.acquire():
                pass

    assert [r.message for r in caplog.records] == []


def test_a_bad_configuration_value_is_logged(monkeypatch, caplog):
    monkeypatch.setenv("QUANTLAB_PG_POOL_MAX", "nonsense")

    with caplog.at_level("WARNING"):
        pool_module.pool_config()

    assert any(r.message == "pool_config_invalid" for r in caplog.records)
