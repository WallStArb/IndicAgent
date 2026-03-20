-- Migration 047: Pattern Reliability Table
-- Stores per-pattern confidence weights with bootstrap priors and live calibration
-- Phase 42: Candlestick Pattern Expansion
--
-- Renaissance principle: "Earn the right through proof"
-- Bootstrap priors from literature (Nison 2001, Bulkowski 2021), discounted 10% for futures.
-- Phase 46 ML analysis will re-calibrate based on actual market outcomes (p < 0.05, N >= 30).

-- Create pattern_reliability table
CREATE TABLE IF NOT EXISTS pattern_reliability (
    pattern_name TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    base_confidence FLOAT NOT NULL,
    sample_size INTEGER DEFAULT 0,
    win_rate FLOAT,
    p_value FLOAT,
    ic_score FLOAT,
    is_bootstrap BOOLEAN DEFAULT true,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (pattern_name, timeframe)
);

-- Index for bootstrap queries (used by I7 plugin to load priors)
CREATE INDEX IF NOT EXISTS idx_pattern_reliability_bootstrap
    ON pattern_reliability(is_bootstrap)
    WHERE is_bootstrap = true;

-- Index for calibration updates (used by weight_updater, gates on sample_size >= 30)
CREATE INDEX IF NOT EXISTS idx_pattern_reliability_sample_size
    ON pattern_reliability(sample_size)
    WHERE sample_size >= 30;

-- Seed literature-based bootstrap priors for 10 new candlestick patterns
-- Default timeframe: 1m (the most active trading timeframe for this platform)
-- All 10 patterns are seeded; Phase 46 will add per-TF rows as data accumulates
INSERT INTO pattern_reliability (pattern_name, timeframe, base_confidence, is_bootstrap) VALUES
    -- Tier 1: High Reliability (0.70) — rare but high win rate at key levels
    ('abandoned_baby_bull', '1m', 0.70, true),
    ('abandoned_baby_bear', '1m', 0.70, true),
    ('kicker_bull',         '1m', 0.70, true),
    ('kicker_bear',         '1m', 0.70, true),
    -- Tier 2: Moderate Reliability (0.55-0.60) — common, moderate directional edge
    ('harami_bull',         '1m', 0.60, true),
    ('harami_bear',         '1m', 0.60, true),
    ('tweezer_top',         '1m', 0.60, true),
    ('tweezer_bottom',      '1m', 0.60, true),
    ('belt_hold_bull',      '1m', 0.55, true),
    ('belt_hold_bear',      '1m', 0.55, true)
ON CONFLICT (pattern_name, timeframe) DO NOTHING;

-- Idempotency notice: re-running this migration is safe (ON CONFLICT DO NOTHING above)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pattern_reliability WHERE is_bootstrap = true LIMIT 1) THEN
        RAISE NOTICE 'pattern_reliability: bootstrap priors present (table seeded)';
    END IF;
END $$;

-- Verification query: run after migration to confirm correct seed data
SELECT
    pattern_name,
    timeframe,
    base_confidence,
    is_bootstrap,
    sample_size
FROM pattern_reliability
WHERE is_bootstrap = true
ORDER BY base_confidence DESC, pattern_name;
