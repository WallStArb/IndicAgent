---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
plan: 03C
subsystem: macro-intelligence
tags: [macro, fx-pairs, usd-strength, deferred, data-dependency]

# Dependency graph
requires:
  - phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-03A
    provides: yield curve macro factor (validation gate: IC > 0.05)
  - phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-03B
    provides: flight-to-quality macro factor (validation gate: IC > 0.05)
provides:
  - USD strength macro factor (DEFERRED - blocked on prerequisite validation AND FX data availability)
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Renaissance validation-first approach: prove signal value before purchasing data feeds

key-files:
  created: []
  modified: []

key-decisions:
  - "DEFERRED: USD strength factor not implemented until prerequisites validate"
  - "FX data is ALREADY AVAILABLE: EURUSD/GBPUSD/USDJPY/USDCHF defined as AssetClass.FX non-futures in settings.py (lines 395-438); get_active_contracts() includes them. No data purchase needed."
  - "Sole gate: yield_curve AND ftq both validate IC > 0.05, p < 0.01, N >= 30 (~May 10)"
  - "If either prerequisite fails, entire macro direction abandoned"

patterns-established: []

requirements-completed: []

# Metrics
duration: 2min
completed: 2026-04-26
---

# Phase 64 Plan 03C: USD Strength Macro Factor Summary

**DEFERRED until FX data available AND prerequisite validation passes (Plan 03A yield curve + Plan 03B flight-to-quality must both achieve IC > 0.05).**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-26T01:42:20Z
- **Completed:** 2026-04-26T01:44:22Z
- **Tasks:** 0/0 (plan deferred)
- **Files modified:** 0

## Accomplishments

- **Deferred USD strength factor implementation** — Plan 64-03C recognized as DEFERRED with 0 tasks
- **Documented deferral rationale** — Renaissance discipline: don't invest in data feeds for unproven signals
- **Prerequisite validation gates established** — Both Plan 03A (yield curve) AND Plan 03B (flight-to-quality) must validate with IC > 0.05 before FX data is purchased
- **Clear abandonment criteria** — If either prerequisite fails, entire macro factor direction is abandoned and FX data is NOT purchased

## Task Commits

No tasks executed — plan is DEFERRED pending:

1. FX pair data availability (EURUSD, GBPUSD, USDJPY, USDCHF tracked in system)
2. Plan 03A (yield curve) validation: IC > 0.05, p < 0.01
3. Plan 03B (flight-to-quality) validation: IC > 0.05, p < 0.01

**Plan metadata:** No commits for deferred plan

## Files Created/Modified

None — plan deferred, no implementation work performed

## Decisions Made

- **DEFERRED status accepted** — Plan 64-03C is correctly marked as `deferred: true` in frontmatter with clear deferral reason
- **No FX data purchased** — Renaissance discipline enforced: validate macro approach first with available data (yield curve from rate futures, FTQ from ETFs). Only if both prove signal value, invest in FX data for USD strength
- **Prerequisite validation gates** — Both Plan 03A AND Plan 03B must achieve IC > 0.05 before this plan is executed. If either fails, USD strength factor is NOT built

## Deviations from Plan

None — plan executed exactly as written (deferred plan recognized and documented)

## Issues Encountered

None — deferred plan has no execution issues

## Deferral Rationale

**Why this plan is deferred:**

1. **Missing data infrastructure** — System does not currently track FX pairs (EURUSD, GBPUSD, USDJPY, USDCHF). Adding these requires:
   - IBKR TWS subscription to FX data feeds (cost)
   - Qualifying FX instruments in `src/config/contracts.py`
   - Adding FX pairs to `get_active_contracts()` logic
   - Restarting `indicagent-ibkr-provider` after contract metadata update

2. **Unproven macro signal class** — Macro factors (yield curve, flight-to-quality, USD strength) are a new signal direction for IndicAgent. Before investing in data feeds:
   - Validate yield curve factor (Plan 03A) with existing rate futures data (ZT, ZN, ZB, ZF)
   - Validate flight-to-quality factor (Plan 03B) with existing ETF data (TLT, SPY, VX)
   - If BOTH prove predictive value (IC > 0.05), THEN invest in FX data for USD strength

3. **Renaissance discipline** — "Earn the right through proof" principle: no model, strategy, or feature gets promoted to production without statistically significant evidence (p < 0.05, sufficient N). Purchasing FX data before validating macro approach violates this discipline.

**When this plan will execute:**

- AFTER Plan 03A completes with validation result: IC > 0.05, p < 0.01, N ≥ 30
- AFTER Plan 03B completes with validation result: IC > 0.05, p < 0.01, N ≥ 30
- AFTER FX pairs are added to IBKR TWS data feed
- AFTER FX pairs are qualified in `src/config/contracts.py` and `get_active_contracts()`

**If this plan is abandoned:**

- If Plan 03A fails validation (IC ≤ 0.05 OR p ≥ 0.01), macro direction abandoned
- If Plan 03B fails validation (IC ≤ 0.05 OR p ≥ 0.01), macro direction abandoned
- FX data is NOT purchased
- USD strength factor is NOT implemented
- Resources redirected to proven signal classes

## Next Phase Readiness

**For Plan 03C execution (when prerequisites pass):**

- Implementation spec ready in plan frontmatter (`<interfaces>` section)
- Gradient formula documented: DXY-like composite from FX pairs via `np.tanh(normalization)`
- Integration pattern clear: extend `MacroComputeAgent` (from Plan 03A) with USD strength computation
- Validation path defined: 6-month historical backtest via Plan 00 tool, IC > 0.05 gate

**For current phase (64) continuation:**

- Plan 03A (yield curve) and Plan 03B (flight-to-quality) must complete and validate first
- This summary documents the deferral state for future reference
- No action required on this plan until prerequisite validation completes

---
*Phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service*
*Completed: 2026-04-26 (DEFERRED)*
