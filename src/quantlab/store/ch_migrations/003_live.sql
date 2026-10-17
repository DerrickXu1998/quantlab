-- 003_live.sql -- ClickHouse: today's live bars, kept apart from history.
--
-- Live prices come from IBKR while a session is trading. They are provisional:
-- Tiingo's end-of-day load is the source of truth, and nothing a backtest
-- reads may ever see a live row. So they get their own database rather than a
-- `source` value in price_bars -- price_bars dedups on (instrument_id,
-- frequency, ts) with no source in the key, so a live row there would
-- silently replace a vendor bar. Nothing under runs/ or replay/ names `live.`.
--
-- bars_1m holds one session per partition: the collector's backfill from the
-- open (kind = 'backfill', IBKR's own minute bars) and the minutes it rolled
-- from ticks after that (kind = 'rolled'). It is for display and is short-
-- lived: a session is dropped once Tiingo has loaded it, and the TTL is the
-- safety net for when that never happens.
--
-- ReplacingMergeTree(ts_ingest): the collector may write a minute twice (a
-- reconnect re-backfills the session); the later write wins. Read with FINAL.

CREATE DATABASE IF NOT EXISTS live;

CREATE TABLE IF NOT EXISTS live.bars_1m
(
    instrument_id UInt64   CODEC(DoubleDelta, ZSTD(1)),
    -- Bar start, UTC, like price_bars.
    ts            DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD(1)),
    -- The New York trading date the bar belongs to.
    session_date  Date,
    open          Float64  CODEC(Gorilla, ZSTD(1)),
    high          Float64  CODEC(Gorilla, ZSTD(1)),
    low           Float64  CODEC(Gorilla, ZSTD(1)),
    close         Float64  CODEC(Gorilla, ZSTD(1)),
    volume        Int64    CODEC(T64, ZSTD(1)),
    -- backfill | rolled
    kind          LowCardinality(String),
    ts_ingest     DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(ts_ingest)
PARTITION BY session_date
ORDER BY (instrument_id, ts)
TTL session_date + INTERVAL 7 DAY;
