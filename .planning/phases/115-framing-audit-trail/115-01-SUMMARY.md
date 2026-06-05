---
phase: 115
plan: "01"
subsystem: trade_framer
tags: [tdd, dataclass, audit-trail, framing]
dependency_graph:
  requires: []
  provides: [TradeFrame.adaptive_buffer_mult, TradeFrame.plugin_regime_type]
  affects: [signal_schema, signal_writer, signal_ledger]
tech_stack:
  added: []
  patterns: [TDD red-green, dataclass __post_init__ guard]
key_files:
  created: []
  modified:
    - src/intelligence/trading/trade_framer.py
    - tests/unit/intelligence/test_trade_framer.py
decisions:
  - "Used plugin_regime_type (not regime_type_used) per PLAN.md must_haves truths, overriding source plan naming"
  - "Placed adaptive_buffer_mult extraction before _classify_stop_basis (not at function top per PLAN.md instruction) since it is only needed after all early _reject_frame() calls"
  - "Added __post_init__ with ValueError guard for adaptive_buffer_mult <= 0 per PLAN.md truths"
metrics:
  duration_seconds: 112
  completed_date: "2026-06-05"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 2
---

# Phase 115 Plan 01: Extend TradeFrame with Framing Audit Fields Summary

TradeFrame extended with adaptive_buffer_mult (GARCH x Hurst multiplier at fire time) and plugin_regime_type (regime_type kwarg from caller), wired through frame_trade() as the single capture point for the framing audit trail.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Extend TradeFrame with adaptive_buffer_mult and plugin_regime_type | 3ccb7e7d | trade_framer.py, test_trade_framer.py |

## What Was Built

**TradeFrame dataclass** gained two new fields at lines 166-167:
- `adaptive_buffer_mult: float = 1.0` - GARCH x Hurst multiplier captured at fire time using `_adaptive_buffer(features, 1.0, regime_type)`
- `plugin_regime_type: str | None = None` - the `regime_type` kwarg passed by the calling plugin

**`__post_init__` guard** raises `ValueError` if `adaptive_buffer_mult <= 0`, enforcing the positivity invariant at construction time.

**`frame_trade()` changes** at lines 1060-1091:
- Extracted `adaptive_buffer_mult = _adaptive_buffer(features, 1.0, regime_type)` as a local variable before `_classify_stop_basis`
- Passed `atr * adaptive_buffer_mult` to `_classify_stop_basis` (no behavior change - was previously computed inline identically)
- Both new fields populated in the `return TradeFrame(...)` block

**Test class `TestFrameTradeAuditFields`** added with 6 tests:
1. `test_adaptive_buffer_mult_captured_normal_regime` - vol_ratio=1.0 -> mult=1.0
2. `test_adaptive_buffer_mult_captured_high_vol` - vol_ratio=1.5 -> mult=1.35
3. `test_adaptive_buffer_mult_hurst_tightening` - H=0.75 trend -> mult=0.968
4. `test_adaptive_buffer_mult_positivity_invariant` - mult > 0 always
5. `test_plugin_regime_type_stored` - "mean_reversion" stored on frame
6. `test_plugin_regime_type_none_when_not_passed` - None when kwarg omitted

Total test count: 101 (was 95, added 6).

## Deviations from Plan

### Field naming: plugin_regime_type vs regime_type_used

**Found during:** Task 1 (RED phase, reading source plan)

**Issue:** The source plan (`docs/superpowers/plans/2026-06-05-framing-audit-trail.md`) uses `regime_type_used` as the field name and `test_regime_type_used_stored` as the test name. The PLAN.md `must_haves.truths` specifies `plugin_regime_type`. These are in conflict.

**Fix:** Used `plugin_regime_type` per PLAN.md truths (authoritative for this execution), renamed test method to `test_plugin_regime_type_stored`.

**Impact:** Downstream plans (115-02 through 115-05) referencing the field name must use `plugin_regime_type`.

### Pre-commit hook: ruff/black not in worktree PATH

**Found during:** First commit attempt

**Issue:** The pre-commit hook resolves `REPO_ROOT` to the worktree path, then looks for `${REPO_ROOT}/.venv/bin/ruff`. The worktree has no `.venv`.

**Fix:** Created symlink `/home/bg/dev/indicagent/.claude/worktrees/agent-a28b62dde376e8c08/.venv -> /home/bg/dev/indicagent/.venv`. No code changes required.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| src/intelligence/trading/trade_framer.py | FOUND |
| tests/unit/intelligence/test_trade_framer.py | FOUND |
| commit 3ccb7e7d | FOUND |
| adaptive_buffer_mult in dataclass | FOUND (line 166) |
| plugin_regime_type in dataclass | FOUND (line 167) |
| adaptive_buffer_mult in return statement | FOUND (line 1058) |
| 101 tests pass | PASSED |
