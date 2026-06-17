---
phase: 131-signal-generation-integrity
plan: "02"
subsystem: intelligence
tags: [bocpd, changepoint, look-ahead-bias, lifecycle-replay, signal-integrity, numpy]

# Dependency graph
requires: []
provides:
  - "BOCPD volume spike check uses prior 20 bars only (no look-ahead bias)"
  - "_verify_replay reports COUNT(DISTINCT signal_id) alongside JOIN-inflated total"
  - "B7 fan-out overcounting surfaced as explicit warning in _verify_replay"
affects:
  - "131-01 (parallel plan — independent fixes)"
  - "131-03 onwards (corpus rebuild integrity depends on correct _verify_replay output)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "vol[-21:-1] slice pattern for 20-bar lookback excluding current bar (matches close[-21:-1] established pattern)"
    - "Dual COUNT in _verify_replay: JOIN-inflated total + COUNT(DISTINCT) for unambiguous signal counts"

key-files:
  created: []
  modified:
    - "src/intelligence/features/smc_context/bocpd_changepoint.py"
    - "production/scripts/lifecycle_replay.py"

key-decisions:
  - "A6: vol[-21:-1] not vol[-20:] — prior 20 bars only, current bar excluded from its own spike evaluation"
  - "B7: additive fix only — no existing query changed, new distinct_row query added in same conn block"
  - "B7 warning logs when total != distinct_signals to surface fan-out overcounting explicitly at runtime"

patterns-established:
  - "SMA-20 lookback pattern: always use [-21:-1] slice (prior 20 bars), never [-20:] (includes current bar)"

requirements-completed:
  - D-04

# Metrics
duration: 5min
completed: 2026-06-17
---

# Phase 131 Plan 02: Targeted Bias and Overcounting Fixes Summary

**BOCPD look-ahead bias eliminated (vol[-21:-1]) and _verify_replay now reports COUNT(DISTINCT signal_id) to surface JOIN fan-out overcounting**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-17T13:25:00Z
- **Completed:** 2026-06-17T13:27:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Eliminated BOCPD look-ahead bias: volume spike check now evaluates current bar against prior 20 bars only (indices -21..-2), not an average that includes the current bar
- Added `COUNT(DISTINCT se.signal_id)` query to `_verify_replay()` within the same connection block, exposing unambiguous distinct signal count in log output
- Added explicit `logger.warning` when `total != distinct_signals`, making B7 dual-track fan-out overcounting visible at runtime rather than silently inflating counts

## Task Commits

1. **T-01: A6 — Fix BOCPD look-ahead bias** - `d7d497e1` (fix)
2. **T-02: B7 — Add COUNT(DISTINCT signal_id) to _verify_replay** - `2c4759ca` (fix)

## Files Created/Modified

- `src/intelligence/features/smc_context/bocpd_changepoint.py` - line 278: `vol[-20:]` -> `vol[-21:-1]`; aligns with established SMA-20 pattern at line 285
- `production/scripts/lifecycle_replay.py` - `_verify_replay()`: added `distinct_row` query, `distinct_signals` extraction, updated `logger.info` format string, added fan-out warning

## Decisions Made

- B7 implemented as strictly additive: the existing CASE expression query is unchanged, new query runs in the same `async with conn:` block to avoid additional roundtrip latency
- Warning threshold is exact equality (`total != distinct_signals`) — any fan-out produces a visible log entry; no threshold tuning needed

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hook could not find `.venv/bin/ruff` and `.venv/bin/black` because the worktree root lacks a `.venv` directory. Resolved by symlinking `/home/bg/dev/indicagent/.venv` into the worktree root. This is a worktree-only infrastructure issue; no code changes were needed.

## Next Phase Readiness

- A6 and B7 correctness fixes are committed and green (4756 unit tests pass)
- These fixes are fully independent of A4/A7 (plan 131-01); both can merge cleanly
- _verify_replay now provides unambiguous distinct signal counts, supporting corpus rebuild integrity checks in 131-03+

---
*Phase: 131-signal-generation-integrity*
*Completed: 2026-06-17*
