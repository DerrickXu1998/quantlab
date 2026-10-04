-- 101_minute_type.sql -- where each minute bar came from.
--
-- Owned by quantlab-data-pipeline (100+, like 100_pipeline_frequency_views).
-- quantlab's 001_bars.sql is left untouched: it creates price_bars without
-- this column, and this file adds it afterwards, on any warehouse.
--
--   reported  the vendor printed this bar (every row loaded by `crawl`/`load`)
--   inferred  `pipeline enrich` filled a missing session minute (zero volume)
--
-- The DEFAULT makes every existing row `reported` without rewriting a part,
-- and keeps quantlab's own inserts (which do not know the column) valid.
-- price_bars_current (quantlab's view) does not expose the column; read it
-- through price_bars_1m, which is redefined here to include it.

ALTER TABLE price_bars
    ADD COLUMN IF NOT EXISTS minute_type LowCardinality(String) DEFAULT 'reported';

CREATE OR REPLACE VIEW price_bars_1m AS
SELECT instrument_id,
       frequency,
       ts,
       toDate(ts) AS date,
       open,
       high,
       low,
       close,
       volume,
       adj_close,
       currency,
       source,
       run_id,
       minute_type
FROM price_bars FINAL
WHERE frequency = '1m';
