-- Migration 361: the regime-shift guard holds only on change against a stratum's own
-- calibrated history, never on a level (todo 407).
--
-- The guard's input, the fraction of cells failing per (tf, regime_group), is dominated by
-- statistical power: measured on the 176-08 IC, cross-asset slices (few instruments per
-- cross-section, CI 3-6x wider than equity) fail 98.4-100% of cells in a normal window and
-- equity 94-97%. The seeded rails (0.85 / 0.995) therefore read low power as dislocation and
-- held every window on the commodity/fx/rates strata. services/feature_lifecycle.py now
-- judges a stratum only against its own empirical band once it has guard_min_history
-- earlier windows; before that the stratum is 'uncalibrated' (recorded, never holds).
-- Demotion hysteresis still covers a single bad window.
--
-- 1. concept_evaluation.guard_status admits 'uncalibrated'.
-- 2. alpha.decay.guard_fail_rate_min / _max are deleted: no code path reads them. Same
--    retirement pattern as migrations 344/349/360.
--
-- Idempotent.

BEGIN;

ALTER TABLE concept_evaluation DROP CONSTRAINT IF EXISTS concept_evaluation_guard_status_check;
ALTER TABLE concept_evaluation ADD CONSTRAINT concept_evaluation_guard_status_check
    CHECK (guard_status = ANY (ARRAY['ok', 'hold_high', 'alert_low', 'insufficient_cells', 'uncalibrated']));

DELETE FROM config_history
 WHERE config_key IN ('alpha.decay.guard_fail_rate_min', 'alpha.decay.guard_fail_rate_max');
DELETE FROM config_state
 WHERE config_key IN ('alpha.decay.guard_fail_rate_min', 'alpha.decay.guard_fail_rate_max');
DELETE FROM config_schema
 WHERE config_key IN ('alpha.decay.guard_fail_rate_min', 'alpha.decay.guard_fail_rate_max');

COMMIT;
