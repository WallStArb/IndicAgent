---
phase: 185-daily-data-foundation
plan: 22
subsystem: bars
tags: [d5, splits, overlap, nightly]
requires: [185-15, 185-17, 185-19]
provides:
  - nightly 1d overlap of the last overlap_sessions sessions (APR, migration 406)
  - services/split_detection.py (splits and unexplained differences from overlapping D1 observations)
  - scripts/ops/bars/ops_split_detect.py (record, re-fetch, re-derive) chained in the nightly
affects: [185-23]
key-files:
  created:
    - production/migrations/406_split_overlap_apr.sql
    - services/split_detection.py
    - scripts/ops/bars/ops_split_detect.py
    - tests/unit/services/test_split_detection.py
    - tests/unit/scripts/test_nightly_overlap.py
    - tests/unit/scripts/test_ops_split_detect.py
  modified:
    - scripts/infrastructure/backfill/_d1_gaps.py
    - scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py
    - scripts/infrastructure/backfill/infrastructure_nightly_backfill.py
decisions:
  - The overlap is a pipeline flag (--overlap-sessions, default 0), not a nightly mode; the nightly passes the APR value and a run id it assigns (--fetch-run-id) so split detection judges exactly its own overlap.
  - Full-history re-fetch reuses the same flag with years x 260 sessions, instead of a second depth option.
  - Order inside ops_split_detect is record, then re-fetch, then derive: D2 counts only a fetch after the recording as post-split. Failure exits non-zero; --refetch-only repeats the last two steps by hand.
  - Non-constant differences become integrity facts (bar_split_detection) and are never recorded as splits.
metrics:
  tasks: 2
  completed: 2026-10-03
---

# Phase 185 Plan 22: split detection from the nightly overlap Summary

A split IBKR re-scales history for now shows up within a night: the nightly re-asks the last 20
sessions, the detector pairs each fresh close with the latest earlier observation of the same
date, and a constant ratio is recorded, re-fetched and re-derived.

## Results

- Detector: 11 tests; excludes test callers and the session of the answer's own UTC date (it may
  still be forming); needs `min_run` overlapping sessions; a non-positive close raises with the
  symbol. Run over all 12 real historical-pipeline runs it found nothing (no false positives).
- Overlap: `with_overlap_window` merges the last-N-sessions window into the planned gaps; the
  planner never asks an answered session, so it is added after planning.
- Nightly order in code: legs, split detection, daily stage, grid stage (tested).
- Measured live (20 symbols, 1d, overlap 20, priority tier, client 45): 295 s end to end including
  lease wait and the daily stage, 33 requests (29 bars, 4 no_data answers, one venue head). That
  is about 15 s per name, so a 931-name nightly adds roughly 2.7 hours at the 58 per 10 minutes
  limit and up to about 3.8 hours at the measured rate; the overlap is one request per name whatever
  its size. `ops_split_detect` on that run: 0.5 s, nothing recorded.

## Deviations

- The plan's `--days` re-fetch option is replaced by `--overlap-sessions` (one flag, one meaning).
- The positive path (a real split recorded, re-fetched and re-derived) is covered by unit tests with
  fakes only; no real split has occurred to exercise it, and I did not fabricate one in production.

## Open

- The added nightly time (about 3 hours) is real. Lowering `infra.bar_derivation.overlap_sessions` does not cut it: the overlap is one request per name whatever its size, so only a smaller symbol set would. Revisit with 185-23's duration metrics.
