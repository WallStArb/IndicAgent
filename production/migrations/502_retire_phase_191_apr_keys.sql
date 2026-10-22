-- Migration 502: retire the five infra.canonical_swap.* APR keys (phase 191 plan 17).
--
-- Seeded by migration 496 for the one-shot canonical rebuild and swap script
-- (scripts/ops/bars/ops_canonical_vendor_kind_swap.py, plans 191-12 and 191-14). Plan 17
-- deletes that script now that the rebuilt table is proven over a full nightly cycle, so the
-- keys have no reader left. Retired in the order history, state, schema (the retirement order
-- of migrations 349, 431, 434, 457, 459 and 499).
--
-- infra.raw_backfill.statement_timeout_s, which plan 17's text also lists, was already retired
-- by migration 499 (plan 191-16 deleted ops_raw_backfill.py, its subject).
-- infra.old_store_backup.disk_margin stays: ops_old_store_backup.py lives until the backup
-- retention date 2026-11-12 and plan 191-18 deletes it with the key.
--
-- Reader check, 2026-10-18: grep -rn "infra.canonical_swap" services src scripts -> no output
-- after the script deletion in the same commit; the remaining matches are the historical
-- migration files 496/500 and the migration-contract tests that assert their text.
--
-- Rerun semantics, stated exactly: the three DELETEs match nothing on a rerun. No table is
-- touched, so no VACUUM clause is owed.

BEGIN;

DELETE FROM config_history
 WHERE config_key IN ('infra.canonical_swap.disk_margin',
                      'infra.canonical_swap.statement_timeout_s',
                      'infra.canonical_swap.copy_statement_timeout_s',
                      'infra.canonical_swap.lock_timeout_s',
                      'infra.canonical_swap.stats_flush_wait_s');
DELETE FROM config_state
 WHERE config_key IN ('infra.canonical_swap.disk_margin',
                      'infra.canonical_swap.statement_timeout_s',
                      'infra.canonical_swap.copy_statement_timeout_s',
                      'infra.canonical_swap.lock_timeout_s',
                      'infra.canonical_swap.stats_flush_wait_s');
DELETE FROM config_schema
 WHERE config_key IN ('infra.canonical_swap.disk_margin',
                      'infra.canonical_swap.statement_timeout_s',
                      'infra.canonical_swap.copy_statement_timeout_s',
                      'infra.canonical_swap.lock_timeout_s',
                      'infra.canonical_swap.stats_flush_wait_s');

COMMIT;
