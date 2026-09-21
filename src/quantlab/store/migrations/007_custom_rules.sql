-- 007_custom_rules.sql -- user-defined signal rules from fixed templates (feature 008, M2).
--
-- Why in the catalog: rules are small, mutable, and user-owned -- the same
-- reasoning that put users and experiment_runs here (003, 006). The SQLite
-- demo store carries the same shape via its idempotent bootstrap.
--
-- user_id NULL means unscoped: rules created with QUANTLAB_AUTH=off. Slug
-- uniqueness is per owner and enforced in the store, because Postgres treats
-- NULLs as distinct in unique constraints.
--
-- experiment_runs.custom_rule is a SNAPSHOT of the resolved definition
-- (template + config + derived lookback) taken at run creation: editing or
-- deleting a rule must never rewrite what a recorded run actually computed.

CREATE TABLE custom_rules (
    rule_id    TEXT        PRIMARY KEY,
    user_id    BIGINT      REFERENCES users ON DELETE CASCADE,
    name       TEXT        NOT NULL,
    slug       TEXT        NOT NULL,
    template   TEXT        NOT NULL,
    config     JSONB       NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX custom_rules_owner_slug_idx
    ON custom_rules (COALESCE(user_id, 0), slug);

CREATE INDEX custom_rules_owner_idx ON custom_rules (user_id);

ALTER TABLE experiment_runs ADD COLUMN IF NOT EXISTS custom_rule JSONB;

COMMENT ON TABLE custom_rules IS
    'User-defined signal rules: a fixed template id plus a validated config. '
    'Never expressions -- templates only.';
COMMENT ON COLUMN experiment_runs.custom_rule IS
    'Snapshot of the custom rule definition this run executed (template, '
    'config, derived lookback). NULL for builtin-model runs.';
