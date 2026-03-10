---
phase: 06-dashboard-connected
plan: 03
subsystem: ui
tags: [react, typescript, nextjs, smart-money, hmm, liquidity-zones, smc]

# Dependency graph
requires:
  - phase: 06-dashboard-connected
    provides: "Plan 02 — event.tf bug fixed, session tracking, price-hero rebuilt"
provides:
  - "SmartMoneyData extended with 17 HMM + liquidity zone fields"
  - "parseIntelligence() maps all smc.* HMM and BSL/SSL fields from Redis"
  - "SmartMoneyPanel renders HMM regime row (RANGING/TREND↑/TREND↓ + probability)"
  - "SmartMoneyPanel renders LIQ row (SSL/BSL price levels + PREM/DISC/EQ badge)"
affects:
  - phase: 06-dashboard-connected
  - phase: 07-signal-browser

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Conditional row rendering: new SMC rows only appear when field data is present — no empty rows"
    - "HMM regime integer (0/1/2) mapped to RANGING/TREND↑/TREND↓ labels with amber/green/red colouring"
    - "premium_position threshold: >=0.6 PREM, <=0.4 DISC, else EQ — badge with dimmed background"
    - "price_in_premium uses nf(v) > 0 pattern (Redis stores bool as float 1.0/0.0) same as cp_detected"

key-files:
  created: []
  modified:
    - dashboard/src/lib/types.ts
    - dashboard/src/hooks/use-market-stream.ts
    - dashboard/src/components/smart-money-panel.tsx

key-decisions:
  - "HMM regime integer encoding: 0=ranging, 1=trending_up, 2=trending_down — matches Python HMM plugin output"
  - "LIQ row renders SSL before BSL (support below price shown first for readability)"
  - "premium_position thresholds: 0.6/0.4 split (not 0.5) gives equilibrium band rather than binary split"
  - "price_in_premium follows same nf(v) > 0 pattern as cp_detected — Redis stores as float 0.0/1.0"

patterns-established:
  - "Conditional SMC rows: only render when data.field !== undefined — prevents ghost rows when smc tier is empty"

requirements-completed: [DASH-06]

# Metrics
duration: 3min
completed: 2026-02-25
---

# Phase 06 Plan 03: SMC Panel — HMM Regime + Liquidity Zones Summary

**SmartMoneyData extended with HMM regime and BSL/SSL liquidity zone fields; SmartMoneyPanel renders regime label with probability and liquidity level rows with premium/discount badge**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-25T12:33:36Z
- **Completed:** 2026-02-25T12:36:45Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added 17 new fields to `SmartMoneyData` interface: full HMM regime suite (regime, prob, all 3 state probabilities, duration) and BSL/SSL liquidity zone suite (levels, significance, ATR distance, touches, premium position, pool count)
- Mapped all new smc.* fields in `parseIntelligence()` with correct `price_in_premium` float-to-boolean conversion
- SmartMoneyPanel HMM row: renders RANGING (amber) / TREND↑ (green) / TREND↓ (red) with probability % and bar duration count — only when data present
- SmartMoneyPanel LIQ row: renders SSL and BSL price levels + PREM/DISC/EQ badge based on premium_position — only when data present

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend SmartMoneyData type + map new fields in parseIntelligence** - `9f4e91b` (feat)
2. **Task 2: Add HMM regime + liquidity zones to SmartMoneyPanel** - `b75d71a` (feat)

## Files Created/Modified

- `dashboard/src/lib/types.ts` — Added 17 new optional fields to SmartMoneyData interface (HMM regime + liquidity zones)
- `dashboard/src/hooks/use-market-stream.ts` — Added all new smc.* field mappings in parseIntelligence() smartMoney construction
- `dashboard/src/components/smart-money-panel.tsx` — Added HMM regime row and LIQ row with conditional rendering

## Decisions Made

- HMM regime integer encoding (0/1/2) maps directly to the Python plugin's HMM state output — no remapping needed
- LIQ row displays SSL (support) before BSL (resistance) for natural price level reading order
- premium_position uses 0.6/0.4 thresholds rather than strict 0.5 to create an equilibrium band (not a binary switch)
- price_in_premium uses `nf(smc.price_in_premium) > 0` identical to `cp_detected` pattern — Redis stores Python bool as float string "1.0"/"0.0"

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SmartMoneyPanel now shows all available SMC data: BOS/CHoCH, FVG, OB, sweeps, BOCPD change point, HMM regime, BSL/SSL liquidity zones
- Dashboard intelligence display is fully wired to live Redis smc tier data
- Ready for Plan 04: signal browser or remaining Phase 6 plans

## Self-Check: PASSED

- SUMMARY.md: FOUND (this file)
- types.ts: FOUND — SmartMoneyData has hmm_regime and bsl_level fields
- use-market-stream.ts: FOUND — parseIntelligence() maps all new smc.* fields
- smart-money-panel.tsx: FOUND — renders HMM and LIQ rows
- Commit 9f4e91b (Task 1): FOUND
- Commit b75d71a (Task 2): FOUND

---
*Phase: 06-dashboard-connected*
*Completed: 2026-02-25*
