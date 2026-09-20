"""Macro series -> pseudo-instrument bars: conversion logic and a live round-trip."""
from __future__ import annotations

import os
import uuid

import pandas as pd
import pytest

from quantlab.schema import BAR_COLUMNS
from quantlab.store import bars as bars_mod
from quantlab.store import catalog
from quantlab.store.macro import (
    DEFAULT_MAPPING,
    ingest_macro_series,
    parse_series_args,
    series_to_bars,
)

# ---------------------------------------------------------------------------
# Pure logic -- no database required
# ---------------------------------------------------------------------------


def _series(values: dict[str, float | None]) -> pd.Series:
    idx = pd.DatetimeIndex(list(values), name="date")
    return pd.Series(list(values.values()), index=idx, dtype="float64")


def test_series_to_bars_makes_degenerate_ohlc_bars():
    bars = series_to_bars(_series({"2024-01-02": 1.27, "2024-01-03": 1.26}), symbol="X.BOE")

    assert list(bars.columns) == list(BAR_COLUMNS)
    assert (bars["open"] == bars["close"]).all()
    assert (bars["high"] == bars["close"]).all()
    assert (bars["low"] == bars["close"]).all()
    assert (bars["adj_close"] == bars["close"]).all()
    assert (bars["volume"] == 0).all()
    assert bars["close"].tolist() == [1.27, 1.26]


def test_series_to_bars_drops_nan_and_sorts():
    """BoE series gap around holidays; a hole must not become a bar."""
    bars = series_to_bars(
        _series({"2024-01-03": 1.26, "2024-01-02": None, "2024-01-04": 1.25})
    )
    assert bars.index.tolist() == list(pd.DatetimeIndex(["2024-01-03", "2024-01-04"]))
    assert bars["close"].tolist() == [1.26, 1.25]


def test_series_to_bars_is_deterministic():
    series = _series({"2024-01-02": 5.25, "2024-01-03": 5.25, "2024-01-04": 5.0})
    pd.testing.assert_frame_equal(series_to_bars(series), series_to_bars(series))


def test_series_to_bars_passes_write_path_validation():
    """volume=0 and open==high==low==close must survive bars.validate -- this is
    the smallest deviation from real bars that the warehouse accepts."""
    bars = series_to_bars(_series({"2024-01-02": 1.27, "2024-01-03": 1.26}))
    accepted, rejected = bars_mod.validate(bars.reset_index())
    assert len(accepted) == 2
    assert rejected.empty


def test_non_positive_values_are_quarantined_not_written():
    """M4 growth went negative post-GFC. bars.validate insists on positive
    prices, so those days become recorded rejects, never silent zeros."""
    bars = series_to_bars(_series({"2024-01-02": 1.5, "2024-01-03": -0.4, "2024-01-04": 0.0}))
    accepted, rejected = bars_mod.validate(bars.reset_index())
    assert len(accepted) == 1
    assert rejected["reason"].tolist() == ["non-positive price", "non-positive price"]


def test_parse_series_args_defaults_to_the_five_common_series():
    mapping = parse_series_args(None)
    assert mapping == DEFAULT_MAPPING
    assert mapping["XUDLUSS"] == "GBPUSD.BOE"


def test_parse_series_args_parses_code_symbol_pairs():
    mapping = parse_series_args(["xudluss:GBPUSD.BOE", "IUDSNPY:GILT10Y.BOE"])
    assert mapping == {"XUDLUSS": "GBPUSD.BOE", "IUDSNPY": "GILT10Y.BOE"}
    with pytest.raises(ValueError):
        parse_series_args(["XUDLUSS"])


# ---------------------------------------------------------------------------
# Live database round-trip (provider stubbed; the store is real)
# ---------------------------------------------------------------------------

needs_store = pytest.mark.skipif(
    not (os.environ.get("QUANTLAB_DB_URL") and os.environ.get("QUANTLAB_CH_URL")),
    reason="needs QUANTLAB_DB_URL and QUANTLAB_CH_URL (run `make store-test`)",
)


@pytest.fixture
def store_conn():
    from quantlab import store

    with store.session() as conn:
        yield conn


@pytest.fixture
def store_client():
    from quantlab import store

    with store.ch_session() as client:
        yield client


class _StubBoe:
    """The BoeProvider interface (series_batch) over fixed data: the live test
    exercises the store, not the BoE endpoint."""

    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    def series_batch(self, codes, start, end=""):
        return self._frame[[c for c in codes if c in self._frame.columns]]


@needs_store
def test_ingest_macro_series_round_trip(store_conn, store_client):
    from quantlab import store

    code = f"T{uuid.uuid4().hex[:8].upper()}"
    symbol = f"TST{uuid.uuid4().hex[:6].upper()}.BOE"
    frame = pd.DataFrame(
        {code: [1.27, 1.26, 1.28]},
        index=pd.DatetimeIndex(["2026-01-05", "2026-01-06", "2026-01-07"], name="date"),
    )
    provider = _StubBoe(frame)

    first = ingest_macro_series(
        store_conn, store_client, {code: symbol}, "2026-01-01", "2026-01-31",
        provider=provider,
    )
    assert first.status == "ok"
    assert first.symbols_ok == 1
    assert first.rows_written == 3

    panel = store.load_panel(store_conn, store_client, [symbol])
    assert len(panel) == 3
    assert panel["close"].tolist() == [1.27, 1.26, 1.28]
    assert (panel["open"] == panel["close"]).all()

    # Re-ingesting the same range must read back once (ReplacingMergeTree).
    second = ingest_macro_series(
        store_conn, store_client, {code: symbol}, "2026-01-01", "2026-01-31",
        provider=provider,
    )
    assert second.run_id > first.run_id
    assert len(store.load_panel(store_conn, store_client, [symbol])) == 3

    # Catalog marker and provenance.
    row = store_conn.execute(
        "SELECT sector, meta->>'macro', meta->>'series_code' FROM instruments WHERE symbol = %s",
        (symbol,),
    ).fetchone()
    assert row == ("Macro", "true", code)
    run = store_conn.execute(
        "SELECT source, kind, status FROM ingest_runs WHERE run_id = %s", (first.run_id,)
    ).fetchone()
    assert run == ("boe", "prices", "ok")

    # ingest_macro_series commits as it goes, so a fixture rollback cannot
    # undo it; remove bars and catalog rows explicitly (symbol_map cascades).
    instrument_id = catalog.instrument_ids(store_conn, [symbol])[symbol]
    store_client.command(
        f"ALTER TABLE {bars_mod.TABLE} DELETE WHERE instrument_id = %(iid)s",
        parameters={"iid": int(instrument_id)},
    )
    store_conn.execute(
        "DELETE FROM ingest_runs WHERE run_id = ANY(%s)", ([first.run_id, second.run_id],)
    )
    store_conn.execute("DELETE FROM instruments WHERE instrument_id = %s", (instrument_id,))
    store_conn.commit()
