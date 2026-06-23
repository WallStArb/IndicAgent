-- Migration 163: forward_returns gradient column naming + APR seed keys
--
-- Renames forward_return columns from bar-count names (return_1bar) to gradient scale
-- names (return_fast). The period values are tunable calibration parameters, not concept
-- definitions. Schema holds the concept (fast/mid/slow/extended); APR holds the period.
-- Pattern: rsi_fast column + feature.period.rsi.fast APR key.
--
-- Also fixes regime_label_source DEFAULT ('filtered' -> 'forward_filter') and seeds
-- alpha.hmm.random_state (moves HMM_RANDOM_STATE out of module constants).
--
-- forward_returns is a TimescaleDB hypertable; RENAME COLUMN propagates to all chunks.
-- Table is truncated first (junk data from initial test runs) to make rename instant.

-- Step 1: Truncate (test data only; full corpus run is P8)
TRUNCATE TABLE forward_returns;

-- Step 2: Rename return columns to gradient scale names
ALTER TABLE forward_returns RENAME COLUMN return_1bar    TO return_fast;
ALTER TABLE forward_returns RENAME COLUMN complete_1bar  TO complete_fast;
ALTER TABLE forward_returns RENAME COLUMN return_5bar    TO return_mid;
ALTER TABLE forward_returns RENAME COLUMN complete_5bar  TO complete_mid;
ALTER TABLE forward_returns RENAME COLUMN return_20bar   TO return_slow;
ALTER TABLE forward_returns RENAME COLUMN complete_20bar TO complete_slow;
ALTER TABLE forward_returns RENAME COLUMN return_60bar   TO return_extended;
ALTER TABLE forward_returns RENAME COLUMN complete_60bar TO complete_extended;

-- Step 3: Fix regime_label_source default (was 'filtered', correct value is 'forward_filter')
ALTER TABLE forward_returns
    ALTER COLUMN regime_label_source SET DEFAULT 'forward_filter';

-- Step 4: Seed APR keys for lookahead periods (alpha.ic.lookahead.* namespace)
-- Schema holds the scale name (fast/mid/slow/extended); APR holds the period in bars.
-- ML learning target: IC horizon calibration per scale.
INSERT INTO config_schema (config_key, value_type, min_value, max_value, description) VALUES
    ('alpha.ic.lookahead.fast',     'int', 1,  20,  '[initial_estimate] fast lookahead period in bars; return_fast column. ML learning target: short-term IC horizon calibration.'),
    ('alpha.ic.lookahead.mid',      'int', 2,  60,  '[initial_estimate] mid lookahead period in bars; return_mid column. ML learning target: medium-term IC horizon calibration.'),
    ('alpha.ic.lookahead.slow',     'int', 5,  120, '[initial_estimate] slow lookahead period in bars; return_slow column. ML learning target: longer-term IC horizon calibration.'),
    ('alpha.ic.lookahead.extended', 'int', 10, 252, '[initial_estimate] extended lookahead period in bars; return_extended column. ML learning target: regime-scale IC horizon calibration.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('alpha.ic.lookahead.fast',     '1',  1),
    ('alpha.ic.lookahead.mid',      '5',  1),
    ('alpha.ic.lookahead.slow',     '20', 1),
    ('alpha.ic.lookahead.extended', '60', 1)
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value;

-- Step 5: Seed alpha.hmm.random_state (moves HMM_RANDOM_STATE = 42 out of module constants)
-- CHANGING THIS SEED INVALIDATES all regime labels in feature_vectors and requires a full
-- regime_writer + ic_engine re-run. Treat as a migration-level decision, not a casual tweak.
INSERT INTO config_schema (config_key, value_type, min_value, max_value, description) VALUES
    ('alpha.hmm.random_state', 'int', 0, 99999,
     '[conventional] numpy random seed for GaussianHMM fitting in regime_writer. CHANGING THIS INVALIDATES all regime labels in feature_vectors and requires full regime_writer + ic_engine re-run.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('alpha.hmm.random_state', '42', 1)
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value;
