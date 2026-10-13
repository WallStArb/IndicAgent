---
phase: 191-unified-raw-bar-table
plan: 03
subsystem: bar data layer
tags: [ohlcv_raw, backfill, balance-check, migration-474]
requires: [191-02]
provides:
  - scripts/ops/bars/ops_raw_backfill.py with --bulk, --delta and --check (temporary, deleted at plan 17)
  - APR key infra.raw_backfill.statement_timeout_s (migration 474)
  - ohlcv_raw loaded from the three old stores for 1,551 symbols
affects: [191-04, 191-17]
key-files:
  created:
    - scripts/ops/bars/ops_raw_backfill.py
    - tests/unit/scripts/test_ops_raw_backfill.py
    - production/migrations/474_raw_backfill_statement_timeout.sql
metrics:
  tasks: 3
  completed: 2026-10-13
---

# Phase 191 Plan 03: bulk backfill into ohlcv_raw Summary

The bulk pass loaded every window for 1,551 symbols (06:34 to 09:54 UTC, 11,991 s; archive 201.7M, observation 15.6M, canonical 318.5M rows inserted). The balance check then ran as four parallel symbol shards (a single process took about 43 s per symbol, roughly 18 hours).

## Balance check result

All four shards exited 1. The failures are small and all trace to the live fetcher writing after the bulk:

- archive twin_missing 3,512 and canonical twin_missing 80 across the four shards; no observation row is missing.
- Of the archive rows written since the bulk began (171,180), 11,515 have no raw twin at the time of the later query and none of them was archived before the bulk ended (09:54 UTC). The check windows therefore miss only rows the fetcher archived after the window was loaded.
- twin_diff 340 + 168 + 5,099 + 485 on canonical tracks `store_disagreement.canonical_vs_archive` (340, 180, 5,082, 464): the same key holds different values in the canonical and archive stores, and raw keeps one value. These are old-store disagreements, not load errors.
- value_mismatches 2 + 12 + 21 + 21 and observation provenance mismatches 1 + 2 are of the same kind.
- raw_rows_without_source_key: 10, all in one shard; not yet explained, checked again by plan 04's delta.

## Not yet verified

The delta backfill and a balance check taken after the timers stop belong to plan 04, which requires them before the cutover. The 10 rows without a source key and the 56 value mismatches are the items to look at then.
