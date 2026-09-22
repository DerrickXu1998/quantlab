"""The bus adapter's read: message filtering and, above all, where it stops.

No broker here -- ``select_bars`` is the pure half of the adapter, so a list
of fake consumer records stands in for the topic, and ``open``'s topic checks
run against a stub ``kafka`` module.

The case that matters is a topic published to more than once. ``publish_replay``
appends one ``{"type": "end"}`` per publish and every read starts at offset 0,
so treating the first marker as the end of the stream served publish #1's bars
for ever after -- silently, with a well-formed SSE stream and a summary
computed over the wrong window.
"""

from __future__ import annotations

import sys
import types
from collections import namedtuple

import pytest

from quantlab.replay.engine import ReplaySummary
from quantlab.signals import registry as signal_registry
from quantlab.signals.engine import compute_signals
from quantlab.streaming import bus, live
from quantlab.synthetic.generator import generate_universe

TOPIC = "quantlab.bars"
START = "2024-01-01"
END = "2024-12-31"
MID = "2024-06-30"
SYMBOLS = ["ZZMEAN", "ZZTRND"]

Record = namedtuple("Record", "topic partition offset value")


def _bar(symbol: str, date: str, close: float = 1.0) -> dict:
    return {
        "type": "bar",
        "symbol": symbol,
        "date": date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100,
    }


def _log(*publishes: list[dict]) -> tuple[list[Record], dict[tuple[str, int], int]]:
    """One partition's log from consecutive publishes, plus its end offsets.

    Each publish is a payload list exactly as ``publish_replay`` would send it,
    terminal marker included or not (an unterminated last publish is one still
    in flight).
    """
    records = [
        Record(TOPIC, 0, offset, payload)
        for offset, payload in enumerate(p for publish in publishes for p in publish)
    ]
    return records, {(TOPIC, 0): len(records)}


def _publish(payloads: list[dict], *, finished: bool = True) -> list[dict]:
    return [*payloads, {"type": "end"}] if finished else list(payloads)


# --- where the read stops -----------------------------------------------------


def test_single_publish_stops_at_its_end_marker():
    records, offsets = _log(_publish([_bar("ZZMEAN", "2024-01-02")]))
    assert list(bus.select_bars(records, {"ZZMEAN"}, offsets)) == [
        _bar("ZZMEAN", "2024-01-02")
    ]


def test_second_publish_is_not_hidden_by_the_first_end_marker():
    """The regression: both publishes' bars must come back, not just the first."""
    records, offsets = _log(
        _publish([_bar("ZZMEAN", "2024-01-02")]),
        _publish([_bar("ZZMEAN", "2024-01-02"), _bar("ZZMEAN", "2024-01-03")]),
    )
    dates = [bar["date"] for bar in bus.select_bars(records, {"ZZMEAN"}, offsets)]
    # The re-published 01-02 arrives twice; de-duplication is live_replay_events'
    # job, so the adapter passes both through.
    assert dates == ["2024-01-02", "2024-01-02", "2024-01-03"]


def test_third_publish_is_reached_too():
    records, offsets = _log(
        _publish([_bar("ZZMEAN", "2024-01-02")]),
        _publish([_bar("ZZMEAN", "2024-01-03")]),
        _publish([_bar("ZZMEAN", "2024-01-04")]),
    )
    dates = [bar["date"] for bar in bus.select_bars(records, {"ZZMEAN"}, offsets)]
    assert dates == ["2024-01-02", "2024-01-03", "2024-01-04"]


def test_publish_still_in_flight_does_not_stop_at_the_earlier_marker():
    """A log whose last message is a bar is mid-publish: keep following it.

    Stopping here would truncate the publish the caller is watching arrive,
    which is the whole point of --pace-ms.
    """
    records, offsets = _log(
        _publish([_bar("ZZMEAN", "2024-01-02")]),
        _publish([_bar("ZZMEAN", "2024-01-03")], finished=False),
    )
    dates = [bar["date"] for bar in bus.select_bars(records, {"ZZMEAN"}, offsets)]
    assert dates == ["2024-01-02", "2024-01-03"]


def test_empty_window_publish_yields_nothing_and_terminates():
    records, offsets = _log(_publish([]))
    assert list(bus.select_bars(records, {"ZZMEAN"}, offsets)) == []


def test_unknown_partition_falls_back_to_stopping_at_the_first_marker():
    """Missing end offsets degrade to the old, safe behaviour rather than hang."""
    records, _ = _log(
        _publish([_bar("ZZMEAN", "2024-01-02")]),
        _publish([_bar("ZZMEAN", "2024-01-03")]),
    )
    dates = [bar["date"] for bar in bus.select_bars(records, {"ZZMEAN"}, {})]
    assert dates == ["2024-01-02"]


# --- what the read passes through ---------------------------------------------


def test_symbols_outside_the_selection_are_dropped():
    records, offsets = _log(
        _publish([_bar("ZZMEAN", "2024-01-02"), _bar("ZZTRND", "2024-01-02")])
    )
    got = list(bus.select_bars(records, {"ZZMEAN"}, offsets))
    assert [bar["symbol"] for bar in got] == ["ZZMEAN"]


def test_non_bar_messages_are_ignored():
    records, offsets = _log(
        _publish(
            [
                {"type": "heartbeat"},
                _bar("ZZMEAN", "2024-01-02"),
            ]
        )
    )
    payloads = list(bus.select_bars(records, {"ZZMEAN"}, offsets))
    assert [p["type"] for p in payloads] == ["bar"]


def test_non_dict_payloads_are_ignored():
    records = [
        Record(TOPIC, 0, 0, "not a dict"),
        Record(TOPIC, 0, 1, _bar("ZZMEAN", "2024-01-02")),
        Record(TOPIC, 0, 2, {"type": "end"}),
    ]
    offsets = {(TOPIC, 0): 3}
    assert len(list(bus.select_bars(records, {"ZZMEAN"}, offsets))) == 1


# --- the payoff: a twice-published topic still replays like the batch engine ---


def _wire(bars_by_symbol, start=None, end=None) -> list[dict]:
    """The publisher's wire format for a window: sorted (date, symbol)."""
    messages = [
        {
            "type": "bar",
            "symbol": symbol,
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        for symbol in SYMBOLS
        for bar in bars_by_symbol[symbol]
        if (start is None or bar.date >= start) and (end is None or bar.date <= end)
    ]
    messages.sort(key=lambda m: (m["date"], m["symbol"]))
    return messages


@pytest.fixture(scope="module")
def bars_by_symbol():
    return {symbol: generate_universe()[symbol] for symbol in SYMBOLS}


def test_live_replay_over_a_twice_published_log_matches_batch(bars_by_symbol):
    """Publish a half window, then the whole one; the reader must see the whole.

    Before the fix this returned the January-June replay under a January-December
    label -- a real equity curve and summary, computed over half the bars asked
    for, with no error anywhere.
    """
    records, offsets = _log(
        _publish(_wire(bars_by_symbol, end=MID)),
        _publish(_wire(bars_by_symbol)),
    )
    stream = bus.select_bars(records, set(SYMBOLS), offsets)
    events = list(
        live.live_replay_events("sma-crossover", None, list(SYMBOLS), START, END, stream)
    )

    rule = signal_registry.get_rule("sma-crossover")
    computed = compute_signals(bars_by_symbol, rules=[rule])
    assert computed is not None

    live_summary = events[-1]
    assert isinstance(live_summary, ReplaySummary)
    # The whole year replayed, not the half that precedes the first marker.
    bar_dates = [e.date for e in events if hasattr(e, "closes")]
    assert bar_dates == sorted(set(bar_dates)), "each date marked once, in order"
    assert max(bar_dates) > MID, "the second publish's bars were never consumed"
    assert min(bar_dates) >= START


# --- open()'s topic checks, against a stub broker ------------------------------


class _StubTopicPartition:
    def __init__(self, topic, partition):
        self.topic = topic
        self.partition = partition

    def __eq__(self, other):
        return (self.topic, self.partition) == (other.topic, other.partition)

    def __hash__(self):
        return hash((self.topic, self.partition))


class _StubConsumer:
    def __init__(self, partitions, **kwargs):
        self._partitions = partitions
        self.closed = False

    def partitions_for_topic(self, topic):
        return self._partitions

    def assign(self, tps):
        self.assigned = list(tps)

    def end_offsets(self, tps):
        return {tp: 7 for tp in tps}

    def seek_to_beginning(self, *tps):
        self.rewound = list(tps)

    def close(self, autocommit=True):
        self.closed = True


@pytest.fixture
def stub_kafka(monkeypatch):
    """Install a stub ``kafka`` module and hand back the consumers it builds."""
    built = []

    def install(partitions):
        module = types.ModuleType("kafka")

        def factory(**kwargs):
            consumer = _StubConsumer(partitions, **kwargs)
            built.append(consumer)
            return consumer

        module.KafkaConsumer = factory
        module.TopicPartition = _StubTopicPartition
        monkeypatch.setitem(sys.modules, "kafka", module)
        return built

    return install


def _stream() -> bus.KafkaBarStream:
    return bus.KafkaBarStream("broker:9092", TOPIC, SYMBOLS, START, END)


def test_open_refuses_a_multi_partition_topic(stub_kafka):
    built = stub_kafka({0, 1, 2})
    with pytest.raises(bus.BusUnavailable, match="3 partitions"):
        _stream().open()
    assert built[0].closed, "the consumer must not leak when the topic is refused"


def test_open_refuses_a_missing_topic(stub_kafka):
    built = stub_kafka(None)
    with pytest.raises(bus.BusUnavailable, match="does not exist"):
        _stream().open()
    assert built[0].closed


def test_open_snapshots_end_offsets_and_rewinds(stub_kafka):
    stub_kafka({0})
    stream = _stream().open()
    assert stream._end_offsets == {(TOPIC, 0): 7}
    assert stream._consumer.rewound == [_StubTopicPartition(TOPIC, 0)]
    stream.close()


def test_iter_before_open_raises():
    with pytest.raises(bus.BusUnavailable, match="open"):
        list(_stream())
