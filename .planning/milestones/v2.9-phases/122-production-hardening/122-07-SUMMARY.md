---
phase: 122-production-hardening
plan: "07"
subsystem: replay
tags: [feature-replay, i7-only, deterministic-ids, shadow-setups]
dependency_graph:
  requires: [122-05, 122-06]
  provides: [feature_replay_script]
  affects: [signal_ledger, shadow_validation]
tech_stack:
  added: []
  patterns: [asyncpg-pool, semaphore-concurrency, jsonb-codec, on-conflict-upsert]
key_files:
  created:
    - production/scripts/feature_replay.py
    - tests/unit/scripts/test_feature_replay.py
  modified: []
decisions:
  - "frames dict uses merged flat features for all tier keys — mirrors run_historical_pipeline.py pattern, enables all I7 plugins to find features regardless of which key they read"
  - "bar_history deque omitted — documented limitation; state-dependent plugins use empty state; full pipeline mode required for HMM/Kalman state"
  - "ON CONFLICT SET updates only mutable fields (setup_plugin, direction, entry_price, stop_loss, raw_confidence, calibrated_confidence) — identity columns preserved for idempotency"
metrics:
  duration_minutes: 7
  tasks_completed: 2
  files_created: 2
  files_modified: 0
  completed_date: "2026-06-12"
---

# Phase 122 Plan 07: feature_replay.py Summary

I7-only replay script: reads intelligence_features JSONB tier columns, reconstructs IntelligenceEvent, runs I7 plugins, upserts signal_ledger — bypassing all I1-I6 compute. Reduces shadow signal regeneration from hours to minutes.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Scaffold feature_replay.py | bba71c16 | production/scripts/feature_replay.py |
| 2 | Static guard tests + shadow-setups wiring | b9001c6c | tests/unit/scripts/test_feature_replay.py |

## What Was Built

**`production/scripts/feature_replay.py`** — new CLI script:

- `_reconstruct_intelligence_event(row)`: reads i1/i2/i3/i4/i5/smc/cross_timeframe_context JSONB columns from asyncpg Record, constructs IntelligenceEvent; returns None on error (row skipped, not crashed)
- `_SELECT_FEATURES_SQL`: selects with new migration-125 column names only
- `_UPSERT_SIGNAL_SQL`: ON CONFLICT (signal_id, timestamp) DO UPDATE preserves identity columns; updates only mutable signal fields
- `_replay_symbol_tf()`: per-(symbol, tf) async loop; merges all tier dicts into flat features dict (same pattern as run_historical_pipeline.py); runs I7 plugins via registry; calls aggregate(); builds LedgerEntry objects; batch upserts via asyncpg executemany
- `main()`: asyncpg pool with JSONB codecs; semaphore-bounded concurrency (--workers); resolves plugins from TIER_I7 or --plugins or --shadow-setups; resolves symbols from CLI or get_active_contracts()

CLI flags: `--plugins`, `--symbols`, `--since`, `--workers`, `--shadow-setups`, `--dry-run`

**`tests/unit/scripts/test_feature_replay.py`** — 7 static guard tests:

- No I1-I6 compute imports (DAG isolation enforcement)
- No uuid4 (deterministic ID enforcement)
- ON CONFLICT SET excludes identity columns (idempotency enforcement)
- No legacy column names (migration-125 compliance)
- SELECT references all required tier column names
- All 6 CLI flags present

## Verification Results

```
python production/scripts/feature_replay.py --help   # exits 0, shows all 6 flags
grep run_analysis_pipeline|run_i7_and_persist|IntelligencePipeline|run_tiers  # zero matches
grep uuid4  # zero matches
--shadow-setups mode: 22 plugins from _SHADOW_VALIDATION_SETUPS  # correct
pytest tests/unit/scripts/test_feature_replay.py  # 7 passed
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Limitations

- `bar_history` deque not provided — plugins requiring multi-bar state (HMM regime) will use empty state. Re-run in full pipeline mode for state-dependent plugins.
- No `validate_intelligence_features_complete()` preflight (noted as optional in D-13 design spec; deferred to future plan).

## Self-Check

- [x] `production/scripts/feature_replay.py` exists
- [x] `tests/unit/scripts/test_feature_replay.py` exists
- [x] Commit bba71c16 exists
- [x] Commit b9001c6c exists
- [x] All 6 CLI flags present in --help output
- [x] Zero forbidden compute imports
- [x] Zero uuid4 usage
- [x] ON CONFLICT identity columns not in SET clause
