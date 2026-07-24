-- Migration 257: recalibrate alpha.equity_regime.breadth_bear/breadth_bull (todo 092)
--
-- ROOT CAUSE (measured directly, not guessed): breadth_frac (fraction of equity ETFs above
-- their 200-bar MA) was bucketed against fixed 0.40/0.60 cuts on the RAW fraction -- guessed
-- defaults, never checked against the real distribution. vix_pct, by contrast, was already a
-- causal expanding percentile RANK, so its 0.33/0.67 cuts were population-balanced by
-- construction. Measured this universe's actual breadth_frac distribution: median ~0.70
-- (intraday) / ~0.76 (1d), heavily right-skewed above the guessed 0.60 "bull" cutoff --
-- equities spend most of their time with most symbols above their own trailing MA.
-- market_regimes.regime_label population counts confirmed the damage: low_bull was 12-17x
-- more populated than low_bear across all 4 tfs.
--
-- FIX: src/intelligence/regime_signals/breadth_vol.py now applies the SAME causal
-- expanding-rank transform already proven for vix_pct to breadth_frac too (extracted into a
-- shared _causal_expanding_rank() helper), before bucketing. This is self-calibrating --
-- population-balanced by construction, permanently, not just at whatever snapshot a new
-- fixed number happened to be chosen against -- rather than a one-time swap of one guessed
-- number (0.40/0.60) for another. Since breadth is now itself a [0,1] percentile rank
-- (mirroring vix_pct exactly), the natural, well-justified cut is the SAME symmetric
-- tercile split already used for vix_pct: 0.33/0.67.
--
-- BLAST RADIUS, NOT A CASUAL CONFIG TWEAK: changing this value (and PROB_KEYS renaming
-- breadth_frac -> breadth_pct) changes every downstream market_regimes.regime_label,
-- feature_ic_scores regime stratum, and ensemble_weights/ensemble_alpha regime assignment
-- for the 'equity' regime_group. This migration seeds the corrected default; it does NOT by
-- itself recompute market_regimes historically -- that is a separate, explicit corpus
-- recompute (services/cross_sectional_regime_model.py full re-run for regime_group='equity'
-- across all 4 tfs and the full historical range), tracked as its own deliberate operation
-- given its cost and the downstream invalidation cascade (feature_ic_scores/ensemble_weights/
-- ensemble_alpha all become stale relative to any bar computed before the recompute).

BEGIN;

UPDATE config_schema
SET description =
    '[rca_analysis] Percentile-rank threshold (matches vix_pct''s own tercile construction, '
    'not a raw-fraction threshold) below which breadth is "bear". Recalibrated 2026-07-24 '
    '(todo 092): breadth_frac is now itself a causal expanding percentile rank before '
    'bucketing, same as vix_pct -- the old 0.40 was a guessed raw-fraction cut, never '
    'checked against the real distribution (measured median breadth_frac ~0.70-0.76, '
    'causing 12-17x population imbalance across regime cells). Changing this value changes '
    'every downstream market_regimes label -- requires a full historical regime recompute.'
WHERE config_key = 'alpha.equity_regime.breadth_bear';

UPDATE config_schema
SET description =
    '[rca_analysis] Percentile-rank threshold (matches vix_pct''s own tercile construction, '
    'not a raw-fraction threshold) above which breadth is "bull". Recalibrated 2026-07-24 '
    '(todo 092): breadth_frac is now itself a causal expanding percentile rank before '
    'bucketing, same as vix_pct -- the old 0.60 was a guessed raw-fraction cut, never '
    'checked against the real distribution (measured median breadth_frac ~0.70-0.76, '
    'causing 12-17x population imbalance across regime cells). Changing this value changes '
    'every downstream market_regimes label -- requires a full historical regime recompute.'
WHERE config_key = 'alpha.equity_regime.breadth_bull';

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.equity_regime.breadth_bear', '0.33', 2),
    ('alpha.equity_regime.breadth_bull', '0.67', 2)
ON CONFLICT (config_key) DO UPDATE SET
    config_value = EXCLUDED.config_value,
    version = config_state.version + 1;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.equity_regime.breadth_bear', 2, '0.33', 'migration_257',
     'todo 092: breadth_frac converted to a causal expanding percentile rank (matching '
     'vix_pct); old 0.40 raw-fraction cut caused measured 12-17x regime population imbalance'),
    (NOW(), 'alpha.equity_regime.breadth_bull', 2, '0.67', 'migration_257',
     'todo 092: breadth_frac converted to a causal expanding percentile rank (matching '
     'vix_pct); old 0.60 raw-fraction cut caused measured 12-17x regime population imbalance')
ON CONFLICT DO NOTHING;

COMMIT;
