---
phase: 27-signal-lifecycle-stream-events
plan: 10
subsystem: ui
tags: [react, typescript, sse, dashboard, signals]

# Dependency graph
requires:
  - phase: 27-signal-lifecycle-stream-events
    provides: SSE snapshot fix (27-09) that seeds signalsByTf on reconnect, making REST seed redundant
provides:
  - setSignalsHistory update on dir===0 terminal events so RecentSignalCard shows OutcomeBadge
affects: [dashboard, use-market-stream, drill-panel, signal history]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Terminal event handler (dir===0) updates both signalsByTf and signalsHistory atomically — resolved signals carry outcome+exit_price into history"

key-files:
  created: []
  modified:
    - dashboard/src/hooks/use-market-stream.ts

key-decisions:
  - "REST seed (fetchActiveSignals) added in Task 1 then reverted in fc1fb6c — 27-09 SSE snapshot fix already seeds signalsByTf on mount/reconnect, making the REST seed redundant; revert is intentional"
  - "setSignalsHistory update in dir===0 branch is unconditional — updates history even when the current active signal was replaced by a newer birth (handles stale-signal edge case)"

patterns-established:
  - "Terminal resolution pattern: dir===0 branch calls setSignalsHistory before touch() to propagate outcome badges to drill panel history"

requirements-completed: [LIFE-02, LIFE-03]

# Metrics
duration: ~20min
completed: 2026-03-12
---

# Phase 27 Plan 10: Dashboard Signal Refresh and OutcomeBadge Summary

**`setSignalsHistory` update on terminal SSE events so drill panel history entries display OutcomeBadge for resolved signals**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-03-12
- **Completed:** 2026-03-12
- **Tasks:** 3 (including checkpoint)
- **Files modified:** 1

## Accomplishments

- Terminal event handler (`dir===0`) now calls `setSignalsHistory` to replace the matching history entry with `resolved:true`, `outcome`, and `exit_price` — enabling `OutcomeBadge` rendering in `RecentSignalCard`
- REST seed (`fetchActiveSignals`) was added then intentionally reverted: 27-09's SSE snapshot fix already seeds `signalsByTf` on mount, making the REST seed redundant
- TypeScript compiles cleanly with no new errors
- Human verified: dashboard shows signals on refresh; drill panel history shows `OutcomeBadge` for resolved signals

## Task Commits

Each task was committed atomically:

1. **Task 1: Add fetchActiveSignals REST seed on mount** - `851ad5a` (feat) — later reverted: `fc1fb6c`
2. **Task 2: Update signalsHistory on terminal event resolution** - `007101c` (feat)
3. **Task 3: Human verify signal refresh and resolved OutcomeBadge** - checkpoint approved

## Files Created/Modified

- `dashboard/src/hooks/use-market-stream.ts` — `dir===0` branch now calls `setSignalsHistory` to update resolved signal history entries with outcome+exit_price

## Decisions Made

- REST seed revert (`fc1fb6c`) is intentional: 27-09's SSE snapshot fix already handles signal seeding on mount/reconnect via the SSE cursor mechanism. Adding a REST seed would have been redundant and introduced duplicate seeding logic.
- The `setSignalsHistory` call in the `dir===0` branch is unconditional (no guard on whether the signal is the current active signal). This is correct because history entries may persist even after the active signal slot is replaced by a newer birth.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Reverted redundant REST seed after recognizing 27-09 already covers it**
- **Found during:** Task 1 (Add fetchActiveSignals REST seed on mount)
- **Issue:** 27-09's SSE snapshot fix already seeds `signalsByTf` on mount via cursor replay — the REST seed duplicated this and would have caused double-population
- **Fix:** Reverted Task 1 commit (`fc1fb6c`); Task 2 (history update on resolution) is the lasting net change
- **Files modified:** `dashboard/src/hooks/use-market-stream.ts`
- **Verification:** TypeScript clean; human verified dashboard shows correct behavior
- **Committed in:** `fc1fb6c` (revert commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — recognized and reverted redundant work)
**Impact on plan:** Revert is correct. Net result is cleaner than the original plan: history resolution via SSE terminal events works without any REST seed.

## Issues Encountered

None beyond the intentional revert described above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Gap 2 (signalsHistory not updated on resolution) is now closed
- Gap 3B (signals not seeded on refresh) is covered by 27-09's SSE snapshot fix
- Phase 27 gap closure complete — both LIFE-02 and LIFE-03 satisfied

---
*Phase: 27-signal-lifecycle-stream-events*
*Completed: 2026-03-12*
