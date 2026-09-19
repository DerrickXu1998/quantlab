-- 001_bars.sql -- ClickHouse: the price bar fact table.
--
-- Why ClickHouse holds this and Postgres does not: bars are append-only,
-- enormous, and read by wide scans ("20 years x 5,000 symbols of close").
-- That is the workload ClickHouse is built for. Everything requiring a
-- foreign key, a unique constraint or a transaction stays in the Postgres
-- catalog -- ClickHouse has none of those.
--
-- Intraday readiness: `ts` is a DateTime64 from day one, not a Date. Daily
-- bars are stored at 00:00:00 UTC of the session date. Moving to minute or
-- tick data later is then a change of what goes in the column, not a
-- migration of 10^9 rows.
--
-- Idempotency: ReplacingMergeTree(run_id) collapses rows sharing the sort
-- key, keeping the highest run_id -- so a re-ingest supersedes an earlier
-- one. Collapsing happens at merge time, NOT at insert, so every read must
-- deduplicate explicitly. Read through the price_bars_current view, never
-- the raw table.

CREATE TABLE IF NOT EXISTS price_bars
(
    instrument_id UInt64   CODEC(DoubleDelta, ZSTD(1)),
    frequency     LowCardinality(String),
    ts            DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD(1)),

    -- Gorilla is designed for slowly-varying float series and is the reason
    -- OHLCV compresses ~10-30x here versus row storage.
    open          Float64  CODEC(Gorilla, ZSTD(1)),
    high          Float64  CODEC(Gorilla, ZSTD(1)),
    low           Float64  CODEC(Gorilla, ZSTD(1)),
    close         Float64  CODEC(Gorilla, ZSTD(1)),
    volume        Int64    CODEC(T64, ZSTD(1)),

    -- The vendor's adjusted close on the day it was fetched. Deliberately
    -- Nullable and deliberately not authoritative: adj_close today differs
    -- from adj_close as of 2019. Rebuild from catalog.corporate_actions.
    adj_close     Nullable(Float64) CODEC(Gorilla, ZSTD(1)),

    currency      LowCardinality(String),
    source        LowCardinality(String),

    -- Foreign key to Postgres ingest_runs in spirit only; ClickHouse cannot
    -- enforce it. It doubles as the ReplacingMergeTree version.
    run_id        UInt64   CODEC(DoubleDelta, ZSTD(1)),
    ingested_at   DateTime DEFAULT now() CODEC(DoubleDelta, ZSTD(1))
)
ENGINE = ReplacingMergeTree(run_id)
PARTITION BY toYYYYMM(ts)
ORDER BY (instrument_id, frequency, ts)
SETTINGS index_granularity = 8192;

-- Cross-sectional access ("every symbol on date D") scans partitions that the
-- ORDER BY does not help with, so give the date its own skip index.
ALTER TABLE price_bars
    ADD INDEX IF NOT EXISTS price_bars_ts_idx ts TYPE minmax GRANULARITY 4;

-- Always read through this. FINAL forces the dedup that the merge process
-- would otherwise apply on its own schedule, so a re-ingested range never
-- reads back doubled.
CREATE VIEW IF NOT EXISTS price_bars_current AS
SELECT instrument_id,
       frequency,
       ts,
       toDate(ts) AS date,
       open,
       high,
       low,
       close,
       volume,
       adj_close,
       currency,
       source,
       run_id
FROM price_bars FINAL;
