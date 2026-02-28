---
phase: 03-historical-data
plan: 01
subsystem: historical-backfill
tags: [tdd, backfill, intelligence-features, signal-ledger, psycopg2]
dependency_graph:
  requires:
    - 02-02-SUMMARY.md  # feature_writer_service (intelligence_features table schema)
    - 02-03-SUMMARY.md  # signal_ledger feature_ts/feature_tf columns
  provides:
    - _build_intelligence_event() in historical_backfill.py
    - _event_to_sync_params() in historical_backfill.py
    - _insert_features_sync() in historical_backfill.py
    - _INSERT_FEATURE_SYNC_SQL constant
    - intelligence_features dual-write in replay_symbol()
    - feature_ts populated on signal_ledger when features row was written
  affects:
    - production/scripts/historical_backfill.py
    - tests/unit/test_historical_backfill.py
tech_stack:
  added: []
  patterns:
    - psycopg2.extras.execute_batch for intelligence_features (mirrors _insert_signals_sync pattern)
    - _pick() key filter for extra='forbid' Pydantic sub-models
    - try/except return None pattern for replay loop safety
key_files:
  created: []
  modified:
    - production/scripts/historical_backfill.py
    - tests/unit/test_historical_backfill.py
decisions:
  - "Use %s psycopg2 placeholders (not asyncpg $N) in _INSERT_FEATURE_SYNC_SQL"
  - "_pick() inner helper filters keys per sub-model before construction (required for extra='forbid' I3-I6 models)"
  - "feature_ts=ts on signal_ledger when features row was written — enables JOIN from signal to feature context"
  - "feature_ts=None remains backward-compatible for bars where _build_intelligence_event returns None"
  - "replay_symbol calls features insert before run_i7_and_persist (every MIN_BARS-qualified bar gets a feature row)"
metrics:
  duration: "~3 min (179 seconds)"
  completed: "2026-02-24"
  tasks_completed: 2
  files_modified: 2
  commits: 2
---

# Phase 3 Plan 1: Intelligence Features Write Path in Historical Backfill Summary

**One-liner:** Extended historical_backfill.py Stage 2 with psycopg2 dual-write to intelligence_features — using IntelligenceEvent construction with _pick() key filtering and feature_ts JOIN linkage on signal_ledger.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| RED | Add failing tests for intelligence_features write path | 21cb710 | tests/unit/test_historical_backfill.py |
| GREEN | Implement intelligence_features write path | 285960e | production/scripts/historical_backfill.py |

## What Was Built

### New constants and functions in `production/scripts/historical_backfill.py`

**`_INSERT_FEATURE_SYNC_SQL`** — Module-level SQL constant with `%s` psycopg2 placeholders (not asyncpg `$N`). Inserts 13 columns: `ts, symbol, tf, platform, source, schema_version, bar, i1, i3, i4, i5, smc, i6`. Uses `ON CONFLICT (ts, symbol, tf) DO NOTHING` for idempotent replays.

**`_build_intelligence_event(bar, i1_features, intelligence, symbol, tf, ts)`** — Builds a valid `IntelligenceEvent` from the flat pipeline dicts Stage 2 already produces per bar. Uses an inner `_pick(model_cls, src)` helper to filter keys before constructing each `extra='forbid'` sub-model (I3-I6). Entire body wrapped in `try/except Exception: return None` so the replay loop never crashes on validation failures. `source="backfill"` is always set.

**`_event_to_sync_params(event)`** — Serializes an `IntelligenceEvent` to a 13-element tuple. First element is the `datetime` ts (psycopg2 handles natively). Elements 6-12 are `json.dumps()` strings: `bar` and `i1` use `model_dump()` (include None); `i3-i6` use `model_dump(exclude_none=True)` for storage compactness.

**`_insert_features_sync(conn, rows)`** — Psycopg2 batch insert via `execute_batch`. No-op guard on empty list. Commits after batch.

### Updated functions

**`_build_ledger_entries()`** — Added `feature_ts: datetime | None = None` and `feature_tf: str | None = None` parameters. These pass through to `LedgerEntry` constructor, replacing the hardcoded `None, None`. Backward compatible — all existing callers continue working.

**`run_i7_and_persist()`** — Added `feature_ts` and `feature_tf` parameters, passed through to `_build_ledger_entries()`.

**`replay_symbol()` inner loop** — After `run_analysis_pipeline()`, calls `_build_intelligence_event()`, then conditionally calls `_insert_features_sync()`. Tracks `written_feature_ts` (set to `ts` on success, `None` on failure). Passes `written_feature_ts` and `feature_tf` to `run_i7_and_persist()`.

### New tests in `tests/unit/test_historical_backfill.py`

- **`TestBuildIntelligenceEvent`** (4 tests): None on exception, source=backfill on valid input, key filter prevents ValidationError on mixed dict, None on type error
- **`TestEventToSyncParams`** (3 tests): 13-element tuple, datetime first element, JSONB columns are strings
- **`TestInsertFeaturesSync`** (3 tests): execute_batch called with correct SQL, commit called, no-op on empty rows
- **`TestBuildLedgerEntriesFeatureTs`** (2 tests): feature_ts passthrough, feature_ts defaults to None

## Verification Results

```
tests/unit/test_historical_backfill.py: 23 passed (11 pre-existing + 12 new)
Full suite: 584 passed, 5 failed (all pre-existing failures — no regressions)
Smoke: _INSERT_FEATURE_SYNC_SQL uses %s not $N — OK
Smoke: _build_intelligence_event({}, {}, {}, ...) returns None — OK
```

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- [x] `production/scripts/historical_backfill.py` modified — verified (git show 285960e)
- [x] `tests/unit/test_historical_backfill.py` modified — verified (git show 21cb710)
- [x] RED commit `21cb710` exists — confirmed
- [x] GREEN commit `285960e` exists — confirmed
- [x] 23/23 tests pass in test_historical_backfill.py
- [x] No new failures in full suite
- [x] `_INSERT_FEATURE_SYNC_SQL` uses `%s` not `$N`
- [x] `_build_intelligence_event` returns None on empty input
