-- 006_auth.sql -- user accounts, sessions, and per-user run ownership.
--
-- Why in the catalog: accounts are small, mutable, and want constraints and
-- cascade deletes -- the same reasoning that put experiment_runs here (003).
-- The SQLite demo store carries the same shape via its idempotent bootstrap.
--
-- Passwords are stored as self-describing PBKDF2-SHA256 records
-- (pbkdf2_sha256$<iterations>$<salt>$<digest>); sessions store only the
-- SHA-256 of the bearer token, so a leaked catalog hands out neither
-- passwords nor usable sessions.

CREATE TABLE users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Case-insensitive identity is enforced by users_username_ci below: the
    -- column keeps the registered casing, the index makes "Alice" and
    -- "alice" the same account.
    username      TEXT        NOT NULL,
    password_hash TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_admin      BOOLEAN     NOT NULL DEFAULT FALSE
);

CREATE UNIQUE INDEX users_username_ci ON users (lower(username));

CREATE TABLE sessions (
    token_hash TEXT        PRIMARY KEY,
    user_id    BIGINT      NOT NULL REFERENCES users ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Rolling: every authenticated request renews the session for another
    -- 14 days, so only 14 idle days log a user out.
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX sessions_user_idx ON sessions (user_id);

-- Run ownership. Pre-existing runs keep user_id NULL and stay visible to
-- every user: reassigning them to whoever happened to register first would
-- be a silent, wrong guess, and hiding them would strand existing work.
ALTER TABLE experiment_runs ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users;

CREATE INDEX IF NOT EXISTS experiment_runs_user_idx ON experiment_runs (user_id);

COMMENT ON TABLE users IS
    'Accounts. username identity is case-insensitive (users_username_ci); '
    'password_hash is a self-describing PBKDF2-SHA256 record.';
COMMENT ON TABLE sessions IS
    'Opaque session tokens, stored SHA-256-hashed, with 14-day rolling expiry.';
COMMENT ON COLUMN experiment_runs.user_id IS
    'Owning user. NULL for runs recorded before accounts existed: those stay '
    'visible to every user rather than being silently reassigned.';
