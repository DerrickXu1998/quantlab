-- 010_live_subscriptions.sql -- which symbols the live collector streams.
--
-- IBKR gives an account ~100 concurrent market-data lines, and the S&P alone
-- is ~500 names, so a line is a scarce thing somebody has to ask for. This
-- table is the asking: the API writes a row while a Market tab watches a
-- symbol (and, later, a deployed strategy while it trades one), and the
-- live-ingest collector reads it, opens or closes lines to match, and writes
-- back what it managed.
--
-- A row is a lease, not a setting. The API renews expires_at while the stream
-- that asked is open; a closed tab stops renewing and its line is freed when
-- the lease lapses, so a crashed browser can never pin a line for good.
--
-- Deployment rows outrank market rows when the budget runs out: a strategy
-- trading a name must not lose its line to someone looking at a chart. A
-- symbol left over budget is marked so and shown as such -- never simulated.

CREATE TABLE IF NOT EXISTS live_subscriptions (
    subscription_id BIGSERIAL   PRIMARY KEY,
    instrument_id   BIGINT      NOT NULL REFERENCES instruments ON DELETE CASCADE,
    -- market: a Market tab watching; deployment: a strategy trading it.
    consumer        TEXT        NOT NULL CHECK (consumer IN ('market', 'deployment')),
    -- The user (market) or deployment that holds the lease. Text, like
    -- strategies.owner_id, so single-user mode needs no users row.
    owner_id        TEXT        NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    -- Written by the collector. pending until it has looked at the row.
    status          TEXT        NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'over_budget', 'unknown_symbol', 'error')),
    status_detail   TEXT        NOT NULL DEFAULT '',
    -- The contract the collector resolved, e.g. 'BRK B' for BRK.B.US, kept so
    -- a mapping surprise is visible in the table rather than only in a log.
    ib_symbol       TEXT,
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_id, consumer, owner_id)
);

-- The collector's poll: every unexpired lease, deployments first.
CREATE INDEX IF NOT EXISTS live_subscriptions_expiry_idx
    ON live_subscriptions (expires_at);

COMMENT ON TABLE live_subscriptions IS
    'Leases on IBKR market-data lines; the API renews them, live-ingest serves them.';
