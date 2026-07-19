-- Migration 219: e-value pilot column — Phase 143.1 Plan 06 (todo 079, Component C)
--
-- Adds one nullable column to feature_ic_scores: cumulative_e_value, the anytime-valid
-- e-process on IC sign (src/intelligence/statistics/ic_math.py's
-- ic_sign_e_value_factor()/update_cumulative_e_value()). Pilot scope: computed ONLY for
-- tf=5m POOLED cross-sectional cells (services/ic_engine.py's _compute_cross_sectional_tf,
-- gated behind _e_value_pilot_active(tf)) — deliberately NOT rolled out to all timeframes
-- this phase, per the source doc's own caution that this is genuinely new statistical
-- machinery for the codebase (docs/research/fable-2026-07-07-renaissance-layer-refinements.md
-- §L4-1). All other rows (other timeframes, per-symbol, daily-context-feature) persist NULL.
--
-- Evidence compounds across corpus reruns instead of resetting each build: each new run
-- reads the prior run's cumulative_e_value for the same cell (same feature_name, symbol,
-- tf, regime, lookahead_bars — different training_window_end) and multiplies in this run's
-- e-value factor. Promotion requires cumulative_e_value > 1/alpha; demotion requires
-- cumulative_e_value < alpha (symmetric reciprocal thresholds on the same process,
-- config.fdr_alpha — no new APR key). Self-checkable against Component D's canaries
-- (feature_registry.is_control): noise/dead canaries' e-values must decay toward zero
-- (scripts/ops/alpha/ops_canary_integrity_assert.py's evaluate_e_value_decay()).
--
-- Migration numbering note: 220-225 already claimed by prior 143.1 plans. 226 is the
-- verified next-free number as of this plan's execution (todo 095 — directory-split
-- collision risk).

BEGIN;

ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS cumulative_e_value DOUBLE PRECISION;

COMMENT ON COLUMN feature_ic_scores.cumulative_e_value IS
    'Anytime-valid e-process on IC sign (Component C, todo 079): this run''s cumulative '
    'e-value = prior run''s cumulative_e_value * this run''s likelihood-ratio e-value '
    'factor (ic_sign_e_value_factor, ic_math.py). Pilot scope ONLY: populated for tf=5m '
    'POOLED cross-sectional cells (services/ic_engine.py''s _compute_cross_sectional_tf, '
    'gated by _e_value_pilot_active); NULL for every other row (not yet rolled out to '
    'other timeframes or per-symbol/daily-context-feature cells this phase). Promotion: '
    'cumulative_e_value > 1/alpha. Demotion: cumulative_e_value < alpha (symmetric '
    'reciprocal thresholds, config.fdr_alpha). Self-verified against Component D''s '
    'canaries -- see scripts/ops/alpha/ops_canary_integrity_assert.py evaluate_e_value_decay().';

COMMIT;
