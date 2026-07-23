-- Migration 253: alpha.frame.* / alpha.ensemble_ic.* APR seeds for Phase 166
-- Frame/Execution Recalibration (scalar candidate + structural candidate Part 1)
--
-- Phase 148's Gate 2 (execution proof) FAILED while Gate 1 (signal proof) PASSED
-- (docs/plans/2026-07-22-phase148-promotion-decision.md). D-02's confirmed baseline: the
-- current `alpha.frame.stop_atr_mult`/`alpha.frame.target_r_multiple` scalars (migration
-- 205/214, '1.5'/'2.0') are single GLOBAL [initial_estimate] values, never conditioned on
-- (regime, tf), never revisited since Phase 142B -- unlike `alpha.frame.hold_max_bars.<regime>.<tf>`,
-- which IS already empirically calibrated (EIC-02, migration 195, CR-02 champion-gated).
-- This migration seeds the fresh APR namespace both Phase 166 candidates need to close that gap:
--
--   Section 1: 72 per-(regime,tf) scalar-candidate keys (36 `stop_atr_mult` + 36
--   `target_r_multiple`), seeded at the current global values as a starting point --
--   overwritten by a future `_calibrate_stop_target()` (EIC-scalar sibling to
--   `_calibrate_hold_max_bars`) run against the champion `weight_version`.
--
--   Section 2: 3 `alpha.ensemble_ic.*` calibration-selection params read by that future
--   `_calibrate_stop_target()` run -- percentile-of-rescaled-MAE/MFE selection criterion
--   (RESEARCH.md Finding 1 / Pitfall 1: NOT a literal decay-threshold-walk copy, since
--   stop/target are distance/reward-ratio parameters with no IC-decay-curve analog).
--
--   Section 3: 7 structural-confluence thresholds for the structural candidate Part 1 --
--   a new v3-native port of `zone_engine.py`'s 3-tier confluence-resolution architecture
--   (cluster/dedup/score core), populated only with Phase-163-owned VP/S-R fields. Namespace
--   discipline (RESEARCH.md Finding 5): these are FRESH `alpha.frame.*` keys, not a reuse of
--   the archived plugin-tier's own already-migrated key families for the same concepts
--   (module-level defaults for cluster radius / zone buffer / min width / strength+proximity
--   weights) -- this phase's candidate is data-limited to a narrower (VP+S-R only) source
--   universe than the archived toolkit's full ~14-source spec table, so several thresholds
--   are seeded independently rather than copied verbatim (documented per-key below).
--
--   Section 4: `alpha.frame.geometry_source` -- the switch a later Phase 166 plan flips to
--   regenerate each candidate's frame population. Default 'global' preserves current
--   AlphaFrameWriter behavior unconditionally (backward-compatible, additive migration).
--
-- Phase 163 ("VP/SR Structural Primitives") is a real Wave-0 prerequisite for the structural
-- candidate's runtime (its columns exist in schema but are 100% NULL until it executes) --
-- this migration itself has no dependency on Phase 163 (pure APR seed, no data read).

BEGIN;

-- -------------------------------------------------------------------------
-- Section 1: alpha.frame.stop_atr_mult.<regime>.<tf> / alpha.frame.target_r_multiple.<regime>.<tf>
-- APR seeds (72 keys: 36 + 36). 9 LIVE market_regimes.regime_label values x 4 TFs, same
-- namespace shape as migration 195's alpha.frame.hold_max_bars.<regime>.<tf> loop. Seeded at
-- the current global scalar values ('1.5'/'2.0', migration 205/214) as a conservative
-- starting point; a future scalar-candidate calibration run (mirrors EIC-02's
-- _calibrate_hold_max_bars, CR-02 champion-weight_version gated) overwrites per-cell.
-- -------------------------------------------------------------------------

DO $$
DECLARE
    regimes text[] := ARRAY[
        'high_bear', 'high_bull', 'high_neutral',
        'low_bear', 'low_bull', 'low_neutral',
        'mid_bear', 'mid_bull', 'mid_neutral'
    ];
    tfs text[] := ARRAY['5m', '15m', '1h', '1d'];
    r text;
    t text;
    stop_key text;
    target_key text;
BEGIN
    FOREACH r IN ARRAY regimes LOOP
        FOREACH t IN ARRAY tfs LOOP
            stop_key := 'alpha.frame.stop_atr_mult.' || r || '.' || t;
            target_key := 'alpha.frame.target_r_multiple.' || r || '.' || t;

            INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
            VALUES (
                stop_key, 'float', '1.5', 0.1, 10.0,
                '[initial_estimate] Phase 166 scalar candidate: per-(regime,tf) stop-loss '
                'distance in ATR multiples. Seeded at the current global alpha.frame.stop_atr_mult '
                '(migration 214) value as a starting point -- overwritten by _calibrate_stop_target '
                '(EIC-scalar) after first champion weight_version run. NOT an ML learning target. '
                'Regime=' || r || ', TF=' || t || '.'
            )
            ON CONFLICT (config_key) DO NOTHING;

            INSERT INTO config_state (config_key, config_value, version)
            VALUES (stop_key, '1.5', 1)
            ON CONFLICT (config_key) DO NOTHING;

            INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
            VALUES (
                NOW(), stop_key, 1, '1.5', 'migration_253',
                'Seed per-(regime,tf) stop_atr_mult at current global value pending EIC-scalar '
                'calibration (Phase 166 D-02) [initial_estimate]'
            )
            ON CONFLICT DO NOTHING;

            INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
            VALUES (
                target_key, 'float', '2.0', 0.1, 20.0,
                '[initial_estimate] Phase 166 scalar candidate: per-(regime,tf) target R-multiple '
                '(reward:risk ratio) applied on top of the ATR-derived stop distance. Seeded at the '
                'current global alpha.frame.target_r_multiple (migration 214) value as a starting '
                'point -- overwritten by _calibrate_stop_target (EIC-scalar) after first champion '
                'weight_version run. NOT an ML learning target. Regime=' || r || ', TF=' || t || '.'
            )
            ON CONFLICT (config_key) DO NOTHING;

            INSERT INTO config_state (config_key, config_value, version)
            VALUES (target_key, '2.0', 1)
            ON CONFLICT (config_key) DO NOTHING;

            INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
            VALUES (
                NOW(), target_key, 1, '2.0', 'migration_253',
                'Seed per-(regime,tf) target_r_multiple at current global value pending EIC-scalar '
                'calibration (Phase 166 D-02) [initial_estimate]'
            )
            ON CONFLICT DO NOTHING;
        END LOOP;
    END LOOP;
END $$;

-- -------------------------------------------------------------------------
-- Section 2: alpha.ensemble_ic.* scalar-candidate calibration-selection params (3 keys),
-- read by the future _calibrate_stop_target() run this migration's Section 1 keys anticipate.
-- Percentile-of-rescaled-MAE/MFE selection criterion (RESEARCH.md Finding 1): the uncensored
-- MAE distribution among closed_target frames informs stop placement, the uncensored MFE
-- distribution among closed_max_hold frames informs target placement (088 censoring caveat).
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ensemble_ic.stop_mae_percentile',
    'float',
    '90.0',
    50.0, 99.0,
    '[initial_estimate] Phase 166 scalar candidate: percentile of the uncensored (closed_target-'
    'only, per 088/RESEARCH.md Finding 1) MAE distribution used to place the per-(regime,tf) '
    'stop_atr_mult. Higher percentile = wider stop, fewer premature stop-outs on normal '
    'adverse-excursion noise. NOT an ML learning target.'
),
(
    'alpha.ensemble_ic.target_mfe_percentile',
    'float',
    '50.0',
    10.0, 90.0,
    '[initial_estimate] Phase 166 scalar candidate: percentile of the uncensored (closed_max_hold-'
    'only) MFE distribution used to place the per-(regime,tf) target_r_multiple. Median (50th) '
    'as a starting point -- the typical favorable excursion among frames that survived to the '
    'hold-bars ceiling without hitting stop or target. NOT an ML learning target.'
),
(
    'alpha.ensemble_ic.stop_target_min_qualifying_symbols',
    'int',
    '3',
    1.0, 80.0,
    '[initial_estimate] Phase 166 scalar candidate: minimum number of qualifying symbols '
    'required in a (regime,tf) cell before _calibrate_stop_target writes a median value for '
    'that cell -- mirrors the qualifying-cells sufficiency gate pattern already applied to '
    'hold_max_bars calibration (EIC-02). Cells below this floor are SKIPPED (prior APR value '
    'stays authoritative), never fall back to a fabricated default.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ensemble_ic.stop_mae_percentile', '90.0', 1),
    ('alpha.ensemble_ic.target_mfe_percentile', '50.0', 1),
    ('alpha.ensemble_ic.stop_target_min_qualifying_symbols', '3', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ensemble_ic.stop_mae_percentile', 1, '90.0', 'migration_253',
     'Seed stop-placement MAE percentile selection criterion, Phase 166 D-02 [initial_estimate]'),
    (NOW(), 'alpha.ensemble_ic.target_mfe_percentile', 1, '50.0', 'migration_253',
     'Seed target-placement MFE percentile selection criterion, Phase 166 D-02 [initial_estimate]'),
    (NOW(), 'alpha.ensemble_ic.stop_target_min_qualifying_symbols', 1, '3', 'migration_253',
     'Seed minimum qualifying-symbols sufficiency floor for stop/target calibration, mirrors '
     'EIC-02 hold_max_bars sufficiency gate [initial_estimate]')
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------------------------
-- Section 3: alpha.frame.* structural-confluence thresholds (7 keys) for the structural
-- candidate Part 1 -- a new v3-native port of the archived plugin tier's confluence-
-- resolution clustering/scoring architecture, populated only with Phase-163-owned VP/S-R
-- candidate sources (2026-07-23 D-06 scope resolution). Fresh alpha.frame.* namespace only
-- (RESEARCH.md Finding 5) -- these are NOT a reuse of the archived plugin tier's own
-- already-migrated key families for the analogous concepts. Where a numeric default is
-- carried over from the archived module's current constant it is noted below; two thresholds
-- (zone_buffer_atr, min_width_atr) are seeded independently, narrower than the archived
-- module's own defaults, appropriate to this candidate's smaller (VP+S-R only, not the full
-- ~14-source spec table) candidate universe.
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.frame.cluster_radius_atr',
    'float',
    '0.5',
    0.05, 5.0,
    '[initial_estimate] Phase 166 structural candidate Part 1: ATR radius within which two '
    'structural candidates (VP POC/VAH/VAL, S/R) are grouped into one confluence cluster. '
    'Carried over from the archived confluence-scoring module''s equivalent constant (same '
    'value, narrower source universe). NOT an ML learning target.'
),
(
    'alpha.frame.single_level_radius_atr',
    'float',
    '0.25',
    0.05, 3.0,
    '[initial_estimate] Phase 166 structural candidate Part 1: ATR radius used when scoring a '
    'single (non-clustered) structural candidate as the fallback tier. Carried over from the '
    'archived confluence-scoring module''s equivalent constant (same value). NOT an ML '
    'learning target.'
),
(
    'alpha.frame.zone_buffer_atr',
    'float',
    '0.1',
    0.0, 1.0,
    '[initial_estimate] Phase 166 structural candidate Part 1: ATR buffer added around a '
    'resolved confluence zone''s outer bounds before deriving a stop/target price. Seeded '
    'narrower than the archived confluence-scoring module''s equivalent constant -- this '
    'candidate''s smaller (VP+S-R only) source universe produces tighter, less noisy clusters '
    'than the archived module''s full multi-source candidate table. NOT an ML learning target.'
),
(
    'alpha.frame.min_width_atr',
    'float',
    '0.05',
    0.0, 2.0,
    '[initial_estimate] Phase 166 structural candidate Part 1: minimum confluence-zone width '
    'in ATR below which the zone is treated as a single point rather than a range. Seeded '
    'narrower than the archived confluence-scoring module''s equivalent constant, consistent '
    'with this candidate''s smaller (VP+S-R only) source universe and correspondingly tighter '
    'expected cluster widths. NOT an ML learning target.'
),
(
    'alpha.frame.strength_weight',
    'float',
    '0.6',
    0.0, 1.0,
    '[initial_estimate] Phase 166 structural candidate Part 1: weight on candidate strength '
    '(vs. proximity) when scoring the single-best-candidate fallback tier. Carried over from '
    'the archived confluence-scoring module''s equivalent constant (same value). Paired with '
    'alpha.frame.proximity_weight; not independently bounds-checked to sum to 1.0. NOT an ML '
    'learning target.'
),
(
    'alpha.frame.proximity_weight',
    'float',
    '0.4',
    0.0, 1.0,
    '[initial_estimate] Phase 166 structural candidate Part 1: weight on candidate proximity-'
    'to-entry (vs. strength) when scoring the single-best-candidate fallback tier. Carried '
    'over from the archived confluence-scoring module''s equivalent constant (same value). '
    'Paired with alpha.frame.strength_weight. NOT an ML learning target.'
),
(
    'alpha.frame.structure_snap_proximity_atr',
    'float',
    '1.5',
    0.1, 5.0,
    '[initial_estimate] Phase 166 structural candidate Part 1: maximum ATR distance between '
    'the ATR-fallback stop/target price and a resolved structural confluence level for the '
    'candidate to "snap" to that structural level instead of the pure-ATR price. Migrated as a '
    'proper fresh alpha.frame.* APR key per this phase''s Migrate-as-you-go rule (D-03.2) -- '
    'not a reuse of the archived plugin tier''s already-migrated analogous key for the same '
    'concept. NOT an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.frame.cluster_radius_atr', '0.5', 1),
    ('alpha.frame.single_level_radius_atr', '0.25', 1),
    ('alpha.frame.zone_buffer_atr', '0.1', 1),
    ('alpha.frame.min_width_atr', '0.05', 1),
    ('alpha.frame.strength_weight', '0.6', 1),
    ('alpha.frame.proximity_weight', '0.4', 1),
    ('alpha.frame.structure_snap_proximity_atr', '1.5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.frame.cluster_radius_atr', 1, '0.5', 'migration_253',
     'Seed structural candidate Part 1 cluster radius, Phase 166 D-03.2/D-06 [initial_estimate]'),
    (NOW(), 'alpha.frame.single_level_radius_atr', 1, '0.25', 'migration_253',
     'Seed structural candidate Part 1 single-level radius, Phase 166 D-03.2/D-06 [initial_estimate]'),
    (NOW(), 'alpha.frame.zone_buffer_atr', 1, '0.1', 'migration_253',
     'Seed structural candidate Part 1 zone buffer, Phase 166 D-03.2/D-06 [initial_estimate]'),
    (NOW(), 'alpha.frame.min_width_atr', 1, '0.05', 'migration_253',
     'Seed structural candidate Part 1 minimum zone width, Phase 166 D-03.2/D-06 [initial_estimate]'),
    (NOW(), 'alpha.frame.strength_weight', 1, '0.6', 'migration_253',
     'Seed structural candidate Part 1 strength weight, Phase 166 D-03.2/D-06 [initial_estimate]'),
    (NOW(), 'alpha.frame.proximity_weight', 1, '0.4', 'migration_253',
     'Seed structural candidate Part 1 proximity weight, Phase 166 D-03.2/D-06 [initial_estimate]'),
    (NOW(), 'alpha.frame.structure_snap_proximity_atr', 1, '1.5', 'migration_253',
     'Seed structural candidate Part 1 structure-snap proximity threshold as a proper APR key '
     '(Migrate-as-you-go), Phase 166 D-03.2 [initial_estimate]')
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------------------------
-- Section 4: alpha.frame.geometry_source selector (1 key) -- the switch a later Phase 166
-- plan flips per-candidate to regenerate each candidate's frame population. Default 'global'
-- preserves current AlphaFrameWriter behavior unconditionally (backward-compatible, additive).
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, allowed_values, description)
VALUES
(
    'alpha.frame.geometry_source',
    'str',
    'global',
    '{global,per_cell_scalar,structural}',
    '[initial_estimate] Phase 166: selects which stop/target geometry AlphaFrameWriter derives '
    'per frame. "global" = current behavior, the single alpha.frame.stop_atr_mult/'
    'target_r_multiple scalars (backward-compatible, unconditional default). '
    '"per_cell_scalar" = the scalar candidate''s alpha.frame.stop_atr_mult.<regime>.<tf>/'
    'alpha.frame.target_r_multiple.<regime>.<tf> keys (Section 1). "structural" = the '
    'structural candidate Part 1''s confluence-resolved VP/S-R geometry (Section 3), falling '
    'back to ATR when no confluence level resolves. NOT an ML learning target -- an '
    'operator-visible switch flipped explicitly per candidate evaluation run.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.frame.geometry_source', 'global', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.frame.geometry_source', 1, 'global', 'migration_253',
    'Seed geometry-source selector defaulting to current AlphaFrameWriter behavior '
    '(backward-compatible), Phase 166 D-01 [initial_estimate]'
)
ON CONFLICT DO NOTHING;

COMMIT;
