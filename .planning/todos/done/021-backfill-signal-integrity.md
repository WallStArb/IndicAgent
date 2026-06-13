---
created: 2026-06-06T00:00:00.000Z
title: Backfill Signal Integrity — Calibration curves + integrity assertion in historical_backfill.py
area: data
files:
  - production/scripts/historical_backfill.py
  - tests/unit/scripts/test_historical_backfill.py
  - docs/plans/2026-06-06-backfill-signal-integrity-plan.md
---

## Problem

Historical backfill runs without calibration curves or perf weights (tables are empty at backfill time). When those tables are populated later, backfill signals will have been scored without them. Also: `was_selected` stacking (duplicate uuid4 signals) was detected on ESM6/1m and ESM6/15m — the integrity assertion that prevents this is missing.

## Action

Plan already written: `docs/plans/2026-06-06-backfill-signal-integrity-plan.md`

6 surgical tasks to `historical_backfill.py` only:

1. `_load_calibration_curves(conn)` + `_load_perf_weights(conn)` loaders
2. Thread into `run_i7_and_persist` — pass `calibration_curves=`, `perf_weights=`, `timeframe=` to `aggregate()`
3. Thread through `replay_symbol`
4. Load in `_replay_worker` (per symbol); load perf_weights once before loop in single-worker path
5. `_assert_backfill_integrity(conn, symbols)` — query was_selected>1 per (sym,tf,ts) + duplicate signal_ids; `sys.exit(1)` on either
6. Run `--replay-only --clean --workers 8`; must print `[INTEGRITY PASS]`

## Notes

- Both tables empty now — loaders return {} and aggregate() passes through unchanged. No behavior change today, correct when tables have data.
- `_assert_backfill_integrity` is the load-bearing invariant preventing silent stacking forever.
- Open issue outside this plan: `schemas.py:924` silent uuid4 fallback should raise (separate todo).
