-- Migration 209: feature_registry lifecycle-routing columns — Phase 143 Plan 02
--
-- Adds the two counters record_transition_sync (Plan 02) and ic_engine's post-run
-- hook (Plan 03) need to gate shadow_only -> active promotion on evidence alone:
--   consecutive_shadow_passes    — consecutive passing corpus runs since entering shadow_only
--   observations_since_demotion  — cumulative new independent observations since demotion
--
-- REVIEW-DRIVEN CHANGE: pre_shadow_weight is deliberately NOT added here (cross-AI
-- review 143-REVIEWS.md HIGH finding 2). services/ensemble_trainer.py is the sole
-- writer of ensemble_weights and recomputes every weight from scratch each run from
-- that run's feature_ic_scores rows (derive_weights / mean_variance_weights are pure
-- functions of current IC + LW covariance; no prior-weight seed is read anywhere in
-- the file). A pre_shadow_weight scalar on feature_registry would therefore be written
-- to a column nothing reads. Promotion is accomplished by the status flip alone: the
-- next ic_engine run stamps feature_status_at_eval='active' from registry status, and
-- the next ensemble_trainer run naturally recomputes a fresh weight from current IC.
--
-- Also seeds the alpha.decay.recovery_min_passes APR key (companion to the existing
-- alpha.decay.recovery_min_observations key from migration 161). Both floors gate
-- is_promotion_eligible; no calendar/cooldown clock is introduced.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_registry lifecycle counter columns
-- ---------------------------------------------------------------------------

ALTER TABLE feature_registry
    ADD COLUMN IF NOT EXISTS consecutive_shadow_passes integer NOT NULL DEFAULT 0;

ALTER TABLE feature_registry
    ADD COLUMN IF NOT EXISTS observations_since_demotion bigint NOT NULL DEFAULT 0;

COMMENT ON COLUMN feature_registry.consecutive_shadow_passes IS
    'Count of consecutive passing corpus runs since this feature entered shadow_only. '
    'Reset to 0 by advance_shadow_counters_sync on any failing run, and reset to 0 by '
    'record_transition_sync whenever the feature re-enters shadow_only from active (a '
    'second decay cycle re-earns the recovery evidence bar from scratch instead of '
    'inheriting counters that already satisfied a prior promotion). Compared against '
    'alpha.decay.recovery_min_passes for shadow_only -> active promotion eligibility. '
    'Lifecycle state — lives with status on feature_registry, not on feature_ic_scores.';

COMMENT ON COLUMN feature_registry.observations_since_demotion IS
    'Cumulative new independent observations counted since this feature was demoted to '
    'shadow_only. Reset to 0 by record_transition_sync on every active -> shadow_only '
    'demotion. Compared against alpha.decay.recovery_min_observations for shadow_only -> '
    'active promotion eligibility. Lifecycle state — lives with status on '
    'feature_registry, not on feature_ic_scores.';

-- ---------------------------------------------------------------------------
-- 2. APR key: alpha.decay.recovery_min_passes
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.decay.recovery_min_passes',
    'int',
    '2',
    1, 20,
    '[initial_estimate] Consecutive passing corpus runs required while shadow_only before is_promotion_eligible returns true. Companion floor to alpha.decay.recovery_min_observations — both must be met, no calendar cooldown. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.decay.recovery_min_passes', '2', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
