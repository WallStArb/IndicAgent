---
phase: 191-unified-raw-bar-table
plan: 24
subsystem: bars
tags: [tradier-retirement, fetcher-scripts]
requires: [191-23]
provides: [fetcher-imported scripts free of Tradier code]
affects: [191-25]
metrics:
  completed: 2026-10-30
---

# Phase 191 Plan 24: fetcher-imported scripts

No code change was needed. The Tradier ingestion branches in `_d1_gaps.py` and `ohlcv_history_fetcher.py` were already gone (the planner's vendor filter is ibkr only, covered by `test_tradier_requests_are_not_an_ibkr_answer`). The two remaining hits are a comment (`_d1_gaps.py:305`) and a docstring clause (`ohlcv_history_fetcher.py:35`); both describe history, and editing a fetcher-imported file mid-backfill needs a timer window for no behavior gain, so they stay.

- `grep -rniE tradier scripts/infrastructure` prints only those two history lines.
- No Tradier rows remain in `ohlcv_raw`; the planner output cannot change because no code changed.
- Unit tests for the three scripts are unchanged and pass.
- Integration criterion not met: four d2 tests and the 1h volume grid test fail on the live DB because they encode the Tradier-primary world (todo 572). They are not in CI.
