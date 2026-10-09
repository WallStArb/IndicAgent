-- Migration 457: retire the Tradier loader's APR keys (phase 185 plan 48).
--
-- The Tradier account is unfunded and will not be funded (owner decision 2026-10-07). Plan
-- 185-47 moved the 1d primary to IBKR from D = 2026-10-07 (migration 456) and plan 185-48
-- deleted the Tradier daily loader, its systemd units and src/providers/tradier.py. The loader
-- was the only reader of the six keys below (seeded by migrations 438 and 440; the seventh,
-- infra.tradier.max_changed_bar_ratio, was retired by migration 459):
--   infra.tradier.concurrency                (live 4)
--   infra.tradier.first_date_tolerance_days  (live 7)
--   infra.tradier.history_start              (live 2000-01-01)
--   infra.tradier.min_session_ratio          (live 0.95)
--   infra.tradier.nightly_enabled            (live true; the timer was disabled by 185-46)
--   infra.tradier.request_timeout_s          (live 30)
-- Reader check, 2026-10-08: grep -rn "infra.tradier" services src scripts  -> no output.
-- Kept: threshold.bar_integrity.tradier_admission_* (migration 454), read by
-- scripts/ops/bars/ops_source_policy.py and scripts/research/swap_1d_primary_measure.py to judge
-- the stored Tradier history, which stays canonical before D.
--
-- Config rows only: no Tradier row in ohlcv_observation, ohlcv_request, ohlcv_load,
-- market_data_ohlcv or bar_source_policy is touched.
--
-- History, then state, then schema (the retirement order of migrations 349, 431, 434 and 459),
-- by literal key, in one transaction. Idempotent: a rerun deletes nothing.
-- Rollback: \copy the three CSVs in data/backups/185-48/ back into config_schema, config_state
-- and config_history (that order), or re-run the seed blocks of migrations 438 and 440.

BEGIN;

DELETE FROM config_history
 WHERE config_key IN ('infra.tradier.concurrency',
                      'infra.tradier.first_date_tolerance_days',
                      'infra.tradier.history_start',
                      'infra.tradier.min_session_ratio',
                      'infra.tradier.nightly_enabled',
                      'infra.tradier.request_timeout_s');
DELETE FROM config_state
 WHERE config_key IN ('infra.tradier.concurrency',
                      'infra.tradier.first_date_tolerance_days',
                      'infra.tradier.history_start',
                      'infra.tradier.min_session_ratio',
                      'infra.tradier.nightly_enabled',
                      'infra.tradier.request_timeout_s');
DELETE FROM config_schema
 WHERE config_key IN ('infra.tradier.concurrency',
                      'infra.tradier.first_date_tolerance_days',
                      'infra.tradier.history_start',
                      'infra.tradier.min_session_ratio',
                      'infra.tradier.nightly_enabled',
                      'infra.tradier.request_timeout_s');

COMMIT;
