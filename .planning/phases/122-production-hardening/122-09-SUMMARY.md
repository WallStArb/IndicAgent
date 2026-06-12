---
phase: 122-production-hardening
plan: 09
subsystem: feature-replay, api-narrative
tags: [bug-fix, gap-closure, literal-type, column-reference]
dependency_graph:
  requires: [122-03, 122-07]
  provides: [feature_replay_produces_signals, narrative_i2_context_correct]
  affects: [feature_replay.py, narrative.py]
tech_stack:
  added: []
  patterns: [pydantic-literal-validation, jsonb-column-reference]
key_files:
  modified:
    - production/scripts/feature_replay.py
    - src/api/routes/narrative.py
decisions:
  - source='backfill' is the correct Literal value for stored-feature replay (not 'feature_replay')
  - narrative.py i2= field must use f.i2 column (holds all I2Events data post-migration 124)
metrics:
  duration: "~5 minutes"
  completed: "2026-06-12"
  tasks_completed: 2
  files_modified: 2
---

# Phase 122 Plan 09: Source Literal + Narrative I2 Column Fix Summary

Two one-line blockers from migration 124 gap analysis: invalid Literal value in feature_replay.py causing zero-signal output, and wrong column reference in narrative.py causing empty I2 tier context in all narrative generations.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix source literal in feature_replay.py | 0d450653 | production/scripts/feature_replay.py |
| 2 | Fix narrative route to select f.i2 | 71f862d5 | src/api/routes/narrative.py |

## Changes

### Task 1: feature_replay.py source literal

`_reconstruct_intelligence_event` passed `source="feature_replay"` to `IntelligenceEvent`. The field is typed as `Literal["live", "backfill"]` -- Pydantic raised `ValidationError` on every row reconstruction, silently completing with zero signals written to signal_ledger.

Fix: `source="feature_replay"` changed to `source="backfill"` at line 148.

### Task 2: narrative.py i2 column reference

`_SIGNAL_QUERY` selected `f.market_context` where `f.i2` was needed. Post-migration 124, the `i2` column holds all I2Events data (RSI, Stochastic, ADX, Volume, composite fields); `market_context` holds only cross_asset data. As a result every narrative generation received empty I2 tier context.

Two changes:
- `_SIGNAL_QUERY` line 163: `f.market_context` replaced with `f.i2`
- `_build_context_from_row` line 125: `row.get("market_context")` replaced with `row.get("i2")` for the `i2=` field

## Verification

All 5 plan acceptance criteria passed:
1. No `source="feature_replay"` in feature_replay.py
2. `source="backfill"` at line 148
3. `f.i2` in `_SIGNAL_QUERY` SELECT clause
4. `row.get("i2")` in `_build_context_from_row` i2= assignment
5. No `f.market_context` in the SELECT clause

Tests: 9/9 `test_narrative_route.py` + 7/7 `test_feature_replay.py` pass.

## Deviations from Plan

None -- plan executed exactly as written.

## Self-Check: PASSED

- [x] production/scripts/feature_replay.py exists and contains `source="backfill"`
- [x] src/api/routes/narrative.py exists and contains `f.i2` + `row.get("i2")`
- [x] Commit 0d450653 exists
- [x] Commit 71f862d5 exists
