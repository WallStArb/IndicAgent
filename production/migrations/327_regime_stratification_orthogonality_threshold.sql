-- Migration 327: alpha.regime_stratification.max_correlation (todos 303/304, Gate 1)
--
-- docs/research/stratification-dimension-unification.md's Gate 1 (orthogonality study)
-- explicitly deferred this threshold: "no default asserted until the first study runs --
-- needs empirical judgment, not a guessed constant." That first study ran 2026-09-01
-- (scripts/analysis/per_symbol_regime_candidates_stage2_orthogonality.py) against
-- feature_vectors.regime_volatility for all 4 gated candidates (hurst_rank, autocorr_rank,
-- skew_tail, volume_pct -- volatility_pct is exempt per the doc's own candidate table):
-- mean|pearson_r| 0.040-0.208, max|pearson_r| 0.061-0.310 across the 5 sample symbols.
-- 0.3 is the standard "weak correlation" convention cutoff (Cohen-style small/moderate/
-- large bands: <0.3 weak, 0.3-0.7 moderate, >0.7 strong) -- chosen as a round, principled
-- default because every observed value already sits comfortably below it (no borderline
-- case existed to tune around), not reverse-engineered to force a pass.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
    ('alpha.regime_stratification.max_correlation', 'float', '0.3',
     '[conventional] Gate 1 orthogonality-study admission threshold for a new per-symbol '
     'stratification candidate vs. an incumbent dimension (Pearson |r| on the continuous '
     'percentile/z-score). Standard weak-correlation convention (Cohen small/moderate/'
     'large bands), first set 2026-09-01 against todos 303/304''s Stage 2 study -- see '
     'docs/research/stratification-dimension-unification.md Gate 1. Not an ML learning '
     'target (a statistical convention, not a fitted parameter).');

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.regime_stratification.max_correlation', '0.3', 1);

COMMIT;
