-- 064_symbol_keyed_aggregates.sql
-- Phase 68-04: Symbol-keyed aggregate tables
-- Adds symbol as a first-class dimension to all six aggregate tables so that
-- per-instrument multipliers, scores, and calibration curves can be stored and
-- looked up independently of the global blended aggregate.
--
-- Sentinel: '*' represents the global (cross-symbol) aggregate row.
-- All existing rows default to '*'. New symbol-specific rows are written by
-- future phases; this migration makes the schema ready.
--
-- Lookup pattern in all consumers:
--   1. Try (... , symbol=<instrument>)  -- symbol-specific
--   2. Fall back to (... , symbol='*')  -- global sentinel
--   3. Fall back to hardcoded prior / passthrough (where applicable)

BEGIN;

-- -- setup_performance --------------------------------------------------------
ALTER TABLE setup_performance
    ADD COLUMN IF NOT EXISTS symbol TEXT NOT NULL DEFAULT '*';

ALTER TABLE setup_performance DROP CONSTRAINT IF EXISTS setup_performance_pkey;
ALTER TABLE setup_performance ADD PRIMARY KEY (setup_plugin, symbol);

-- -- tod_multipliers -----------------------------------------------------------
ALTER TABLE tod_multipliers
    ADD COLUMN IF NOT EXISTS symbol TEXT NOT NULL DEFAULT '*';

ALTER TABLE tod_multipliers DROP CONSTRAINT IF EXISTS tod_multipliers_pkey;
ALTER TABLE tod_multipliers ADD PRIMARY KEY (regime_type, tf, hour_et, symbol);

-- -- calibration_curves --------------------------------------------------------
ALTER TABLE calibration_curves
    ADD COLUMN IF NOT EXISTS symbol TEXT NOT NULL DEFAULT '*';

ALTER TABLE calibration_curves DROP CONSTRAINT IF EXISTS calibration_curves_pkey;
ALTER TABLE calibration_curves ADD PRIMARY KEY (setup_plugin, symbol);

-- -- llm_model_scores ----------------------------------------------------------
ALTER TABLE llm_model_scores
    ADD COLUMN IF NOT EXISTS symbol TEXT NOT NULL DEFAULT '*';

ALTER TABLE llm_model_scores DROP CONSTRAINT IF EXISTS llm_model_scores_pkey;
ALTER TABLE llm_model_scores ADD PRIMARY KEY (model, regime, setup_type, call_type, symbol);

-- -- signal_metrics ------------------------------------------------------------
ALTER TABLE signal_metrics
    ADD COLUMN IF NOT EXISTS symbol TEXT NOT NULL DEFAULT '*';

ALTER TABLE signal_metrics DROP CONSTRAINT IF EXISTS signal_metrics_pkey;
ALTER TABLE signal_metrics ADD PRIMARY KEY (track, setup_plugin, tf, regime_type, window_days, symbol);

-- -- signal_metrics_ic ---------------------------------------------------------
ALTER TABLE signal_metrics_ic
    ADD COLUMN IF NOT EXISTS symbol TEXT NOT NULL DEFAULT '*';

ALTER TABLE signal_metrics_ic DROP CONSTRAINT IF EXISTS signal_metrics_ic_pkey;
ALTER TABLE signal_metrics_ic ADD PRIMARY KEY (setup_plugin, tf, regime_type, window_days, symbol);

COMMIT;
