---
phase: 110-renaissance-rename
plan: 01
subsystem: infra
tags: [rename, base-classes, ring0, naming-system]

# Dependency graph
requires: []
provides:
  - "BaseDaemon - renamed from BaseAgent (src/core/agent/base.py)"
  - "BaseWriter - renamed from BaseWriterAgent (src/core/agent/base_writer.py)"
  - "BaseProvider - renamed from BaseProviderAgent (src/providers/base_provider_agent.py)"
  - "BaseAIWorker - renamed from BaseAIAgent (src/core/ai/base_agent.py)"
  - "BaseSwarmCoordinator - renamed from BaseGroupService (src/core/ai/base_group_service.py)"
  - "Wave 1 CI gate green - safe for Wave 2"
affects:
  - "110-02 (Wave 2 - service layer renames inherit from new Ring 0 bases)"
  - "110-03 (Wave 3 - intelligence layer)"
  - "110-04 (Wave 4 - file renames)"
  - "095 (Pydantic AI adapter - creates new classes at correct names)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Ring 0 base classes use role nouns: BaseDaemon, BaseWriter, BaseProvider, BaseAIWorker, BaseSwarmCoordinator"
    - "agent_id OTel labels and name= string literals are operational exceptions - never renamed"

key-files:
  created: []
  modified:
    - "src/core/agent/base.py - class BaseDaemon (was BaseAgent)"
    - "src/core/agent/base_writer.py - class BaseWriter (was BaseWriterAgent)"
    - "src/core/agent/__init__.py - updated exports and __all__"
    - "src/providers/base_provider_agent.py - class BaseProvider (was BaseProviderAgent)"
    - "src/core/ai/base_agent.py - class BaseAIWorker (was BaseAIAgent)"
    - "src/core/ai/base_group_service.py - class BaseSwarmCoordinator (was BaseGroupService)"
    - "41 files total across src/, services/, tests/"

key-decisions:
  - "File names unchanged in Wave 1 (file renames are Wave 4) - only class identifiers and imports renamed"
  - "agent_id OTel label values and name= string literals preserved - operational exception from plan"
  - "src/config/ files (config_consumer.py, outbox_dispatcher.py, runtime_defaults.py, settings.py) required explicit fix - bash glob 'src/**/*.py' does not expand to subdirectories in xargs context; used find instead"

patterns-established:
  - "Ring 0 vocabulary: BaseDaemon (any daemon), BaseWriter (Kafka-to-DB), BaseProvider (data ingestion), BaseAIWorker (LLM agents), BaseSwarmCoordinator (group coordination)"
  - "Word-boundary sed replace: 's/\\bOldName\\b/NewName/g' via find ... | xargs to reach all subdirectories"

requirements-completed: [RENAME-01]

# Metrics
duration: 12min
completed: 2026-05-30
---

# Phase 110 Plan 01: Wave 1 Ring 0 Base Class Rename Summary

**Renamed 5 Ring 0 base classes to role nouns across 41 files - BaseDaemon, BaseWriter, BaseProvider, BaseAIWorker, BaseSwarmCoordinator - with 4049 unit tests green and ruff clean**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-30T19:31:00Z
- **Completed:** 2026-05-30T19:33:44Z
- **Tasks:** 3
- **Files modified:** 41

## Accomplishments

- Renamed all 5 Ring 0 base classes to role nouns per naming spec Section 9
- Zero old identifiers remain across src/, services/, tests/, production/scripts/
- agent_id OTel labels and name= string literals preserved unchanged (operational exception)
- Wave 1 CI gate: 4049 unit tests pass, ruff clean, commit on rename/phase-110

## Task Commits

All tasks committed together in one atomic Wave 1 commit:

1. **Task 1: Rename BaseAgent -> BaseDaemon** - `395e6344` (refactor)
2. **Task 2: Rename remaining 4 base classes** - `395e6344` (refactor)
3. **Task 3: Wave 1 CI gate - lint, tests, commit** - `395e6344` (refactor)

**Plan metadata:** (see below - committed with SUMMARY.md)

## Files Created/Modified

- `src/core/agent/base.py` - class BaseDaemon (was BaseAgent); internal self-refs updated
- `src/core/agent/__init__.py` - exports BaseDaemon, BaseWriter; __all__ updated
- `src/core/agent/base_writer.py` - class BaseWriter (was BaseWriterAgent)
- `src/providers/base_provider_agent.py` - class BaseProvider (was BaseProviderAgent)
- `src/core/ai/base_agent.py` - class BaseAIWorker (was BaseAIAgent)
- `src/core/ai/base_group_service.py` - class BaseSwarmCoordinator (was BaseGroupService)
- `src/config/config_consumer.py` - docstring + outbox_dispatcher import fixed
- `src/config/outbox_dispatcher.py` - OutboxDispatcherAgent(BaseDaemon) fixed
- `src/config/runtime_defaults.py` - docstring fixed
- `src/config/settings.py` - docstring fixed
- `src/core/ai/multiplier_agent.py` - BaseMultiplierAgent(BaseAIWorker, ABC)
- `src/core/ai/safe_wrapper.py` - updated reference
- `src/core/agent/manifest.py` - ProcessManifest(agents: list[BaseDaemon])
- `services/*.py` (30 service files) - all subclass references updated
- `tests/unit/**/*.py` (10+ test files) - test fixtures and mocks updated

## Decisions Made

- File names unchanged in Wave 1 (base.py, base_writer.py, etc.); file renames are Wave 4.
- agent_id OTel label values and name= string literals are operational exceptions - never renamed per plan constraint.
- src/config/ files required explicit fix pass - bash glob `src/**/*.py` does not expand to src/config/ in xargs; used `find src -name '*.py'` for comprehensive coverage.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] src/config/ files not reached by initial sed command**
- **Found during:** Task 3 (CI gate sweep)
- **Issue:** Bash glob `'src/**/*.py'` in xargs sed does not expand subdirectory recursively in all shells. `src/config/outbox_dispatcher.py` had live Python identifier `from src.core.agent.base import BaseAgent` and `class OutboxDispatcherAgent(BaseAgent)` that were missed.
- **Fix:** Ran second comprehensive pass using `find src services tests production/scripts -name '*.py' | xargs sed -i` to reach all files.
- **Files modified:** src/config/config_consumer.py, src/config/outbox_dispatcher.py, src/config/runtime_defaults.py, src/config/settings.py (and 4 others in the sweep)
- **Verification:** `find src services tests -name '*.py' | xargs grep -lw "BaseAgent|..."` returns zero
- **Committed in:** 395e6344 (Wave 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug: missed files from glob expansion)
**Impact on plan:** Required to meet acceptance criteria of zero old identifiers. No scope creep.

## Issues Encountered

- Pre-commit hook could not find ruff/black on first commit attempt because venv was not activated in the bash environment. Resolved by sourcing the venv before the git commit command.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Wave 1 complete on rename/phase-110 branch
- All 5 Ring 0 bases have correct role-noun names
- Wave 2 (Plan 02) can start immediately - service layer renames all inherit from the correct Ring 0 bases
- Phase 095 (Pydantic AI adapter) can create WorkerContext, AgentProtocol at correct names directly - no rename needed for those (they don't exist yet)

---
*Phase: 110-renaissance-rename*
*Completed: 2026-05-30*
