-- 001_catalog.sql -- the catalog: identity, provenance, universe history.
--
-- Storage is split by shape (see docs/STORAGE.md):
--
--   Postgres (this file)  small, mutable, relational, constraint-hungry.
--                         Instruments, vendor symbol mappings, universe
--                         snapshots, ingest runs, corporate actions.
--   ClickHouse            large, append-only, scan-heavy. Price bars only.
--
-- The rule of thumb: anything with bar-level cardinality goes to ClickHouse;
-- anything that needs a foreign key, a unique constraint or a transaction
-- stays here. ClickHouse has none of those, which is exactly why the catalog
-- does not live there.

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ---------------------------------------------------------------------------
-- Identity
-- ---------------------------------------------------------------------------

CREATE TABLE instruments (
    instrument_id   BIGSERIAL PRIMARY KEY,
    symbol          TEXT        NOT NULL UNIQUE,   -- canonical quantlab id: AAPL.US, HSBA.LON
    name            TEXT        NOT NULL DEFAULT '',
    exchange        TEXT        NOT NULL DEFAULT '',  -- MIC: XNYS, XLON, XNAS
    country         TEXT        NOT NULL DEFAULT '',  -- ISO-2
    -- currency of the numbers actually stored in ClickHouse price_bars, after
    -- the GBX->GBP normalisation that happens at the adapter boundary.
    currency        TEXT        NOT NULL,
    -- what the vendor quoted in, before normalisation. Keeping both is what
    -- makes the 100x pence/pound bug detectable after the fact instead of
    -- silently corrupting every cross-sectional number.
    quote_currency  TEXT        NOT NULL,
    sector          TEXT        NOT NULL DEFAULT '',
    industry        TEXT        NOT NULL DEFAULT '',
    isin            TEXT        NOT NULL DEFAULT '',
    sedol           TEXT        NOT NULL DEFAULT '',
    cik             TEXT        NOT NULL DEFAULT '',  -- SEC (US)
    company_number  TEXT        NOT NULL DEFAULT '',  -- Companies House (UK)
    figi            TEXT        NOT NULL DEFAULT '',
    active          BOOLEAN     NOT NULL DEFAULT TRUE,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    meta            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT instruments_currency_len CHECK (char_length(currency) = 3),
    CONSTRAINT instruments_quote_currency_len CHECK (char_length(quote_currency) = 3)
);

CREATE INDEX instruments_exchange_idx ON instruments (exchange);
CREATE INDEX instruments_isin_idx ON instruments (isin) WHERE isin <> '';
CREATE INDEX instruments_cik_idx  ON instruments (cik)  WHERE cik  <> '';

COMMENT ON TABLE instruments IS
    'Authoritative instrument identity. instrument_id is the join key used by '
    'the ClickHouse price_bars table, which has no foreign keys of its own.';
COMMENT ON COLUMN instruments.currency IS
    'Currency of the values stored in price_bars (post GBX->GBP normalisation).';
COMMENT ON COLUMN instruments.quote_currency IS
    'Currency the vendor quoted in. GBX for London lines quoted in pence.';

-- A vendor ticker maps to one instrument over a date range. The exclusion
-- constraint makes it impossible for one vendor symbol to point at two
-- instruments on the same day -- the ticker-reuse trap, enforced by the DB.
CREATE TABLE symbol_map (
    symbol_map_id BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES instruments ON DELETE CASCADE,
    source        TEXT   NOT NULL,        -- 'stooq', 'yahoo', 'sec_edgar', ...
    vendor_symbol TEXT   NOT NULL,        -- as the vendor spells it: 'aapl.us'
    valid         DATERANGE NOT NULL DEFAULT daterange('1900-01-01', NULL),
    EXCLUDE USING gist (
        source        WITH =,
        vendor_symbol WITH =,
        valid         WITH &&
    )
);

CREATE INDEX symbol_map_instrument_idx ON symbol_map (instrument_id);

-- ---------------------------------------------------------------------------
-- Universe snapshots (survivorship bias)
-- ---------------------------------------------------------------------------

CREATE TABLE universe_snapshots (
    snapshot_id   BIGSERIAL PRIMARY KEY,
    universe      TEXT        NOT NULL,   -- 'nasdaqtrader', 'lse', 'static'
    snapshot_date DATE        NOT NULL,
    source        TEXT        NOT NULL DEFAULT '',
    captured_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    member_count  INTEGER     NOT NULL DEFAULT 0,
    UNIQUE (universe, snapshot_date)
);

CREATE TABLE universe_members (
    snapshot_id   BIGINT NOT NULL REFERENCES universe_snapshots ON DELETE CASCADE,
    instrument_id BIGINT NOT NULL REFERENCES instruments,
    PRIMARY KEY (snapshot_id, instrument_id)
);

CREATE INDEX universe_members_instrument_idx ON universe_members (instrument_id);

-- Append-only, enforced. A snapshot that can be edited after the fact is not
-- a snapshot, and reconstructing a historical universe is the whole point.
CREATE OR REPLACE FUNCTION universe_members_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'universe_members is append-only: % is not permitted (drop the snapshot instead)',
        TG_OP;
END;
$$;

CREATE TRIGGER universe_members_no_mutate
    BEFORE UPDATE OR DELETE ON universe_members
    FOR EACH ROW EXECUTE FUNCTION universe_members_append_only();

-- ---------------------------------------------------------------------------
-- Provenance
-- ---------------------------------------------------------------------------

CREATE TABLE ingest_runs (
    run_id            BIGSERIAL PRIMARY KEY,
    source            TEXT        NOT NULL,  -- provider actually used, or 'multi'
    kind              TEXT        NOT NULL
                      CHECK (kind IN ('prices', 'corporate_actions', 'universe', 'fundamentals')),
    status            TEXT        NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'ok', 'partial', 'failed')),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    requested_start   DATE,
    requested_end     DATE,
    frequency         TEXT        NOT NULL DEFAULT '1d',
    symbols_requested INTEGER     NOT NULL DEFAULT 0,
    symbols_ok        INTEGER     NOT NULL DEFAULT 0,
    rows_written      BIGINT      NOT NULL DEFAULT 0,
    rows_rejected     BIGINT      NOT NULL DEFAULT 0,
    snapshot_id       BIGINT      REFERENCES universe_snapshots,
    quantlab_version  TEXT        NOT NULL DEFAULT '',
    error             TEXT,
    params            JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX ingest_runs_started_idx ON ingest_runs (started_at DESC);

-- run_id doubles as the ClickHouse ReplacingMergeTree version column: bars
-- written by a later run supersede the same key from an earlier one. The
-- sequence is therefore load-bearing and must stay monotonic.
COMMENT ON COLUMN ingest_runs.run_id IS
    'Also the ReplacingMergeTree version for ClickHouse price_bars. Monotonic by construction.';

-- Rows a provider returned that failed validation. Free sources ship bad
-- ticks; one of them must not abort a 5,000-symbol refresh, and dropping it
-- silently would violate "no silent data mutations". Validation happens in
-- the ingest library because ClickHouse will not do it for us.
CREATE TABLE ingest_rejects (
    reject_id     BIGSERIAL PRIMARY KEY,
    run_id        BIGINT NOT NULL REFERENCES ingest_runs ON DELETE CASCADE,
    instrument_id BIGINT REFERENCES instruments,
    symbol        TEXT   NOT NULL,
    ts            TIMESTAMPTZ,
    reason        TEXT   NOT NULL,
    payload       JSONB  NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX ingest_rejects_run_idx ON ingest_rejects (run_id);

-- ---------------------------------------------------------------------------
-- Corporate actions
-- ---------------------------------------------------------------------------
-- Low volume, mutable (restatements happen), and worth a foreign key, so it
-- stays in Postgres rather than joining the bars in ClickHouse.

CREATE TABLE corporate_actions (
    instrument_id BIGINT NOT NULL REFERENCES instruments,
    ex_date       DATE   NOT NULL,
    action_type   TEXT   NOT NULL CHECK (action_type IN ('dividend', 'split')),
    dividend      DOUBLE PRECISION,
    split_ratio   DOUBLE PRECISION,
    currency      TEXT,
    source        TEXT   NOT NULL,
    run_id        BIGINT NOT NULL REFERENCES ingest_runs,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, ex_date, action_type),
    CONSTRAINT corporate_actions_payload CHECK (
        (action_type = 'dividend' AND dividend IS NOT NULL AND dividend > 0)
        OR
        (action_type = 'split' AND split_ratio IS NOT NULL AND split_ratio > 0)
    )
);

CREATE INDEX corporate_actions_ex_date_idx ON corporate_actions (ex_date);

COMMENT ON TABLE corporate_actions IS
    'Splits and dividends, kept so point-in-time adjustment factors can be '
    'rebuilt for any as-of date. Vendor adj_close cannot be rewound.';
