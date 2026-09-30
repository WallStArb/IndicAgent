---
phase: 185-daily-data-foundation
plan: 15
subsystem: bars
tags: [d1-bootstrap, split-seam-audit, corporate-action, ibkr]
requires: [185-07, 185-09, 185-10, 185-14]
provides:
  - D1 holds the stored 1d corpus (931 legacy_import requests) and one fresh paired TRADES and ADJUSTED_LAST run
  - corporate_action append-only table (migration 400), empty: no split found
  - split-seam audit over 931 names (docs/research/split-seam-audit.md)
affects: [185-16, 185-17, 185-21, 185-22]
key-files:
  created:
    - production/migrations/400_corporate_action.sql
    - scripts/ops/bars/ops_d1_bootstrap.py
    - scripts/ops/bars/ops_seam_audit.py
    - docs/research/split-seam-audit.md
decisions:
  - No split is inferred where the ratio is not constant over a run; 74 isolated single-day differences are reported as unexplained (D-24).
  - Which side is right on the 2026-08-06 and early-ETF single-day differences is left open for plan 10's scrub and plan 23's daily-versus-intraday check.
metrics:
  tasks: 2
  completed: 2026-09-30
---

# Phase 185 Plan 15: D1 bootstrap and split-seam audit Summary

D1 now holds the stored 1d corpus and a fresh paired fetch, and the split-seam audit over all 931 names found no split and no seam. `corporate_action` is empty and no `split_seam` flag was written.

## Results

- Legacy import: 931 `legacy_import` requests, one per symbol (quarantined rows included).
- Fresh run `c9b625b5-5fc4-4656-8b49-06fd93062123` (client 47, priority lease): 1,862 requests over 931 names, 0 failed, 3,867,030 TRADES and 3,867,030 ADJUSTED_LAST observations. Both series have the same row count, so the pair is complete for every name.
- Seam audit: 931 names audited, 0 seams, 0 splits, 74 unexplained single-day disagreements, 0 names skipped.
- MRNA 2026-08-19 and ALMS 2026-09-01 (audited first, D-24): events, not splits. The stored/fresh ratio stays 1 through both dates.

## Open finding

The 74 unexplained items are single days, not runs. Thirty of the listed rows are 2006 and 2007 ETF days (0.2 to 0.7%). Twelve names differ on 2026-08-06 only (0.7 to 2.7%), with neighbouring days matching exactly (LMT: stored 579.01, fresh 582.85). The audit cannot say which side is right. Plan 10's scrub and plan 23's daily-versus-intraday check are where to settle it. Detail is in the report's "Reading of the result".

## Commits

`b85ced71a` migration 400 and seam APR keys; `b3e0d0727` bootstrap script; `939fa13da` seam audit script (scrub prune keeps `split_seam` flags); `4ebbea46d` MRNA and ALMS verdict; plus the completed report and this SUMMARY.

## Deviations

- Two executor sessions hit their usage limit: the first after the legacy import, the second after the fresh fetch finished. The orchestrator ran the full seam audit (dry run, then `--apply`), added the reading to the report and wrote this SUMMARY. No fetch was repeated.
- `--apply` wrote nothing to `corporate_action` or `bar_quality_flag` because no split was found.

## Discipline

Priority lease held about 4 hours across the two runs; the todo 449 chain waited behind it. `PAUSE_5M` and `logs/backfill_ops/` untouched. Nothing pushed.
