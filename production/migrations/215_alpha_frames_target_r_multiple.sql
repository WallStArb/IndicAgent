-- Migration 215: snapshot target_r_multiple onto alpha_frames + bootstrap seed APR key
-- (Phase 142B code-review CR-02 + WR-01)
--
-- CR-02: alpha_frames already snapshots stop_atr_mult and cost_r onto every row explicitly so
-- they can never silently drift from historical truth on a later APR recalibration (migration
-- 214's own column comments state this reasoning for cost_r). target_r_multiple received no
-- such treatment: AlphaFrameWriter used its load-time APR value to compute gross_expected_r/
-- net_expected_r but never persisted it, so CounterfactualTracker re-read
-- alpha.frame.target_r_multiple live at scan time -- a mid-lifecycle recalibration between an
-- AlphaFrameWriter run and a later CounterfactualTracker run would silently desync the
-- expected-R diagnostics from the actual target_price/r_multiple/counterfactual_pnl_r used for
-- scoring. This migration closes that gap by mirroring the stop_atr_mult pattern exactly.
--
-- WR-01: frame_gate_passes' scipy.stats.bootstrap call had no random_state, making the
-- "frozen, no post-hoc renegotiation" FRAME-04 gate verdict non-reproducible across identical
-- re-runs. Seeds it per this project's APR seed convention (mirrors alpha.hmm.random_state).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS / ON CONFLICT DO NOTHING. Safe to re-run. alpha_frames
-- is empty as of this migration (no backfill has run yet), so no backfill UPDATE is needed for
-- existing rows.

BEGIN;

ALTER TABLE alpha_frames ADD COLUMN IF NOT EXISTS target_r_multiple double precision;

COMMENT ON COLUMN alpha_frames.target_r_multiple IS
    'APR snapshot at creation: alpha.frame.target_r_multiple. Mirrors stop_atr_mult -- read '
    'back unchanged by CounterfactualTracker instead of re-deriving live from APR at scan '
    'time, so target_price/r_multiple/counterfactual_pnl_r never silently desync from the '
    'gross_expected_r/net_expected_r diagnostics computed at frame-creation time under this '
    'same value (Phase 142B code-review CR-02).';

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES (
    'alpha.scoring.bootstrap_random_state',
    'int',
    '42',
    '[initial_estimate] FRAME-04: seeds scipy.stats.bootstrap''s BCa resampling in '
    'frame_gate_passes so the frozen "no post-hoc gate renegotiation" verdict is reproducible '
    'across identical re-runs. Changing this key invalidates any prior gate verdict for cells '
    'that used the BCa path (day-clusters <= alpha.scoring.bootstrap_max_n). NOT an ML '
    'learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.scoring.bootstrap_random_state', '42', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
