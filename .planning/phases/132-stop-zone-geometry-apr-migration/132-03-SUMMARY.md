---
phase: 132-stop-zone-geometry-apr-migration
plan: "03"
subsystem: trade_framer APR migration
tags: [apr, adaptive-buffer, garch, migration, regression-test]
dependency_graph:
  requires: ["132-02"]
  provides: ["_adaptive_buffer() fully APR-backed with anchor-point regression test"]
  affects: ["intelligence_pipeline prewarm", "trade_framer stop geometry", "ML parameter tuning surface"]
tech_stack:
  added: []
  patterns: ["_cfg() with local variable pre-read pattern for repeated calls in branches"]
key_files:
  created:
    - production/migrations/147_phase132_adaptive_buffer_apr.sql
  modified:
    - src/intelligence/trading/trade_framer.py
    - services/intelligence_pipeline.py
    - tests/unit/intelligence/test_trade_framer.py
decisions:
  - "Used migration 147 instead of plan-specified 145 — 145 already taken by db_optimization_indexes (Rule 3 auto-fix)"
  - "Read all 12 _cfg() values once into locals at function top to avoid repeated calls in piecewise branches"
  - "StrictMockConfigService raises ValueError for unknown keys (not silently returning default) to catch key typos"
  - "1.00 mathematical anchors in high-vol branch left as literals per plan spec — these are curve anchors, not tunable coefficients"
metrics:
  duration_minutes: 25
  completed: "2026-06-18"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
---

# Phase 132 Plan 03: Adaptive Buffer APR Migration Summary

Migrated the 12 piecewise GARCH vol-response curve coefficients inside `_adaptive_buffer()` to APR, wired the function body to read via `_cfg()`, and added an anchor-point regression test that proves byte-identical output at seed values under both the hardcoded-fallback and strict-mock-seed-config paths.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Write migration 147 + register in _THRESHOLD_KEYS | 6a1a7572 | production/migrations/147_phase132_adaptive_buffer_apr.sql, services/intelligence_pipeline.py |
| 2 | Wire _adaptive_buffer() body + hard cap via _cfg() | f8eda86e | src/intelligence/trading/trade_framer.py |
| 3 | Anchor-point regression test | 35983655 | tests/unit/intelligence/test_trade_framer.py |

## Outcomes

### Migration 147

- Seeds 12 piecewise coefficient keys in `config_schema` + `config_state` at exact current literals
- All 12 descriptions include: `[initial_estimate]`, "ML learning target", coupling warning ("tune as a group or preserve the piecewise structure")
- Denominator keys (`low_vol_slope_den`, `high_vol_slope_den`) have `min_value > 0` to prevent division by zero
- `config_history` records seeded with `changed_by='migration_147'`
- 12 keys registered in `_THRESHOLD_KEYS` in `services/intelligence_pipeline.py` under comment `# --- migration 147: Phase 132 adaptive buffer coefficients (coupled piecewise — tune as a group) ---`
- DB count verification: 12 coefficient keys + 1 hard_cap key = 13 total `adaptive_buffer_*` keys

### _adaptive_buffer() Rewrite

- `ADAPTIVE_BUFFER_HARD_CAP = 1.40` module-level constant removed
- All 12 piecewise coefficients + hard_cap read via `_cfg()` with seed values as fallbacks
- Local variable pattern: each coefficient read once at function top, used in piecewise math (no repeated `_cfg()` calls in branches)
- Piecewise structure identical: low-vol branch (vol_ratio <= 1.0), high-vol branch, Hurst tightening, GARCH shock floor
- `1.00` mathematical anchors in high-vol branch preserved as literals (curve anchors, not tunable)
- Module imports clean; `ruff` and `black` both pass

### Regression Test (`TestAdaptiveBufferAPRRegressionAnchorPoints`)

- 11 tests proving anchor-point identity
- `_StrictMockConfigService.get_sync()` raises `ValueError` for any unknown key — key typos fail loudly
- Tests cover: 5 vol_ratio anchor/interior points, GARCH shock floor, Hurst trend tightening, Hurst MR tightening, strict mock key-rejection
- Each assertion verified under both None-config (hardcoded fallback) and strict-mock-seed-config paths
- Both paths must produce identical output within `1e-9` relative tolerance
- Full unit suite: 4774 passed, 37 skipped

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking Issue] Migration number collision — used 147 instead of plan-specified 145**
- **Found during:** Task 1
- **Issue:** Plan file referenced migration 145, but `145_db_optimization_indexes.sql` already exists on disk in this worktree. The fix commit `1d74fe22` updated the plan to use 147, but the plan file in the worktree still showed 145 (the worktree was branched before that fix was applied to the worktree's copy).
- **Fix:** Used migration 147, which was the correct number per the fix commit and the intent of the plans 03/04/05 renaming.
- **Files modified:** `production/migrations/147_phase132_adaptive_buffer_apr.sql` (created with correct number)

## Verification

```
SELECT COUNT(*) FROM config_state 
WHERE config_key LIKE 'feature.trade_framer.adaptive_buffer\_%' ESCAPE '\'
  AND config_key != 'feature.trade_framer.adaptive_buffer_hard_cap';
-- Returns: 12

SELECT COUNT(*) FROM config_state 
WHERE config_key LIKE 'feature.trade_framer.adaptive_buffer\_%' ESCAPE '\';
-- Returns: 13

grep -nE "^ADAPTIVE_BUFFER_HARD_CAP *=" src/intelligence/trading/trade_framer.py
-- Returns: no output (constant removed)

grep -c '_cfg("feature.trade_framer.adaptive_buffer' src/intelligence/trading/trade_framer.py
-- Returns: 13 (12 coefficients + 1 hard cap)
```

## Self-Check: PASSED

All created files exist on disk. All 3 task commits found in git log.
- FOUND: production/migrations/147_phase132_adaptive_buffer_apr.sql
- FOUND: .planning/phases/132-stop-zone-geometry-apr-migration/132-03-SUMMARY.md
- FOUND commit 6a1a7572 (Task 1)
- FOUND commit f8eda86e (Task 2)
- FOUND commit 35983655 (Task 3)
