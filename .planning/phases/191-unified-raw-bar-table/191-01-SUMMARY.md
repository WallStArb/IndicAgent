---
phase: 191-unified-raw-bar-table
plan: 01
subsystem: bar data layer
tags: [ohlcv_raw, cvr, migration-472, vendor-kind, glossary]
requires: []
provides:
  - ohlcv_raw hypertable (empty) keyed (timestamp, symbol, timeframe, vendor, kind)
  - CVR namespaces bar_vendor and bar_kind
  - src/intelligence/bars/vendor_kind.py, the one label to (vendor, kind) map
  - ohlcv_revision vendor, kind, request_id (nullable), origin admits raw
affects: [191-02, 191-03, 191-04]
key-files:
  created:
    - production/migrations/472_ohlcv_raw_unified_table.sql
    - src/intelligence/bars/vendor_kind.py
    - tests/unit/test_vendor_kind.py
    - tests/unit/test_ohlcv_raw_migration_contract.py
  modified:
    - tests/unit/test_single_writer_registry.py
    - tests/unit/test_table_and_apr_key_readers.py
    - docs/foundation/glossary.md
    - docs/plans/2026-10-12-unified-raw-bar-table-design.md
decisions:
  - D-191-A to D-191-H recorded in the design doc (planner decisions, owner acknowledgement pending)
metrics:
  tasks: 3
  completed: 2026-10-12
---

# Phase 191 Plan 01: schema, vendor_kind and decision record Summary

Migration 472 creates the empty `ohlcv_raw` hypertable and the CVR vocabularies, extends `ohlcv_revision`, and widens the `ohlcv_load` and `bar_source_policy` checks, all additively while the IBKR fetcher timer kept running; `vendor_kind.py` is the single label to (vendor, kind) map.

## Commits

- 0330d76f7 feat(191-01): vendor_kind module (Task 1)
- c8cd72030 feat(191-01): migration 472 ohlcv_raw (Task 2, applied live with psql -f in the same step)
- 041f1f2b3 docs(191-01): glossary entries and design decision record D-191-A to H (Task 3)
- 9d8c59b0c refactor(191-01): drop stale comment in vendor_kind

## Verification

- `select count(*) from timescaledb_information.hypertables where hypertable_name='ohlcv_raw'` returned 1.
- CVR rows for bar_vendor and bar_kind: 15 (4 vendors + 11 kinds), equal to len(BAR_VENDORS)+len(BAR_KINDS); a contract test pins the seeds to the module.
- `ohlcv_revision` rows with null vendor: 0 (3,890,676 updated from old_source; 0 after the fetcher kept running).
- `ohlcv_load_source_check` count 0; destination check admits raw; origin check admits raw.
- `bar_source_policy` keeps check, check1 (distinct), check2 (derived mode), ingress_mode, timeframe, closed_at; the primary_source and fallback_source CHECKs are gone.
- `indicagent-ibkr-history-fetcher.timer` active before and after.
- `pytest tests/unit/ -q`: full suite green. Targeted: vendor_kind, ohlcv_raw contract, compressed-hypertable VACUUM check, single-writer registry, table/APR readers, temporary allow-list expiry, glossary.

## Deviations from plan

None in scope. Notes:

- Migration number 472 (next free after 471).
- The plan named `intraday raw archive` and `parity lane` for retirement marking; the glossary entries are `raw archive` and, for the parity lane, a clause on the `ohlcv_history_fetcher` entry. `observation` is also marked retiring.
- LEGACY_IMPORT observations (ibkr, TRADES) map to `smart_trades` in `observation_kind`; the plan said "resolves by its source column", and ADJUSTED_LAST under LEGACY_IMPORT raises.
- The /simplify and /review slash commands are not invocable from an executor agent; a self-review of the diff found one stale comment, fixed in 9d8c59b0c. The full unit suite was run as the gate.

## For the next plans

- Plan 04: the fetcher still inserts `ohlcv_revision` rows without vendor, kind or request_id, so rows written after migration 472 have null vendor/kind. Re-run the label-map UPDATE (same VALUES list, `WHERE vendor IS NULL`) in the cutover window before setting NOT NULL and widening the key.
- Plan 02: replace the `ohlcv_raw` placeholder in `tests/unit/test_single_writer_registry.py` (empty tuple) with the real writer and remove `ohlcv_raw` from `_PENDING_RETIREMENT` in `tests/unit/test_table_and_apr_key_readers.py` (both carry `retire: 191-02`).
- Plan 03: add the compression policy for `ohlcv_raw` after the backfill (none exists; compression is enabled, segmentby symbol, timeframe, vendor).
- `bar_derivation_writer` holds INSERT, SELECT, UPDATE on `ohlcv_raw`; no new role.
- `sources.LABEL_VENDOR` is untouched (retires in plan 13).

## Self-Check: PASSED

Files created exist, all four commits are on main, acceptance queries returned the expected values.
