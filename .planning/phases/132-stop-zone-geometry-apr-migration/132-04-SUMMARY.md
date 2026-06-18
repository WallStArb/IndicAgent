---
phase: 132-stop-zone-geometry-apr-migration
plan: "04"
subsystem: trade_framer per-asset-class stop floor APR migration
tags: [apr, stop-geometry, per-class-floor, migration, regression-test]
dependency_graph:
  requires: ["132-03"]
  provides: ["_min_stop_multiplier_floor(asset_class) router applied in long+short stop calculation"]
  affects: ["intelligence_pipeline prewarm", "trade_framer stop geometry", "commodity stop floor (1.5 ATR)"]
tech_stack:
  added: []
  patterns: ["_min_stop_multiplier_floor mirrors _min_zone_width_atr exactly — universal default + per-class override when config_service wired"]
key_files:
  created:
    - production/migrations/148_phase132_stop_floor_per_class.sql
    - tests/unit/intelligence/test_trade_framer_stop_floor_per_class.py
  modified:
    - src/intelligence/trading/trade_framer.py
    - services/intelligence_pipeline.py
decisions:
  - "Migration number is 148 (not 146 as in original plan) — fix commit 1d74fe22 had updated plans 03/04/05 from 145/146 to 147/148; this worktree required a merge from main before executing to get Plan 02/03 changes"
  - "Unknown asset_class test uses None-config path (not strict mock) because strict mock raises on unknown keys by design; the production path falls back to ConfigService.get_sync returning the default, which can't be simulated by a raise-on-unknown mock"
  - "_min_stop_multiplier_floor docstring documents the 1-tick gate is below this floor and is a correctness invariant not a tunable (per CONTEXT D-02)"
metrics:
  duration_minutes: 15
  completed: "2026-06-18"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
---

# Phase 132 Plan 04: Per-Asset-Class Stop Floor APR Migration Summary

Added 4 per-asset-class minimum stop floor APR keys (migration 148), the `_min_stop_multiplier_floor(asset_class)` router function mirroring `_min_zone_width_atr`, applied it in `_resolve_stop_long` and `_resolve_stop_short`, and added 14 regression tests covering all 4 classes, the None/unknown fallback, and integration proofs.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Write migration 148 + register in _THRESHOLD_KEYS | 6d074a6d | production/migrations/148_phase132_stop_floor_per_class.sql, services/intelligence_pipeline.py |
| 2 | Add _min_stop_multiplier_floor router + apply in stop calculation | 42457714 | src/intelligence/trading/trade_framer.py |
| 3 | Per-class floor regression test | ad41a9f0 | tests/unit/intelligence/test_trade_framer_stop_floor_per_class.py |

## Outcomes

### Migration 148

- 4 per-class stop floor keys seeded in `config_schema` + `config_state` + `config_history`
- Seed values: `commodity_small_tick=1.5` (NG only 1.5x ATR/tick headroom), `fx/equity_etf/futures_large_tick=1.0`
- All descriptions include `[initial_estimate]`, "ML learning target", derivation note (empirical ATR/tick medians from 5M `intelligence_features` rows, 2026-06-17)
- `config_history` records: `changed_by='migration_148'`, `reason='Phase 132 A3 per-asset-class stop floor seed'`
- 4 keys registered in `_THRESHOLD_KEYS` in `services/intelligence_pipeline.py` under `# --- migration 148: Phase 132 A3 per-asset-class stop floors ---`
- DB count verification: 4 rows in `config_state WHERE config_key LIKE 'feature.trade_framer.stop_multiplier_floor.%'`

### _min_stop_multiplier_floor Router

- New function at line 177 of `trade_framer.py`, modeled exactly on `_min_zone_width_atr`
- Universal default: `_cfg("feature.trade_framer.min_stop_atr", 1.0)`
- Per-class override: `_cfg(f"feature.trade_framer.stop_multiplier_floor.{asset_class}", default)` when `asset_class and _config_service is not None`
- Applied in `_resolve_stop_long`: `asset_class = features.get("asset_class")`, then `_min_stop_multiplier_floor(asset_class)` replaces the inline `_cfg("feature.trade_framer.min_stop_atr", 1.0)` call
- Applied symmetrically in `_resolve_stop_short` (max_stop direction)
- At seed values: commodity stops widen (1.5x floor vs 1.0x universal), all other classes unchanged
- 1-tick gate (`validate_stop_against_zone`) and Phase 126 stop distance floor gate unchanged

### Regression Test (`test_trade_framer_stop_floor_per_class.py`)

- 14 tests covering:
  - `_min_stop_multiplier_floor` returns 1.5 for `commodity_small_tick`, 1.0 for `equity_etf`/`fx`/`futures_large_tick`
  - `_min_stop_multiplier_floor(None)` returns universal 1.0
  - Unknown class without ConfigService returns universal 1.0 (fallback path)
  - `_resolve_stop_long` with `asset_class="commodity_small_tick"` produces stop at or below `entry - 1.5*ATR`
  - `_resolve_stop_long` with `asset_class="equity_etf"` produces stop at or below `entry - 1.0*ATR`
  - Commodity stop is lower than FX stop at identical features (1.5 vs 1.0 floor)
  - `_resolve_stop_short` with `commodity_small_tick` produces max_stop at or above `entry + 1.5*ATR`
  - Tiny-ATR (0.001) still applies the 1.5x commodity floor correctly
  - Without ConfigService, universal 1.0 fallback applies for any asset_class
- STRICT mock ConfigService: `ValueError` for unknown keys to catch key typos at test time
- Full unit suite: 4815 passed, 37 skipped

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking Issue] Worktree behind main — merged Plans 01/02/03 changes before executing**
- **Found during:** Task 1 (pre-execution check)
- **Issue:** The worktree branch was created before Plans 01/02/03 were merged to main. The plan depends on Plan 03 (adaptive buffer APR wiring). The worktree had none of those changes.
- **Fix:** `git merge 285a95ba` (main HEAD) brought in 30 files including trade_framer.py APR rewrites, migrations 146+147, and the existing test regressions. Fast-forward merge, no conflicts.
- **Files modified:** All Plan 02/03 files (via merge)
- **Migration note:** Plan 04's migration is 148 (not 146 as in the original plan frontmatter) because the fix commit `1d74fe22` had already renumbered plan 04 from 146 to 148.

**2. [Rule 3 - Blocking Issue] .venv symlink for worktree pre-commit hook**
- **Found during:** Task 1 commit
- **Issue:** Pre-commit hook uses `${REPO_ROOT}/.venv/bin/ruff` where `REPO_ROOT` resolves to the worktree path. No `.venv` exists in the worktree.
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv .venv` in worktree root. Symlink not committed (`.venv` is gitignored).
- **Impact:** Pre-commit passed cleanly for all subsequent commits.

## Self-Check

Verified before creating this SUMMARY.
