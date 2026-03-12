---
phase: 28-dashboard-completion
plan: 05
subsystem: ui
tags: [dashboard, react, typescript, signals, drill-panel, fetch, sse]

# Dependency graph
requires:
  - phase: 28-dashboard-completion/28-04
    provides: GET /api/signals/recent endpoint with DB signals and setup_performance JOIN

provides:
  - DrillPanel fetches /api/signals/recent on mount; DB-backed signal history on fresh panel open
  - Summary line above RecentSignals (n_resolved, win_rate, avg_pnl_r, n_suppressed)
  - Merged SSE + DB signal list deduplicated by signal_id (SSE wins)
  - Per-signal setup performance annotation (30d win rate + avg pnl_r when available)
  - setup_win_rate and setup_avg_pnl_r optional fields on SignalData type

affects: [28-dashboard-completion, signal-display, types.ts consumers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DB+SSE merge pattern: fetch DB on mount, merge with live SSE state, SSE wins on same signal_id"
    - "Non-fatal fetch: .catch(() => {}) on API call — SSE history still works if DB fetch fails"

key-files:
  created: []
  modified:
    - dashboard/src/components/drill-panel.tsx
    - dashboard/src/lib/types.ts

key-decisions:
  - "Summary line conditioned on n_resolved > 0 || n_suppressed > 0 — not shown for brand-new symbols with no history"
  - "Setup perf annotation omits null setup_win_rate silently — absence means < 30 samples, no placeholder shown"
  - "mergedSignalsHistory sorted by signal_computed_at DESC so newest signals appear first regardless of source"

patterns-established:
  - "DB+SSE merge: DB provides history on fresh load; SSE provides live updates; deduplicate by signal_id"

requirements-completed: [DASH-03]

# Metrics
duration: 2min
completed: 2026-03-12
---

# Phase 28 Plan 05: Drill Panel DB Signal History Summary

**DrillPanel fetches /api/signals/recent on mount with DB+SSE dedup merge, summary line, and per-signal setup perf annotation**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-12T21:35:56Z
- **Completed:** 2026-03-12T21:37:57Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- DrillPanel now fetches DB-backed signal history on mount — resolves empty-on-first-load problem
- Summary line above RecentSignals: "14 resolved · 57% win · avg +0.31R · 8 suppressed" with correct green/red/amber coloring
- SSE+DB merge deduplicates by signal_id with SSE winning — live lifecycle state always takes precedence
- Per-signal setup win rate + avg pnl_r annotation shown when 30d sample data available; hidden when null

## Task Commits

1. **Task 1: Add DB fetch, merge, summary display, and per-signal setup perf** - `869ccdd` (feat)

**Plan metadata:** committed with docs commit below

## Files Created/Modified

- `dashboard/src/components/drill-panel.tsx` - Added DbSignalRow/SignalWindowSummary interfaces, dbRowToSignalData helper, useState/useEffect for DB fetch, useMemo merge, summary line JSX, per-signal setup perf annotation
- `dashboard/src/lib/types.ts` - Added `setup_win_rate?: number` and `setup_avg_pnl_r?: number` optional fields to SignalData

## Decisions Made

- Summary line is conditional on `n_resolved > 0 || n_suppressed > 0` to avoid showing an empty placeholder on brand-new symbols
- Setup perf annotation omits null `setup_win_rate` silently — absence means < 30 samples, plan specifies no placeholder
- Merged list sorted by `signal_computed_at ?? timestamp` DESC so newest signals from either source appear first

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Drill panel DB history complete — plan 28-05 done
- Remaining phase 28 plans: 28-01, 28-02, 28-03, 28-07 (from git status untracked files)

---
*Phase: 28-dashboard-completion*
*Completed: 2026-03-12*
