---
phase: 185-daily-data-foundation
plan: 20
subsystem: bars
tags: [d3, d4, intraday, venue-fallback, recovery-gate]
requires: [185-13, 185-19]
provides:
  - gated intraday venue recovery tool (--check refuses today, three reasons)
  - empty-history reconcile for any venue-fallback timeframe and for derived 15m/1h
  - migrations 405 (recovery locks) and 437 (venue fallback back to 1d only)
  - measured cost of a verify-only 5m venue walk
affects: [185-23, 186-27]
key-files:
  created:
    - production/migrations/405_intraday_verify_only.sql
    - production/migrations/437_venue_fallback_timeframes_1d_only.sql
    - scripts/ops/bars/ops_intraday_venue_recovery.py
    - tests/unit/scripts/test_intraday_venue_recovery.py
  modified:
    - scripts/infrastructure/backfill/_empty_history.py
    - src/intelligence/bars/sources.py
    - tests/integration/test_d3_d4_live.py
    - docs/research/moved-name-inventory.md
decisions:
  - Venue fallback stays 1d-only. A verify-only 5m walk downloads and discards the venue's pre-move history (about 46 s per 150-day chunk; minutes per venue for a 2013 mover) and the first live re-ask timed out; nothing reads that data before 186's rebuild (D-19). The switch is APR.
  - Recovery reuses the provider's existing venue-routed path (route=), the pipeline's store function and the grid stage; no new provider channel.
  - 15m and 1h empty-history rows inherit 5m's confirmation in the reconcile (the grid is derived from 5m) and are only kept or deleted; the live test asserts 1d only.
  - Migration numbers: 405 as reserved; the revert is 437 because 434 is 189-08's, 435 is 185-18's and 436 is wave 2 onboarding's (I first wrote it as 436, found the collision from the uniqueness test and renamed it).
metrics:
  tasks: 2
  completed: 2026-10-03
---

# Phase 185 Plan 20: intraday D3/D4 and the recovery gate Summary

Intraday recovery is built and provably refuses. `ops_intraday_venue_recovery.py --check` exits 1
today and lists the venue study's 5m verdict, phase 186's rebuild and the empty
`rebuild_state_table`; it also refuses while an ic_engine, feature factory or rebuild process
runs or any rebuild unit is not completed.

## Results

- Gate (11 unit tests): every lock names its own reason; a malformed or non-identifier state
  table value refuses without querying; incomplete units are counted; only python processes count
  as runs. Targets come from recorded venue answers and exclude the venue study's own windows.
  The apply flow (fetch, store, grid stage with `--changed-only`) is tested with fakes and is
  never run live while the locks are closed.
- Reconcile now serves any venue-fallback timeframe; 15m and 1h inherit 5m's answers.
- The 90 intraday 5m empty-history rows were deleted (nothing could confirm them); the 174 15m
  and 174 1h rows stay.
- Measurement (client 49, bounded probes): XEL at ARCA 2016 11,550 bars in 46 s per 150-day
  chunk; TMUS at NYSE 2012 11,664 bars in 52 s, 2008 11,624 in 18 s; TMUS at NYSE 2016 a
  definitive no_data in 6 to 42 s. The live pipeline re-ask of 90 names was stopped after its
  first venue request timed out on every retry.
- No `ibkr_venue` 5m, 15m or 1h rows exist.

## Deviations

- Plan truth 1 (verify-only fallback covers 5m) is not kept: migration 405 enabled it, 437
  reverts it after the measurement above. Truth 2 (intraday rows re-verified every-route) holds
  for 5m by deletion and is not met for 15m and 1h, which cannot corrupt features.
- Task 2's intraday inventory (moved intraday names and spans) is empty: it needs the walk
  this plan chose not to run. `--timeframes 5m` verify-only remains one APR change away.

## Note for phase 186

At rebuild completion (plan 186-27) set `infra.bar_derivation.intraday_recovery_unlocked` to true
and `infra.bar_derivation.rebuild_state_table` to
`{"table": "provenance_batch", "target_tables": ["feature_vectors_v2", "feature_vectors"]}`;
the venue study's 5m verdict must also have passed before the tool will store anything.
