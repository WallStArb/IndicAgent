-- Migration 165: Add alpha.ic.bootstrap_seed APR key.
--
-- Seeds the IC engine's circular block bootstrap RNG so runs are reproducible.
-- Without a fixed seed, CI bounds vary between runs for identical inputs -- making
-- it impossible to know whether a difference between two runs reflects real signal
-- change or bootstrap sampling variance.
--
-- WARNING: changing this seed invalidates all existing IC CI bounds. If changed,
-- all feature_ic_scores rows must be recomputed (truncate + full backfill run).
-- That is the intent: use APR to A/B test seed sensitivity, then lock in a stable
-- value. Not an ML learning target -- this is a reproducibility parameter.
--
-- Seed 42 is the conventional initial estimate. Once sufficient data accumulates,
-- measure CI variance across seeds 0-99 on a held-out window; if variance < 1%
-- of IC magnitude, the seed choice is immaterial and 42 can be locked permanently.

-- -------------------------------------------------------------------------
-- Section 1: config_schema
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.ic.bootstrap_seed',
    'int',
    '42',
    0, 2147483647,
    '[conventional] RNG seed for circular block bootstrap IC confidence interval estimation. Fixed seed ensures reproducible CI bounds across runs with identical inputs. CAUTION: changing this seed invalidates all existing feature_ic_scores CI columns; a full recompute (truncate + backfill) is required. Not an ML learning target. Seed sensitivity test: run with seeds 0-99 on a held-out window; if CI variance < 1% of IC magnitude, seed choice is immaterial.'
)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- Section 2: config_state
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.ic.bootstrap_seed', '42', 1)
ON CONFLICT (config_key) DO NOTHING;
