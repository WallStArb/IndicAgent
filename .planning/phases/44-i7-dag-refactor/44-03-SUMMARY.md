---
phase: 44-i7-dag-refactor
plan: "03"
subsystem: intelligence
tags: [confluence, refactor, i6, dag, cross-timeframe]

requires:
  - phase: 44-01
    provides: "I7 utility extraction (exhaustion_utils.py, signal_schema.py) — established extraction pattern"

provides:
  - "confluence_weights.py: pure numeric helpers (_TF_MINUTES, _sign, _proximity_decay, get_recency_weight, extract_trend_sign)"
  - "confluence_alignment.py: trend/structure/regime/pattern/i2 scoring functions"
  - "confluence_smc.py: SMC-specific scoring (BOS, FVG, OB alignment)"
  - "cross_timeframe.py: reduced from 464 to 133 lines — thin orchestrator class + imports only"

affects: [44-04, market_analysis_service, i6-confluence]

tech-stack:
  added: []
  patterns:
    - "Computation-stage decomposition: pure math → market scoring → domain-specific (SMC) → orchestrator"
    - "One-way import dependency: cross_timeframe imports all three; confluence_smc imports confluence_weights only"
    - "Verbatim extraction with signature adaptation: method→function by removing self"

key-files:
  created:
    - src/intelligence/confluence/confluence_weights.py
    - src/intelligence/confluence/confluence_alignment.py
    - src/intelligence/confluence/confluence_smc.py
  modified:
    - src/intelligence/confluence/cross_timeframe.py

key-decisions:
  - "FVG/OB scoring functions take cur_trend as explicit parameter (was extracted from self.features) — cleaner module-level function signature"
  - "Re-export _sign/_proximity_decay from cross_timeframe.py with noqa F401 to preserve any potential callers"
  - "Pre-existing test_setup_performance_updater and test_weight_updater failures are unrelated to this refactor — confirmed by checking failure causes"

patterns-established:
  - "Confluence module decomposition: weights (pure math) → alignment (market scoring) → smc (domain logic) → orchestrator"

requirements-completed: [DAG-04]

duration: 3min
completed: 2026-03-21
---

# Phase 44 Plan 03: I6 cross_timeframe.py Decomposition Summary

**cross_timeframe.py decomposed from 464-line monolith into 3 focused modules (confluence_weights, confluence_alignment, confluence_smc) + 133-line thin orchestrator, with CrossTimeframeConfluencePlugin interface unchanged**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-21T02:24:11Z
- **Completed:** 2026-03-21T02:27:22Z
- **Tasks:** 2
- **Files modified:** 4 (3 created, 1 reduced)

## Accomplishments

- `confluence_weights.py` (57 lines): pure numeric helpers — `_TF_MINUTES`, `_sign`, `_proximity_decay`, `get_recency_weight`, `extract_trend_sign` — zero market domain knowledge
- `confluence_alignment.py` (183 lines): trend/structure/regime/pattern/I2 scoring functions, imports only from `confluence_weights`
- `confluence_smc.py` (127 lines): BOS, FVG, and OB alignment scoring — SMC-domain logic isolated
- `cross_timeframe.py` reduced from 464 to 133 lines: class + imports only; all 20 existing tests pass unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract confluence_weights.py and confluence_alignment.py** - `d466218` (feat)
2. **Task 2: Extract confluence_smc.py and reduce cross_timeframe.py to orchestrator** - `b9fcab4` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/intelligence/confluence/confluence_weights.py` — Pure numeric helpers: TF minutes map, sign, proximity decay, recency weight, trend sign extraction
- `src/intelligence/confluence/confluence_alignment.py` — Trend/structure/regime/pattern/I2 scoring; imports _sign/extract_trend_sign from confluence_weights
- `src/intelligence/confluence/confluence_smc.py` — SMC-specific BOS/FVG/OB alignment scoring; imports _proximity_decay/extract_trend_sign from confluence_weights
- `src/intelligence/confluence/cross_timeframe.py` — Reduced to class + imports; CrossTimeframeConfluencePlugin interface unchanged

## Decisions Made

- FVG/OB scoring functions take `cur_trend` as an explicit parameter instead of extracting it internally — the orchestrator already has `cur_trend` computed, passing it avoids redundant computation and makes the function signatures cleaner for isolated testing.
- Re-exported `_sign` and `_proximity_decay` from `cross_timeframe.py` via `noqa: F401` to protect any caller that might import them from the old location.
- The 3 pre-existing failures in `test_setup_performance_updater` and `test_weight_updater` were verified as unrelated to this refactor (weight updater statistical logic, unaffected by confluence decomposition).

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 44-04 (I7 plugin CTF wiring) can proceed immediately — `confluence_weights`, `confluence_alignment`, and `confluence_smc` are all importable independently
- Import graph is acyclic: `cross_timeframe` → all three modules; `confluence_smc` → `confluence_weights`; `confluence_alignment` → `confluence_weights`
- `market_analysis_service.py` imports `CrossTimeframeConfluencePlugin` from `cross_timeframe` — no change needed

---
*Phase: 44-i7-dag-refactor*
*Completed: 2026-03-21*

## Self-Check: PASSED
