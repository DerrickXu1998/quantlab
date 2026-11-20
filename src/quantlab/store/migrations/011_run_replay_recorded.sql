-- 011_run_replay_recorded.sql -- a run's replay is a record, not a re-run.
--
-- Replaying a run re-simulated it from its stored signals against the bars,
-- corporate actions and minutes as they are *now*. Those are revised -- a
-- corrected print, a restated split, a re-ingest -- and a replay of an old run
-- then showed fills and a result the run never had. The worker now records the
-- replay stream when a run completes, from the inputs it executed on, and the
-- replay endpoints only read it.
--
-- `events` is gzip, one `kind<TAB>json` frame per line (the JSON is the SSE payload). A run completed
-- before this migration has no row; the worker rebuilds it once by
-- re-execution and stores it with `reconstructed = true`, or records why it
-- could not in `error` so it is not retried forever.

CREATE TABLE IF NOT EXISTS experiment_replays (
    run_id         TEXT PRIMARY KEY REFERENCES experiment_runs ON DELETE CASCADE,
    events         BYTEA,
    summary        JSONB,
    reconstructed  BOOLEAN NOT NULL DEFAULT false,
    error          TEXT,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((events IS NULL) = (error IS NOT NULL))
);
