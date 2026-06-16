---
phase: "130"
plan: "06"
subsystem: "script-rewriting"
tags: ["3-table-schema", "signal_events", "trade_frames", "trade_executions", "backfill", "lifecycle", "replay"]
dependency_graph:
  requires: ["130-02", "130-03"]
  provides: ["signal_events+trade_frames inserts from backfill", "lifecycle status updates via signal_events", "feature_replay G0 grouping"]
  affects: ["signal_events", "trade_frames", "trade_executions"]
tech_stack:
  added: []
  patterns: ["G0 grouping (one signal_events + one trade_frames per signal)", "uuid5 deterministic frame_id + execution_id", "direction int-to-text conversion", "asyncpg transaction wrapping"]
key_files:
  created: []
  modified:
    - "production/scripts/run_historical_pipeline.py"
    - "production/scripts/lifecycle_replay.py"
    - "production/scripts/feature_replay.py"
    - "tests/unit/scripts/test_run_historical_pipeline.py"
    - "tests/unit/scripts/test_feature_replay.py"
decisions:
  - "_seed_orphan_outcomes converted to no-op: signal_events inserts status='pending' at creation, so orphan seeding is unnecessary in 3-table schema"
  - "execution_id = uuid5(NAMESPACE_DNS, '{signal_id}:zone') for zone exits and ':market' for market exits - deterministic across re-runs"
  - "frame_details JSONB archives stop architecture fields (stop_basis, entry_zone_low/high, etc.) that were direct columns in signal_outcomes"
  - "direction conversion: int 1/-1 on write to signal_events (text long/short); reverse conversion on read in lifecycle_replay for evaluate_signal() compat"
  - "target_price wrapped as [float(tp)] list for evaluate_signal() backward compat"
  - "counterfactual_pnl_r = NULL (v2.11 CounterfactualTracker not in Phase 130 scope)"
metrics:
  duration_minutes: 180
  completed_date: "2026-06-16"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 5
---

# Phase 130 Plan 06: Script Rewriting - 3-Table Schema Summary

One-liner: Three backfill/replay scripts rewritten from signal_ledger+signal_outcomes monolith to signal_events+trade_frames+trade_executions with G0 grouping, uuid5 deterministic IDs, and direction text conversion.

## What Was Built

### Task 1: run_historical_pipeline.py (commit e053715b)

Replaced the legacy `_INSERT_SYNC_SQL` + `_INSERT_OUTCOMES_SQL` pair with:

- `_INSERT_SIGNAL_EVENTS_SYNC_SQL`: 26-column INSERT with `ON CONFLICT (signal_id, ts) DO NOTHING`
- `_INSERT_TRADE_FRAMES_SYNC_SQL`: 14-column INSERT with `ON CONFLICT (frame_id) DO NOTHING`
- `_INSERT_SIGNAL_EVENTS_SYNC_TEMPLATE` / `_INSERT_TRADE_FRAMES_SYNC_TEMPLATE` for psycopg2 `execute_values`
- `_direction_text(int) -> str` helper (1 -> "long", -1 -> "short")
- `_make_frame_id(signal_id, entry_type)` -> `str(uuid5(NAMESPACE_DNS, f"{signal_id}:{entry_type}"))`

`_insert_signals_sync()` now builds two param lists per entry and calls `execute_values` twice (signal_events then trade_frames) in a single cursor context. `is_backfill=TRUE` is embedded as a SQL literal in the template. `counterfactual_pnl_r=NULL` similarly embedded. Status starts as `'pending'`.

`--clean` path updated: DELETE trade_executions (via subquery), then trade_frames, then signal_events. `_assert_backfill_integrity()` queries the new tables.

### Task 2: lifecycle_replay.py + feature_replay.py (commit 74bb2356)

**lifecycle_replay.py:**
- `_seed_orphan_outcomes()` converted to a no-op logger - signal_events already has `status='pending'` at insert time
- `reset_corrupt_window()`: DELETEs trade_executions + resets trade_frames frame_details + UPDATEs signal_events.status back to 'pending'
- `_fetch_work_queue()`: queries signal_events instead of signal_outcomes
- Main SELECT in `_process_symbol_tf()`: JOIN signal_events + trade_frames, extracts stop fields from `tf.frame_details->>'entry_zone_low'` etc.
- Added reverse direction conversion (`text -> int`) for `evaluate_signal()` compatibility
- Added `target_price` -> `targets` list wrapping for `evaluate_signal()` compatibility
- `_flush_writes()`: activation = UPDATE signal_events status + JSONB merge into trade_frames.frame_details; zone/market exits = INSERT trade_executions with uuid5 execution_id; ON CONFLICT DO NOTHING
- `_run_validate()` + `_verify_replay()`: query signal_events + trade_frames + trade_executions

**feature_replay.py:**
- Replaced `_UPSERT_SIGNAL_SQL` + `_UPSERT_OUTCOMES_SQL` with asyncpg-parameterized `_INSERT_SIGNAL_EVENTS_SQL` + `_INSERT_TRADE_FRAMES_SQL`
- Write section wrapped in `async with conn.transaction()` for atomicity
- Same G0 pattern: one signal_events + one trade_frames row per replay entry
- Same uuid5 `frame_id` derivation as run_historical_pipeline
- `ON CONFLICT (signal_id, ts) DO NOTHING` + `ON CONFLICT (frame_id) DO NOTHING` for idempotency

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Unit tests referenced removed SQL constants**
- **Found during:** Task 2 verification run
- **Issue:** `TestCISColumnsInSQL` imported `_INSERT_SYNC_SQL`, `_INSERT_SYNC_TEMPLATE` (now replaced); `test_insert_signals_sync_params_include_cis_nulls` expected a 34-element tuple and imported from `signal_ledger_repository`; `test_feature_replay.py::test_on_conflict_identity_columns_not_in_set` expected old DO UPDATE SET pattern; `test_insert_signals_sync_writes_cis_fields` expected 34-element tuple + signal_outcomes row
- **Fix:** Rewrote all 5 affected tests to use `_INSERT_SIGNAL_EVENTS_SYNC_SQL`, `_INSERT_SIGNAL_EVENTS_SYNC_TEMPLATE`, `_INSERT_TRADE_FRAMES_SYNC_SQL`, `_INSERT_TRADE_FRAMES_SYNC_TEMPLATE`; updated assertions for 25-element signal_events tuple and 13-element trade_frames tuple; updated imports to `signal_events_repository`
- **Files modified:** `tests/unit/scripts/test_run_historical_pipeline.py`, `tests/unit/scripts/test_feature_replay.py`
- **Commit:** 74bb2356

### Scope Discovery: feature_replay.py

As noted in 130-RESEARCH.md Pitfall 3, `feature_replay.py` was not listed in the plan's D-09 context section but writes to `signal_ledger` / `signal_outcomes`. It was brought into scope and rewritten alongside `lifecycle_replay.py` in Task 2. This is consistent with the plan's objective ("all three historical backfill/replay scripts").

## Self-Check

**Files exist:**
- `production/scripts/run_historical_pipeline.py` - FOUND
- `production/scripts/lifecycle_replay.py` - FOUND
- `production/scripts/feature_replay.py` - FOUND
- `tests/unit/scripts/test_run_historical_pipeline.py` - FOUND
- `tests/unit/scripts/test_feature_replay.py` - FOUND

**Commits exist:**
- e053715b (Task 1: run_historical_pipeline.py rewrite) - FOUND
- 74bb2356 (Task 2: lifecycle_replay + feature_replay + tests) - FOUND

**Test results:** 4748 passed, 37 skipped, 0 failures

## Self-Check: PASSED
