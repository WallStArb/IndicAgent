-- Migration 346: ITR materiality evidence columns, instrument_tags_active view,
-- materiality APR keys (Phase 175, todo 380; folds in todos 125 and 126).
--
-- Every block in this file is idempotent -- safe to re-run.
--
-- Block 1: eleven Pass 4 partial-loading evidence columns on instrument_tags, plus the
--   discovery_state/first_measured_at JSONB->column promotion (todo 125).
-- Block 2: a table-scoped CHECK constraint on discovery_state.
-- Block 3: instrument_tags_active view -- the required read path for unexpired rows (todo 126).
-- Block 4/5: eleven alpha.tag_calibrator.materiality.* APR keys, seeded across all three
--   config_schema/config_state/config_history tables (migration 230's pattern).
--
-- Note: PostgreSQL requires '' to escape a literal apostrophe inside a single-quoted string --
-- see the description/reason strings in Block 4/5 below.

BEGIN;

-- ── Block 1: instrument_tags evidence columns ─────────────────────────────────

ALTER TABLE instrument_tags
    ADD COLUMN IF NOT EXISTS partial_loading           double precision,
    ADD COLUMN IF NOT EXISTS partial_loading_ci_low    double precision,
    ADD COLUMN IF NOT EXISTS incremental_r2            double precision,
    ADD COLUMN IF NOT EXISTS sign_stable_windows       integer,
    ADD COLUMN IF NOT EXISTS sign_stable_windows_total integer,
    ADD COLUMN IF NOT EXISTS null_arm_p_value          double precision,
    ADD COLUMN IF NOT EXISTS null_arm_bh_p             double precision,
    ADD COLUMN IF NOT EXISTS materiality_sample_n      integer,
    ADD COLUMN IF NOT EXISTS passes_materiality        boolean,
    ADD COLUMN IF NOT EXISTS discovery_state           text,
    ADD COLUMN IF NOT EXISTS first_measured_at         timestamptz;

COMMENT ON COLUMN instrument_tags.partial_loading IS
    'Pass 4: OLS beta of the (symbol, tag) loading after orthogonalizing against the control '
    'factor set (control_factor_series). The materiality-filtered replacement for a raw, '
    'unconditioned loading.';
COMMENT ON COLUMN instrument_tags.partial_loading_ci_low IS
    'Pass 4: lower bound of the confidence interval around partial_loading (Codex''s R-05 '
    'lower-CI gate). A real column and a real gate, not dropped.';
COMMENT ON COLUMN instrument_tags.incremental_r2 IS
    'Pass 4: incremental R-squared contributed by this tag''s factor_series beyond the '
    'control set alone -- the explanatory-power component of the materiality gate.';
COMMENT ON COLUMN instrument_tags.sign_stable_windows IS
    'Pass 4: count of rolling measurement windows (out of sign_stable_windows_total) in which '
    'partial_loading''s sign matched the run-level sign -- the D-06 sign-stability component.';
COMMENT ON COLUMN instrument_tags.sign_stable_windows_total IS
    'Pass 4: total number of rolling measurement windows evaluated for sign stability. '
    'Denominator for sign_stable_windows.';
COMMENT ON COLUMN instrument_tags.null_arm_p_value IS
    'Pass 4: raw p-value from the D-06 circular-shift null-arm control for this (symbol, tag) '
    'pair, before BH-FDR adjustment.';
COMMENT ON COLUMN instrument_tags.null_arm_bh_p IS
    'Pass 4: Benjamini-Hochberg run-level FDR-adjusted null_arm_p_value.';
COMMENT ON COLUMN instrument_tags.materiality_sample_n IS
    'Pass 4''s own post-control-alignment observation count -- distinct from sample_n, which '
    'is Pass 1''s bivariate alignment count. The two counts measure different alignments and '
    'must not be conflated.';
COMMENT ON COLUMN instrument_tags.passes_materiality IS
    'Pass 4: the STATISTICAL gate only (R-04). Readers MUST additionally AND this with '
    'discovery_state = ''confirmed'' (the temporal gate, todo 125) and valid_to IS NULL (the '
    'expiry gate, todo 126) -- the three gates are stored separately, not collapsed, so a '
    'future per-consumer cutover can calibrate its own bar.';
COMMENT ON COLUMN instrument_tags.discovery_state IS
    'todo 125: typed promotion of the discovery-state concept out of the evidence JSONB blob. '
    'NULL until TagCalibrator''s next run backfills it; otherwise ''pending_oos'' or '
    '''confirmed''. The temporal gate referenced by passes_materiality''s comment (R-04).';
COMMENT ON COLUMN instrument_tags.first_measured_at IS
    'todo 125: typed promotion of the first-measurement timestamp out of the evidence JSONB '
    'blob -- the anchor discovery_oos_days counts forward from.';

-- ── Block 2: discovery_state CHECK constraint (table-scoped guard) ───────────
--
-- ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS is not supported by PostgreSQL for CHECK
-- constraints, so this is guarded manually. The conrelid predicate is load-bearing and must
-- not be dropped: pg_constraint.conname is unique per table, not database-wide, so a
-- same-named constraint sitting on some unrelated table would otherwise satisfy a
-- name-only NOT EXISTS guard and make this block silently skip creating the constraint it
-- exists to create. NULL must remain permitted -- every existing row has NULL until
-- TagCalibrator's next run backfills it.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'instrument_tags_discovery_state_check'
          AND conrelid = 'instrument_tags'::regclass
    ) THEN
        ALTER TABLE instrument_tags
            ADD CONSTRAINT instrument_tags_discovery_state_check
            CHECK (discovery_state IS NULL OR discovery_state IN ('pending_oos', 'confirmed'));
    END IF;
END $$;

-- ── Block 3: instrument_tags_active view (todo 126) ───────────────────────────

CREATE OR REPLACE VIEW instrument_tags_active AS
    SELECT * FROM instrument_tags WHERE valid_to IS NULL;

COMMENT ON VIEW instrument_tags_active IS
    'todo 126: the required read path for any tag-membership query. Returns only unexpired '
    '(valid_to IS NULL) instrument_tags rows.';

-- ── Block 4: eleven alpha.tag_calibrator.materiality.* APR keys ───────────────
--
-- 3-table seed pattern (config_schema / config_state / config_history), migration 230's
-- pattern. Ten keys carry Codex's conservative proposed defaults (D-05 -- not averaged
-- across Codex/Fable/AGY into a synthesized-but-unvalidated middle value, D-04), tagged
-- initial_estimate below. null_arm_seed is tagged conventional below (this project's
-- standing default RNG seed, not an uncalibrated statistical estimate).

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.tag_calibrator.materiality.min_partial_loading',
    'float',
    '0.35',
    0.0, 1.0,
    '[initial_estimate] Minimum absolute partial_loading (OLS beta after control-set '
    'orthogonalization) required to pass the Pass 4 materiality gate. Proposed by Codex; NOT '
    're-derived against this corpus''s actual partial-loading distribution. See '
    'docs/foundation/apr-calibration-backlog.md.'
),
(
    'alpha.tag_calibrator.materiality.min_partial_loading_ci_low',
    'float',
    '0.20',
    0.0, 1.0,
    '[initial_estimate] Minimum lower-CI bound on partial_loading (R-05, Codex''s lower-CI '
    'gate) required to pass the Pass 4 materiality gate. Proposed by Codex; NOT re-derived '
    'against this corpus''s actual partial-loading distribution. See '
    'docs/foundation/apr-calibration-backlog.md.'
),
(
    'alpha.tag_calibrator.materiality.min_incremental_r2',
    'float',
    '0.05',
    0.0, 1.0,
    '[initial_estimate] Minimum incremental_r2 (explanatory power beyond the control set '
    'alone) required to pass the Pass 4 materiality gate. Proposed by Codex; NOT re-derived '
    'against this corpus''s actual partial-loading distribution. See '
    'docs/foundation/apr-calibration-backlog.md.'
),
(
    'alpha.tag_calibrator.materiality.min_sample_n',
    'int',
    '756',
    60, 5000,
    '[initial_estimate] Minimum materiality_sample_n (Pass 4''s own post-control-alignment '
    'observation count) required before a (symbol, tag) partial loading is measured at all. '
    'Proposed by Codex; NOT re-derived against this corpus''s actual partial-loading '
    'distribution. See docs/foundation/apr-calibration-backlog.md.'
),
(
    'alpha.tag_calibrator.materiality.sign_stability_window_days',
    'int',
    '252',
    60, 1260,
    '[initial_estimate] Length in trading days of each rolling window used for the D-06 '
    'sign-stability measurement. Proposed by Codex; NOT re-derived against this corpus''s '
    'actual partial-loading distribution. See docs/foundation/apr-calibration-backlog.md.'
),
(
    'alpha.tag_calibrator.materiality.sign_stability_window_count',
    'int',
    '4',
    2, 12,
    '[initial_estimate] Number of rolling sign_stability_window_days windows evaluated for '
    'sign stability (sign_stable_windows_total). Proposed by Codex; NOT re-derived against '
    'this corpus''s actual partial-loading distribution. See '
    'docs/foundation/apr-calibration-backlog.md.'
),
(
    'alpha.tag_calibrator.materiality.min_sign_stable_windows',
    'int',
    '3',
    1, 12,
    '[initial_estimate] Minimum sign_stable_windows (out of sign_stability_window_count) '
    'required to pass the Pass 4 materiality gate. Proposed by Codex; NOT re-derived against '
    'this corpus''s actual partial-loading distribution. See '
    'docs/foundation/apr-calibration-backlog.md.'
),
(
    'alpha.tag_calibrator.materiality.null_arm_alpha',
    'float',
    '0.05',
    0.001, 0.25,
    '[initial_estimate] BH-FDR alpha applied to the D-06 circular-shift null-arm p-vector '
    '(null_arm_p_value -> null_arm_bh_p), mirroring the project''s standing '
    'alpha.tag_calibrator.fdr_alpha=0.05 convention. Proposed by Codex; NOT re-derived '
    'against this corpus''s actual partial-loading distribution. See '
    'docs/foundation/apr-calibration-backlog.md.'
),
(
    'alpha.tag_calibrator.materiality.null_arm_draws',
    'int',
    '1000',
    100, 10000,
    '[initial_estimate] Monte-Carlo draw count for the D-06 circular-shift null-arm control. '
    'A cost/resolution knob -- the floor of 100 means the smallest resolvable p-value is '
    '1/101. Proposed by Codex; NOT re-derived against this corpus''s actual partial-loading '
    'distribution. See docs/foundation/apr-calibration-backlog.md.'
),
(
    'alpha.tag_calibrator.materiality.null_arm_seed',
    'int',
    '42',
    0, 2147483647,
    '[conventional] Base seed mixed with a per-(symbol, tag) hash to derive each pair''s D-06 '
    'circular-shift null generator. 42 is this project''s standing default RNG seed '
    '(HMM_RANDOM_STATE), not an uncalibrated statistical estimate. WARNING: changing this '
    'value invalidates every previously computed null_arm_p_value/null_arm_bh_p in '
    'instrument_tags. Exists so an operator can test seed sensitivity or force '
    're-randomization without a code edit. Not routed to '
    'docs/foundation/apr-calibration-backlog.md -- not a gate-shaped threshold awaiting '
    'corpus calibration.'
),
(
    'alpha.tag_calibrator.materiality.control_factor_series',
    'json',
    '["SPY","TLT","HYG-IEF","UUP"]',
    NULL, NULL,
    '[initial_estimate] R-03: the orthogonalization control set used to compute '
    'partial_loading/incremental_r2. Four legs only, no DBC commodity leg: SPY (broad equity), '
    'TLT (rates), HYG-IEF (credit), UUP (dollar). No commodity-broad leg is wired today '
    'because commodity_broad has measurement_type=''definitional'' with no factor_series; DBC '
    'is the pre-identified candidate to append here (an APR edit, not a code change or a '
    'tag_vocabulary mutation) if the shadow diagnostic surfaces commodity-cycle confounding.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.tag_calibrator.materiality.min_partial_loading', '0.35', 1),
    ('alpha.tag_calibrator.materiality.min_partial_loading_ci_low', '0.20', 1),
    ('alpha.tag_calibrator.materiality.min_incremental_r2', '0.05', 1),
    ('alpha.tag_calibrator.materiality.min_sample_n', '756', 1),
    ('alpha.tag_calibrator.materiality.sign_stability_window_days', '252', 1),
    ('alpha.tag_calibrator.materiality.sign_stability_window_count', '4', 1),
    ('alpha.tag_calibrator.materiality.min_sign_stable_windows', '3', 1),
    ('alpha.tag_calibrator.materiality.null_arm_alpha', '0.05', 1),
    ('alpha.tag_calibrator.materiality.null_arm_draws', '1000', 1),
    ('alpha.tag_calibrator.materiality.null_arm_seed', '42', 1),
    ('alpha.tag_calibrator.materiality.control_factor_series', '["SPY","TLT","HYG-IEF","UUP"]', 1)
ON CONFLICT (config_key) DO NOTHING;

-- ── Block 5: config_history provenance (mandatory -- APR requires every parameter write to
-- be recorded with changed_by and reason; a key seeded into config_schema/config_state alone
-- has no provenance record at all) ────────────────────────────────────────────
--
-- config_history's primary key is (timestamp, config_key, version) -- timestamp is part of
-- the key, so a literal `VALUES (NOW(), ...) ON CONFLICT DO NOTHING` can never actually
-- conflict across two separate invocations of this file (each invocation gets its own NOW()),
-- silently duplicating all 11 provenance rows on every re-run. Guarded with an explicit
-- WHERE NOT EXISTS per (config_key, changed_by) instead, so a second run of this migration
-- inserts zero additional rows.

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT * FROM (VALUES
    (NOW(), 'alpha.tag_calibrator.materiality.min_partial_loading', 1, '0.35', 'migration_346',
        'Initial value: minimum absolute partial_loading for the Pass 4 materiality gate [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.materiality.min_partial_loading_ci_low', 1, '0.20', 'migration_346',
        'Initial value: minimum lower-CI bound on partial_loading (R-05 lower-CI gate) [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.materiality.min_incremental_r2', 1, '0.05', 'migration_346',
        'Initial value: minimum incremental R-squared for the Pass 4 materiality gate [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.materiality.min_sample_n', 1, '756', 'migration_346',
        'Initial value: minimum materiality_sample_n before a partial loading is measured [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.materiality.sign_stability_window_days', 1, '252', 'migration_346',
        'Initial value: length in trading days of each D-06 sign-stability rolling window [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.materiality.sign_stability_window_count', 1, '4', 'migration_346',
        'Initial value: number of rolling windows evaluated for sign stability [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.materiality.min_sign_stable_windows', 1, '3', 'migration_346',
        'Initial value: minimum sign-stable windows required for the Pass 4 materiality gate [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.materiality.null_arm_alpha', 1, '0.05', 'migration_346',
        'Initial value: BH-FDR alpha applied to the D-06 circular-shift null-arm p-vector [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.materiality.null_arm_draws', 1, '1000', 'migration_346',
        'Initial value: Monte-Carlo draw count for the D-06 circular-shift null-arm control [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.materiality.null_arm_seed', 1, '42', 'migration_346',
        'Initial value: base RNG seed for the D-06 circular-shift null arm [conventional]'),
    (NOW(), 'alpha.tag_calibrator.materiality.control_factor_series', 1, '["SPY","TLT","HYG-IEF","UUP"]', 'migration_346',
        'Initial value: R-03 orthogonalization control set (SPY/TLT/HYG-IEF/UUP) [initial_estimate]')
) AS v(timestamp, config_key, version, config_value, changed_by, reason)
WHERE NOT EXISTS (
    SELECT 1 FROM config_history ch
    WHERE ch.config_key = v.config_key AND ch.changed_by = v.changed_by
);

COMMIT;
