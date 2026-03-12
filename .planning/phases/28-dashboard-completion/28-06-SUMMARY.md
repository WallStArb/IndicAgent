---
phase: 28-dashboard-completion
plan: 06
subsystem: ui
tags: [react, typescript, dashboard, garch, kalman, smc, drill-panel]

# Dependency graph
requires:
  - phase: 28-dashboard-completion
    provides: drill-panel.tsx and ContextData type foundation from prior plans
provides:
  - GARCH/Kalman fields in ContextData type (6 new optional fields)
  - parseIntelligence() maps all 6 from i4 tier
  - drill-panel I4 Context section renders GARCH regime (amber on high), sigma, vol_ratio, shock, Kalman slope, pos, uncertainty
  - drill-panel Smart Money section renders BSL/SSL touches+significance and price_in_premium/equilibrium_level
affects: [28-dashboard-completion, drill-panel, intelligence-display]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pipeline-derived classification for UI styling: garch_vol_regime=2 triggers amber — UI never makes own threshold calls"
    - "valueClassName prop on KV component for conditional value color (single-prop override pattern)"
    - "Conditional rendering with != null guards — absent fields produce no placeholder rows"

key-files:
  created: []
  modified:
    - dashboard/src/lib/types.ts
    - dashboard/src/hooks/use-market-stream.ts
    - dashboard/src/components/drill-panel.tsx

key-decisions:
  - "GARCH regime amber styling uses pipeline-classified garch_vol_regime===2, never hardcoded number threshold — UI passively reflects pipeline decision"
  - "valueClassName added to KV as minimal-surface prop for color override without redesigning the component"
  - "kalman_trend omitted from display per plan — smoothed price level requires price context to be meaningful"

patterns-established:
  - "Pipeline-as-authority: all conditional styling in drill-panel derives from pipeline-computed fields, never UI-side recalculation"

requirements-completed: [DASH-04]

# Metrics
duration: 2min
completed: 2026-03-12
---

# Phase 28 Plan 06: GARCH/Kalman and SMC Detail Fields Summary

**GARCH sigma/vol_ratio/shock and Kalman slope/position/uncertainty added to I4 Context display; BSL/SSL touches+significance and price_in_premium/equilibrium_level added to Smart Money display; GARCH regime row amber when pipeline classifies vol=high**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-12T21:32:36Z
- **Completed:** 2026-03-12T21:34:27Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Extended `ContextData` with 6 new optional fields: `garch_sigma`, `garch_vol_ratio`, `garch_shock`, `kalman_slope`, `kalman_price_position`, `kalman_uncertainty`
- Mapped all 6 from the i4 tier in `parseIntelligence()` with null-guards
- Added GARCH regime KV with amber styling driven by pipeline-classified `garch_vol_regime === 2` — no hardcoded thresholds
- Added BSL/SSL touches and significance rows after each liquidity level KV
- Added `price_in_premium` (bool label "yes ▲"/"no ▼") and `equilibrium_level` after the Prem/disc KV
- No duplicate bsl_dist_atr, ssl_dist_atr, or premium_discount_pct fields

## Task Commits

Each task was committed atomically:

1. **Task 1: Add GARCH/Kalman fields to ContextData and parseIntelligence** - `91044ce` (feat)
2. **Task 2: Render GARCH/Kalman and SMC detail fields in drill panel** - `8da7477` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `dashboard/src/lib/types.ts` — 6 new optional fields on ContextData
- `dashboard/src/hooks/use-market-stream.ts` — 6 new i4 field mappings in parseIntelligence()
- `dashboard/src/components/drill-panel.tsx` — valueClassName on KV; 7 new KVs in I4 section; 4 new KVs in SMC section

## Decisions Made
- Added `valueClassName` prop to `KV` component: minimal surface change enabling amber styling on GARCH regime without redesigning the component or adding wrapper divs
- GARCH regime styling strictly follows pipeline's `garch_vol_regime` integer (0/1/2) — renaissance framing: UI is a passive consumer of pipeline decisions
- `kalman_trend` omitted per plan guidance — the smoothed price level requires price context to interpret meaningfully; slope and position are more directly readable

## Deviations from Plan

None - plan executed exactly as written. The plan noted that `className` may not exist on KV and to check; it didn't, so `valueClassName` was added as the minimal-surface alternative (consistent with plan guidance to find the equivalent prop).

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All GARCH/Kalman I4 fields now visible in drill panel
- BSL/SSL detail and premium/discount context complete in Smart Money section
- Remaining Phase 28 plans can proceed independently

---
*Phase: 28-dashboard-completion*
*Completed: 2026-03-12*
