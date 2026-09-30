-- Migration 412: retire alpha.regime_stratification.max_correlation and
-- alpha.validation.regime_gate_min_clusters (phase 186 plan 16).
--
-- Both keys were read only by scripts under scripts/analysis/, deleted in 186-16:
--   alpha.regime_stratification.max_correlation (0.3, seeded by migration 327) was the
--     orthogonality threshold of the per-symbol regime candidates stage 2 script.
--   alpha.validation.regime_gate_min_clusters (20, seeded by migration 244) was the
--     day-cluster coverage floor of the one-off evaluation scripts.
-- A literal and an f-string grep over src, services, scripts, tools, tests and
-- production/{systemd,grafana} on the post-deletion tree finds no reader of either key.
-- Deleted rather than left registered-but-unused, same pattern as migrations 344/349/360.
--
-- Idempotent: DELETE by primary key, safe to re-run.

BEGIN;

DELETE FROM config_history
 WHERE config_key IN ('alpha.regime_stratification.max_correlation',
                      'alpha.validation.regime_gate_min_clusters');
DELETE FROM config_state
 WHERE config_key IN ('alpha.regime_stratification.max_correlation',
                      'alpha.validation.regime_gate_min_clusters');
DELETE FROM config_schema
 WHERE config_key IN ('alpha.regime_stratification.max_correlation',
                      'alpha.validation.regime_gate_min_clusters');

COMMIT;
