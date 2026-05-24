---
phase: 105-architecture-hotfix-sprint
plan: 04
subsystem: intelligence
tags: [shadow-governance, signal-processing, executor, shadow-auditor, otel-metrics]

# Dependency graph
requires:
  - phase: 105-03
    provides: shadow metrics defined as point_gauge (.set() API)
provides:
  - is_shadow stamped on every signal dict before signal_writer persists it
  - shadow plugins excluded from select_winner via eligible_ranked
  - shadow signals marked regime_suppressed so lifecycle never activates them
  - shadow_auditor promotion gate counts shadow observations (is_shadow=TRUE)
  - shadow_auditor demotion gate counts only live signals (is_shadow=FALSE)
  - swarm agents skipped in shadow_auditor to prevent demotion counter resets
  - shadow metrics report point-in-time values via .set()
affects: [shadow-governance, signal-ledger, lifecycle-tracker, shadow-auditor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - eligible_ranked pattern: filter shadow plugins from winner candidates while keeping full ranked list for persistence
    - is_shadow stamp-then-filter pattern: executor stamps -> signal_processor filters -> auditor queries by is_shadow

key-files:
  created: []
  modified:
    - src/intelligence/pipeline/executor.py
    - src/intelligence/pipeline/signal_processor.py
    - services/shadow_auditor_agent.py

key-decisions:
  - "Promotion query uses is_shadow=TRUE (counts shadow plugin's own shadow observations toward n gate)"
  - "Demotion query uses is_shadow=FALSE (live-plugin demotion counts only live resolved signals)"
  - "Swarm agents skipped in _run_audit() by component_type check to prevent n=0 demotion counter resets"
  - "eligible_ranked excludes shadows from select_winner; full ranked list kept for signal_ledger persistence"
  - "Shadow signals receive status=regime_suppressed — lifecycle_tracker never activates this status"

patterns-established:
  - "is_shadow stamp-then-filter: executor stamps sig['is_shadow'] from shadow_cache; signal_processor builds eligible_ranked excluding shadows from winner; auditor queries by is_shadow direction"
  - "Point gauge .set() vs counter .add(): SHADOW_N_RESOLVED/WIN_RATE/EV_R/EV_CI_LOWER/DAYS_TO_GATE/PROMOTION_READY use .set(); TAIL_RISK_BLOCKED/TAIL_GATE_DB_ERROR are counters using .add()"

requirements-completed: []

# Metrics
duration: 10min
completed: 2026-05-24
---

# Phase 105 Plan 04: Shadow Signal Suppression Bypass Fix Summary

**Shadow-mode plugins blocked from live trading via is_shadow stamp in executor, eligible_ranked filter in signal_processor, and corrected is_shadow filter direction in shadow_auditor promotion/demotion queries**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-24T11:51:00Z
- **Completed:** 2026-05-24T11:53:40Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Executor now stamps `sig["is_shadow"]` on every emitted signal dict via `_is_shadow(plugin_name, shadow_cache)` so signal_writer_agent persists the correct is_shadow value to signal_ledger
- signal_processor builds `eligible_ranked` (shadow-excluded) for `select_winner()` while keeping the full `ranked` list for persistence — shadow plugins are observed but cannot win the live trade slot; shadow signals are marked `is_shadow=True` and `status="regime_suppressed"` before winner selection
- shadow_auditor promotion query adds `AND is_shadow = TRUE` (counts shadow observations toward n gate); demotion query adds `AND is_shadow = FALSE` (live signals only); swarm agents skipped via `component_type == "swarm_agent"` guard to prevent n=0 demotion counter resets; all 6 point-gauge SHADOW_* metrics changed from `.add()` to `.set()`

## Task Commits

Each task was committed atomically:

1. **Task 1: Stamp is_shadow in executor post-processing loop** - `414de7bb` (feat)
2. **Task 2: Filter shadows from select_winner and stamp non-live status** - `4cfabcc2` (feat)
3. **Task 3: Shadow auditor query filters, swarm skip, .set() metric calls** - `c5d27299` (fix)

## Files Created/Modified

- `src/intelligence/pipeline/executor.py` - Added `sig["is_shadow"] = self._is_shadow(task.plugin_name, cache_snapshot.shadow_cache)` in run_i7_complete post-processing loop
- `src/intelligence/pipeline/signal_processor.py` - Added shadow override loop (is_shadow=True, status=regime_suppressed) and eligible_ranked filter before select_winner
- `services/shadow_auditor_agent.py` - is_shadow=TRUE on promotion query, is_shadow=FALSE on demotion query, swarm_agent skip in _run_audit, all SHADOW_* point gauges changed to .set()

## Decisions Made

- Promotion gate uses `is_shadow = TRUE` because shadow plugins accumulate signal_ledger rows with is_shadow=TRUE — filtering FALSE would force n=0 and permanently block promotion
- Demotion gate uses `is_shadow = FALSE` because live-plugin demotion must evaluate only live (non-shadow) signals as evidence
- Shadow signals receive `status="regime_suppressed"` as the safe non-live status (lifecycle_tracker never activates this status per CLAUDE.md)
- `eligible_ranked` is built separately rather than filtering `ranked` in-place to preserve shadow observation data for the auditor's promotion gate

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-commit hook could not find ruff/black in worktree path (no `.venv` in worktree directory). Fixed by creating a symlink: `ln -s /home/bg/dev/indicagent/.venv .venv` in the worktree. Hook uses `${REPO_ROOT}/.venv/bin/ruff` where REPO_ROOT is the worktree's `git rev-parse --show-toplevel`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Shadow suppression bypass (HF-1, SG-1 through SG-7) fully resolved
- Shadow plugins now observed via signal_ledger (is_shadow=TRUE) but excluded from live trading
- Shadow auditor promotion/demotion gates use correct is_shadow filter direction
- Ready for remaining phase 105 plans

---
*Phase: 105-architecture-hotfix-sprint*
*Completed: 2026-05-24*
