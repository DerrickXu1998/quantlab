-- 011_user_universes.sql -- universes a user publishes are theirs alone.
--
-- POST /universes used to write into universe_snapshots, the shared table the
-- data pipeline fills, with no caller attached: anybody could publish a
-- snapshot under a name everyone screens (a dated, append-only one, so it
-- could never be taken back), and every reader of that name would get it.
--
-- A user's universes live here instead. universe_snapshots stays the shared,
-- pipeline-owned list -- its writers look snapshots up by name alone, so a
-- private row there could shadow or block a shared one -- and a reader sees
-- the shared universes plus their own. Same shape and the same append-only
-- rule as the shared tables: a snapshot that can be edited is not a snapshot.

CREATE TABLE IF NOT EXISTS user_universe_snapshots (
    snapshot_id   BIGSERIAL   PRIMARY KEY,
    -- Text, like strategies.owner_id, so single-user mode needs no users row.
    owner_id      TEXT        NOT NULL,
    universe      TEXT        NOT NULL,
    snapshot_date DATE        NOT NULL,
    captured_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    member_count  INTEGER     NOT NULL DEFAULT 0,
    UNIQUE (owner_id, universe, snapshot_date)
);

CREATE TABLE IF NOT EXISTS user_universe_members (
    snapshot_id   BIGINT NOT NULL REFERENCES user_universe_snapshots ON DELETE CASCADE,
    instrument_id BIGINT NOT NULL REFERENCES instruments,
    PRIMARY KEY (snapshot_id, instrument_id)
);

-- The function is 001's; only the table differs.
CREATE TRIGGER user_universe_members_no_mutate
    BEFORE UPDATE OR DELETE ON user_universe_members
    FOR EACH ROW EXECUTE FUNCTION universe_members_append_only();

COMMENT ON TABLE user_universe_snapshots IS
    'Universes published through POST /universes; visible only to owner_id.';
