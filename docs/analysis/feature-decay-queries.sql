-- Feature Decay Diagnostics (LIFECYCLE-06, Phase 143 Plan 03)
--
-- Ad-hoc, ready-to-run SQL for inspecting the feature lifecycle routing system built
-- in Phase 143 (concept_registry(domain='feature') status routing + ic_engine's
-- post-run lifecycle hook). Repointed from feature_registry/feature_transition_log
-- to the concept tables 2026-08-10 (Phase 170, migration 311 DROPped both).
-- No dashboard is wired to these queries -- deferred until the routed system has
-- operated for >= 30 days (enough history to make a Superset panel meaningful rather
-- than an empty chart). Run any block manually via psql:
--
--   PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f docs/analysis/feature-decay-queries.sql
--
-- Or copy individual queries into an interactive psql session.

-- ---------------------------------------------------------------------------
-- (a) Recent transitions -- last 50 concept_transition_log rows for domain='feature',
--     most recent first, grouped visually by trigger_reason so automated
--     (promotion/demotion_performance) and operator (operator_override/parent_cascade)
--     transitions are easy to tell apart.
-- ---------------------------------------------------------------------------

SELECT
    name AS feature_name,
    from_status,
    to_status,
    trigger_reason,
    ci_lower AS ic_value,
    gate_metric AS ic_sharpe,
    gate_n AS ic_n,
    triggered_at
FROM concept_transition_log
WHERE domain = 'feature'
ORDER BY triggered_at DESC
LIMIT 50;

-- ---------------------------------------------------------------------------
-- (b) Current shadow_only features and their recovery progress against the two
--     promotion floors (alpha.decay.recovery_min_passes, alpha.decay.recovery_min_observations).
--     "pending_passes" / "pending_observations" are the remaining gap to eligibility;
--     0 or negative means that individual floor is already satisfied (both must be
--     satisfied simultaneously for is_promotion_eligible to return true).
-- ---------------------------------------------------------------------------

SELECT
    cr.name AS feature_name,
    cg.consecutive_shadow_passes,
    (SELECT config_value::int FROM config_state WHERE config_key = 'alpha.decay.recovery_min_passes') AS recovery_min_passes,
    GREATEST(
        0,
        (SELECT config_value::int FROM config_state WHERE config_key = 'alpha.decay.recovery_min_passes')
        - cg.consecutive_shadow_passes
    ) AS pending_passes,
    cg.observations_since_demotion,
    (SELECT config_value::bigint FROM config_state WHERE config_key = 'alpha.decay.recovery_min_observations') AS recovery_min_observations,
    GREATEST(
        0,
        (SELECT config_value::bigint FROM config_state WHERE config_key = 'alpha.decay.recovery_min_observations')
        - cg.observations_since_demotion
    ) AS pending_observations
FROM concept_registry cr
JOIN concept_gate cg ON cg.concept_id = cr.concept_id
WHERE cr.domain = 'feature' AND cr.status = 'shadow_only'
ORDER BY cg.observations_since_demotion DESC;

-- ---------------------------------------------------------------------------
-- (c) integrity_monitor regime-shift-hold events over time -- runs where the hook
--     held ALL weights because >= alpha.decay.regime_shift_fraction of active cells
--     failed simultaneously (a market dislocation, not feature-specific decay).
-- ---------------------------------------------------------------------------

SELECT
    training_window_end,
    metric_value AS regime_shift_fraction,
    threshold_value AS regime_shift_fraction_threshold,
    evaluated_at
FROM integrity_monitor
WHERE monitor_type = 'ic_lifecycle'
  AND metric_name = 'regime_shift_fraction'
ORDER BY evaluated_at DESC;

-- (d) retired 2026-11-04: it read the ic_engine-era feature_ic_scores scopes, ensemble_weights
-- and alpha.ic.lookahead.mid, all gone (migration 575, phase 186); see git history.
