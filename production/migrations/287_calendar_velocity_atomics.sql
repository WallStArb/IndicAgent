-- Migration 287: Calendar Cycle/TDOM/Minute + Velocity Atomics — Phase 151 Plan 01
--
-- Adds the first batch of Phase 151 tier-0 atomic primitives: 6 calendar
-- coordinates (todo 104) and 4 velocity primitives (todo 123), 10 new
-- feature_vectors columns total. These are the cheapest, most self-contained
-- of the phase's 28 atomic candidates -- pure functions of bar_ts (calendar)
-- or of an already-computed z-score series (velocity). No cross-asset bar
-- fetches, no new symbols, no new DAG surface.
--
-- Migration numbering note: this plan's own text names the file
-- "259_calendar_velocity_atomics.sql" (provisional target as of the plan's
-- 2026-07-24 authoring date, when 258 was the latest migration on disk).
-- Live inspection at execution time (2026-08-05) shows the sequence has
-- since advanced through 285 -- same collision class as migration 255's own
-- numbering note (243 -> 255) and migration 216's (221 -> 222/223). 286 was
-- the first provisional target but collided with a concurrent sibling
-- worktree session's own migration (286_cluster_regime_conditioned.sql,
-- Phase 151 Plan 04/Wave 4's alpha.ensemble.cluster_regime_conditioned key,
-- confirmed via config_history: that key's changed_by='migration_286' row
-- timestamped 2026-08-05 09:47:25 UTC, ~29 minutes before this migration's
-- own first apply attempt) -- discovered only after applying, since the
-- sibling's file lives on a different, not-yet-merged worktree branch and
-- was invisible to this worktree's own `ls production/migrations/` check.
-- 287 is the verified next-free number, checked against both worktree
-- branches' git trees and config_history before this file's final apply.
--
-- Column type: DOUBLE PRECISION for all 10 new columns, matching every other
-- feature_vectors column added since migration 201 (no `real`/float32 column
-- exists in this table despite some historical plan drafts claiming
-- otherwise -- see migration 255's own header note #3 for the same
-- correction). ADD COLUMN IF NOT EXISTS with no DEFAULT is metadata-only
-- against the compressed hypertable -- no decompression step required
-- (confirmed via migration 197/206/216/255/266/267 precedent).
--
-- Phase 170 parity (Section 5 below, added retroactively -- this plan was
-- written 2026-07-24, before Phase 170 shipped its dual-write cutover
-- 2026-08-04/05): ic_engine.py's _apply_feature_transitions now runs a
-- PARITY PRECONDITION on every corpus pass (Phase 170 Plan 06, T-170-17)
-- that hard-stops if any feature_registry row lacks a concept_registry
-- counterpart. Without Section 5, the next ic_engine run after this
-- migration lands would treat these 10 rows as a split-brain and refuse to
-- apply any transitions at all, for every feature, not just these 10. Field
-- mapping matches migration 284's feature-domain seed exactly (derived from
-- the feature_registry rows this migration's own Section 3 just inserted,
-- never re-typed literals, so the two tables cannot drift).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_vectors: 10 new columns (6 calendar coordinates + 4 velocity)
-- ---------------------------------------------------------------------------

ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS quarter_cycle_sin DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS quarter_cycle_cos DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS tdom_sin DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS tdom_cos DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS minute_of_hour_sin DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS minute_of_hour_cos DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS momentum_z_velocity_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS momentum_z_velocity_mid DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS momentum_z_velocity_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vwap_dev_sigma_velocity DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.quarter_cycle_sin IS
    'sin(2*pi*quarter_position) -- first circular harmonic of the existing quarter_position value. Phase 151.';
COMMENT ON COLUMN feature_vectors.quarter_cycle_cos IS
    'cos(2*pi*quarter_position) -- first circular harmonic of the existing quarter_position value. Phase 151.';
COMMENT ON COLUMN feature_vectors.tdom_sin IS
    'sin(2*pi*trading_day_of_month/weekdays_in_month) -- t = count of Mon-Fri weekdays from the 1st of the month through bar_ts.date() inclusive; W = total Mon-Fri weekday count in that calendar month. Ignores market holidays by design. Phase 151.';
COMMENT ON COLUMN feature_vectors.tdom_cos IS
    'cos(2*pi*trading_day_of_month/weekdays_in_month), same construction as tdom_sin. Phase 151.';
COMMENT ON COLUMN feature_vectors.minute_of_hour_sin IS
    'sin(2*pi*bar_ts.minute/60). Constant at 1h/1d by construction (minute is always 0). Phase 151.';
COMMENT ON COLUMN feature_vectors.minute_of_hour_cos IS
    'cos(2*pi*bar_ts.minute/60). Constant at 1h/1d by construction (minute is always 0). Phase 151.';
COMMENT ON COLUMN feature_vectors.momentum_z_velocity_fast IS
    'z-score of the rolling velocity (first difference) of momentum_z_fast over feature.momentum_velocity.window bars. Phase 151.';
COMMENT ON COLUMN feature_vectors.momentum_z_velocity_mid IS
    'z-score of the rolling velocity (first difference) of momentum_z_mid over feature.momentum_velocity.window bars. Phase 151.';
COMMENT ON COLUMN feature_vectors.momentum_z_velocity_slow IS
    'z-score of the rolling velocity (first difference) of momentum_z_slow over feature.momentum_velocity.window bars. Phase 151.';
COMMENT ON COLUMN feature_vectors.vwap_dev_sigma_velocity IS
    'z-score of the rolling velocity (first difference) of vwap_dev_sigma over feature.vwap_velocity.window bars. Phase 151.';

-- ---------------------------------------------------------------------------
-- 2. feature_registry: 10 new rows (tier='0_atomic', added_phase='151')
-- ---------------------------------------------------------------------------

INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready, requires_htf, status, added_phase)
VALUES
    ('quarter_cycle_sin', 'calendar', '0_atomic',
     'sin(2*pi*quarter_position)', 'bounded_signed', true, false, 'active', '151'),
    ('quarter_cycle_cos', 'calendar', '0_atomic',
     'cos(2*pi*quarter_position)', 'bounded_signed', true, false, 'active', '151'),
    ('tdom_sin', 'calendar', '0_atomic',
     'sin(2*pi*trading_day_of_month/weekdays_in_month)', 'bounded_signed', true, false, 'active', '151'),
    ('tdom_cos', 'calendar', '0_atomic',
     'cos(2*pi*trading_day_of_month/weekdays_in_month)', 'bounded_signed', true, false, 'active', '151'),
    ('minute_of_hour_sin', 'calendar', '0_atomic',
     'sin(2*pi*minute/60)', 'bounded_signed', true, false, 'active', '151'),
    ('minute_of_hour_cos', 'calendar', '0_atomic',
     'cos(2*pi*minute/60)', 'bounded_signed', true, false, 'active', '151'),
    ('momentum_z_velocity_fast', 'momentum', '0_atomic',
     'zscore(diff(momentum_z_fast))', 'z_scored', true, false, 'active', '151'),
    ('momentum_z_velocity_mid', 'momentum', '0_atomic',
     'zscore(diff(momentum_z_mid))', 'z_scored', true, false, 'active', '151'),
    ('momentum_z_velocity_slow', 'momentum', '0_atomic',
     'zscore(diff(momentum_z_slow))', 'z_scored', true, false, 'active', '151'),
    ('vwap_dev_sigma_velocity', 'volume', '0_atomic',
     'zscore(diff(vwap_dev_sigma))', 'z_scored', true, false, 'active', '151')
ON CONFLICT (feature_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. APR keys: feature.momentum_velocity.window, feature.vwap_velocity.window
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.momentum_velocity.window',
    'int',
    '14',
    2, 200,
    '[conventional] Bar-lag window for the first-difference-then-z-score construction behind momentum_z_velocity_fast/mid/slow. Seeded to match feature.vol_velocity.window''s live value (14). Phase 151. ML learning target: yes.'
),
(
    'feature.vwap_velocity.window',
    'int',
    '14',
    2, 200,
    '[conventional] Bar-lag window for vwap_dev_sigma_velocity. Separate key from feature.vol_velocity.window / feature.momentum_velocity.window per naming-system.md section 7 (semantically distinct family). Phase 151. ML learning target: yes.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.momentum_velocity.window', '14', 1),
    ('feature.vwap_velocity.window', '14', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.momentum_velocity.window', 1, '14', 'migration_287',
     'Seed momentum-velocity z-score window, Phase 151 [conventional]'),
    (NOW(), 'feature.vwap_velocity.window', 1, '14', 'migration_287',
     'Seed VWAP-velocity z-score window, Phase 151 [conventional]')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. Phase 170 parity: concept_registry/concept_gate mirror for this
--    migration's 10 rows (see header note above).
-- ---------------------------------------------------------------------------

INSERT INTO concept_registry
    (domain, name, description, status, enabled, group_name, is_control, control_expectation,
     added_phase, created_at, metadata)
SELECT
    'feature', fr.feature_name, fr.formula_short, fr.status, (fr.status = 'active'),
    fr.group_name, fr.is_control, fr.control_expectation, fr.added_phase, fr.added_at,
    jsonb_strip_nulls(jsonb_build_object(
        'tier', fr.tier, 'formula_short', fr.formula_short, 'normalization', fr.normalization,
        'linear_ready', fr.linear_ready, 'requires_htf', fr.requires_htf,
        'window_apr_keys', to_jsonb(fr.window_apr_keys), 'source_dims', to_jsonb(fr.source_dims),
        'notes', fr.notes, 'apr_namespace', 'feature.'
    ))
FROM feature_registry fr
WHERE fr.feature_name IN (
    'quarter_cycle_sin', 'quarter_cycle_cos', 'tdom_sin', 'tdom_cos',
    'minute_of_hour_sin', 'minute_of_hour_cos', 'momentum_z_velocity_fast',
    'momentum_z_velocity_mid', 'momentum_z_velocity_slow', 'vwap_dev_sigma_velocity'
)
ON CONFLICT (domain, name) DO NOTHING;

INSERT INTO concept_gate
    (concept_id, gate_metric_name, gate_eval_method, min_gate_metric, min_gate_n,
     fdr_required, fdr_alpha)
SELECT cr.concept_id, 'ic_sharpe_hac', 'bootstrap_ci', fr.min_ic_sharpe, fr.min_ic_n,
       fr.fdr_required, fr.fdr_alpha
FROM feature_registry fr
JOIN concept_registry cr ON cr.domain = 'feature' AND cr.name = fr.feature_name
WHERE fr.feature_name IN (
    'quarter_cycle_sin', 'quarter_cycle_cos', 'tdom_sin', 'tdom_cos',
    'minute_of_hour_sin', 'minute_of_hour_cos', 'momentum_z_velocity_fast',
    'momentum_z_velocity_mid', 'momentum_z_velocity_slow', 'vwap_dev_sigma_velocity'
)
ON CONFLICT (concept_id) DO NOTHING;

COMMIT;
