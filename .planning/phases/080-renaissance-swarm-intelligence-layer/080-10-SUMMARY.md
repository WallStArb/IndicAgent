---
phase: "080"
plan: "10"
subsystem: "core/ai"
tags:
  - bug-fix
  - base-group-service
  - context-seeding
  - intelligence-tiers
dependency_graph:
  requires:
    - "src/core/ai/base_group_service.py"
  provides:
    - "Full tier column coverage in _seed_context_cache SELECT"
  affects:
    - "src/core/ai/context.py (seed_from_db_row consumer)"
    - "All AI agents declaring tiers_needed with I2, I3, I5, or SMC"
tech_stack:
  added: []
  patterns:
    - "asyncpg conn.fetch with full JSONB column list"
key_files:
  modified:
    - "src/core/ai/base_group_service.py"
  created: []
decisions:
  - "One-line SQL fix only — seed_from_db_row() was already correct; bug was purely in SELECT list"
  - "No schema change required — intelligence_features already stores i2/i3/i5/smc columns"
metrics:
  duration: "5 minutes"
  completed: "2026-05-07"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
  files_created: 0
---

# Phase 080 Plan 10: Fix _seed_context_cache Tier Column Coverage Summary

**One-liner:** Fixed `_seed_context_cache` SQL SELECT to include all 8 tier columns (i1-i7, smc), unblocking agents that declare I2/I3/I5/SMC in `tiers_needed` from receiving context on startup.

## What Was Done

`BaseGroupService._seed_context_cache()` had a SELECT list that only fetched 4 of 8 tier columns (`i1, i4, i6, i7`). This silently starved any AI agent that declared `tiers_needed` containing `I2`, `I3`, `I5`, or `SMC` — those agents would receive `None` for those tiers on startup and compute as if no prior context existed.

The fix adds the missing 4 columns (`i2, i3, i5, smc`) to the SELECT list. The downstream consumer `seed_from_db_row()` in `context.py` was already calling `row.get("i2")`, `row.get("i3")`, `row.get("i5")`, `row.get("smc")` — so no other change was needed.

## Tasks

| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Fix `_seed_context_cache` SELECT to include i2, i3, i5, smc | 165ac733 | Done |

## Deviations from Plan

None — plan executed exactly as written.

## Verification

- `grep -c "i1, i2, i3, i4, i5, i6, i7, smc" src/core/ai/base_group_service.py` returns `1`
- `grep "symbol, tf, ts, bar" src/core/ai/base_group_service.py` shows the full column list
- `ruff check src/core/ai/base_group_service.py` exits 0
- `black --check src/core/ai/base_group_service.py` exits 0

## Self-Check: PASSED

- File modified: `src/core/ai/base_group_service.py` — confirmed present
- Commit `165ac733` — confirmed in git log
