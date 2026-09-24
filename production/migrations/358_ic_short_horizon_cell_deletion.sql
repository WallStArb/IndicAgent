-- Migration 358: stop measuring the two structurally uneconomical short-horizon IC scales (todo 389)
--
-- Pre-registration: docs/research/ic-engine-short-horizon-cell-deletion-prereg.md. Rule: a
-- candidate scale is deleted iff it fails the personal-scale cost hurdle by at least 5x at every
-- point of the 2x2 sensitivity grid (breadth 4.5/8.4 x library rank 3/10). Measured 2026-09-24 on
-- the post-176-08 corpus (scripts/analysis/personal_cost_hurdle_by_tf.py, extended to 1d):
--
--   5m  fast (H=1)   min IC_min/measured = 25.12  -> DELETE
--   15m fast (H=1)   min IC_min/measured =  5.50  -> DELETE
--   5m  mid  (H=6)   min 2.03 (mixed across grid)  -> keep
--   5m  slow (H=12)  min 0.99 (clears at one point) -> keep
--   1h  fast (H=1)   min 0.60                       -> keep
--   1d  fast (H=1)   min 0.05 (clears everywhere)   -> keep
--
-- Stops MEASURING these cells only: forward_returns still computes return_fast, and existing
-- feature_ic_scores rows at these scales stay untouched. active_scales is hashed whole into every
-- cell's apr_snapshot_key, so this invalidates every cell once; it lands in the post-176 bundle,
-- whose code changes already force the full recompute. BH-FDR families shrink by these cells:
-- pre- and post-change FDR columns are different families (methodology change).

BEGIN;

UPDATE config_state
SET config_value = '["mid","slow","extended"]', version = version + 1, updated_at = NOW()
WHERE config_key IN ('alpha.ic.active_scales.5m', 'alpha.ic.active_scales.15m');

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_358',
       'Todo 389 pre-registered rule: fast scale fails the personal cost hurdle by >=5x on the whole '
       'sensitivity grid (5m 25.1x, 15m 5.5x, measured 2026-09-24). '
       'docs/research/ic-engine-short-horizon-cell-deletion-prereg.md. [rca_analysis]'
FROM config_state
WHERE config_key IN ('alpha.ic.active_scales.5m', 'alpha.ic.active_scales.15m');

COMMIT;
