-- 005_strategies_and_identity.sql -- accounts, saved strategies, and the
-- columns a run needs now that a strategy is more than one rule.
--
-- Numbered 005, not 004: the fundamentals schema landed as 004 on a parallel
-- branch. Both applied fine (migrations run in filename order) but two files
-- sharing a number means the number no longer says which came first. A
-- database that already applied this under `004_strategies_and_identity`
-- needs its tracking row renamed rather than a re-run:
--     UPDATE schema_migrations SET version = '005_strategies_and_identity'
--      WHERE version = '004_strategies_and_identity';
--
-- Three things arrive together because they are one change: a run belongs to
-- somebody, that somebody can save the strategy that produced it, and the run
-- has to record the execution criteria it actually ran under. Splitting them
-- would leave a migration in between where a run has an owner but no way for
-- that owner to be authenticated.
--
-- Everything here is additive. An older build still reads a migrated catalog,
-- which matters because a rollback must not require a restore.

-- Identity ------------------------------------------------------------------
--
-- Why rows and not signed tokens: a JWT cannot be withdrawn before it expires,
-- so signing out would be a lie the client tells itself and a stolen token
-- would stay valid for its full lifetime. A row can be deleted.

CREATE TABLE users (
    id            TEXT        PRIMARY KEY,
    email         TEXT        NOT NULL UNIQUE,
    -- pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>. The cost travels with
    -- the hash, so raising it later does not invalidate existing passwords.
    password_hash TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled      BOOLEAN     NOT NULL DEFAULT false
);

-- Only the SHA-256 of a token is stored, so a backup, a query log or a
-- read-only replica leak hands nobody a usable session. SHA-256 and not a slow
-- KDF: the token is 32 bytes of CSPRNG output with no guessable structure, so
-- there is nothing for PBKDF2 to protect, and paying its cost on every
-- authenticated request would be absurd.
CREATE TABLE sessions (
    token_hash TEXT        PRIMARY KEY,
    user_id    TEXT        NOT NULL REFERENCES users ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT sessions_window CHECK (created_at <= expires_at)
);

CREATE INDEX sessions_user_idx   ON sessions (user_id);
CREATE INDEX sessions_expiry_idx ON sessions (expires_at);

-- Saved strategies -----------------------------------------------------------
--
-- The spec is JSONB rather than shredded into columns: it is validated by
-- quantlab.strategy on the way in and on the way out, that module owns its
-- shape, and a schema migration for every new execution setting would be a tax
-- on all of them.

CREATE TABLE strategies (
    id          TEXT        PRIMARY KEY,
    owner_id    TEXT        NOT NULL,
    name        TEXT        NOT NULL,
    description TEXT        NOT NULL DEFAULT '',
    spec        JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX strategies_owner_idx ON strategies (owner_id, updated_at DESC);

-- Runs ------------------------------------------------------------------------

ALTER TABLE experiment_runs
    -- Null on runs recorded before accounts existed. Those are visible only in
    -- single-user mode, which is the honest outcome: there is no way to know
    -- retroactively whose they were.
    ADD COLUMN owner_id          TEXT,
    -- The resolved strategy and execution criteria that actually ran, and what
    -- the engine did with them. Recorded so a result carries the assumptions
    -- that produced it instead of relying on the reader to remember them.
    ADD COLUMN strategy          JSONB,
    ADD COLUMN execution         JSONB,
    ADD COLUMN execution_summary JSONB;

CREATE INDEX experiment_runs_owner_idx ON experiment_runs (owner_id, created_at DESC);

-- Whether a stored signal opens a position, closes one, or does both. Defaulted
-- to 'both' so existing rows keep their meaning exactly: they came from
-- single-model runs, where one rule opened on bullish and closed on bearish.
ALTER TABLE experiment_signals
    ADD COLUMN kind TEXT NOT NULL DEFAULT 'both'
        CHECK (kind IN ('entry', 'exit', 'both'));

COMMENT ON TABLE users IS
    'Accounts. Passwords are PBKDF2-HMAC-SHA256 with the cost recorded in the '
    'hash; see docs/SECURITY.md for why not argon2.';
COMMENT ON TABLE sessions IS
    'Bearer sessions, stored as the SHA-256 of the token so the table holds no '
    'usable credential. Deletable, which is what makes logout mean something.';
COMMENT ON TABLE strategies IS
    'User-saved strategies: several signal components, their combination logic, '
    'and the execution criteria attached to them.';
