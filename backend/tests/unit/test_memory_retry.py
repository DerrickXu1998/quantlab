"""Bar-store reads retry ClickHouse's server-wide memory cancellations.

On the self-hosted VM every query shares one 2 GiB server ceiling, so two
heavy reads that each fit alone can still get one of them cancelled. Those are
retried; a query over its own per-query limit, or any other error, is not.
"""

from __future__ import annotations

import pytest

from quantlab.storage import warehouse
from quantlab.storage.warehouse import _MemoryRetryingClient, _server_memory_exhausted

TOTAL = (
    "Code: 241. DB::Exception: Memory limit (total) exceeded: would use 2.09 GiB "
    "(attempt to allocate chunk of 4718592 bytes), maximum: 2.00 GiB. OvercommitTracker "
    "decision: Query was selected to stop by OvercommitTracker. (MEMORY_LIMIT_EXCEEDED)"
)
PER_QUERY = (
    "Code: 241. DB::Exception: Memory limit (for query) exceeded: would use 1.75 GiB "
    "(attempt to allocate chunk of 1073741824 bytes), maximum: 1.50 GiB. (MEMORY_LIMIT_EXCEEDED)"
)


class _DatabaseError(Exception):
    """Shaped like clickhouse_connect's: the server code on ``.code``."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class _FlakyClient:
    def __init__(self, failures: list[Exception]):
        self._failures = list(failures)
        self.calls = 0
        self.database = "quantlab"

    def query(self, sql, parameters=None):
        self.calls += 1
        if self._failures:
            raise self._failures.pop(0)
        return ("rows", sql, parameters)


def _client(failures):
    inner = _FlakyClient(failures)
    slept: list[float] = []
    return _MemoryRetryingClient(inner, sleep=slept.append), inner, slept


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_DatabaseError(TOTAL, code=241), True),
        (_DatabaseError(TOTAL), True),  # older clickhouse-connect: code only in the text
        (_DatabaseError(PER_QUERY, code=241), False),
        (_DatabaseError("Code: 60. Unknown table", code=60), False),
        (RuntimeError("connection reset"), False),
    ],
)
def test_only_server_wide_memory_cancellations_count(exc, expected):
    assert _server_memory_exhausted(exc) is expected


def test_a_cancelled_read_is_retried_until_it_succeeds():
    client, inner, slept = _client([_DatabaseError(TOTAL, code=241)] * 2)

    assert client.query("SELECT 1", parameters={"a": 1}) == ("rows", "SELECT 1", {"a": 1})
    assert inner.calls == 3
    assert slept == list(warehouse.MEMORY_RETRY_DELAYS[:2])


def test_retries_are_bounded_and_the_last_error_surfaces():
    attempts = len(warehouse.MEMORY_RETRY_DELAYS) + 1
    client, inner, slept = _client([_DatabaseError(TOTAL, code=241)] * attempts)

    with pytest.raises(_DatabaseError):
        client.query("SELECT 1")
    assert inner.calls == attempts
    assert slept == list(warehouse.MEMORY_RETRY_DELAYS)


@pytest.mark.parametrize(
    "exc",
    [_DatabaseError(PER_QUERY, code=241), _DatabaseError("Code: 62. Syntax error", code=62)],
)
def test_other_failures_are_raised_at_once(exc):
    client, inner, slept = _client([exc])

    with pytest.raises(_DatabaseError):
        client.query("SELECT 1")
    assert inner.calls == 1
    assert slept == []


def test_everything_else_passes_through_to_the_pooled_client():
    client, inner, _ = _client([])
    assert client.database == "quantlab"
