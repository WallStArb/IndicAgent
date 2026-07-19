-- Migration 110: raise setup_performance sample gate from 30 to 100
-- Minimum 100 samples required; values below 200 are statistically unreliable
-- on fat-tailed return distributions typical of futures/equity setups.
-- After applying this migration, rows with sample_size < 100 will no longer
-- be used by the perf_multiplier ranking path (ranker.py and aggregator.py
-- both gate at 100). Existing rows with sample_size < 100 remain in the table
-- for audit purposes but are treated as warm-up (multiplier = 0.5).

-- Remove stale rows that no longer meet the new gate threshold.
-- These are safe to delete: the next weight update cycle will re-insert any
-- that have since crossed 100 signals.
DELETE FROM setup_performance WHERE sample_size < 100;
