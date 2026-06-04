---
phase: 095-pydantic-ai-agents
plan: "01"
subsystem: ai
tags: [pydantic-ai, dataclass, ring0, worker-context, type-checking]

# Dependency graph
requires: []
provides:
  - "pydantic-ai 1.x installed and pinned in requirements.txt"
  - "WorkerContext frozen dataclass at src/core/ai/worker_context.py"
  - "Unit tests for WorkerContext (construction, defaults, immutability, Ring 0 boundary)"
affects:
  - "095-02: LLMAdapter bridge (consumes WorkerContext)"
  - "095-03: _run_typed() (passes WorkerContext to LLMAdapter)"
  - "097-*: Zep memory integration (adds db_pool/memory_client fields)"

# Tech tracking
tech-stack:
  added:
    - "pydantic-ai>=1.0,<2 (1.104.0 installed)"
  patterns:
    - "frozen=True dataclass as immutable dep container (not Pydantic model)"
    - "TYPE_CHECKING-only import for Ring 1 boundary in Ring 0 module"
    - "Any typing for cross-ring field to avoid runtime coupling"

key-files:
  created:
    - "src/core/ai/worker_context.py"
    - "tests/unit/core/test_core_ai_worker_context.py"
  modified:
    - "requirements.txt"

key-decisions:
  - "WorkerContext is a frozen dataclass (not Pydantic BaseModel) - pure in-memory container, never serialized"
  - "signal_context typed Any to preserve Ring 0 boundary; LLMProviderChain annotation deferred to TYPE_CHECKING"
  - "db_pool and memory_client reserved as None defaults now to prevent Phase 097 from touching call sites"

patterns-established:
  - "Ring 0 dep containers: use @dataclass(frozen=True), not BaseModel"
  - "Cross-ring type annotation: use Any for Ring 1 types in Ring 0; TYPE_CHECKING for Ring 0 imports of Ring 1"

requirements-completed:
  - AGENT-EXEC-02

# Metrics
duration: 8min
completed: 2026-05-31
---

# Phase 095 Plan 01: WorkerContext Frozen Dep Container Summary

**pydantic-ai 1.104.0 pinned and installed; WorkerContext frozen dataclass with four ordered fields and TYPE_CHECKING-only Ring 1 guard, fully unit tested**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-31T09:00:00Z
- **Completed:** 2026-05-31T09:08:00Z
- **Tasks:** 3
- **Files modified:** 3 (requirements.txt, worker_context.py, test file)

## Accomplishments
- Pinned `pydantic-ai>=1.0,<2` (resolved to 1.104.0) in requirements.txt and installed into project venv
- Created `WorkerContext` frozen dataclass at Ring 0 with four fields: `signal_context`, `llm_chain`, `db_pool`, `memory_client`
- Preserved Ring 0 boundary: `LLMProviderChain` under TYPE_CHECKING only, `signal_context` typed Any (no runtime Ring 1 import)
- 10 passing unit tests covering construction, defaults, immutability (FrozenInstanceError), and Ring 0 import cleanliness

## Task Commits

Each task was committed atomically:

1. **Task 1: Add pydantic-ai dependency and install** - `0b52f28e` (feat)
2. **Task 2: Create WorkerContext frozen dataclass** - `18dc306a` (feat)
3. **Task 3: Unit tests for WorkerContext** - `aed9df9c` (test)

## Files Created/Modified
- `requirements.txt` - Added `pydantic-ai>=1.0,<2` near existing pydantic lines
- `src/core/ai/worker_context.py` - WorkerContext frozen dataclass (Ring 0 dep container)
- `tests/unit/core/test_core_ai_worker_context.py` - 10 tests: construction, defaults, FrozenInstanceError, Ring 0 boundary

## Decisions Made
- Used `@dataclass(frozen=True)` not Pydantic BaseModel because WorkerContext is an in-memory dep container, never serialized - dataclass frozen is more appropriate and avoids Pydantic overhead
- Typed `signal_context: Any` rather than attempting a conditional import, following the same ring boundary principle as `AgentOutput.payload: dict[str, Any]`
- Reserved `db_pool` and `memory_client` as `None` defaults now so Phase 097 Zep integration never needs to touch `_run_typed()` call sites

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Symlinked main .venv into worktree**
- **Found during:** Task 2 commit
- **Issue:** Pre-commit hook resolves `${REPO_ROOT}/.venv/bin/ruff` using the worktree root; the main project `.venv` lives at the main repo root, causing "ruff not found" block
- **Fix:** Created symlink `/worktree-root/.venv -> /home/bg/dev/indicagent/.venv`
- **Files modified:** `.venv` symlink (not tracked by git)
- **Verification:** Pre-commit passed after symlink
- **Committed in:** n/a (symlink not committed)

---

**Total deviations:** 1 auto-fixed (blocking)
**Impact on plan:** Necessary worktree infrastructure fix. No scope creep.

## Issues Encountered
- Root-owned `__pycache__` files in venv site-packages blocked `uv pip install`. Fixed with sudo chmod before install could proceed.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `WorkerContext` and `pydantic-ai` are ready for Plan 02 (LLMAdapter bridge uses FunctionModel/AgentInfo)
- `pydantic_ai.models.function.FunctionModel`, `AgentInfo`, `ModelResponse`, `ToolCallPart`, and `Agent` all confirmed importable
- Ring 0 boundary intact - no regressions to existing unit tests expected

---
*Phase: 095-pydantic-ai-agents*
*Completed: 2026-05-31*
