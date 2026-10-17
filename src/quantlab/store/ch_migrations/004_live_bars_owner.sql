-- 004_live_bars_owner.sql -- live bars belong to the user whose IBKR login
-- fetched them.
--
-- Live prices now come from each user's own IBKR account, never one shared
-- login: an account's market data is licensed to that account's holder, so
-- one user's bars must never be served to another. The owner therefore joins
-- the sort key -- ReplacingMergeTree deduplicates on the key, so with the
-- owner outside it two users' bars for the same minute would collapse into
-- one. A sort key cannot be altered in place, and this table is a 7-day cache
-- of provisional prices that Tiingo supersedes nightly, so it is rebuilt.

DROP TABLE IF EXISTS live.bars_1m;

CREATE TABLE IF NOT EXISTS live.bars_1m
(
    -- quantlab user id (the owner of the IBKR login that fetched the bar).
    owner_id      LowCardinality(String),
    instrument_id UInt64   CODEC(DoubleDelta, ZSTD(1)),
    ts            DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD(1)),
    session_date  Date,
    open          Float64  CODEC(Gorilla, ZSTD(1)),
    high          Float64  CODEC(Gorilla, ZSTD(1)),
    low           Float64  CODEC(Gorilla, ZSTD(1)),
    close         Float64  CODEC(Gorilla, ZSTD(1)),
    volume        Int64    CODEC(T64, ZSTD(1)),
    kind          LowCardinality(String),
    ts_ingest     DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(ts_ingest)
PARTITION BY session_date
ORDER BY (owner_id, instrument_id, ts)
TTL session_date + INTERVAL 7 DAY;
