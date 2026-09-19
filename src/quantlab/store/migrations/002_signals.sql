-- 002_signals.sql -- materialised signal output.
--
-- Signals are derived data: reproducible from price_bars plus deterministic
-- plugin logic (Constitution II/III). They are stored only because the API
-- serves them; the registry remains authoritative and this table is a cache
-- that can be dropped and rebuilt at any time.
--
-- data_window_end <= date is the point-in-time guard: a signal stamped for
-- date D must not have been computed from a bar after D.

CREATE TABLE signal_rules (
    rule_id             BIGSERIAL PRIMARY KEY,
    rule_name           TEXT NOT NULL,
    rule_version        TEXT NOT NULL,
    parameters          JSONB NOT NULL,       -- canonical, sorted keys
    lookback_days       INTEGER NOT NULL CHECK (lookback_days > 0),
    scale_class         TEXT NOT NULL CHECK (scale_class IN ('scale_free', 'price_scaled')),
    direction_semantics TEXT NOT NULL DEFAULT '',
    UNIQUE (rule_name, rule_version, parameters)
);

CREATE TABLE signals (
    signal_id       BIGSERIAL PRIMARY KEY,
    instrument_id   BIGINT NOT NULL REFERENCES instruments,
    rule_id         BIGINT NOT NULL REFERENCES signal_rules ON DELETE CASCADE,
    date            DATE   NOT NULL,
    direction       TEXT   NOT NULL CHECK (direction IN ('bullish', 'bearish')),
    trigger_values  JSONB  NOT NULL DEFAULT '{}'::jsonb,
    data_window_end DATE   NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_id, rule_id, date),
    CONSTRAINT signals_point_in_time CHECK (data_window_end <= date)
);

-- The API's dominant query: filter by instrument and/or date, sort by date.
CREATE INDEX signals_date_idx ON signals (date DESC);
CREATE INDEX signals_instrument_date_idx ON signals (instrument_id, date DESC);
CREATE INDEX signals_rule_idx ON signals (rule_id);

CREATE VIEW signals_expanded AS
SELECT s.signal_id,
       i.symbol,
       i.name AS instrument_name,
       r.rule_name,
       r.rule_version,
       r.parameters,
       r.scale_class,
       s.date,
       s.direction,
       s.trigger_values,
       s.data_window_end
FROM signals s
JOIN instruments  i USING (instrument_id)
JOIN signal_rules r USING (rule_id);
