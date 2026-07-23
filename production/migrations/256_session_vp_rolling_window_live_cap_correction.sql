-- Migration 256: correct feature.session_vp.rolling_window's description
--
-- Code review finding CR-02 (163-REVIEW.md): migration 255 seeded this key's description
-- claiming "this phase's stateless bars[-N:] slicing genuinely reaches the full 480-bar
-- window (D-18)" -- true for the batch/backfill path (which reads unbounded history from
-- market_data_ohlcv_tradeable), but false for the live path. FeatureVectorPipeline's
-- self._bar_history is a BarHistory(maxlen=200) (services/feature_vector_pipeline.py:126),
-- so live poc_rolling_dist_atr/poc_session_rolling_divergence_atr can never see more than
-- 200 bars regardless of this key's configured value -- a systematic train/serve skew for
-- these two fields specifically, not caught by this phase's tests (they call
-- FeatureFactory.compute() directly against an unbounded synthetic bar list, never through
-- BarHistory's actual cap).
--
-- BarHistory's 200-bar cap is shared by several other pre-existing feature.* windows
-- (momentum_zscore_window/hurst_window/vix_zscore_window default 252, already silently
-- exceeding 200 before this phase) -- raising BarHistory's maxlen to fix all of them is a
-- separate, systemic follow-on (filed as a todo), out of this description-only correction's
-- scope. This migration only corrects the misleading claim for the key Phase 163 introduced.
--
-- No behavior change: description-only. Idempotent: guarded by a NOT LIKE check on the
-- corrected prefix so a re-run is a no-op.

BEGIN;

UPDATE config_schema
SET description = '[conventional] Rolling-track window (bars) for the multi-day POC/VAH/VAL '
    'anchor (poc_rolling_dist_atr, poc_session_rolling_divergence_atr). Matches '
    'ctx_VolumeProfile''s documented _ROLLING_WINDOW. Backfill''s stateless bars[-N:] slicing '
    'genuinely reaches the full configured window against unbounded historical OHLCV. The '
    'LIVE pipeline is bounded by FeatureVectorPipeline''s BarHistory(maxlen=200) regardless of '
    'this value -- code review finding CR-02 (163-REVIEW.md) corrected the original migration '
    '255 description''s claim that live "genuinely reaches the full 480-bar window," which was '
    'true only for backfill. Phase 163. Not an ML learning target.'
WHERE config_key = 'feature.session_vp.rolling_window'
  AND description NOT LIKE '%CR-02%';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT
    NOW(),
    'feature.session_vp.rolling_window',
    (SELECT COALESCE(MAX(version), 0) + 1 FROM config_history WHERE config_key = 'feature.session_vp.rolling_window'),
    config_value,
    'migration-256',
    'description-only correction (CR-02, 163-REVIEW.md): live path is bounded by '
    'BarHistory(maxlen=200), backfill is not -- not a behavior change'
FROM config_state
WHERE config_key = 'feature.session_vp.rolling_window'
  AND NOT EXISTS (
      SELECT 1 FROM config_history
      WHERE config_key = 'feature.session_vp.rolling_window'
        AND changed_by = 'migration-256'
  );

COMMIT;
