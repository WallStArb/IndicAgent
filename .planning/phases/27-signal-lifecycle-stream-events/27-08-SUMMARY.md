---
phase: 27-signal-lifecycle-stream-events
plan: 08
subsystem: ui
tags: [react, nextjs, dashboard, signal-lifecycle, outcome-badge]

# Dependency graph
requires:
  - phase: 27-signal-lifecycle-stream-events plan 07
    provides: OutcomeBadge component and SignalPanel wrapper in signal-panel.tsx
provides:
  - OutcomeBadge wired into signal-banner.tsx (resolved state: opacity-50 + badge)
  - signal-panel.tsx trimmed to OutcomeBadge-only export (SignalPanel deleted)
  - drill-panel.tsx RecentSignalCard uses shared OutcomeBadge (inline badge deleted)
affects: [phase-28-dashboard-completion]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "OutcomeBadge as shared primitive: single implementation imported by both signal-banner and drill-panel"
    - "Resolved-signal dimming: opacity-50 wrapper div around button in signal-banner"

key-files:
  created: []
  modified:
    - dashboard/src/components/signal-banner.tsx
    - dashboard/src/components/signal-panel.tsx
    - dashboard/src/components/drill-panel.tsx

key-decisions:
  - "signal-panel.tsx is the canonical home for OutcomeBadge — file retained as ~41-line utility, not deleted"
  - "Resolved state in signal-banner: opacity-50 wrapping div + OutcomeBadge inside button row (left-aligned before direction icon)"
  - "drill-panel.tsx inline badge replaced with shared OutcomeBadge — intentional trade-off: shared bg-green-600/red-600 vs old CSS var colors"
  - "small prop added to OutcomeBadge (4a21000) for compact banner rendering based on human verify feedback"
  - "signal-banner redesigned to two-line layout (088580d) based on operator UI feedback during verification — trade info line 1, zone/timing line 2"

patterns-established:
  - "Shared badge pattern: outcome display uses OUTCOME_LABEL_MAP from signal-panel.tsx exclusively"

requirements-completed: [SLES-02, SLES-03]

# Metrics
duration: ~45min
completed: 2026-03-12
---

# Phase 27 Plan 08: OutcomeBadge Wiring Summary

**Single canonical OutcomeBadge wired into signal-banner (resolved dimming + badge) and drill-panel (inline badge eliminated) — phase 27 gap closed**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-03-12T12:06:13Z
- **Completed:** 2026-03-12
- **Tasks:** 3/3 complete (2 auto + 1 human-verify — approved)
- **Files modified:** 3

## Accomplishments
- signal-banner.tsx renders resolved signal state: 50% opacity wrapper + OutcomeBadge in button row
- signal-panel.tsx stripped from 164 lines to 41 lines — SignalPanel component and SignalPanelProps deleted, only OutcomeBadge exported
- drill-panel.tsx RecentSignalCard uses shared OutcomeBadge; inline badge JSX const and `_outcomeLabel` helper deleted
- Zero duplicate badge implementations remain in codebase

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire OutcomeBadge into signal-banner + trim signal-panel** - `6c75754` (feat)
2. **Task 2: Replace inline badge in drill-panel with shared OutcomeBadge** - `4268ced` (feat)
3. **Task 3: Human verify** - APPROVED; UI feedback actioned in `4a21000` (small prop) and `088580d` (two-line banner layout)

## Files Created/Modified
- `dashboard/src/components/signal-banner.tsx` - Added OutcomeBadge import, opacity-50 wrapper div, conditional badge render when signal.resolved
- `dashboard/src/components/signal-panel.tsx` - Deleted SignalPanel + SignalPanelProps; now exports only OutcomeBadge (~41 lines)
- `dashboard/src/components/drill-panel.tsx` - Added OutcomeBadge import, deleted inline outcomeBadge const and _outcomeLabel helper, added shared OutcomeBadge in RecentSignalCard

## Decisions Made
- Retained signal-panel.tsx as the canonical home for OutcomeBadge rather than moving it elsewhere — clean single-responsibility file
- Used opacity-50 wrapper div (not class on button) in signal-banner so the dim applies to the entire clickable area without conflicting with the button's style prop

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pre-existing TooltipContent type error in drill-panel.tsx**
- **Found during:** Task 1 build verification
- **Issue:** Two `tooltip` props in `SignalDetail` used raw string literals; `TooltipContent` interface requires `{ description: string; context: string | null }` — TypeScript error blocking build
- **Fix:** Converted both strings to proper `{ description, context: null }` objects
- **Files modified:** `dashboard/src/components/drill-panel.tsx`
- **Verification:** `npm run build` exits 0 with zero TypeScript errors
- **Committed in:** `6c75754` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug)
**Impact on plan:** Pre-existing TypeScript error in unrelated function was blocking the build; fix was necessary for correctness.

## Issues Encountered
None beyond the pre-existing TypeScript error documented above.

## Next Phase Readiness
- Phase 27 gap fully closed: OutcomeBadge single implementation, signal-banner renders resolved state, human verified
- Phase 27 VERIFICATION.md truth #2 satisfied: dashboard renders resolved signal as dimmed + outcome badge in primary signal view
- Phase 28 (Dashboard Completion) ready to proceed — OutcomeBadge available at `@/components/signal-panel`

---
*Phase: 27-signal-lifecycle-stream-events*
*Completed: 2026-03-12*
