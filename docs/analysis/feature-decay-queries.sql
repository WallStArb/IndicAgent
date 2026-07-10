-- Feature Decay Diagnostics (LIFECYCLE-06, Phase 143 Plan 03)
--
-- Ad-hoc, ready-to-run SQL for inspecting the feature lifecycle routing system built
-- in Phase 143 (feature_registry status routing + ic_engine's post-run lifecycle hook).
-- No dashboard is wired to these queries -- deferred until the routed system has
-- operated for >= 30 days (enough history to make a Superset panel meaningful rather
-- than an empty chart). Run any block manually via psql:
--
--   PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f docs/analysis/feature-decay-queries.sql
--
-- Or copy individual queries into an interactive psql session.

-- ---------------------------------------------------------------------------
-- (a) Recent transitions -- last 50 feature_transition_log rows, most recent first,
--     grouped visually by trigger_reason so automated (ic_promotion/ic_demotion) and
--     operator (operator_override/parent_cascade) transitions are easy to tell apart.
-- ---------------------------------------------------------------------------

SELECT
    feature_name,
    from_status,
    to_status,
    trigger_reason,
    ic_value,
    ic_sharpe,
    ic_n,
    triggered_at
FROM feature_transition_log
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
    fr.feature_name,
    fr.consecutive_shadow_passes,
    (SELECT config_value::int FROM config_state WHERE config_key = 'alpha.decay.recovery_min_passes') AS recovery_min_passes,
    GREATEST(
        0,
        (SELECT config_value::int FROM config_state WHERE config_key = 'alpha.decay.recovery_min_passes')
        - fr.consecutive_shadow_passes
    ) AS pending_passes,
    fr.observations_since_demotion,
    (SELECT config_value::bigint FROM config_state WHERE config_key = 'alpha.decay.recovery_min_observations') AS recovery_min_observations,
    GREATEST(
        0,
        (SELECT config_value::bigint FROM config_state WHERE config_key = 'alpha.decay.recovery_min_observations')
        - fr.observations_since_demotion
    ) AS pending_observations
FROM feature_registry fr
WHERE fr.status = 'shadow_only'
ORDER BY fr.observations_since_demotion DESC;

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

-- ---------------------------------------------------------------------------
-- (d) Active features whose latest feature_ic_scores cell sits closest to the
--     materiality boundary -- an early-warning view of features at risk of demotion
--     on the NEXT ic_engine run. "distance_to_boundary" is standing_weight *
--     |ic_ci_lower| minus alpha.decay.materiality_threshold; values near zero (from
--     either side) are the features to watch. Restricted to POOLED cross-sectional
--     cells at the pinned mid lookahead (the same population the lifecycle hook
--     evaluates), most recent training_window_end only.
-- ---------------------------------------------------------------------------

WITH latest_window AS (
    SELECT max(training_window_end) AS training_window_end
    FROM feature_ic_scores
    WHERE symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'
),
mid_lookahead AS (
    SELECT config_value::int AS lookahead_bars
    FROM config_state
    WHERE config_key = 'alpha.ic.lookahead.mid'
)
SELECT
    fis.feature_name,
    fis.tf,
    fis.regime,
    fis.ic_ci_lower,
    fis.passes_fdr,
    COALESCE(ew.weight, 0.0) AS standing_weight,
    COALESCE(ew.weight, 0.0) * abs(fis.ic_ci_lower) AS material_score,
    (SELECT config_value::float FROM config_state WHERE config_key = 'alpha.decay.materiality_threshold') AS materiality_threshold,
    COALESCE(ew.weight, 0.0) * abs(fis.ic_ci_lower)
        - (SELECT config_value::float FROM config_state WHERE config_key = 'alpha.decay.materiality_threshold')
        AS distance_to_boundary
FROM feature_ic_scores fis
CROSS JOIN latest_window lw
CROSS JOIN mid_lookahead ml
LEFT JOIN ensemble_weights ew
       ON ew.symbol = 'UNIVERSE'
      AND ew.tf = fis.tf
      AND ew.regime = fis.regime
      AND ew.feature_name = fis.feature_name
      AND ew.weight_version = (SELECT config_value FROM config_state WHERE config_key = 'alpha.ensemble.weight_version')
WHERE fis.symbol = 'POOLED'
  AND fis.is_pooled = true
  AND fis.regime != '_pooled'
  AND fis.training_window_end = lw.training_window_end
  AND fis.lookahead_bars = ml.lookahead_bars
  AND fis.feature_status_at_eval = 'active'
ORDER BY abs(
    COALESCE(ew.weight, 0.0) * abs(fis.ic_ci_lower)
    - (SELECT config_value::float FROM config_state WHERE config_key = 'alpha.decay.materiality_threshold')
) ASC
LIMIT 25;
