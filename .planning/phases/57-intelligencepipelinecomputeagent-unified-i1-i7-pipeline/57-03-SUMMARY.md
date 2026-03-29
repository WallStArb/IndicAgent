---
phase: 57-intelligencepipelinecomputeagent-unified-i1-i7-pipeline
plan: 03
subsystem: intelligence-pipeline
tags: [kafka, async, checkpointing, msgpack, attribution, signal-pipeline, prometheus]

# Dependency graph
requires:
  - phase: 57-01
    provides: stream_keys topic functions, DB migration for attribution columns
  - phase: 57-02
    provides: StateSerializer encode/decode for checkpoint persistence
provides:
  - IntelligencePipelineComputeAgent — unified I1-I7 in-process pipeline (1260 lines)
  - Async output buffer with QueueFull handling and background drain task
  - State checkpoint encode/publish and restore/decode via compacted Kafka topic
  - Attribution capture at quality-gate and calibration pipeline stages
  - LedgerEntry extended to 60 params with pre_quality_confidence + pre_calibration_confidence
  - 14 unit tests covering enqueue, drain, state restore, import, shadow mode, attribution invariant
affects: [feature-writer, signal-tracker, intelligence-compute-agent-retirement]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Async output buffer: asyncio.Queue(maxsize=500) with non-blocking enqueue and background drain"
    - "State checkpoint: StateSerializer.encode() to compacted Kafka topic after each bar"
    - "Attribution capture: pre_quality_confidence before apply_quality_gate(), pre_calibration_confidence before apply_calibration()"

key-files:
  created:
    - services/intelligence_pipeline_agent.py
    - tests/unit/test_intelligence_pipeline_agent.py
    - tests/unit/test_pipeline_attribution.py
  modified:
    - src/persistence/repository/signal_ledger_repository.py

key-decisions:
  - "Existing WIP skeleton was mostly correct; only ruff fixes (UP041, E501) and pre-commit dead import removals needed"
  - "consumer.subscribe() in _restore_state_checkpoint returns unawaited coroutine in test mocks — test-only warning, harmless in production"
  - "Pre-existing collection errors in test_signal_ledger.py and test_gap_fill_service.py are out of scope per deviation boundary rule"

patterns-established:
  - "IntelligencePipelineComputeAgent.__new__() test pattern: bypass __init__ with manually set attributes for unit testing"

requirements-completed: []

# Metrics
duration: 2min
completed: "2026-03-29"
---

# Phase 57 Plan 03: IntelligencePipelineComputeAgent Summary

**Unified I1-I7 in-process pipeline agent with async output buffer, state checkpointing via compacted Kafka topic, and per-stage confidence attribution capture**

## Performance

- **Duration:** 2 min (WIP skeleton was 90% complete; final fixes + verification)
- **Started:** 2026-03-29T22:47:46Z
- **Completed:** 2026-03-29T22:49:38Z
- **Tasks:** 2 (Task 1: LedgerEntry — previously committed; Task 2: Agent + tests — this session)
- **Files modified:** 3 (agent + 2 test files)

## Accomplishments
- Completed IntelligencePipelineComputeAgent: full I1-I7 in-process pipeline (1260 lines)
- All 14 unit tests passing: enqueue, drain, state restore, version mismatch, empty topic, agent import, BaseAgent inheritance, shadow mode, attribution invariant
- Ruff-clean agent file (fixed UP041 asyncio.TimeoutError -> TimeoutError, 2x E501 line length)
- Pre-commit hooks pass (removed 3 unused imports from test files)

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend LedgerEntry with attribution fields** - `53ca8cf` + `faa4553` (feat/fix) — committed in prior session
2. **Task 2: IntelligencePipelineComputeAgent core implementation + tests** - `8cfb51c` (feat)

**Plan metadata:** (pending final docs commit)

_Note: Task 2 WIP skeleton was `122b594`; this session completed it as `8cfb51c`._

## Files Created/Modified
- `services/intelligence_pipeline_agent.py` - Unified I1-I7 in-process pipeline agent (1260 lines)
- `tests/unit/test_intelligence_pipeline_agent.py` - 11 tests: enqueue, drain, state restore, import, shadow mode (240 lines)
- `tests/unit/test_pipeline_attribution.py` - 3 tests: attribution invariant, zero confidence, LedgerEntry fields (97 lines)
- `src/persistence/repository/signal_ledger_repository.py` - LedgerEntry extended with pre_quality_confidence + pre_calibration_confidence (committed in prior session)

## Decisions Made
- Pre-existing test collection errors (test_signal_ledger.py ImportError, test_gap_fill_service.py ModuleNotFoundError) are out of scope — not caused by this plan's changes
- The `consumer.subscribe()` RuntimeWarning in state restore tests is a test-only artifact (AsyncMock coroutine not awaited); harmless in production where KafkaConsumerClient.subscribe() is synchronous

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ruff UP041: asyncio.TimeoutError aliased errors**
- **Found during:** Task 2 (agent implementation)
- **Issue:** Python 3.13 deprecates `asyncio.TimeoutError` in favor of builtin `TimeoutError`
- **Fix:** Replaced 2 instances of `except asyncio.TimeoutError` with `except TimeoutError`
- **Files modified:** services/intelligence_pipeline_agent.py (lines 691, 925)
- **Committed in:** 8cfb51c

**2. [Rule 1 - Bug] Fixed ruff E501: line length violations**
- **Found during:** Task 2 (agent implementation)
- **Issue:** Two lines exceeded 100-char limit (tier_name filter, validation error log)
- **Fix:** Wrapped long conditions across multiple lines
- **Files modified:** services/intelligence_pipeline_agent.py (lines 820, 897)
- **Committed in:** 8cfb51c

**3. [Rule 3 - Blocking] Removed dead imports flagged by pre-commit hooks**
- **Found during:** Task 2 (commit attempt)
- **Issue:** 3 unused imports (datetime.UTC, datetime.datetime in test_intelligence_pipeline_agent.py; pytest in test_pipeline_attribution.py) and 1 invalid noqa directive
- **Fix:** Removed unused imports, fixed noqa directive format
- **Files modified:** tests/unit/test_intelligence_pipeline_agent.py, tests/unit/test_pipeline_attribution.py
- **Committed in:** 8cfb51c

---

**Total deviations:** 3 auto-fixed (2 bugs, 1 blocking)
**Impact on plan:** All auto-fixes were code quality issues preventing clean commit. No scope creep.

## Issues Encountered
None - the WIP skeleton was substantially correct. The "7 failing tests" mentioned in the handoff context were already resolved in the working copy.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Agent is ready for shadow-mode deployment alongside existing feature_compute_agent + signal_generator_agent
- Set `INTELLIGENCE_PIPELINE_SHADOW=1` env var to enable shadow mode
- Next step: systemd unit file, shadow validation period, then cutover and retirement of legacy agents
- The `IntelligenceComputeAgent` (separate I7/I8 standalone agent) is NOT replaced — needs separate retirement plan

---
*Phase: 57-intelligencepipelinecomputeagent-unified-i1-i7-pipeline*
*Completed: 2026-03-29*

## Self-Check: PASSED
- All 4 files verified present (agent, 2 test files, LedgerEntry repository)
- All 3 commit hashes verified in git log (8cfb51c, 53ca8cf, faa4553)
- All 14 tests passing
- Agent imports cleanly
- Ruff clean on agent file
