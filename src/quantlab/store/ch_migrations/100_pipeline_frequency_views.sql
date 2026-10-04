-- 100_pipeline_frequency_views.sql -- one named view per bar frequency.
--
-- Owned by quantlab-data-pipeline, not quantlab: numbered 100+ so it can never
-- collide with quantlab's own ch_migrations (001, 002, ...), which quantlab's
-- migrator applies by name and ignores versions it does not ship.
--
-- price_bars stays one physical table (quantlab's schema; the backend filters
-- by `frequency`). These views give each frequency its own name so a query
-- cannot mix daily and minute rows by forgetting the filter. Both read
-- through price_bars_current, so they inherit its FINAL dedup.

CREATE VIEW IF NOT EXISTS price_bars_1m AS
SELECT * FROM price_bars_current WHERE frequency = '1m';

CREATE VIEW IF NOT EXISTS price_bars_1d AS
SELECT * FROM price_bars_current WHERE frequency = '1d';
