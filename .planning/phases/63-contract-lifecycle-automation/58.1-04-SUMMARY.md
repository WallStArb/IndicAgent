---
phase: 58.1-contract-lifecycle-automation
plan: 04
subsystem: infra
tags: [roll-monitor, backtest, futures, contract-lifecycle, systemd]

# Dependency graph
requires:
  - phase: 58.1-02
    provides: RollComputeAgent deployed but disabled in systemd
provides:
  - Deterministic bar-replay backtest script for RollComputeAgent validation
  - Documented decision: graduation deferred to June 2026 roll (M6→U6)
affects: [58.1-05, roll-monitor-graduation, futures-contract-lifecycle]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bar-replay backtest: import algorithm directly, feed historical bars, assert detection within known window — no system_events dependency"

key-files:
  created:
    - production/scripts/roll_backtest.py
  modified: []

key-decisions:
  - "Graduation deferred to June 2026 roll: H6 contracts (ESH6, NQH6, RTYH6, YMH6) returned 0 bars from market_data_ohlcv — expired without backfill under those codes"
  - "RollComputeAgent remains disabled (do NOT enable indicagent-roll-compute.service)"
  - "Backtest script is reusable — will validate M6→U6 transition in June 2026 with same methodology"

patterns-established:
  - "Roll graduation gate: backtest must PASS (not SKIP) before systemctl enable — SKIP is treated as FAIL for graduation purposes"

requirements-completed: [CLA-04]

# Metrics
duration: 5min
completed: 2026-04-02
---

# Phase 58.1 Plan 04: RollComputeAgent Graduation Summary

**Backtest ran against H6 contracts but found 0 bars (expired without backfill) — graduation deferred to June 2026 M6→U6 roll; script is ready**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-04-02T00:00:00Z
- **Completed:** 2026-04-02T00:05:00Z
- **Tasks:** 2 (Task 1 complete via prior commit; Task 2 resolved as deferral decision)
- **Files created:** 1

## Accomplishments

- `production/scripts/roll_backtest.py` created and committed (967fc4e) — deterministic bar-replay validation, no system_events dependency
- Backtest executed: all 4 symbols (ES, NQ, RTY, YM) returned SKIP due to 0 bars for H6 contracts in `market_data_ohlcv`
- Decision made: do NOT enable `indicagent-roll-compute.service`; graduation deferred to June 2026 roll (M6→U6)

## Task Commits

1. **Task 1: Write roll_backtest.py** - `967fc4e` (feat: deterministic bar-replay backtest script)

**Plan metadata:** (this commit — docs: graduation deferred)

## Files Created/Modified

- `production/scripts/roll_backtest.py` - Standalone async backtest: loads 1m bars from `market_data_ohlcv`, replays through `RollMonitor.update_volume()` + `check_roll()`, validates detection-in-window / no-false-positives / no-double-fire; exits 0=PASS, 1=FAIL

## Decisions Made

- **H6 contracts absent from DB:** ESH6, NQH6, RTYH6, YMH6 contracts expired in March 2026 and were never backfilled under those ticker codes in `market_data_ohlcv`. The query returned 0 rows, so all 4 symbols hit the `< 100 bars` guard and printed `[SKIP]`.
- **SKIP = FAIL for graduation:** The backtest script correctly treats insufficient data as a failed check (`failed += 1`). Script output was: `Results: 0 passed, 4 failed / FAILED — do NOT enable RollComputeAgent`.
- **Service stays disabled:** `indicagent-roll-compute.service` remains in its current disabled/inactive state. No systemctl changes made.
- **June 2026 plan:** When M6 contracts roll to U6 (~June 2026), the backtest script can be re-run as-is against `market_data_ohlcv` rows for ESM6, NQM6, RTYM6, YMM6 — no script changes needed.

## Deviations from Plan

None — plan explicitly accounted for the SKIP/FAIL path ("If SKIP/FAIL: defer graduation to next quarterly roll (June 2026)").

## Issues Encountered

- **Root cause of SKIP:** H6 contracts expired ~2026-03-21 without historical backfill stored under their contract codes. The live pipeline tracks base symbols (ES, NQ) rather than expiry-specific codes (ESH6), so `market_data_ohlcv` does not contain rows for `symbol = 'ESH6'`. Backfilling expired contracts is not actionable post-expiry.

## User Setup Required

None — no external service configuration required. `indicagent-roll-compute.service` intentionally NOT enabled.

## Next Phase Readiness

- RollComputeAgent code and systemd unit remain deployed and ready
- `production/scripts/roll_backtest.py` is the graduation gate — run it when M6 data is available (June 2026)
- No blockers for Phase 58.1-05 (downstream lifecycle phases do not depend on roll graduation)

---
*Phase: 58.1-contract-lifecycle-automation*
*Completed: 2026-04-02*
