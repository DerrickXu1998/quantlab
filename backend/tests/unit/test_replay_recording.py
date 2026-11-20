"""A run's replay is a record of what it did, not a re-run on today's data.

Bars are revised, splits restated, symbols re-ingested. A replay that
re-simulated on request would then show fills and a result the run never had.
The replay is recorded when the run completes and only ever read back; a run
that predates recording is rebuilt once, marked as such, and then read back
like any other.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from quantlab import seed
from quantlab.api.app import create_app
from quantlab.replay import engine as replay_engine
from quantlab.replay import recording
from quantlab.research import runner
from quantlab.storage import backends, db, experiments, repository
from quantlab.synthetic.generator import generate_universe

# --- the record itself ---------------------------------------------------------


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    path = tmp_path_factory.mktemp("rec") / "test.db"
    conn = db.connect(path)
    db.bootstrap(conn)
    repository.upsert_instruments(conn)
    repository.insert_bars(conn, generate_universe())
    conn.commit()
    conn.close()
    backend = backends.SqliteBackend(str(path))
    store = experiments.SqliteExperimentStore(str(path))
    symbols = sorted(item["symbol"] for item in backend.list_instruments()["items"][:2])
    result = runner.run_experiment(
        backend, model_name="sma-crossover", overrides={}, symbols=symbols,
        start_date="2024-01-01", end_date="2024-12-31",
    )
    store.save_run(result)
    run = store.get_run(result.id)
    signals, bars = replay_engine.load_replay_inputs(backend, store, run)
    return run, signals, bars


@pytest.mark.parametrize("step", [1, 2, 3, 7, 50])
def test_playback_thins_exactly_as_the_engine_does(seeded, step):
    run, signals, bars = seeded
    recorded = recording.record(replay_engine.replay_events(run, signals, bars))
    expected = [
        json.loads(json.dumps(replay_engine.to_dict(e), sort_keys=True))
        for e in replay_engine.replay_events(run, signals, bars, step=step)
    ]
    assert list(recording.playback(recorded.events, step=step)) == expected


def test_the_record_carries_its_summary_and_whether_it_was_reconstructed(seeded):
    run, signals, bars = seeded
    events = list(replay_engine.replay_events(run, signals, bars))
    recorded = recording.record(events)
    assert recorded.reconstructed is False
    assert recorded.summary["final_equity"] == pytest.approx(events[-1].final_equity)
    assert recorded.summary["reconstructed"] is False
    assert "event" not in recorded.summary

    rebuilt = recording.record(events, reconstructed=True)
    assert rebuilt.summary["reconstructed"] is True
    assert list(recording.frames(rebuilt.events))[-1]["reconstructed"] is True


def test_a_stream_without_a_summary_is_not_a_record(seeded):
    run, signals, bars = seeded
    events = list(replay_engine.replay_events(run, signals, bars))[:-1]
    with pytest.raises(ValueError, match="summary"):
        recording.record(events)


# --- through the API: the data changes, the replay does not ---------------------


@pytest.fixture
def api(tmp_path):
    path = tmp_path / "quantlab.db"
    seed.run(path)
    with TestClient(create_app(str(path))) as client:
        yield client, path


def _frames(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _create(client):
    symbols = [i["symbol"] for i in client.get("/api/v1/instruments").json()["items"][:2]]
    body = {"model_name": "sma-crossover", "symbols": symbols,
            "start_date": "2024-01-01", "end_date": "2024-12-31"}
    created = client.post("/api/v1/runs", json=body)
    assert created.status_code == 201
    return created.json()["id"], symbols, body


def _revise_bars(path, symbols):
    """A vendor revision: every bar from March on, 50% higher."""
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE price_bars SET open = open * 1.5, high = high * 1.5, low = low * 1.5, "
            f"close = close * 1.5 WHERE date >= '2024-03-01' AND symbol IN "
            f"({', '.join('?' * len(symbols))})",
            symbols,
        )


def test_a_replay_is_unchanged_when_the_underlying_bars_are_revised(api):
    client, path = api
    run_id, symbols, body = _create(client)
    before = client.get(f"/api/v1/runs/{run_id}/replay/stream")
    summary_before = client.get(f"/api/v1/runs/{run_id}/replay/summary").json()
    assert before.headers["x-replay-source"] == "recorded"
    assert summary_before["reconstructed"] is False

    _revise_bars(path, symbols)

    after = client.get(f"/api/v1/runs/{run_id}/replay/stream")
    assert _frames(after) == _frames(before)
    assert client.get(f"/api/v1/runs/{run_id}/replay/summary").json() == summary_before
    # The revision is real: a new run with the same configuration sees it.
    fresh = client.post("/api/v1/runs", json=body).json()["id"]
    fresh_summary = client.get(f"/api/v1/runs/{fresh}/replay/summary").json()
    assert fresh_summary["final_equity"] != pytest.approx(summary_before["final_equity"])


def test_the_replay_reconciles_with_the_runs_stored_performance(api):
    client, _ = api
    run_id, _, _ = _create(client)
    summary = client.get(f"/api/v1/runs/{run_id}/replay/summary").json()
    perf = client.get(f"/api/v1/runs/{run_id}/performance").json()
    assert summary["final_equity"] == pytest.approx(perf["equity"][-1]["value"])
    assert summary["trade_count"] == perf["metrics"]["trade_count"]


def test_a_run_from_before_recording_is_rebuilt_once_and_then_kept(api):
    client, path = api
    run_id, symbols, _ = _create(client)
    with sqlite3.connect(path) as conn:  # as if recorded before replays were
        conn.execute("DELETE FROM experiment_replays WHERE run_id = ?", (run_id,))

    first = client.get(f"/api/v1/runs/{run_id}/replay/stream")
    assert first.headers["x-replay-source"] == "reconstructed"
    assert _frames(first)[-1]["reconstructed"] is True

    _revise_bars(path, symbols)

    # Rebuilt once: the later revision does not reach it.
    again = client.get(f"/api/v1/runs/{run_id}/replay/stream")
    assert _frames(again) == _frames(first)


def test_deleting_a_run_deletes_its_replay(api):
    client, _ = api
    run_id, _, _ = _create(client)
    store = client.app.state.experiments
    assert store.get_replay(run_id) is not None
    assert client.delete(f"/api/v1/runs/{run_id}").status_code in (200, 204)
    assert store.get_replay(run_id) is None


def test_a_nan_in_the_stream_is_stored_as_strict_json(seeded):
    from dataclasses import replace as dc_replace

    run, signals, bars = seeded
    events = list(replay_engine.replay_events(run, signals, bars))
    events[-1] = dc_replace(events[-1], final_equity=float("nan"), sharpe_ratio=float("inf"))
    recorded = recording.record(events)
    assert recorded.summary["final_equity"] is None
    assert recorded.summary["sharpe_ratio"] is None
    for frame in recording.frames(recorded.events):
        json.dumps(frame, allow_nan=False)  # raises on NaN/inf


def test_an_inline_run_stores_its_performance_and_replay_at_completion(api):
    client, path = api
    run_id, symbols, _ = _create(client)
    store = client.app.state.experiments
    performance = store.get_performance(run_id)
    assert performance is not None
    _revise_bars(path, symbols)
    # Read back, never recomputed against the revised bars.
    served = client.get(f"/api/v1/runs/{run_id}/performance").json()
    assert served["reconstructed"] is False  # recorded, not rebuilt
    assert served == performance
    assert store.get_replay(run_id, events=False)["events"] is None
    assert store.get_replay(run_id, events=False)["summary"]["final_equity"] == pytest.approx(
        performance["equity"][-1]["value"]
    )


def test_a_thinned_record_keeps_whole_sessions_and_every_trade(seeded):
    run, signals, bars = seeded
    events = list(replay_engine.replay_events(run, signals, bars))
    full = list(recording.frames(recording.record(events).events))
    frames = list(recording.frames(recording.record(events, every=5).events))
    equity = [f for f in frames if f["event"] == "equity"]
    eventful = {f["date"] for f in full if f["event"] in ("signal", "fill")}
    # Bar and equity frames both thinned, to whole sessions...
    sessions = sum(1 for f in full if f["event"] == "equity")
    assert len(equity) <= sessions // 5 + 2 + len(eventful)
    assert {f["date"] for f in frames if f["event"] == "bar"} <= {f["date"] for f in equity}
    # ...but no trade ever loses its price or its mark, and the summary is whole.
    assert eventful <= {f["date"] for f in equity}
    assert eventful <= {f["date"] for f in frames if f["event"] == "bar"}
    assert frames[-1] == full[-1]
    # The curve ends where the run did, on the summary's own mark.
    last_mark = [f for f in full if f["event"] == "equity"][-1]
    assert equity[-1] == last_mark
    assert frames[-2] == full[-2]


def test_only_an_intraday_run_is_thinned():
    from quantlab.execution import ExecutionConfig
    from quantlab.research import jobs

    run = {"start_date": "2000-01-01", "end_date": "2024-12-31", "symbols": ["A", "B"]}
    assert jobs._record_step(run, ExecutionConfig()) == (1, 1)  # 25y daily: every mark
    every, _ = jobs._record_step(run, ExecutionConfig(bar_frequency="5m"))
    assert every > 1
    # A wide selection thins its bar frames (closes), never its equity marks.
    wide = {**run, "symbols": [f"S{i}" for i in range(2000)]}
    assert jobs._record_step(wide, ExecutionConfig())[0] == 1
    assert jobs._record_step(wide, ExecutionConfig())[1] > 1


def test_a_transient_failure_while_recording_is_retried(api, monkeypatch):
    from quantlab.research import jobs

    calls = {"n": 0}
    real = jobs._replay

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("minute store timed out")
        return real(*args, **kwargs)

    monkeypatch.setattr(jobs, "_replay", flaky)
    monkeypatch.setattr(jobs.time, "sleep", lambda s: None)
    client, _ = api
    run_id, _, _ = _create(client)
    stored = client.app.state.experiments.get_replay(run_id)
    assert stored["error"] is None and stored["reconstructed"] is False


def test_thinning_closes_keeps_every_equity_mark(seeded):
    run, signals, bars = seeded
    events = list(replay_engine.replay_events(run, signals, bars))
    full = list(recording.frames(recording.record(events).events))
    thin = list(recording.frames(recording.record(events, bars_every=4).events))
    marks = lambda fs: [f for f in fs if f["event"] == "equity"]  # noqa: E731
    assert marks(thin) == marks(full)
    assert sum(f["event"] == "bar" for f in thin) < sum(f["event"] == "bar" for f in full)
    eventful = {f["date"] for f in full if f["event"] in ("signal", "fill")}
    assert eventful <= {f["date"] for f in thin if f["event"] == "bar"}


def test_step_on_a_thinned_record_counts_the_bars_it_kept(seeded):
    """``step`` means every Nth bar the record holds, not every Nth group:
    groups whose bar frame the record dropped are not counted."""
    run, signals, bars = seeded
    events = list(replay_engine.replay_events(run, signals, bars))
    thin = recording.record(events, bars_every=2).events
    kept = list(dict.fromkeys(f["date"] for f in recording.frames(thin) if f["event"] == "bar"))
    eventful = {f["date"] for f in recording.frames(thin) if f["event"] in ("signal", "fill")}
    played = {f["date"] for f in recording.playback(thin, step=2) if f["event"] == "bar"}
    assert played == set(kept[::2]) | (eventful & set(kept))


def test_a_fill_never_plays_back_without_its_bar(seeded):
    run, signals, bars = seeded
    stored = recording.record(replay_engine.replay_events(run, signals, bars)).events
    for step in (3, 7):
        played = list(recording.playback(stored, step=step))
        priced = {f["date"] for f in played if f["event"] == "bar"}
        fills = {f["date"] for f in played if f["event"] == "fill"}
        assert fills and fills <= priced
        # And the stream as stored is the stream decoded: nothing re-encoded.
        lines = list(recording.playback_lines(stored, step=step))
        assert [kind for kind, _ in lines] == [f["event"] for f in played]


def test_an_intraday_summary_counts_sessions_not_bars():
    from quantlab.execution import ExecutionConfig
    from quantlab.storage.warehouse import Bar

    bars = [
        Bar(date=f"2024-01-0{d}T{9 + k // 12:02d}:{(k % 12) * 5:02d}:00",
            open=100.0, high=101.0, low=99.0, close=100.0 + d + k / 100, volume=1000)
        for d in (2, 3, 4) for k in range(24)
    ]
    run = {"id": "r", "symbols": ["X"], "start_date": "2024-01-02"}
    events = list(replay_engine.replay_events(
        run, [], {"X": bars}, config=ExecutionConfig(bar_frequency="5m")
    ))
    assert events[-1].days == 3  # sessions, as performance counts them
    assert sum(isinstance(e, replay_engine.ReplayEquity) for e in events) == 72  # each bar


def test_a_clickhouse_memory_cancellation_is_retried_not_stored():
    from quantlab.research import jobs

    class DatabaseError(Exception):
        code = 241

    DatabaseError.__module__ = "clickhouse_connect.driver.exceptions"
    assert jobs.transient(DatabaseError("Code: 241. Memory limit (total) exceeded"))
    assert not jobs.transient(DatabaseError("Code: 241. Memory limit (for query) exceeded"))


def test_a_stored_parameter_the_rule_cannot_use_falls_back_to_its_floor():
    from quantlab.signals.registry import get_rule

    run = {"model_name": "sma-crossover", "parameters": {"fast": None, "slow": "200"}}
    assert replay_engine._lookback_days(run) == get_rule("sma-crossover").lookback_days
