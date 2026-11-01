-- Migration 550: retire the Tradier arm's APR keys (phase 191 plan 25).
--
-- Plan 191-20 deleted the Tradier rows and plan 191-25 deleted the readers of three of these
-- four keys (the fourth's reader, ops_tradier_delete.py, is retained until the 2026-11-12
-- backup retention date, todo 574, and resolves its keys to defaults until then):
--   infra.tradier_delete.min_free_disk_gb                       (live 200; read by
--        scripts/ops/bars/ops_tradier_delete.py, retained until 2026-11-12 (todo 574); its
--        backup files stay under data/backups/191/ until the same date)
--   infra.tradier_delete.batch_symbols                          (live 20; same reader)
--   threshold.bar_integrity.tradier_admission_min_overlap_sessions (live 60; read by the
--        --admission-sweep arm of scripts/ops/bars/ops_source_policy.py, deleted in this
--        plan, and by src/intelligence/bars/source_admission.py, retained dormant until
--        2026-11-12 as restore-path evidence judge (todo 574); migration 457 kept the pair
--        for exactly those readers)
--   threshold.bar_integrity.tradier_admission_min_agree_share   (live 0.9; same two readers,
--        plus scripts/ops/bars/ops_d191q_arbitration.py, which resolves it to its own equal
--        default (0.9) after the retirement, so its behavior is unchanged)
--
-- Reader check, 2026-10-31: grep -rn "tradier_delete\.\|tradier_admission_min" src services
-- scripts --include=*.py (excluding the deleted scripts and their tests) -> only
-- ops_d191q_arbitration.py's _cfg fallback above.
--
-- Config rows only: no bar_source_policy, market_data_ohlcv or ohlcv_* row is touched. The
-- bar_source_policy rows the arbitration wrote (254 symbol rows under D-191-Q) are load-bearing
-- and stay.
--
-- History, then state, then schema (the retirement order of migrations 349, 431, 434, 457 and
-- 459), by literal key, in one transaction. Idempotent: a rerun deletes nothing.
-- Rollback: re-run the seed blocks of migrations 454 and 524.

BEGIN;

DELETE FROM config_history
 WHERE config_key IN ('infra.tradier_delete.min_free_disk_gb',
                      'infra.tradier_delete.batch_symbols',
                      'threshold.bar_integrity.tradier_admission_min_overlap_sessions',
                      'threshold.bar_integrity.tradier_admission_min_agree_share');
DELETE FROM config_state
 WHERE config_key IN ('infra.tradier_delete.min_free_disk_gb',
                      'infra.tradier_delete.batch_symbols',
                      'threshold.bar_integrity.tradier_admission_min_overlap_sessions',
                      'threshold.bar_integrity.tradier_admission_min_agree_share');
DELETE FROM config_schema
 WHERE config_key IN ('infra.tradier_delete.min_free_disk_gb',
                      'infra.tradier_delete.batch_symbols',
                      'threshold.bar_integrity.tradier_admission_min_overlap_sessions',
                      'threshold.bar_integrity.tradier_admission_min_agree_share');

COMMIT;
