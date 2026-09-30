---
phase: 185-daily-data-foundation
plan: 14
subsystem: bars
tags: [head-rerun, moved-names, d1, ibkr, verify-only]
requires: [185-03, 185-09, 185-13]
provides:
  - late-name dispositions from stored D1 answers (moved, reached_window_start, verified_empty, unresolved)
  - moved-name inventory report (docs/research/moved-name-inventory.md)
affects: [185-15, 185-16, 185-19, 185-20]
key-files:
  created:
    - scripts/ops/bars/ops_head_rerun.py
    - tests/unit/scripts/test_head_rerun.py
    - docs/research/moved-name-inventory.md
decisions:
  - Unresolved is never counted as empty: a name is verified empty only when every route answered no data (D-20). Forty-two names stay unresolved because the ISLAND route never answered.
  - Venue bars stay stored and unused (plan 13 verdict); the re-run runs under verify-only.
metrics:
  tasks: 2
  completed: 2026-09-30
---

# Phase 185 Plan 14: 1d head re-run and moved-name inventory Summary

The re-run classified all 382 late 1d names from stored D1 answers: 39 moved, 301 reached the window start, 0 verified empty and 42 unresolved. None of the 42 unresolved names could be resolved, because the ISLAND (Nasdaq) route did not answer for them.

## Results

| Disposition | Names |
| --- | --- |
| moved | 39 |
| reached_window_start | 301 |
| verified_empty | 0 |
| unresolved | 42 |
| total | 382 |

The run (client id 49, priority lease, fetch runs b8312c6e and 1847bc00) issued 66 requests across 14 names; the pipeline's provider-verified empty-history rule skipped 9 symbol and timeframe pairs (verified 2026-09-29) and the rest needed no request. Outcomes: 53 `no_data` from SMART, ARCA, NYSE, AMEX and BATS, and 13 `failed`. Every one of the 13 failed requests was an ISLAND request that ran about 3.3 minutes (which looks like the retry loop timing out) and carried no error code or text, so the venue never answered. By D-20 a name is verified empty only when every route answers no data, so all 42 stay unresolved and no name was counted as empty. Integrity facts (monitor_type `bar_head_rerun`): moved 39, reached_window_start 301, verified_empty 0, unresolved 42 (failed).

AMD, CSX, IEF, PEP and TLT are all in the moved set, with their former venues and pre-move spans in the report. `ohlcv_venue_head` holds 39 distinct pre-move symbols, equal to the report's moved count. The report lists every one of the 382 late names once.

## Commits

- `9d3a1c944` head re-run script with the disposition classifier and 9 unit tests
- `8bd31f30b` the moved-name inventory report

## Deviations

- The executor session hit its usage limit right after the run finished (report written, lease released), before it committed the report or wrote this SUMMARY. The orchestrator closed the plan out: verified the acceptance criteria against the database and the report, committed the report, and wrote this file. Nothing was re-run.
- The 42 unresolved names are an open item, not a result about the names. The ISLAND route timing out for names that were never listed there looks like a provider non-answer rather than a no-data answer, and plan 19 (D3 rebase and D4 from recorded answers) and plan 20 (intraday verify-only and empty history) need to decide how such a route counts. Until then the nightly's empty-history skip treats them as unresolved.

## Discipline

- Priority lease held for about 45 minutes; the todo 449 chain waited behind it and resumed afterwards.
- `logs/backfill_ops/PAUSE_5M` and everything under `logs/backfill_ops/` untouched; nothing pushed; explicit pathspecs throughout.
