---
phase: 06-dashboard-connected
plan: 02
subsystem: ui
tags: [react, typescript, nextjs, sse, real-time, dashboard]

# Dependency graph
requires:
  - phase: 06-dashboard-connected
    provides: "Plan 01 — API SSE endpoints flowing, price hero initial build"
provides:
  - "Fixed intelligence TF bucketing bug (event.tf not event.timeframe)"
  - "SessionState type with daily H/L reset for session range bar"
  - "tickFlash field on TickData and SymbolData for flash animation"
  - "price-hero.tsx reads session H/L from session state (real session range)"
  - "price-hero.tsx reads VWAP from indicatorsByTf[activeTf]"
  - "Connection status label fixed: Disconnected (was Offline)"
affects:
  - phase: 06-dashboard-connected
  - phase: 07-signal-browser

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "tickFlash set inside setSymbolData, cleared via separate setTimeout after 350ms outside callback"
    - "Session H/L tracked in hook state with date-based daily reset using YYYY-MM-DD from bar timestamp"
    - "PriceHero reads tickFlash from SymbolData (not internal useEffect) — single source of truth"

key-files:
  created: []
  modified:
    - dashboard/src/lib/types.ts
    - dashboard/src/hooks/use-market-stream.ts
    - dashboard/src/hooks/use-demo-data.ts
    - dashboard/src/components/price-hero.tsx
    - dashboard/src/components/trading-dashboard.tsx

key-decisions:
  - "tickFlash stored on both SymbolData.tickFlash (for PriceHero) and tick.tickFlash (for type completeness)"
  - "Session reset: isNewSession = barDate !== sess.date && barDate !== empty string"
  - "price-hero.tsx reads tickFlash from data prop (not internal useEffect) — avoids stale closure, simpler component"
  - "StatusDot label Disconnected matches DASH-08 spec (was Offline)"

patterns-established:
  - "Flash animation: set direction in state, clear via separate setTimeout outside setSymbolData"
  - "Session state: daily YYYY-MM-DD date comparison for reset detection"

requirements-completed: [DASH-03, DASH-05, DASH-08]

# Metrics
duration: 18min
completed: 2026-02-25
---

# Phase 06 Plan 02: Stream Audit + Price Hero Rebuild Summary

**Fixed intelligence TF bucketing bug (event.tf) and rebuilt price-hero to show session H/L range, VWAP from per-TF indicator map, and tickFlash animation driven by hook state**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-02-25T12:10:00Z
- **Completed:** 2026-02-25T12:28:56Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Fixed `event.tf` bug: intelligence data now stores under the correct timeframe key
- Added `SessionState` type with daily H/L/open tracking and date-based reset detection
- Rebuilt `price-hero.tsx` to accept `data: SymbolData` and `activeTf: string` props — reads real session H/L and VWAP from per-TF indicator map
- tickFlash animation driven by hook state (350ms clear timeout outside `setSymbolData` callback)
- Fixed connection status label from "Offline" to "Disconnected" (DASH-08)
- Fixed `use-demo-data.ts` to include `tickFlash` in `TickData` constructions (Rule 3 auto-fix)

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend types + fix event.tf bug** - `94833c6` (feat)
2. **Task 2: Session tracking + tickFlash 350ms clear** - `aa8f292` (feat)
3. **Task 3: Rebuild price-hero + wire activeTf + DASH-08** - `943d7b2` (feat)

## Files Created/Modified

- `dashboard/src/lib/types.ts` — Added `tickFlash` to `TickData`, new `SessionState` interface, `session` and `tickFlash` to `SymbolData`
- `dashboard/src/hooks/use-market-stream.ts` — Fixed `event.tf` bug; added session tracking in `market_data` handler; tickFlash with 350ms clear in `tick_data` handler
- `dashboard/src/hooks/use-demo-data.ts` — Added `tickFlash` to TickData constructions and session tracking in demo simulation (Rule 3 auto-fix)
- `dashboard/src/components/price-hero.tsx` — Full rebuild: accepts `data/activeTf` props, reads `session` for real session range bar, reads `indicatorsByTf[activeTf].vwap`, uses `tickFlash` from SymbolData state
- `dashboard/src/components/trading-dashboard.tsx` — Pass `data={data} activeTf={activeTf}` to PriceHero; fix StatusDot "Offline" → "Disconnected"

## Decisions Made

- `tickFlash` stored on both `SymbolData.tickFlash` and `tick.tickFlash` for type completeness and accessibility from both directions
- `price-hero.tsx` reads `tickFlash` from the `data` prop rather than maintaining internal `useEffect` state — eliminates stale closure risk and simplifies the component
- Session reset detection uses `YYYY-MM-DD` date string extracted from `payload.timestamp.slice(0, 10)` — zero-dependency, works with ISO timestamps
- `prevClose` in market_data handler uses `old.bar.close || close` in both new-session and same-session cases (plan noted this correctly)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed use-demo-data.ts TickData constructions**
- **Found during:** Task 1 (Extend types)
- **Issue:** Adding `tickFlash: "up" | "down" | null` as required field to `TickData` caused TypeScript compile error in `use-demo-data.ts` (two places constructing TickData without the new field)
- **Fix:** Added `tickFlash: null` to both TickData constructions in the demo hook; added full session tracking and tickFlash direction to the tick simulation loop for correctness
- **Files modified:** `dashboard/src/hooks/use-demo-data.ts`
- **Verification:** `npm run build` passed after fix
- **Committed in:** `94833c6` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking compile error)
**Impact on plan:** Required fix for type completeness. Demo hook also got session/tickFlash improvements as a side effect.

## Issues Encountered

None beyond the Rule 3 auto-fix above. All three tasks executed cleanly with no architectural decisions required.

## Next Phase Readiness

- Intelligence TF bucketing now correct — data lands in the right `intelligenceByTf[tf]` bucket
- Session H/L state tracked — session range bar shows real daily range (resets on new trading day)
- VWAP displayed from the correct per-TF indicator map
- tickFlash animation wired end-to-end from hook → state → component
- Price hero is complete per CONTEXT.md spec
- Ready for Plan 03: full panel audit and wiring remaining intelligence tier panels

## Self-Check: PASSED

- SUMMARY.md: FOUND
- types.ts: FOUND
- use-market-stream.ts: FOUND
- price-hero.tsx: FOUND
- Commit 94833c6 (Task 1): FOUND
- Commit aa8f292 (Task 2): FOUND
- Commit 943d7b2 (Task 3): FOUND

---
*Phase: 06-dashboard-connected*
*Completed: 2026-02-25*
