-- Migration 321: concept_gate demotion hysteresis (todo 323)
--
-- ic_engine.py's active -> shadow_only demotion (services/ic_engine.py:4333-4378) fires
-- immediately off a SINGLE corpus run's cross-sectional materiality check
-- (demote_fraction >= demotion_fraction_floor), with no requirement the failure repeat
-- across runs. ConceptRegistryService.advance_shadow_counters_sync's own docstring states
-- this explicitly: "there is no fail-counter for active concepts; demotion is decided by
-- the caller's per-run materiality check, not by any registry counter." That's a real
-- asymmetry against this project's own principles -- Invariant 7 requires promotion to
-- clear an effective-N floor specifically because a single lucky draw isn't proof; the
-- same logic applies to demotion evidence, but nothing currently enforces it there. A
-- data-quality blip or one-off regime noise can demote an already-proven, active concept
-- on one bad run.
--
-- Mirrors the existing promotion_consecutive/min_promotion_consecutive shape exactly
-- (same table, same nullable-override-of-an-APR-default convention as
-- record_comparison_outcome's default_min_promotion_consecutive parameter) rather than
-- inventing a new pattern -- this is the demotion-side sibling of that same mechanism,
-- applied to the feature domain's sync (ic_engine.py) lifecycle path instead of the
-- ensemble_strategy domain's async (record_comparison_outcome) path.

BEGIN;

ALTER TABLE concept_gate
    ADD COLUMN IF NOT EXISTS consecutive_active_fails INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS min_demotion_consecutive INTEGER;

COMMENT ON COLUMN concept_gate.consecutive_active_fails IS
    'Todo 323: consecutive corpus runs (for an active concept) where the cross-sectional '
    'materiality check failed (demote_fraction >= demotion_fraction_floor). Incremented by '
    'ConceptRegistryService.advance_active_counters_sync on a failing run, reset to 0 on a '
    'passing run AND on any transition into active (a freshly (re)promoted concept must '
    'not inherit a stale fail-streak from before its last demotion). Demotion only fires '
    'once this crosses min_demotion_consecutive.';

COMMENT ON COLUMN concept_gate.min_demotion_consecutive IS
    '[initial_estimate] Todo 323: per-concept override of the APR default '
    '(alpha.decay.demotion_min_consecutive) -- NULL (the seeded value for every existing '
    'row) means "use the caller-resolved APR default", matching min_promotion_consecutive''s '
    'existing override convention exactly. Candidate ML learning target once enough '
    'demotion history accumulates to tune it empirically.';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    ('alpha.decay.demotion_min_consecutive', 'int', '2', 1, 20,
     '[initial_estimate] Consecutive failing corpus runs an active feature concept must '
     'accumulate before demotion to shadow_only actually fires (todo 323). Matches '
     'alpha.concept_registry.ensemble_strategy_min_promotion_consecutive''s value (2) as '
     'the most directly defensible symmetric starting point -- promotion already requires '
     '2 consecutive passing evaluations on the ensemble_strategy side; demotion evidence '
     'deserves the same bar. Only the feature domain currently uses the sync '
     '(ic_engine.py) demotion path this key gates; no ensemble_strategy-side key added '
     '(YAGNI -- that domain has no equivalent per-run sync demotion call site today). '
     'Bounds mirror alpha.decay.recovery_min_passes (migration 209).')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.decay.demotion_min_consecutive', '2', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
