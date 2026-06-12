---
phase: 122-production-hardening
plan: "06"
subsystem: signal-integrity
tags: [signal-id, uuid4, replay-idempotency, deterministic-ids, ValueError]

requires:
  - phase: 122-production-hardening
    provides: "i2 write path and deterministic signal_id generation via make_signal_id()"

provides:
  - "No uuid4() fallback exists in run_historical_pipeline.py, schemas.py, signal_writer.py, alpha_swarm.py, narrative_swarm.py"
  - "Missing signal_id raises ValueError with signal context in 4 files"
  - "last_bar=None case in run_historical_pipeline.py logs warning + skips signal (cannot determine ID)"

affects: [signal-replay, signal-ledger, replay-idempotency]

tech-stack:
  added: []
  patterns:
    - "Loud failure pattern: missing deterministic field raises ValueError with context, never falls back to random"

key-files:
  created: []
  modified:
    - production/scripts/run_historical_pipeline.py
    - src/intelligence/schemas.py
    - services/signal_writer.py
    - services/alpha_swarm.py
    - services/narrative_swarm.py

key-decisions:
  - "last_bar=None case gets warning+skip (not raise) — signal has no bar data and cannot be deterministically identified; raising would abort the whole batch"
  - "uuid4 import removed from all 5 files — no remaining callers; schemas.py retains UUID (used for bar_id field)"
  - "Added structlog import + module-level _logger to run_historical_pipeline.py for warning emission"

duration: 12min
completed: 2026-06-12
---

# Phase 122 Plan 06: Signal ID Fallback Elimination Summary

**uuid4() random fallbacks eliminated from 5 files — missing signal_id now raises ValueError with context or logs warning+skip, breaking replay idempotency immediately instead of silently**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-12T15:24:00Z
- **Completed:** 2026-06-12T15:36:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Removed all 5 uuid4() fallback sites that silently generated random signal IDs when upstream omitted signal_id
- run_historical_pipeline.py: last_bar=None case now logs warning + continues (deterministic ID impossible without bar data)
- schemas.py, signal_writer.py, alpha_swarm.py, narrative_swarm.py: missing signal_id raises ValueError with setup_plugin context
- Removed uuid4 imports from all 5 files; added structlog module-level logger to run_historical_pipeline.py

## Task Commits

1. **Task 1: Fix uuid4() fallback in run_historical_pipeline.py** - `7b787b37` (fix)
2. **Task 2: Fix uuid4() fallbacks in schemas.py, signal_writer.py, alpha_swarm.py, narrative_swarm.py** - `836da2df` (fix)

## Files Created/Modified

- `production/scripts/run_historical_pipeline.py` - Replaced uuid4() fallback with _logger.warning + continue; removed uuid4 import; added structlog import + _logger
- `src/intelligence/schemas.py` - signal_dict_to_ranked raises ValueError if signal_id missing; uuid4 removed from import (UUID retained)
- `services/signal_writer.py` - LedgerEntry construction raises ValueError with setup_plugin+symbol context; uuid4 import removed
- `services/alpha_swarm.py` - signal_id guard raises ValueError with setup_plugin context; uuid4 import removed
- `services/narrative_swarm.py` - signal_id guard raises ValueError with setup_plugin context; uuid4 import removed

## Decisions Made

- last_bar=None case uses warning+skip not raise: aborting the entire batch for one malformed signal would be disproportionate; the signal simply cannot be identified, so it is dropped and logged
- Module-level _logger added to run_historical_pipeline.py: the file previously had no module-level logger (only a lazy local in seed_roll_chain); the warning site is a module-level function so a module-level logger is the correct pattern

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan referenced `logger` but file had no module-level logger**
- **Found during:** Task 1 (run_historical_pipeline.py)
- **Issue:** ruff reported `F821 Undefined name 'logger'`; the file uses `print()` for module-level warnings and only has a lazy local `log` inside `seed_roll_chain()`
- **Fix:** Added `import structlog` at top and `_logger = structlog.get_logger(__name__)` after imports; updated warning call to `_logger.warning()`
- **Files modified:** production/scripts/run_historical_pipeline.py
- **Verification:** `ruff check` passes; `black` unchanged; tests pass
- **Committed in:** 7b787b37 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - naming discrepancy between plan spec and file's actual logger pattern)
**Impact on plan:** Required to make the code correct; no scope creep.

## Issues Encountered

None beyond the logger naming deviation above.

## Self-Check

- [x] `production/scripts/run_historical_pipeline.py` - uuid4 removed, warning+continue present
- [x] `src/intelligence/schemas.py` - uuid4() call replaced with ValueError
- [x] `services/signal_writer.py` - uuid4() call replaced with ValueError
- [x] `services/alpha_swarm.py` - uuid4() call replaced with ValueError
- [x] `services/narrative_swarm.py` - uuid4() call replaced with ValueError
- [x] Commits 7b787b37 and 836da2df exist
- [x] 40 pre-existing failures unchanged; 4617 passing tests unchanged

## Self-Check: PASSED

## Next Phase Readiness

- All uuid4() fallback sites eliminated; signal_id is now mandatory at every insertion point
- Replay idempotency is enforced: ON CONFLICT DO NOTHING will work correctly since no phantom IDs can be generated
- Upstream bugs (missing signal_id) surface immediately as ValueError with signal context for fast debugging

---
*Phase: 122-production-hardening*
*Completed: 2026-06-12*
