-- 004_fundamentals.sql -- point-in-time fundamentals (SEC EDGAR, Companies House).
--
-- Shaped by what the providers actually return:
--
--   sec_edgar (XBRL companyfacts): facts.<taxonomy>.<tag>.units.<unit>[] with
--   {start, end, val, accn, fy, fp, form, filed}, keyed by CIK. One tag can
--   appear under several units, and the same fact is re-published (and
--   occasionally restated) by later filings.
--
--   companies_house (iXBRL accounts): numeric tags parsed per filed document,
--   keyed by company number, dated by the filing-history date. No ticker
--   anywhere in the payload.
--
-- Both therefore reduce to the same long row: who, which tag, which unit,
-- which period, what value, and -- the point of the table -- when the market
-- could first know it (filed_at, Constitution VII).

-- Identifier bridge: none needed. CIK and company_number already live on
-- instruments (001), and symbol_map can carry 'sec_edgar' / 'companies_house'
-- rows for them if a vendor-style binding is ever wanted -- these are stable
-- company-level identifiers, so the GiST "one binding at a time" exclusion is
-- the correct semantics and no separate bridge table is warranted.

CREATE TABLE fundamentals (
    fundamental_id BIGSERIAL PRIMARY KEY,
    instrument_id  BIGINT NOT NULL REFERENCES instruments ON DELETE CASCADE,
    provider       TEXT   NOT NULL,            -- 'sec_edgar', 'companies_house'
    taxonomy       TEXT   NOT NULL DEFAULT '', -- 'us-gaap', 'dei', 'ifrs-full', 'uk-gaap', ...
    tag            TEXT   NOT NULL,            -- raw XBRL tag as filed
    concept        TEXT   NOT NULL DEFAULT '', -- canonical: 'revenue', 'equity', ... (CONCEPT_TAGS/UK_TAGS)
    unit           TEXT   NOT NULL DEFAULT '', -- 'USD', 'GBP', 'shares', 'USD/shares', ...
    period_start   DATE,                       -- NULL for instantaneous facts (balance sheet)
    period_end     DATE   NOT NULL,            -- fiscal period the fact describes
    filed_at       DATE   NOT NULL,            -- when the market could first know it
    value          DOUBLE PRECISION NOT NULL,
    -- SEC accession number / Companies House document id: the filing this fact
    -- came from. In the identity so two filings on the same day cannot collide
    -- and a re-pull of the same filing is idempotent.
    accession      TEXT   NOT NULL DEFAULT '',
    run_id         BIGINT NOT NULL REFERENCES ingest_runs,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    meta           JSONB  NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (instrument_id, provider, taxonomy, tag, unit, period_end, filed_at, accession)
);

-- The as-of read: everything the market knew about an instrument by date D is
-- `WHERE instrument_id = ... AND filed_at <= D`, latest filed_at per concept
-- wins. Restatements are new rows with a later filed_at, never edits -- a
-- backtest must only see facts filed before its as-of date.
CREATE INDEX fundamentals_pit_idx ON fundamentals (instrument_id, concept, filed_at);
CREATE INDEX fundamentals_filed_idx ON fundamentals (filed_at);

COMMENT ON TABLE fundamentals IS
    'Raw XBRL facts, point-in-time by filed_at. Identity includes the filing '
    '(accession), so restatements land as new rows and re-ingest of one filing '
    'is a no-op via ON CONFLICT DO NOTHING. Canonical-concept resolution '
    '(CONCEPT_TAGS / UK_TAGS fallback chains) is a read-time concern.';
COMMENT ON COLUMN fundamentals.filed_at IS
    'Filing date, not fiscal period end. The point-in-time anchor: a fact is '
    'visible to a backtest only from filed_at onwards.';
