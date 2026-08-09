-- Migration 308: reconcile alpha.hmm_volatility.* APR values against 172-01's measured
-- null-arm wider-scope GO verdict (Phase 172, plan 05).
--
-- 172-NULL-ARM-WIDER-SCOPE.md's "Recommended shipped configuration" section measured the
-- real-minus-null block-reliability margin for realized_vol and vol_of_vol jointly across
-- {20, 60, 120, 250} at 15m and 5m (the two required GO timeframes) and found window 250 the
-- joint maximum for BOTH columns, not merely the larger of two competing candidates:
--
--   realized_vol margin by window (15m / 5m): 20 -> +0.532/+0.354, 60 -> +0.680/+0.573,
--   120 -> +0.718/+0.641, 250 -> +0.728/+0.732 (joint max).
--   vol_of_vol margin by window (15m / 5m): 20 -> +0.070/-0.023, 60 -> +0.315/+0.221,
--   120 -> +0.403/+0.327, 250 -> +0.477/+0.452 (joint max).
--
-- Two of migration 307's four seeded alpha.hmm_volatility.* values were plan-time estimates
-- (172-RESEARCH.md / 171-FINAL-VERDICT.md section 6's qualitative "solid from 60 up" read, not
-- a swept measurement) that this reconciliation now corrects to the measured optimum:
--
--   - vol_window: 20 -> 250. realized_vol is window-invariant in direction (30/30 real>null at
--     every window/timeframe tested per 172-NULL-ARM-WIDER-SCOPE.md's measured-result table),
--     so moving to the joint-max window costs it nothing and is the correct application of the
--     plan's own "largest joint real-minus-null margin" selection rule.
--   - vol_of_vol_window: 60 -> 250. This directly extends 171-FINAL-VERDICT.md section 6's
--     "thin at 20, solid from 60 up" finding: the wider-scope sweep in 172-NULL-ARM-WIDER-SCOPE.md
--     finds the true optimum further out, at 250, not merely "60 or higher" as a floor. No
--     contradiction with section 6 -- the measured recommendation is 250, not 20, so the case
--     172-05's own plan text flags (a measurement recommending 20, which would contradict the
--     thin-margin finding) does not apply here.
--
-- n_components (3) and covariance_type (full) are unchanged -- 172-NULL-ARM-WIDER-SCOPE.md's
-- K=3 default recommendation and 171-FINAL-VERDICT.md section 5's covariance_type=full model
-- specification both match migration 307's seeded values exactly; no reconciliation needed for
-- either key.
--
-- Both new values (250) fall inside migration 307's seeded [5, 500] bounds for both keys --
-- no bound widening required.
--
-- Idempotent: each UPDATE is guarded by config_value <> '<measured>' so a second application is
-- a no-op and does not double-increment version. Each config_history INSERT is separately
-- guarded by NOT EXISTS against changed_by = 'migration_308' for that key, so a re-run after
-- the UPDATE has already been applied does not write a duplicate history row either -- an
-- unguarded INSERT ... SELECT FROM config_state re-reads the post-migration row and duplicates
-- it even when the paired UPDATE was correctly a no-op.

BEGIN;

UPDATE config_state
SET config_value = '250', version = version + 1
WHERE config_key = 'alpha.hmm_volatility.vol_window'
  AND config_value <> '250';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.hmm_volatility.vol_window', version, config_value, 'migration_308',
       '172-NULL-ARM-WIDER-SCOPE.md: window 250 is the joint real-minus-null margin maximum '
       'for realized_vol at both 15m (+0.728) and 5m (+0.732), superseding migration 307''s '
       'plan-time estimate of 20 (+0.532/+0.354 at those windows). realized_vol clears '
       '30/30 real>null at every window tested, so moving to the joint-max window is free.'
FROM config_state
WHERE config_key = 'alpha.hmm_volatility.vol_window'
  AND NOT EXISTS (
      SELECT 1 FROM config_history
      WHERE config_key = 'alpha.hmm_volatility.vol_window' AND changed_by = 'migration_308'
  );

UPDATE config_state
SET config_value = '250', version = version + 1
WHERE config_key = 'alpha.hmm_volatility.vol_of_vol_window'
  AND config_value <> '250';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.hmm_volatility.vol_of_vol_window', version, config_value, 'migration_308',
       '172-NULL-ARM-WIDER-SCOPE.md: window 250 is the joint real-minus-null margin maximum '
       'for vol_of_vol at both 15m (+0.477) and 5m (+0.452), superseding migration 307''s '
       'plan-time estimate of 60. Extends 171-FINAL-VERDICT.md section 6''s "solid from 60 up" '
       'finding -- the wider-scope sweep finds the true optimum further out, at 250, not '
       'merely a 60-bar floor. No contradiction: the measured recommendation is 250, not 20.'
FROM config_state
WHERE config_key = 'alpha.hmm_volatility.vol_of_vol_window'
  AND NOT EXISTS (
      SELECT 1 FROM config_history
      WHERE config_key = 'alpha.hmm_volatility.vol_of_vol_window' AND changed_by = 'migration_308'
  );

UPDATE config_schema
SET description = '[rca_analysis] Phase 172: realized-vol rolling-std window for the '
    'volatility-only regime HMM. This is the axis''s ORDERING column (column 0 of the '
    '2-column observation matrix, drives ascending calm->elevated->turbulent label sort). '
    'Reconciled by migration 308 to 250 -- the joint real-minus-null margin maximum at 15m '
    '(+0.728) and 5m (+0.732) per 172-NULL-ARM-WIDER-SCOPE.md''s window sweep {20,60,120,250}, '
    'superseding migration 307''s plan-time estimate of 20. Not an ML learning target.'
WHERE config_key = 'alpha.hmm_volatility.vol_window';

UPDATE config_schema
SET description = '[rca_analysis] Phase 172: vol-of-vol rolling-std window for the '
    'volatility-only regime HMM. 171-FINAL-VERDICT.md section 6 found this column''s margin '
    'thin at window 20 and solid from window 60 up. Reconciled by migration 308 to 250 -- the '
    'joint real-minus-null margin maximum at 15m (+0.477) and 5m (+0.452) per '
    '172-NULL-ARM-WIDER-SCOPE.md''s window sweep {20,60,120,250}, which extends section 6''s '
    'finding to its true measured optimum rather than a 60-bar floor. Not an ML learning target.'
WHERE config_key = 'alpha.hmm_volatility.vol_of_vol_window';

COMMIT;
