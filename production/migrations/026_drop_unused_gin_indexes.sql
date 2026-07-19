-- Migration 026: Drop unused GIN indexes and redundant llm_calls index (2026-03-11)
--
-- FINDINGS:
--
-- 1. idx_intel_features_i7_gin / idx_intel_features_i8_gin:
--    No production query uses JSONB @> operators on i7 or i8.
--    Every intelligence_features INSERT (hot path: 17K+ inserts, growing) pays
--    GIN maintenance cost on a 1661 MB / 379-chunk hypertable for zero benefit.
--    Drop both.
--
-- 2. Migration 009 defined i1–i6 GIN indexes but they were never applied to the
--    live DB (or were dropped). They are equally unused — no query filters inside
--    i1–i6 JSONB with @>. Migration 009 has been updated to remove them so a
--    fresh DB rebuild does not recreate them.
--
-- 3. idx_llm_calls_model_regime:
--    The only production query on llm_calls that groups by (model, regime) always
--    also filters WHERE outcome IS NOT NULL — so idx_llm_calls_outcome_stats
--    (model, regime, setup_type, call_type, win, pnl_r) WHERE outcome IS NOT NULL
--    already covers it more efficiently. idx_llm_calls_model_regime has no unique
--    query to serve.

DROP INDEX IF EXISTS idx_intel_features_i7_gin;
DROP INDEX IF EXISTS idx_intel_features_i8_gin;
DROP INDEX IF EXISTS idx_llm_calls_model_regime;
