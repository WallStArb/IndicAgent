-- Migration 179: equity_regime_model window constants + validation/floor keys
--
-- Migrates _REALIZED_VOL_WINDOW=20, _VIX_Z_WINDOW=252, _MA_WINDOW=200 from
-- module-level constants to the existing alpha.regime.* APR namespace (same block
-- the service already reads). These are rolling-window calibration parameters
-- (tunable, not statistical concept definitions) — CLAUDE.md migrate-as-you-go mandate.
--
-- Also adds:
--   alpha.validation.oos_start  — OOS holdout boundary (set in P1-T1.5)
--   alpha.ic.min_obs_per_regime — per-regime observation floor for BH-FDR gate (CORPUS-06)

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
  ('alpha.regime.realized_vol_window', 'int', '20',
   'Rolling window (daily bars) for SPY realized vol (log-return std). [initial_estimate] '
   'Scaled to TF bars via _tf_window(daily, tf). ML target: No.'),
  ('alpha.regime.vix_z_window', 'int', '252',
   'Rolling window (daily bars) for VIX z-score mean/std normalization. [conventional] '
   '252 trading days scaled via _tf_window(). ML target: No.'),
  ('alpha.regime.ma_window', 'int', '200',
   'Rolling window (daily bars) for 200MA breadth signal. [conventional] '
   'Scaled via _tf_window(). ML target: No.'),
  ('alpha.validation.oos_start', 'string', '',
   'OOS holdout start timestamp (ISO8601 UTC). Set once during Phase 141 CORPUS-02. '
   'All IC measurement uses data BEFORE this timestamp. OOS used for final validation '
   'at Phase 142 exit gate only. [user_preference] ML target: No.'),
  ('alpha.ic.min_obs_per_regime', 'int', '3000',
   'Minimum independent observations per (symbol, tf, regime) cell required for IC score '
   'to count toward BH-FDR gate and ensemble weighting. [initial_estimate] '
   'IC Sharpe on <3K obs too noisy to survive BH-FDR. ML target: No.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('alpha.regime.realized_vol_window', '20', 1),
  ('alpha.regime.vix_z_window', '252', 1),
  ('alpha.regime.ma_window', '200', 1),
  ('alpha.validation.oos_start', '', 1),
  ('alpha.ic.min_obs_per_regime', '3000', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
