-- 005_execution.sql -- user-settable execution criteria recorded on each run.
--
-- Execution criteria (capital, sizing, costs, stops, fill timing) change how a
-- run's stored signals are turned into fills, so they are provenance: two runs
-- with identical model parameters but different criteria are not comparable,
-- and the run's record must say which produced it.

ALTER TABLE experiment_runs ADD COLUMN IF NOT EXISTS execution JSONB;

COMMENT ON COLUMN experiment_runs.execution IS
    'Effective execution criteria (capital, sizing, costs, stops, fill timing) '
    'the run was created with. NULL for runs recorded before they existed: '
    'those use the historical zero-cost equal-weight measuring instrument.';
