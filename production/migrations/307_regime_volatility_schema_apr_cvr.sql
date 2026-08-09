-- Migration 307: regime_volatility schema + APR keys + CVR namespace (Phase 172, plan 02).
--
-- 171-FINAL-VERDICT.md section 3's null-arm block-reliability control found only
-- realized_vol/vol_of_vol carry real, validated regime structure -- production's live
-- `regime` column has been a volatility partition wearing trend-direction names since before
-- that investigation started, not a defect this migration introduces. Section 5's recommended
-- design: ship `regime_volatility` as a standalone label built from realized_vol + vol_of_vol
-- only, GaussianHMM K=2 or K=3, honest calm/elevated/turbulent vocabulary, reusing the
-- already-built-and-tested walk-forward fitting fix unchanged. This migration lands the
-- schema/APR/CVR foundation only -- no compute path change, no corpus write. Phase 172 ships a
-- phased cutover: `regime_volatility` lands alongside the legacy `regime` column and
-- `regime_hmm` CVR namespace, both untouched, not a swap.
--
-- Block 1 (DDL): 8 new feature_vectors columns, one-for-one shape match with the existing
-- 8-column REGIME_WRITER_OWNED_COLUMN_NAMES family (regime + 3 prob + regime_prob + entropy +
-- duration + churn). All 3 probability columns (calm/elevated/turbulent) are added regardless
-- of the configured K -- at K=2, hmm_vol_prob_elevated simply stays NULL. This keeps the schema
-- stable across a future K=2/K=3 config change, so a K flip never requires a follow-up
-- migration.
--
-- Block 2 (APR): 4 new config_schema/config_state key pairs under alpha.hmm_volatility.*.
--   - alpha.hmm_volatility.n_components: [rca_analysis] both K=2 and K=3 cleared the
--     null-arm block-reliability control per 171-FINAL-VERDICT.md section 3; K=3 default
--     preserves the calm/elevated/turbulent framing per section 5's recommendation.
--   - alpha.hmm_volatility.vol_window: [rca_analysis] the realized-vol window, this axis's
--     ORDERING column (column 0 of the 2-column observation matrix, drives _build_label_map's
--     ascending calm->elevated->turbulent sort). +0.62 real-vs-null margin measured at
--     window 20 per 171-FINAL-VERDICT.md section 3's governing table.
--   - alpha.hmm_volatility.vol_of_vol_window: [rca_analysis] 171-FINAL-VERDICT.md section 6
--     explicitly flags this column's margin as window-dependent -- thin at the 20-bar window
--     used everywhere else in the investigation, solid from 60 bars up. Deliberately NOT
--     inherited from feature.hmm.obs_vol_of_vol_window (which is 20) -- that would repeat the
--     exact unexamined-inheritance mistake 172-RESEARCH.md Pitfall 1 warns against (assuming a
--     composite-model default transfers to a differently-validated axis). Default 60, the low
--     end of the "solid" range cited in section 6.
--   - alpha.hmm_volatility.covariance_type: [rca_analysis] GaussianHMM covariance_type per
--     171-FINAL-VERDICT.md section 5's model specification (2 observation dimensions,
--     covariance_type=full).
--
-- Deliberately NOT created: alpha.hmm_volatility.walk_forward.enabled. Migration 292's
-- alpha.hmm.walk_forward.enabled default-false gate exists because that code changes an
-- EXISTING live column's values -- landing the walk-forward code must not itself change any
-- existing feature_vectors.regime value. regime_volatility is a brand-new column with no
-- legacy corpus to protect; per 172-RESEARCH.md Pattern 3, the walk-forward path runs
-- unconditionally for it. Do not add this key back for symmetry with migration 292 -- there is
-- no dual-write-blend risk to gate against for a column that has never had any other writer.
--
-- Deliberately NOT created: new per-tf walk-forward schedule keys. The volatility path reuses
-- the existing alpha.hmm.walk_forward.refit_every_bars.<tf> / .initial_warmup_bars.<tf> keys
-- (migration 292) unchanged -- those are calibrated on bar density per refit window, a property
-- of the timeframe, not of which observation columns are fitted.
--
-- Deliberately NOT created: new keys for n_iter, min_hold_bars, churn_window,
-- min_state_occupation, full_cov_min_obs, min_obs_factor, or random_state. 171-FINAL-VERDICT.md
-- section 1 explicitly states these fitting-mechanics parameters were never implicated by the
-- investigation. The volatility path reuses the existing feature.hmm.* and
-- alpha.hmm.random_state keys unchanged. This enumeration is a recorded reuse decision, not an
-- omission.
--
-- Block 3 (CVR): new `regime_volatility` namespace, 3 codes (calm/elevated/turbulent). This is
-- a NEW namespace, not a repoint of the existing `regime_hmm` namespace (migration 233) --
-- entirely different taxonomy, and regime_hmm's existing rows describe the composite/trend
-- label set 171-FINAL-VERDICT.md retires. No vocabulary_group is seeded: a 3-code namespace
-- with a single ordinal axis (low/mid/high volatility) has no natural sub-grouping, and an
-- empty grouping layer would be complexity without a consumer.
--
-- All three blocks idempotent: DDL uses ADD COLUMN IF NOT EXISTS (migration 158's pattern);
-- APR uses ON CONFLICT (config_key) DO NOTHING (migration 292's pattern); CVR uses
-- ON CONFLICT (namespace, code) DO NOTHING (migration 233's pattern). Safe to re-run.

BEGIN;

-- ── Block 1: feature_vectors DDL ────────────────────────────────────────────────

ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS regime_volatility     TEXT,
    ADD COLUMN IF NOT EXISTS hmm_vol_prob_calm      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_prob_elevated  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_prob_turbulent DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_regime_prob    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_entropy        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_duration       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_churn          DOUBLE PRECISION;

-- ── Block 2: alpha.hmm_volatility.* APR keys ────────────────────────────────────

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.hmm_volatility.n_components',
    'int',
    '3',
    2, 3,
    '[rca_analysis] Phase 172: K for the volatility-only regime HMM (realized_vol, '
    'vol_of_vol). Both K=2 and K=3 cleared the null-arm block-reliability control per '
    '171-FINAL-VERDICT.md section 3; K=3 preserves the calm/elevated/turbulent framing per '
    'section 5''s recommended design. Not an ML learning target.'
),
(
    'alpha.hmm_volatility.vol_window',
    'int',
    '20',
    5, 500,
    '[rca_analysis] Phase 172: realized-vol rolling-std window for the volatility-only '
    'regime HMM. This is the axis''s ORDERING column (column 0 of the 2-column observation '
    'matrix, drives ascending calm->elevated->turbulent label sort). +0.62 real-vs-null '
    'margin measured at window 20 per 171-FINAL-VERDICT.md section 3''s governing result '
    'table. Not an ML learning target.'
),
(
    'alpha.hmm_volatility.vol_of_vol_window',
    'int',
    '60',
    5, 500,
    '[rca_analysis] Phase 172: vol-of-vol rolling-std window for the volatility-only regime '
    'HMM. 171-FINAL-VERDICT.md section 6 explicitly found this column''s real-vs-null margin '
    'is thin at window 20 (the value used everywhere else in the investigation) and solid '
    'from window 60 up. Deliberately NOT inherited from feature.hmm.obs_vol_of_vol_window '
    '(which is 20) -- that would repeat the unexamined-inheritance mistake 172-RESEARCH.md '
    'Pitfall 1 warns against. Default 60, the low end of the solid range. Not an ML learning '
    'target.'
),
(
    'alpha.hmm_volatility.covariance_type',
    'str',
    'full',
    NULL, NULL,
    '[rca_analysis] Phase 172: GaussianHMM covariance_type for the volatility-only regime '
    'HMM (2 observation dimensions: realized_vol, vol_of_vol) per 171-FINAL-VERDICT.md '
    'section 5''s recommended model specification. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.hmm_volatility.n_components', '3', 1),
('alpha.hmm_volatility.vol_window', '20', 1),
('alpha.hmm_volatility.vol_of_vol_window', '60', 1),
('alpha.hmm_volatility.covariance_type', 'full', 1)
ON CONFLICT (config_key) DO NOTHING;

-- ── Block 3: regime_volatility CVR namespace (3 codes, new namespace) ──────────
-- Does NOT touch, rename, or delete the existing regime_hmm namespace (migration 233).

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES
('regime_volatility', 'calm',      'Calm',      'Lowest realized-vol / vol-of-vol HMM state', 1),
('regime_volatility', 'elevated',  'Elevated',  'Middle realized-vol / vol-of-vol HMM state (K=3 only)', 2),
('regime_volatility', 'turbulent', 'Turbulent', 'Highest realized-vol / vol-of-vol HMM state', 3)
ON CONFLICT (namespace, code) DO NOTHING;

COMMIT;
