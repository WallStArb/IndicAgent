---
phase: 22-i8-narrative-three-tier-redesign
plan: "04"
subsystem: ui
tags: [typescript, dashboard, sse, narrative, langgraph, nextjs]

# Dependency graph
requires:
  - phase: 22-i8-narrative-three-tier-redesign
    provides: 22-03 published narrative_type field on narratives Redis stream
provides:
  - Updated NarrativeData TypeScript interface with action_tag, narrative_short, narrative_deep, signal_id
  - SSE handler that routes short/deep narrative events into merged state per symbol+tf key
affects:
  - 22-05-narrative-panel (consumes NarrativeData.narrative_short, .narrative_deep, .action_tag)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Spread-merge pattern for SSE state updates — short and deep arrive independently, merged into same Record key
    - narrativeType routing — payload.narrative_type ?? 'short' guards both write paths

key-files:
  created: []
  modified:
    - dashboard/src/lib/types.ts
    - dashboard/src/hooks/use-market-stream.ts

key-decisions:
  - "narrative?: string kept as optional backward-compat alias — set when narrative_type === 'short', reads as undefined when only deep has arrived"
  - "action_tag required (not optional) in NarrativeData — always set from signal bar deterministic logic, no loading state needed"
  - "signal_id optional in NarrativeData — correlates short+deep pair; absent for old-format events without this field"

patterns-established:
  - "Spread-merge SSE pattern: existing = prev[key] ?? defaults; return {...prev, [key]: {...existing, ...newFields}} — enables partial updates from async arrivals"

requirements-completed:
  - I8-05
  - I8-09

# Metrics
duration: 2min
completed: 2026-03-09
---

# Phase 22 Plan 04: Dashboard Types and SSE Handler for Three-Tier Narratives Summary

**NarrativeData interface extended with action_tag, narrative_short, narrative_deep, signal_id; SSE handler routes narrative_type='short'/'deep' into merged per-symbol state via spread pattern**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-09T12:25:43Z
- **Completed:** 2026-03-09T12:27:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Added `action_tag: string`, `narrative_short?: string`, `narrative_deep?: string`, `signal_id?: string` to NarrativeData interface
- Kept `narrative?: string` for backward compat (set when narrative_type is 'short')
- Updated SSE `narrative_data` handler to read `payload.narrative_type` (defaults to 'short')
- Short events set both `narrative_short` and `narrative` (compat alias); deep events set `narrative_deep` only
- Both arrive independently and merge into the same `{sym}:{tf}` key via spread pattern
- Group narrative path unchanged
- TypeScript compiles with zero errors

## Task Commits

1. **Task 1: Update NarrativeData interface and SSE handler** - `0fa7fd1` (feat)

**Plan metadata:** (to follow in final commit)

## Files Created/Modified
- `dashboard/src/lib/types.ts` - NarrativeData interface extended with three-tier fields
- `dashboard/src/hooks/use-market-stream.ts` - narrative_data SSE handler updated to merge short/deep

## Decisions Made
- `narrative?: string` stays optional (not removed) — existing components like `narrative-elevated.tsx` access it; will be updated by 22-05
- `action_tag: string` required rather than optional — always available from signal bar, no shimmer needed
- Used spread-merge pattern (`{...existing, ...newFields}`) rather than overwrite — preserves whichever tier arrived first

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Types and SSE handler ready for 22-05 narrative panel UI update
- `narrative_short`, `narrative_deep`, `action_tag` all accessible from `narratives` state
- No blockers

---
*Phase: 22-i8-narrative-three-tier-redesign*
*Completed: 2026-03-09*
