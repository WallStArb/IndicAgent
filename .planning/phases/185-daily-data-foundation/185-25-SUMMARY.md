---
phase: 185-daily-data-foundation
plan: 25
subsystem: bars / storage
tags: [D-15, todo-462, real-rows, swap]
requires: [185-12, 185-18, 185-23]
provides: [market_data_ohlcv without synthetic_fill, ops_real_rows_swap]
affects: [market_data_ohlcv, market_data_5m, market_data_ohlcv_scrub_input, market_data_ohlcv_tradeable]
key-files:
  created:
    - production/migrations/439_market_data_ohlcv_real_rows_swap.sql
    - scripts/ops/bars/ops_real_rows_swap.py
    - tests/unit/scripts/test_ops_real_rows_swap.py
    - tests/integration/test_ops_real_rows_swap_scratch.py
  modified:
    - tests/unit/test_market_data_ohlcv_boundary.py
decisions:
  - "Copy by 90-day chunk-aligned window rather than per symbol: peak disk stays near one window"
  - "The three placeholder-coverage readers (5m _d1_gaps, 1m pipeline gap detection, 1m bar_auditor) were accepted with --accept-placeholder-coverage: cost is a one-time re-ask of fetch windows, never a wrong row"
  - "Digest and copy filter use source IS DISTINCT FROM 'synthetic_fill' so NULL-source rows are never dropped (none exist today)"
metrics:
  completed: 2026-10-06
---

# Phase 185 plan 25: real-rows swap of market_data_ohlcv

market_data_ohlcv was rebuilt from its real rows and swapped in on 2026-10-06; the old table is dropped.

## Live run (2026-10-06, EDT)

- Lane stopped by PID (htf lane, 5.4 h in, about 3% of 697 names); no orphan workers, no lease holder, writer units inactive.
- Dry run blocked only on the three accepted placeholder-coverage readers; masked-slot fact (185-23) zero for 15m and 1h.
- Migration 439 applied (empty market_data_ohlcv_new, structurally identical).
- Copy: real rows per timeframe equal the original's exactly (5m 81,768,711; 15m 57,779,665; 1h 15,646,951; 1m 9,775,958; 1d 7,007,640; 4h 2,184; total 171,981,109).
- Swap: per-(symbol, timeframe) count and digest verify passed, exclusive lock about 31 s, post-checks passed, total 354 s; gap-planner smoke slots equal the original real counts for every timeframe; market_data_ohlcv_tradeable identical.
- Drop: old table dropped (9.3 GiB), bare VACUUM run, free disk 549.5 to 558.8 GiB (reclaimed 9.32 GiB).
- Source mix after: ibkr_named 132,487,326; derived_5m 33,223,214; tradier 6,270,569; zero synthetic_fill.
- Lane relaunched with `nohup bash logs/backfill_ops/intraday_chain.sh`; the ibkr_history_stream lease holder reappeared and the log advances.

## Follow-ups

- The 5m and 1m gap planners re-ask windows that were covered only by placeholders (one IBKR history stream each, settles after one answered pass); the 5m lane is still paused.
- market_data_5m has no volume filter and now shrinks; its only reader is ops_validate_roll_detection.py (manual).
- The new table uses uniform 90-day chunks (about 110) instead of the old 30/90 mix.
- The plan's smoke read through BarDerivation was replaced by reading every dependent view plus the gap planner's SQL (running it would mean running a writer).
