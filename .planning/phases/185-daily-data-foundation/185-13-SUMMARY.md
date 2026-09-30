---
phase: 185-daily-data-foundation
plan: 13
subsystem: bars
tags: [venue-study, d3, ibkr, apr, preregistration]
requires: [185-02, 185-03, 185-07, 185-09]
provides:
  - venue study verdict (1d and 5m) as the only switch for venue bar use
  - APR infra.bar_derivation.venue_bars_1d and venue_bars_intraday (both false)
affects: [185-17, 185-19, 185-20, 185-23]
key-files:
  created:
    - production/migrations/401_venue_study_switches.sql
    - scripts/ops/bars/ops_venue_study.py
    - tests/unit/scripts/test_venue_study_script.py
    - config/bars/venue_study_verdict.json
    - docs/research/venue-validation-study.md
decisions:
  - Verdict is unfavourable for both timeframes; venue bars stay stored and unused (D-17).
metrics:
  tasks: 2
  completed: 2026-09-29
---

# Phase 185 Plan 13: D3 venue validation study Summary

The D3 study ran on 36 names (12 each NYSE, Nasdaq/ISLAND, NYSE Arca) chosen by the seeded pre-registered rule, and both timeframes fail the pre-registered thresholds, so venue bars stay stored and unused.

## Results

| Timeframe | Criterion A (listing venue leads volume) | Criterion B (only listing closes match) | Passed |
| --- | --- | --- | --- |
| 1d | 30/36 = 0.833 (need 0.9), fail | 5/36 = 0.139, fail | false |
| 5m | 1/36 = 0.028, fail | 0/36 = 0.000, fail | false |

Criterion B fails because non-listing venues also match SMART's close within one cent or five basis points on well over half the days, so "only the listing venue's closes match" does not hold. Full per-name tables and reading are in `docs/research/venue-validation-study.md`. The 1d misses on A are five Arca ETFs and FISV.

APR after the run: venue_bars_1d = false, venue_bars_intraday = false (version 2, changed_by venue_study_185, reason cites verdict sha256 4688a1c6...). `market_data_ohlcv` rows with source 'ibkr_venue': 0 before and after. Fetch run id 62cd2054-db25-4f92-889a-d9cb13e8bc0f; 5m artifact `data/venue_study/62cd2054-....csv.gz` (sha256 4aa3c211..., not committed).

## Commits

- d36961079: migration 401 (applied live, committed same step)
- f1b21d914: study script, pre-registration refusals, tests
- cd6de8ef5: fresh connection for the verdict write, --apply-only
- 3fbc367d7: verdict JSON and report

## Deviations from Plan

**1. [Rule 1 - Bug] Verdict write failed on an idle-timed-out connection**
- Found during: task 2 (the fetch ran about 75 minutes; the control connection opened at start hit the server idle-session timeout).
- Fix: verdict is applied on a fresh connection and an --apply-only mode reads the verdict file; the study was not re-run. Verdict and report had already been written. The apply ran from the committed-to-be file (sha256 recorded in config_history).
- Files: scripts/ops/bars/ops_venue_study.py. Commit cd6de8ef5.

**2. Windows wider than pre-registered.** The provider rounds history requests up to whole chunks, so each route returned 751 daily bars and 2340 5m bars (about 3 years, 30 sessions) instead of 504 and 20 sessions. SMART and every venue cover the same span, so shares are on identical day sets. No result sits near a threshold, so it does not change the verdict.

Nothing else. The priority lease was held for the whole run (about 75 minutes), the todo 449 chain waited behind it; no yield was requested. PAUSE_5M and logs/backfill_ops were untouched.

## Known Stubs

None.

## Self-Check: PASSED

Files and commits above exist (verified via git log); tests `test_venue_study_script.py`, `test_ibkr_history_lease_boundary.py`, `test_migration_number_uniqueness.py` pass.
