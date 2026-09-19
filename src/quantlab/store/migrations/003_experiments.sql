-- 003_experiments.sql -- workbench experiment runs and their output.
--
-- Why here and not in ClickHouse: runs are small, mutable, and want foreign
-- keys and cascade deletes -- none of which ClickHouse has. Bars go to the
-- columnar store; anything needing a constraint stays in the catalog.
--
-- Why a separate table from `signals`: that table is a rebuildable cache of
-- registry output, and the API serves it. Experiment output would insert into
-- it cleanly -- parameters are part of its key -- and would then surface in
-- the Signal Viewer, mixing exploratory runs into curated output with nothing
-- to indicate it. The same trap exists on the SQLite demo store.

CREATE TABLE experiment_runs (
    run_id                  TEXT PRIMARY KEY,
    name                    TEXT,
    model_name              TEXT        NOT NULL,
    model_version           TEXT        NOT NULL,
    -- Effective parameters: declared defaults merged with the researcher's
    -- overrides. Recording the bare defaults while having executed overrides
    -- would make the run unreproducible from its own record.
    parameters              JSONB       NOT NULL,
    symbols                 JSONB       NOT NULL,
    -- Surrogate identities actually run against. The canonical symbol is
    -- unique but editable; instrument_id is the stable key the bar store
    -- joins on.
    instrument_ids          JSONB,
    -- The ingest runs behind the bars this run read. price_bars.run_id doubles
    -- as the ReplacingMergeTree version, so a re-ingest supersedes earlier
    -- rows -- which is what makes a re-ingest distinguishable from the
    -- original run when every input the researcher chose is identical.
    ingest_run_ids          JSONB,
    -- Splits/dividends inside the window. Persisted rather than only
    -- reported, so reopening a saved run still warns that its price series
    -- contains unadjusted discontinuities.
    corporate_actions       JSONB NOT NULL DEFAULT '[]'::jsonb,
    dataset                 TEXT        NOT NULL CHECK (dataset IN ('sqlite', 'warehouse')),
    start_date              DATE        NOT NULL,
    end_date                DATE        NOT NULL,
    status                  TEXT        NOT NULL CHECK (status IN ('completed', 'failed')),
    error                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    signal_count            INTEGER     NOT NULL CHECK (signal_count >= 0),
    instruments_requested   INTEGER     NOT NULL CHECK (instruments_requested >= 1),
    instruments_with_data   INTEGER     NOT NULL CHECK (instruments_with_data >= 0),
    instruments_full_warmup INTEGER     NOT NULL CHECK (instruments_full_warmup >= 0),
    CONSTRAINT experiment_runs_window CHECK (start_date <= end_date),
    CONSTRAINT experiment_runs_error_iff_failed
        CHECK ((status = 'failed') = (error IS NOT NULL))
);

CREATE TABLE experiment_signals (
    run_id          TEXT   NOT NULL REFERENCES experiment_runs ON DELETE CASCADE,
    instrument_id   BIGINT REFERENCES instruments,
    -- Kept alongside instrument_id so a run stays readable for display even if
    -- an instrument is later removed from the catalog.
    symbol          TEXT   NOT NULL,
    date            DATE   NOT NULL,
    direction       TEXT   NOT NULL CHECK (direction IN ('bullish', 'bearish')),
    trigger_values  JSONB  NOT NULL DEFAULT '{}'::jsonb,
    data_window_end DATE   NOT NULL,
    -- The same point-in-time guard the catalog's own signals table carries: a
    -- signal stamped for date D must not have been built from a later bar.
    CONSTRAINT experiment_signals_point_in_time CHECK (data_window_end <= date)
);

CREATE INDEX experiment_runs_created_idx ON experiment_runs (created_at DESC);
CREATE INDEX experiment_runs_saved_idx   ON experiment_runs (created_at DESC) WHERE name IS NOT NULL;
CREATE INDEX experiment_signals_run_idx  ON experiment_signals (run_id, symbol, date);

COMMENT ON TABLE experiment_runs IS
    'Workbench experiment runs with full provenance: model, effective '
    'parameters, selection, window, dataset and ingest lineage.';
COMMENT ON TABLE experiment_signals IS
    'Signals produced by an experiment run. Deliberately separate from the '
    'materialised signals table, which the Signal Viewer serves.';
