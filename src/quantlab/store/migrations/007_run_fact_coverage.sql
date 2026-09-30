-- 007_run_fact_coverage.sql -- which names had the filings a run's rules read.
--
-- A fundamental gate with no facts holds shut and says nothing, so a run over
-- a universe where a third of the names never filed revenue looks exactly like
-- a run where their revenue never grew. The runner now records, per run, the
-- concepts its rules read, how many requested names lacked each, and which
-- names lacked at least one; the API returns it as `coverage.facts`.
--
-- JSONB, nullable: null on runs whose rules read no fundamentals, and on every
-- run recorded before this column existed. The SQLite demo store carries the
-- same column via its idempotent bootstrap.

ALTER TABLE experiment_runs
    ADD COLUMN fact_coverage JSONB;
