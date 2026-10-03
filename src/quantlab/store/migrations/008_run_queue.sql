-- 008_run_queue.sql -- backtests run in the background.
--
-- A run used to exist only once it had finished: the API executed it inside
-- the request and inserted a completed (or failed) row. Long intraday runs
-- outlived the request -- something between browser and VM drops a request
-- that has sent nothing for 60 s -- so a run that finished on the server never
-- reached the person who asked for it.
--
-- Now the API checks the request, inserts a `queued` row and returns. A worker
-- claims queued rows (FOR UPDATE SKIP LOCKED), marks them `running`, and on
-- finishing writes the result -- including the performance figures, computed
-- once and stored, so opening a run never re-simulates it.

ALTER TABLE experiment_runs DROP CONSTRAINT IF EXISTS experiment_runs_status_check;
ALTER TABLE experiment_runs ADD CONSTRAINT experiment_runs_status_check
    CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled'));

ALTER TABLE experiment_runs
    -- What the worker runs: the resolved strategy, symbols and window, fixed at
    -- submission so a later edit to a saved strategy cannot change it.
    ADD COLUMN IF NOT EXISTS request          JSONB,
    ADD COLUMN IF NOT EXISTS estimated_bars   BIGINT,
    ADD COLUMN IF NOT EXISTS started_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS finished_at      TIMESTAMPTZ,
    -- data | validation | limit | worker: what kind of fix a failure needs.
    ADD COLUMN IF NOT EXISTS error_category   TEXT
        CHECK (error_category IN ('data', 'validation', 'limit', 'worker')),
    ADD COLUMN IF NOT EXISTS attempts         INTEGER NOT NULL DEFAULT 0,
    -- Which worker holds a running run, and until when. A worker renews its
    -- lease while it works; a run whose lease lapsed belongs to a worker that
    -- died (a deploy, an OOM kill) and is queued again or failed.
    ADD COLUMN IF NOT EXISTS worker           TEXT,
    ADD COLUMN IF NOT EXISTS lease_until      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN NOT NULL DEFAULT false,
    -- research.performance's result, stored at completion. Null on runs that
    -- predate the queue; those are computed on first read and stored then.
    ADD COLUMN IF NOT EXISTS performance      JSONB;

-- The worker's claim query: the oldest queued run. Partial, so it stays tiny
-- however many finished runs accumulate.
CREATE INDEX IF NOT EXISTS experiment_runs_queue_idx
    ON experiment_runs (created_at, run_id) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS experiment_runs_running_idx
    ON experiment_runs (lease_until) WHERE status = 'running';

COMMENT ON COLUMN experiment_runs.request IS
    'The resolved run request (strategy, symbols, window) the worker executes.';
COMMENT ON COLUMN experiment_runs.performance IS
    'research.performance output, stored when the run completes.';
