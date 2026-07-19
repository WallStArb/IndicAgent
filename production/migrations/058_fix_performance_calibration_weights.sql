-- Fix missing columns for intelligence pipeline v2.1
-- Applied: 2026-04-01
-- Purpose: Fix DB schema issues preventing perf_weights, calibration, and cis_weights loading

-- These three schema fixes resolve warnings in intelligence_pipeline_agent startup:

-- 1. Add 'direction' column to setup_performance
-- Needed for perf_weights lookup by (setup_plugin, direction)
ALTER TABLE setup_performance ADD COLUMN IF NOT EXISTS direction text DEFAULT 'long';

-- 2. Add 'weights' JSONB column to cis_weights
-- Needed for learned weight storage and retrieval
ALTER TABLE cis_weights ADD COLUMN IF NOT EXISTS weights jsonb DEFAULT '{}'::jsonb;

-- Populate weights from individual columns for existing records
UPDATE cis_weights
SET weights = jsonb_build_object(
    'trend_w', trend_w,
    'momentum_w', momentum_w,
    'structure_w', structure_w,
    'pattern_w', pattern_w,
    'institutional_w', institutional_w,
    'regime_w', regime_w,
    'threshold', threshold,
    'sample_size', COALESCE(sample_size, 0),
    'signal_quality_mean', signal_quality_mean
)
WHERE weights IS NULL OR weights = '{}'::jsonb;

-- 3. Create calibration_curves table
-- Needed for calibration curve storage and lookup
CREATE TABLE IF NOT EXISTS calibration_curves (
    setup_plugin text NOT NULL PRIMARY KEY,
    curve_data jsonb NOT NULL,
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

-- Migrate data from confidence_calibration if it exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'confidence_calibration') THEN
        INSERT INTO calibration_curves (setup_plugin, curve_data, updated_at)
        SELECT
            plugin_name as setup_plugin,
            jsonb_build_object(
                'timeframe', timeframe,
                'breakpoints', breakpoints,
                'values', values,
                'ece', ece,
                'sample_size', sample_size
            ) as curve_data,
            updated_at
        FROM confidence_calibration
        ON CONFLICT (setup_plugin) DO NOTHING;
    END IF;
END $$;

-- Verification queries
-- SELECT setup_plugin, direction, win_rate FROM setup_performance LIMIT 5;
-- SELECT version, weights FROM cis_weights LIMIT 5;
-- SELECT setup_plugin, curve_data FROM calibration_curves LIMIT 5;
