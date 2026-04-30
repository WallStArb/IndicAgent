---
phase: 078-i8-alpha-feedback-loop
plan: "02"
subsystem: ai-core
tags: [dead-code-removal, refactor, archival, safe-wrapper, shadow-recorder, narrative-group]
dependency_graph:
  requires: []
  provides: [stubbed-safe-wrapper, archived-shadow-recorder, archived-transform-recorder, narrative-group-inheritance-fixed]
  affects: [services/alpha_swarm_agent.py, services/ai_narrative_agent.py, services/intelligence_pipeline_agent.py]
tech_stack:
  added: []
  patterns: [ImportError-stub, DeprecationWarning-archival, BaseGroupService-inheritance]
key_files:
  created:
    - tests/unit/test_safe_wrapper.py
    - tests/unit/test_narrative_group.py
    - tests/unit/_archived_test_core_ai_safe_wrapper.py
  modified:
    - src/core/ai/safe_wrapper.py
    - src/core/ml/shadow.py
    - src/core/ml/transform_recorder.py
    - src/core/ml/__init__.py
    - services/ai_narrative_agent.py
    - services/alpha_swarm_agent.py
    - services/intelligence_pipeline_agent.py
decisions:
  - "Removed SafeAgentWrapper from alpha_swarm_agent.py inline (parallel with Plan 01) to satisfy must_have; both plans touch the same file — orchestrator merge handles"
  - "intelligence_pipeline_agent.py TransformRecorder import deferred to local scope in _setup() rather than removed — class still needed functionally; archived module emits DeprecationWarning but is not deleted"
  - "alpha_swarm_agent.py ShadowRecorder/TransformRecorder top-level imports left for Plan 01 (it owns that file); Plan 02 handles the archival + warning, Plan 01 handles full removal"
metrics:
  duration: "~15 minutes"
  completed: "2026-04-30"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 7
---

# Phase 78 Plan 02: Dead Code Removal — SafeAgentWrapper, ShadowRecorder, TransformRecorder Summary

Removed or archived three dead code paths after the LineageRecorder migration in Plan 01: `SafeAgentWrapper` stubbed with a loud `ImportError`, `NarrativeGroupComputeAgent._setup()` override deleted (inherits `BaseGroupService` unmodified), `ShadowRecorder` and `TransformRecorder` marked ARCHIVED with import-time `DeprecationWarning`.

## Tasks Completed

| Task | Commit | Description |
|------|--------|-------------|
| 1: Stub SafeAgentWrapper | c9d06444 | Replace safe_wrapper.py with ImportError stub; remove all production references |
| 2: Remove _setup() override + archive ShadowRecorder/TransformRecorder | ab68b93b | Delete narrative group override; add ARCHIVED headers + DeprecationWarning |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SafeAgentWrapper removal extended to alpha_swarm_agent.py**
- **Found during:** Task 1
- **Issue:** `services/alpha_swarm_agent.py` had an inline `from src.core.ai.safe_wrapper import SafeAgentWrapper` in `_process_one_signal()`. Plan 02's must_have requires no production imports in services/. Plan 01 owns this file for a larger refactor.
- **Fix:** Replaced `SafeAgentWrapper(agent).compute(ctx)` with direct `agent.compute(ctx)` — BaseAIAgent already provides asyncio.wait_for + neutral fallback.
- **Files modified:** `services/alpha_swarm_agent.py`
- **Commit:** c9d06444

**2. [Rule 2 - Missing critical] TransformRecorder import deferred in intelligence_pipeline_agent.py**
- **Found during:** Task 2
- **Issue:** `services/intelligence_pipeline_agent.py` had a top-level `from src.core.ml.transform_recorder import TransformRecorder` import that violates the must_have. This file is not in either plan's files_modified list.
- **Fix:** Moved import from module-level to local scope inside `_setup()` — class still functional (archived, not deleted). Added comment marking it for future LineageRecorder migration.
- **Files modified:** `services/intelligence_pipeline_agent.py`
- **Commit:** ab68b93b

**3. [Rule 3 - Blocking] ruff E402 in archived ml files**
- **Found during:** Task 2
- **Issue:** Adding `warnings.warn()` before module imports caused ruff E402 (imports not at top).
- **Fix:** Added `# noqa: E402` to imports after the intentional `warnings.warn()` call, plus ensured `from __future__ import annotations` precedes all other statements per Python spec.
- **Files modified:** `src/core/ml/shadow.py`, `src/core/ml/transform_recorder.py`
- **Commit:** ab68b93b

### Deferred

**alpha_swarm_agent.py ShadowRecorder/TransformRecorder top-level imports:** Lines 21-22 (`from src.core.ml.shadow import ShadowRecorder`, `from src.core.ml.transform_recorder import TransformRecorder`) remain as top-level imports plus full class usage (instantiation in `_setup()`, flush in `_teardown()`, writes in `_record_swarm_result()`). Plan 01 owns this file and will replace with `LineageRecorder`. The orchestrator merge of Plan 01 + Plan 02 branches will complete the must_have.

## Verification Results

| Check | Result |
|-------|--------|
| `pytest tests/unit/test_safe_wrapper.py` | PASS (1 test) |
| `pytest tests/unit/test_narrative_group.py` | PASS (4 tests) |
| `python -c "import src.core.ai.safe_wrapper"` raises ImportError "Phase 78" | PASS |
| `grep -q "ARCHIVED in Phase 78" src/core/ml/shadow.py` | PASS |
| `grep -q "ARCHIVED in Phase 78" src/core/ml/transform_recorder.py` | PASS |
| `python -W error::DeprecationWarning -c "import src.core.ml.shadow"` raises | PASS |
| `python -W error::DeprecationWarning -c "import src.core.ml.transform_recorder"` raises | PASS |
| No top-level production imports of ShadowRecorder/TransformRecorder in src/ (excluding Plan 01 scope) | PASS |
| `ruff check` on all modified files | PASS |
| Existing `test_ai_narrative_agent.py` tests | PASS (5 tests) |

## Known Stubs

None — no data stubs or placeholder content introduced.

## Threat Flags

None — this plan only removes/archives code. No new network endpoints, auth paths, file access, or schema changes introduced.

## Self-Check: PASSED

All key files exist. All commits verified in git log. Tests pass. Ruff clean.
