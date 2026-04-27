-- 073_autovacuum_tuning.sql
-- Autovacuum tuning for high-churn write-heavy tables.
--
-- Problem: default autovacuum fires at 20% dead tuples. Small tables that
-- receive frequent UPDATEs accumulate bloat well below that threshold.
-- As of 2026-04-26:
--   setup_performance:  87.5% dead (7 live / 49 dead) — last vacuum 2026-04-06
--   signal_metrics:     19.5% dead — last vacuum 2026-04-12
--   signal_metrics_ic:  18.5% dead — last vacuum 2026-04-12
--   instruments:        44.8% dead — last vacuum 2026-04-22
--
-- Fix: lower scale factors so autovacuum fires much earlier on these tables.
-- Also VACUUM ANALYZE immediately to clean up existing bloat and refresh stats.

BEGIN;

ALTER TABLE setup_performance SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_analyze_scale_factor = 0.02
);

ALTER TABLE signal_metrics SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_analyze_scale_factor = 0.02
);

ALTER TABLE signal_metrics_ic SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_analyze_scale_factor = 0.02
);

ALTER TABLE instruments SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_analyze_scale_factor = 0.02
);

COMMIT;

-- Run outside transaction — VACUUM cannot run inside a transaction block.
VACUUM ANALYZE setup_performance;
VACUUM ANALYZE signal_metrics;
VACUUM ANALYZE signal_metrics_ic;
VACUUM ANALYZE instruments;
