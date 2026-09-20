"""The replay publisher: warehouse history -> chronological Kafka event stream.

No Kafka and no ClickHouse here: the producer is a list-backed fake with the
kafka-python shape (send/flush), and the store reads are monkeypatched. What
is under test is the contract the backend consumer relies on -- chronological
(date, symbol) ordering, the payload schema, and the terminal end message.
"""
from __future__ import annotations

import pandas as pd
import pytest

from quantlab import store
from quantlab.streaming import publish_replay


class FakeProducer:
    def __init__(self):
        self.sent = []  # (topic, key, value)
        self.flushed = False

    def send(self, topic, key=None, value=None):
        self.sent.append((topic, key, value))

    def flush(self):
        self.flushed = True


def _frame(rows):
    """A frame shaped like store.bars.load_bars output."""
    return pd.DataFrame(
        rows,
        columns=["instrument_id", "ts", "open", "high", "low", "close", "volume"],
    )


@pytest.fixture()
def patched_store(monkeypatch):
    state = {"ids": {"AAA.US": 1, "BBB.US": 2}, "frame": _frame([])}
    monkeypatch.setattr(store, "instrument_ids", lambda conn, symbols: state["ids"])
    monkeypatch.setattr(
        store, "load_bars", lambda client, ids, **kw: state["frame"]
    )
    return state


def _bars_frame():
    # Deliberately not in (date, symbol) order within the frame: the publisher
    # sorts, whatever the store returns.
    return _frame(
        [
            (2, pd.Timestamp("2024-01-03"), 21.0, 22.0, 20.0, 21.5, 300),
            (1, pd.Timestamp("2024-01-02"), 10.0, 11.0, 9.0, 10.5, 100),
            (2, pd.Timestamp("2024-01-02"), 20.0, 21.0, 19.0, 20.5, 200),
            (1, pd.Timestamp("2024-01-03"), 11.0, 12.0, 10.0, 11.5, 150),
        ]
    )


def test_publishes_chronologically_with_the_wire_schema(patched_store):
    patched_store["frame"] = _bars_frame()
    producer = FakeProducer()

    report = publish_replay(
        None, None, producer, ["AAA.US", "BBB.US"], "2024-01-01", "2024-01-31"
    )

    messages = producer.sent
    assert len(messages) == 5  # 4 bars + the end control message
    topic, key, end = messages[-1]
    assert end == {"type": "end"}
    assert producer.flushed

    bars = [value for _, _, value in messages[:-1]]
    assert [(b["date"], b["symbol"]) for b in bars] == sorted(
        (b["date"], b["symbol"]) for b in bars
    )
    # Every message is keyed by its symbol, so a symbol's partition is ordered.
    assert all(key == value["symbol"] for _, key, value in messages[:-1])
    assert bars[0] == {
        "type": "bar",
        "symbol": "AAA.US",
        "date": "2024-01-02",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 100,
    }

    assert report.bars_published == 4
    assert report.dates == 2
    assert report.symbols == ["AAA.US", "BBB.US"]
    assert report.topic == "quantlab.bars"


def test_empty_window_publishes_only_the_end_message(patched_store):
    producer = FakeProducer()

    report = publish_replay(None, None, producer, ["AAA.US"], "2024-01-01", "2024-01-31")

    assert [value for _, _, value in producer.sent] == [{"type": "end"}]
    assert report.bars_published == 0
    assert report.dates == 0


def test_unknown_symbols_are_rejected(patched_store):
    with pytest.raises(ValueError, match="ZZZ.US"):
        publish_replay(None, None, FakeProducer(), ["AAA.US", "ZZZ.US"], "2024-01-01", "2024-02-01")


def test_no_symbols_is_rejected(patched_store):
    with pytest.raises(ValueError, match="at least one symbol"):
        publish_replay(None, None, FakeProducer(), [], "2024-01-01", "2024-02-01")


def test_custom_topic(patched_store):
    producer = FakeProducer()
    publish_replay(
        None, None, producer, ["AAA.US"], "2024-01-01", "2024-01-31", topic="quantlab.test"
    )
    assert all(topic == "quantlab.test" for topic, _, _ in producer.sent)
