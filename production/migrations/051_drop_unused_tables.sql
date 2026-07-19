-- Migration: Drop unused tables
-- Date: 2026-03-23
-- Reason: Signal refactoring - these tables were created but never wired into the pipeline
--
-- signal_performance_segmented: Created Phase 39 for segmented performance stats,
--   but the aggregator uses setup_performance table instead.
-- signal_features: Intended for per-signal ML feature snapshots, but never implemented.
--
-- Renaissance principle: "Storage is the cheapest thing we own" — but unused
-- tables that create confusion and maintenance burden should be removed.

BEGIN;

-- Drop signal_performance_segmented (IC-based segmented performance, never used)
DROP TABLE IF EXISTS signal_performance_segmented CASCADE;

-- Drop signal_features (per-signal ML snapshots, never implemented)
DROP TABLE IF EXISTS signal_features CASCADE;

COMMIT;

-- Verification: confirm tables are gone
SELECT
    checks.tablename,
    CASE WHEN pg_tables.tablename IS NULL THEN 'DROPPED ✓' ELSE 'ERROR: still exists' END as status
FROM (
    SELECT 'signal_performance_segmented' as tablename UNION ALL
    SELECT 'signal_features'
) checks
LEFT JOIN pg_tables ON pg_tables.tablename = checks.tablename AND pg_tables.schemaname = 'public';
