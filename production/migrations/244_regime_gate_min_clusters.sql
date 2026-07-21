-- Migration 244: alpha.validation.regime_gate_min_clusters APR key (todo 165)
--
-- Day-cluster coverage floor for the new regime-stratified OOS promotion gate
-- (evaluate_frame_gate's min_clusters parameter, services/counterfactual_tracker.py).
-- Distinct from alpha.scoring.min_strategy_n (a frame-COUNT floor) -- a (direction,
-- regime) cell can clear that floor on raw frame count while resting on too few
-- independent day-clusters for a day-clustered bootstrap CI to mean anything (e.g. a
-- live-observed OOS cell: 261 frames, only 8 days). Below this floor, the cell is
-- reported coverage="insufficient" and excluded from the promotion verdict combination
-- -- never silently counted as a pass or a fail.
--
-- PRE-REGISTERED, NOT TUNABLE POST-HOC: this value must be frozen at the moment it is
-- committed and never adjusted in response to seeing whether a specific promotion
-- decision passes or fails under it -- same "no post-hoc gate renegotiation" discipline
-- already established for frame_gate_passes' bootstrap_random_state (WR-01,
-- SHADOW-REVIEW.md). Any future change to this key must cite new empirical evidence
-- about coverage-floor calibration in general, never a specific pending verdict.
--
-- Seed 20 is [initial_estimate]: no empirical calibration performed yet (todo 165 filed
-- this alongside the mechanism, not a tuned number) -- chosen as meaningfully smaller
-- than the existing pooled 60-day floor (alpha.scoring.min_strategy_n's day-equivalent
-- for a single-window gate) while still large enough for a day-clustered BCa bootstrap
-- to be non-degenerate.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.validation.regime_gate_min_clusters',
    'int',
    '20',
    5, 60,
    '[initial_estimate] Day-cluster coverage floor for the regime-stratified OOS '
    'promotion gate (todo 165). A (direction, regime) cell below this many distinct '
    'day-clusters is reported coverage=insufficient and excluded from the promotion '
    'verdict combination, rather than silently counted as pass or fail. PRE-REGISTERED: '
    'must not be tuned in response to any specific promotion decision''s outcome (same '
    'discipline as alpha.scoring.bootstrap_random_state, WR-01). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.validation.regime_gate_min_clusters', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.validation.regime_gate_min_clusters', 1, '20', 'migration_244',
     'Seed regime-stratified OOS gate day-cluster coverage floor, todo 165 [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
