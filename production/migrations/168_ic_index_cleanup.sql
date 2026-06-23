-- Migration 168: IC table index cleanup.
--
-- 1. DROP forward_returns_symbol_tf_ts_idx — duplicate of the PK.
--    Migration 160 explicitly created this index ON (symbol, tf, bar_ts), which is
--    identical to the PRIMARY KEY index already created by the PK constraint. Every
--    insert was maintaining two B-tree indexes over the same columns for zero benefit.
--
-- 2. ADD feature_ic_scores_symbol_tf_ts_idx — for temporal ordering queries.
--    Alpha emission path: "get all IC-passing features for (symbol, tf), latest run first."
--    The existing gate_idx ON (passes_walkforward, passes_fdr, symbol, tf) handles the
--    filtered-by-pass-status pattern but cannot satisfy ORDER BY training_window_end DESC
--    without an extra sort step. This index covers the ordered-by-symbol/tf access pattern.
--
-- All statements are idempotent (DROP IF EXISTS / CREATE IF NOT EXISTS).
-- Safe to re-run.

-- -------------------------------------------------------------------------
-- Section 1: Drop redundant forward_returns index
-- -------------------------------------------------------------------------

DROP INDEX IF EXISTS forward_returns_symbol_tf_ts_idx;

-- -------------------------------------------------------------------------
-- Section 2: Add temporal ordering index on feature_ic_scores
-- -------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS feature_ic_scores_symbol_tf_ts_idx
    ON feature_ic_scores (symbol, tf, training_window_end DESC);
