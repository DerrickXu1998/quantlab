"""Price bars in ClickHouse: validation, insert, and dedup-correct reads.

Two things ClickHouse does not do for us, handled here:

1. **Constraints.** There are none. Everything the Postgres CHECK constraints
   used to enforce -- positive prices, OHLC ordering, non-negative volume --
   is enforced in `validate` before insert, and what fails is handed back to
   the caller to record in the catalog's ingest_rejects table. Nothing is
   dropped silently.

2. **Immediate dedup.** ReplacingMergeTree collapses duplicate sort keys at
   merge time on its own schedule, not at insert. Every read here therefore
   goes through `price_bars_current` (a FINAL view) so a re-ingested range
   never reads back doubled.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import pandas as pd

from ..schema import Currency
from .catalog import storage_currency

log = logging.getLogger(__name__)

TABLE = "price_bars"
VIEW = "price_bars_current"

_BAR_COLUMNS = ("open", "high", "low", "close", "volume", "adj_close")

# The table is partitioned by toYYYYMM(ts), and ClickHouse refuses an insert
# block touching more than max_partitions_per_insert_block (default 100)
# partitions. A chunk of a full year stays comfortably under the default while
# keeping the number of round-trips small for multi-decade backfills.
MAX_PARTITIONS_PER_INSERT = 12

_INSERT_COLUMNS = [
    "instrument_id",
    "frequency",
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adj_close",
    "currency",
    "source",
    "run_id",
]


@dataclass
class WriteResult:
    """Outcome of a bulk bar write."""

    written: int = 0
    rejected: pd.DataFrame = field(default_factory=pd.DataFrame)
    symbols_ok: int = 0

    @property
    def rejected_count(self) -> int:
        return 0 if self.rejected is None else len(self.rejected)

    @property
    def reasons(self) -> dict[str, int]:
        if self.rejected is None or self.rejected.empty:
            return {}
        return {str(k): int(v) for k, v in self.rejected["reason"].value_counts().items()}


def validate(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split bars into (accepted, rejected_with_reason).

    Free sources ship bad ticks; one of them must not poison the table, and
    ClickHouse would happily accept it.
    """
    if frame.empty:
        return frame, frame.assign(reason=pd.Series(dtype=object))

    prices = frame[["open", "high", "low", "close"]]
    finite = prices.notna().all(axis=1)
    positive = (prices > 0).all(axis=1)
    ordered = (
        (frame["high"] >= frame[["open", "close"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close"]].min(axis=1))
        & (frame["high"] >= frame["low"])
    )
    volume_ok = frame["volume"].isna() | (frame["volume"] >= 0)

    reason = pd.Series("", index=frame.index, dtype=object)
    reason = reason.mask(~finite, "missing OHLC value")
    reason = reason.mask(~positive & (reason == ""), "non-positive price")
    reason = reason.mask(~ordered & (reason == ""), "OHLC ordering violated")
    reason = reason.mask(~volume_ok & (reason == ""), "negative volume")

    bad = reason != ""
    rejected = frame[bad].copy()
    rejected["reason"] = reason[bad]
    return frame[~bad].copy(), rejected


def partition_chunks(
    frame: pd.DataFrame,
    *,
    ts_column: str = "ts",
    max_partitions: int = MAX_PARTITIONS_PER_INSERT,
) -> list[pd.DataFrame]:
    """Split a payload into chunks each touching at most `max_partitions`
    calendar months of `ts` -- one chunk per `toYYYYMM` partition batch.

    ClickHouse rejects an insert block spanning more partitions than
    max_partitions_per_insert_block (default 100), so a long backfill must not
    go in as one block. Chunks follow month boundaries so each insert is as
    large as the limit safely allows. Pure: no client, no I/O.
    """
    if frame.empty:
        return []
    months = frame[ts_column].dt.to_period("M")
    codes, uniques = pd.factorize(months, sort=True)
    return [
        frame[(codes >= start) & (codes < start + max_partitions)]
        for start in range(0, len(uniques), max_partitions)
    ]


def write_bars(
    client,
    panel: pd.DataFrame,
    *,
    run_id: int,
    ids: Mapping[str, int],
    currencies: Mapping[str, Currency],
    source_by_symbol: Mapping[str, str] | None = None,
    source: str = "",
    frequency: str = "1d",
) -> WriteResult:
    """Insert a long (date, symbol) panel into ClickHouse price_bars.

    `currencies` holds the *quote* currency per symbol as reported by
    fx.normalise_panel; the panel is expected to already be in major units,
    so what lands in the currency column is the normalised one.

    Idempotent by way of ReplacingMergeTree(run_id): re-ingesting a range
    inserts new rows that supersede the old on the next merge, and reads
    through `price_bars_current` see only the winner in the meantime.
    """
    if panel is None or panel.empty:
        return WriteResult()

    frame = panel.reset_index()
    if "date" not in frame.columns or "symbol" not in frame.columns:
        raise ValueError("panel must be indexed by (date, symbol)")

    for column in _BAR_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA

    frame = frame[frame["symbol"].isin(ids)].copy()
    if frame.empty:
        return WriteResult()

    frame["instrument_id"] = frame["symbol"].map(ids).astype("int64")
    # Daily bars land at 00:00:00 UTC of the session date. The column is a
    # DateTime64 so intraday needs no migration, only finer values.
    frame["ts"] = pd.to_datetime(frame["date"])
    frame["frequency"] = frequency
    frame["run_id"] = int(run_id)
    frame["currency"] = frame["symbol"].map(
        lambda s: storage_currency(currencies.get(s, Currency.USD)).value
    )
    source_by_symbol = source_by_symbol or {}
    frame["source"] = frame["symbol"].map(lambda s: source_by_symbol.get(s, source) or source)

    for column in ("open", "high", "low", "close", "adj_close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")

    accepted, rejected = validate(frame)
    if accepted.empty:
        return WriteResult(written=0, rejected=rejected, symbols_ok=0)

    payload = accepted[_INSERT_COLUMNS].copy()
    # ClickHouse Int64 volume is not nullable in the schema; an unreported
    # volume becomes 0, which is distinguishable from a real trade count of 0
    # only via the source. Prices stay float and adj_close stays nullable.
    payload["volume"] = payload["volume"].fillna(0).round().astype("int64")
    payload["instrument_id"] = payload["instrument_id"].astype("int64")
    payload["run_id"] = payload["run_id"].astype("int64")
    payload["adj_close"] = payload["adj_close"].astype(object).where(
        payload["adj_close"].notna(), None
    )

    # Chunk by partition month: a long backfill in one block trips
    # max_partitions_per_insert_block. Chunks insert in calendar order; a
    # mid-way failure leaves the run marked failed, and a re-run supersedes
    # whatever landed (ReplacingMergeTree).
    written = 0
    for chunk in partition_chunks(payload):
        client.insert_df(TABLE, chunk)
        written += len(chunk)

    return WriteResult(
        written=written,
        rejected=rejected,
        symbols_ok=int(accepted["symbol"].nunique()),
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _ts_bound(value: str | dt.date | dt.datetime | None) -> dt.datetime | None:
    if value is None or value == "":
        return None
    return pd.Timestamp(value).to_pydatetime()


def load_bars(
    client,
    instrument_ids: Sequence[int] | None = None,
    *,
    start: str | dt.date | None = None,
    end: str | dt.date | None = None,
    frequency: str = "1d",
) -> pd.DataFrame:
    """Raw bars for the given instruments, deduplicated.

    Returns a frame keyed by instrument_id; callers that want symbols join
    against the catalog. Keeping the join out of ClickHouse is deliberate --
    identity is Postgres's job.
    """
    clauses = ["frequency = %(frequency)s"]
    params: dict = {"frequency": frequency}

    if instrument_ids:
        clauses.append("instrument_id IN %(ids)s")
        params["ids"] = tuple(int(i) for i in instrument_ids)
    if (lower := _ts_bound(start)) is not None:
        clauses.append("ts >= %(start)s")
        params["start"] = lower
    if (upper := _ts_bound(end)) is not None:
        # Inclusive of the whole end day when a bare date is given.
        if not isinstance(end, dt.datetime) and pd.Timestamp(end).normalize() == pd.Timestamp(end):
            upper = upper + dt.timedelta(days=1) - dt.timedelta(milliseconds=1)
        clauses.append("ts <= %(end)s")
        params["end"] = upper

    query = f"""
        SELECT instrument_id, ts, open, high, low, close, volume, adj_close,
               currency, source
          FROM {VIEW}
         WHERE {' AND '.join(clauses)}
         ORDER BY ts, instrument_id
    """
    return client.query_df(query, parameters=params)


def coverage(client, frequency: str = "1d") -> pd.DataFrame:
    """Per-instrument coverage: bar count, range, sources, freshness."""
    query = """
        SELECT instrument_id,
               count()                AS bars,
               min(ts)                AS first_ts,
               max(ts)                AS last_ts,
               groupUniqArray(source) AS sources
          FROM {view:Identifier}
         WHERE frequency = %(frequency)s
         GROUP BY instrument_id
         ORDER BY instrument_id
    """.replace("{view:Identifier}", VIEW)
    return client.query_df(query, parameters={"frequency": frequency})


def bar_count(client, frequency: str = "1d") -> int:
    """Total deduplicated bars held for a frequency."""
    rows = client.query(
        f"SELECT count() FROM {VIEW} WHERE frequency = %(frequency)s",
        parameters={"frequency": frequency},
    ).result_rows
    return int(rows[0][0]) if rows else 0


def storage_stats(client) -> pd.DataFrame:
    """Compressed vs uncompressed size -- the reason bars live here."""
    query = """
        SELECT partition,
               sum(rows)                        AS rows,
               formatReadableSize(sum(data_compressed_bytes))   AS compressed,
               formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed,
               round(sum(data_uncompressed_bytes)
                     / greatest(sum(data_compressed_bytes), 1), 1) AS ratio
          FROM system.parts
         WHERE table = %(table)s AND active
         GROUP BY partition
         ORDER BY partition
    """
    return client.query_df(query, parameters={"table": TABLE})


def optimize(client) -> None:
    """Force the ReplacingMergeTree merge.

    Only worth calling after a large backfill, when you would rather pay the
    merge cost now than have FINAL pay it on every read.
    """
    client.command(f"OPTIMIZE TABLE {TABLE} FINAL")
