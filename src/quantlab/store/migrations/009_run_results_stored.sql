-- 009_run_results_stored.sql -- a run's results are read, never recomputed.
--
-- Since 008 the worker stores performance (and its headline) when a run
-- completes. Runs recorded before that had neither, and opening one re-ran its
-- simulation inside the API request from the stored strategy -- slow, and for
-- a long intraday run longer than the 60 s a request survives. The worker now
-- computes those once in the background and stores them like any other run.
--
-- A run whose results cannot be computed (a symbol since removed from the
-- catalog, a rule no longer registered) records why here, so it is not
-- retried forever and the UI can say so instead of waiting.

ALTER TABLE experiment_runs
    ADD COLUMN IF NOT EXISTS performance_error TEXT;

-- The worker's backfill query: completed runs still without results.
CREATE INDEX IF NOT EXISTS experiment_runs_unscored_idx
    ON experiment_runs (created_at DESC)
    WHERE status = 'completed' AND performance IS NULL AND performance_error IS NULL;
