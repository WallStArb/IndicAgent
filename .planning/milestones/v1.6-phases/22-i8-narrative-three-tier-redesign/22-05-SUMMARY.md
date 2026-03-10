---
phase: 22-i8-narrative-three-tier-redesign
plan: "05"
subsystem: ui
tags: [react, typescript, dashboard, narrative, ux]

# Dependency graph
requires:
  - phase: 22-i8-narrative-three-tier-redesign
    plan: "04"
    provides: "NarrativeData with action_tag, narrative_short, narrative_deep fields; spread-merge SSE handler"
provides:
  - "Three-tier NarrativeCard: action_tag badge + narrative_short primary text + expand/collapse narrative_deep"
  - "Skeleton loading states for narrative_short and narrative_deep while LLM responds"
  - "Expand/collapse toggle with '▼ Full analysis' / '▲ Hide analysis' labels"
affects:
  - dashboard-consumers
  - i8-narrative-rendering

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "useState expand toggle pattern — local boolean toggled via setExpanded(e => !e)"
    - "Skeleton pulse div (bg-white/5 rounded animate-pulse) as loading placeholder for async LLM text"
    - "Tier-derivation pattern: shortText = narrative_short ?? narrative (backward compat fallback)"

key-files:
  created: []
  modified:
    - dashboard/src/components/narrative-panel.tsx

key-decisions:
  - "action_tag badge uses text-xs font-mono text-amber-400 — amber mono distinguishes machine-generated instruction from narrative prose"
  - "Expand button only rendered when shortText is present — prevents orphaned toggle when no narrative has arrived"
  - "narrative_short ?? narrative fallback preserves backward compatibility for consumers that haven't migrated to three-tier fields"
  - "Deep skeleton is h-12 (larger than short skeleton h-8) — signals deeper content to come without layout shift"

patterns-established:
  - "Skeleton as async loading state: render placeholder div when field is null but parent context is present"
  - "Tiered text derivation: always derive from new field, fall back to legacy field, render skeleton if both absent"

requirements-completed:
  - I8-05
  - I8-06

# Metrics
duration: ~30min
completed: 2026-03-09
---

# Phase 22 Plan 05: Three-Tier Narrative Panel Summary

**NarrativeCard redesigned with action_tag amber badge, narrative_short primary text with skeleton loading, and expand/collapse deep narrative — completing the I8 UI layer of the three-tier redesign.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-03-09T08:00:00Z
- **Completed:** 2026-03-09T08:39:12Z
- **Tasks:** 1 auto + 1 human-verify
- **Files modified:** 1

## Accomplishments
- NarrativeCard renders action_tag as amber mono badge above narrative text (immediate, from signal data, no LLM wait)
- narrative_short shown as primary text with skeleton placeholder when not yet arrived
- Expand/collapse toggle button below short text reveals narrative_deep slot (text or skeleton)
- Backward-compatible fallback: `shortText = narrative_short ?? narrative` preserves existing narrative field consumers
- TypeScript compiles clean; user approved visual layout

## Task Commits

Each task was committed atomically:

1. **Task 1: Update NarrativeCard with three-tier layout** - `9302c7b` (feat)
2. **Task 2: Human verification** - approved by user

## Files Created/Modified
- `dashboard/src/components/narrative-panel.tsx` - Three-tier NarrativeCard: action_tag badge, short/deep narrative tiers, expand state, skeleton loading

## Decisions Made
- action_tag badge: `text-xs font-mono text-amber-400` — amber mono visually separates the machine-generated action instruction from prose narrative
- Expand button only shown when shortText is present — no orphaned toggle when narrative has not arrived yet
- Deep skeleton height h-12 vs short skeleton h-8 — communicates "more content coming" with proportional sizing

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- All five UI-layer requirements for the three-tier narrative redesign are now complete
- Phase 22 as a whole delivers: context extraction (22-01), SYSTEM_PROMPT rewrite (22-02), concurrent task runner (22-03), NarrativeData types + SSE handler (22-04), NarrativeCard UI (22-05), provider config (22-06)
- LLM routing via `_apply_score_routing` uses narrative_short/narrative_deep call types aligned with new fields
- No blockers for production deployment of three-tier narrative flow

---
*Phase: 22-i8-narrative-three-tier-redesign*
*Completed: 2026-03-09*
