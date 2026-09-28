---
phase: 185-daily-data-foundation
plan: 10
subsystem: bars
tags: [d2a, scrub, historical-pass, quarantine]

# Dependency graph
requires: [185-04, 185-05]
provides:
  - services/bar_scrub.py (scrub_symbols library, provenance batches, integrity facts)
  - scripts/ops/bars/ops_scrub_historical_pass.py (--tf 1d|5m, dry-run default, --apply)
  - Applied quarantine state: 86 quarantine flags at 1d (price_sanity 83, non_positive_price 3) plus migration 381's 67 legacy; 5m informational only
  - docs/research/scrub-historical-pass.md (run times, per-rule counts, known answers, 441-move analysis, top-20 hand-check)
  - tests/integration/test_scrub_pass_live.py (7 read-only live checks)
affects: [185-15, 185-16, 185-22]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dry-run default on any pass that writes flags; apply is the explicit opt-in"

key-files:
  created:
    - services/bar_scrub.py
    - scripts/ops/bars/ops_scrub_historical_pass.py
    - tests/unit/services/test_bar_scrub.py
    - tests/integration/test_scrub_pass_live.py
    - docs/research/scrub-historical-pass.md
  modified: []

key-decisions:
  - "5m pass runs D-14 ports only (return_magnitude, gap_before_next) per D-14; 418,814 gap_before_next flags (~0.54% of bars) stay informational"
  - "Exactly 1 of the 441 beyond-ln(1.5) moves has a quarantine co-fire (UHAL 2022-11-09 bad print) — the informational tier records large real moves without hiding them"
  - "Todo 454 filed for the RCAT ultra-thin-series defect class (todo 052 sweep): treatment decision (eligibility dimension vs informational rule) stays there"

patterns-established:
  - "One completed bar_derivation_batch row plus per-rule integrity facts per pass run"

requirements-completed: [D-08, D-09, D-12, D-28-scrub-condition]

# Metrics
duration: about 2.5 h total (executor for task 1 + RED/GREEN, then inline finish after a 429 killed the executor mid-task-2; quota reset 13:23 UTC)
completed: 2026-09-28
---

# Plan 185-10: historical scrub pass summary

**Both timeframes applied and verified live; the informational tier records without hiding, and the quarantine tier is not over-firing on real moves**

## Performance
- 1d pass: 45.2 s, 931 symbols, 3,343 flags, 86 quarantine
- 5m pass: 96.7 s, 931 symbols, 418,962 informational flags, 0 quarantine

## Task commits
1. **Task 1: scrub library + CLI (RED then GREEN)** - `31142717d`, `6d3e9868e` (executor)
2. **Task 2: both passes applied, live verification, report, todo 454** - `04f06b156` (inline)

**Plan metadata:** this commit

## Acceptance criteria
- Completed scrub batches: 2 (1d, 5d) — verified live
- Integration test passes: 7/7 (72 dry-run keys quarantined and hidden, 0 of 1,864 AMBIGUOUS quarantined, 15 legacy quarantined)
- Tradeable view admits no quarantined bar: count 0
- Report committed with per-rule counts and wall times: docs/research/scrub-historical-pass.md

## Deviations from plan
- Task 2 finished inline in the orchestrator session: the executor hit the account's 5-hour quota wall (429) after applying the 1d pass; the standing owner directive covers inline continuation
- The plan's known-answer comparison ran against the applied live state (the executor had already passed the dry-run-vs-expectations gate before the 1d apply)

## Issues encountered
- The 441-move query and the top-20 context windows were measured after the passes (never write results before running)

## User setup required
None.

## Next phase readiness
- Plan 15 (seam audit) has 5 named split-like candidates from the hand-check (FRHC x2, KDP, SSP, and GYRE-2017 to watch)
- Plan 16's D-28 check reads the integrity facts written here
- Todo 454 owns the ultra-thin-series treatment decision

---
*Phase: 185-daily-data-foundation*
*Completed: 2026-09-28*
