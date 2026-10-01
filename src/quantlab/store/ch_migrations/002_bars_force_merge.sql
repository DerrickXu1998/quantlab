-- 002_bars_force_merge.sql -- keep price_bars at about one part per month.
--
-- price_bars_current reads through FINAL, and FINAL's memory grows with the
-- number of parts it must read side by side, not with the rows. An ingest
-- writes one new part into every month it touches, and ClickHouse's own merge
-- schedule leaves them apart for as long as it likes. Measured on 24.8 under
-- the self-hosted VM's 2 GiB ceiling, the /instruments count over 43.8M rows:
--   759 parts: the server total peaked at 2.0 GiB and the query was cancelled,
--              whatever the read settings;
--   240 parts (one per month): 557 MiB, and well under a second.
--
-- These settings have the server merge every part of a month into one once all
-- of them are ten minutes old, with no OPTIMIZE to remember after an ingest.
-- Each such merge peaked under 50 MiB, so it does not compete with reads.
-- The ten minutes leave the merge clear of an ingest still writing a month.

ALTER TABLE price_bars
    MODIFY SETTING min_age_to_force_merge_seconds = 600,
                   min_age_to_force_merge_on_partition_only = 1;
