---
phase: "084-base-agent-hardening"
plan: "03"
subsystem: "core-ai"
tags: ["observability", "lineage", "graduation", "dead-code", "hardening"]
dependency_graph:
  requires: ["084-01"]
  provides: ["AI_AGENT_ERRORS_TOTAL emission", "LineageRecorder lifecycle in BaseGroupService"]
  affects: ["services/alpha_swarm_agent.py", "src/core/ai/base_agent.py", "src/core/ai/base_group_service.py"]
tech_stack:
  added: []
  patterns: ["OTel counter via .add(1, labels)", "TYPE_CHECKING guard for circular import avoidance", "hasattr override-detection dispatch"]
key_files:
  created:
    - "tests/unit/test_base_group_service.py"
  modified:
    - "src/core/ai/base_agent.py"
    - "src/core/ai/base_group_service.py"
    - "services/alpha_swarm_agent.py"
decisions:
  - "Use TYPE_CHECKING guard for LineageRecorder in base_agent.py to avoid circular import"
  - "Use hasattr(type(self), '_graduation_loop') dispatch (not 'is not' comparison) since base stub is fully deleted"
  - "Remove AlphaSwarmAgent._teardown() lineage stop since BaseGroupService._teardown() now owns it with getattr guard"
  - "Remove LineageRecorder import from alpha_swarm_agent.py since construction moved to base"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-16"
  tasks: 4
  files_changed: 4
---

# Phase 084 Plan 03: Base Agent Hardening - INFRA-04 + INFRA-06 Summary

One-liner: OTel error counter + lineage publish wired in _on_error; graduation stub deleted; LineageRecorder lifecycle consolidated onto BaseGroupService; AlphaSwarmAgent duplicate plumbing removed.

## What Was Built

### INFRA-04: BaseAIAgent._on_error observability (Task 1)

`_on_error` was previously a no-op (`pass`). It now:
- Increments `AI_AGENT_ERRORS_TOTAL.add(1, {"agent_id": ..., "error_type": ...})` on every call
- Publishes a lineage event via `self._lineage.record(signal_id=UUID(int=0), event_type="agent_prediction", ...)` when `self._lineage` is set
- Initializes `self._lineage: LineageRecorder | None = None` in `__init__` (set externally by BaseGroupService after construction)

`LineageRecorder` is imported under `TYPE_CHECKING` to avoid circular dependency (base_agent -> lineage -> kafka_utils).

### INFRA-06: BaseGroupService graduation stub + LineageRecorder wiring (Task 2)

Five surgical changes to `base_group_service.py`:
1. Deleted `has_graduation: bool = False` class attribute
2. Deleted `_graduation_loop()` stub (22 lines of TODO-only code)
3. Replaced `if self.has_graduation:` dispatch with `if hasattr(type(self), "_graduation_loop"):` - fires only when a concrete subclass defines the method
4. Added LineageRecorder wiring in `_setup()`: instantiates once, starts it, propagates via `agent._lineage = self._lineage` to all constituent agents
5. Added `_lineage.stop()` guard at top of `_teardown()` before pool/consumer shutdown

### AlphaSwarmAgent consolidation (Task 3)

Removed from `services/alpha_swarm_agent.py`:
- `has_graduation = True` class attribute
- `self._lineage: LineageRecorder | None = None` from `__init__`
- `LineageRecorder(producer=..., env_name=...)` construction + `await self._lineage.start()` from `_setup()`
- `await self._lineage.stop()` from `_teardown()`
- `from src.core.ai.lineage import LineageRecorder` import

`_graduation_loop()` override preserved - base dispatch via `hasattr` picks it up automatically.

### Unit tests (Task 4)

Created `tests/unit/test_base_group_service.py` with 5 tests (all passing):
- `test_base_group_service_has_no_graduation_attr` - structural verification
- `test_on_error_increments_ai_agent_errors_total` - counter call verification
- `test_on_error_publishes_to_lineage_when_set` - lineage.record() call verification
- `test_on_error_skips_lineage_when_none` - guard path verification
- `test_graduation_dispatch_via_override_detection` - hasattr dispatch logic

## Commits

| Task | Hash | Description |
|------|------|-------------|
| 1 | 459d1275 | feat(084-03): wire AI_AGENT_ERRORS_TOTAL + lineage publish in BaseAIAgent._on_error |
| 2 | a557e510 | feat(084-03): wire LineageRecorder in BaseGroupService; delete graduation stub; dispatch via override detection |
| 3 | b3579a8f | feat(084-03): remove AlphaSwarmAgent.has_graduation and self-instantiated LineageRecorder |
| 4 | 42a65939 | test(084-03): add unit tests for INFRA-04 and INFRA-06 |

## Deviations from Plan

None - plan executed exactly as written.

Note: `services/narrative_group_compute_agent.py` still contains `has_graduation = False` (a pre-existing file outside this plan's scope). Deferred to `deferred-items.md`.

## Verification Results

- `pytest tests/unit/test_base_group_service.py tests/unit/test_core_ai_base_agent.py`: 12 passed
- `ruff check src/core/ai/base_agent.py src/core/ai/base_group_service.py services/alpha_swarm_agent.py tests/unit/test_base_group_service.py`: all checks passed
- `grep -rn "has_graduation" src/ services/alpha_swarm_agent.py`: no matches
- `grep "def _graduation_loop" src/core/ai/base_group_service.py`: no matches (stub deleted)
- AlphaSwarmComputeAgent._graduation_loop override: confirmed present at line 206

## Self-Check: PASSED

Files verified to exist:
- /home/bg/dev/indicagent/.claude/worktrees/agent-aec30cca18d3ba59c/src/core/ai/base_agent.py - FOUND
- /home/bg/dev/indicagent/.claude/worktrees/agent-aec30cca18d3ba59c/src/core/ai/base_group_service.py - FOUND
- /home/bg/dev/indicagent/.claude/worktrees/agent-aec30cca18d3ba59c/services/alpha_swarm_agent.py - FOUND
- /home/bg/dev/indicagent/.claude/worktrees/agent-aec30cca18d3ba59c/tests/unit/test_base_group_service.py - FOUND

Commits verified:
- 459d1275 - FOUND
- a557e510 - FOUND
- b3579a8f - FOUND
- 42a65939 - FOUND
