---
phase: 095-pydantic-ai-agents
plan: 05
subsystem: ai-agents
tags: [skeptic-agent, pydantic-ai, agent-id-rename, _run_typed, migration]
dependency_graph:
  requires: [095-04]
  provides: [skeptic-evaluator-typed-path]
  affects: [alpha-swarm, ai-stats, validate-skeptic-tool]
tech_stack:
  added: []
  patterns: [result_type ClassVar opt-in, _run_typed typed output path, TYPE_CHECKING import for heavy deps]
key_files:
  created: []
  modified:
    - src/intelligence/ai/alpha/skeptic_agent.py
    - services/alpha_swarm.py
    - src/api/routes/ai_stats.py
    - tools/validate_skeptic.py
    - tests/unit/services/test_skeptic_agent.py
    - tests/unit/services/test_alpha_swarm.py
    - tests/integration/test_swarm_graduation_loop.py
decisions:
  - "Move LLMProviderChain to TYPE_CHECKING in skeptic_agent.py: from __future__ import annotations makes all type annotations lazy strings, so the runtime import is unnecessary. This avoids the instructor/mistral import error in unit tests and is architecturally cleaner."
  - "Patch _run_typed on instance (not class) in tests: _run_typed is inherited from BaseAIWorker; monkeypatch.setattr on subclass fails unless the method is defined there. Instance patching is the correct pattern."
metrics:
  duration: ~7 minutes
  completed: "2026-05-31T13:30:33Z"
  tasks_completed: 3
  files_changed: 7
---

# Phase 095 Plan 05: SkepticEvaluator _run_typed Migration Summary

SkepticEvaluator migrated to pydantic-ai typed path via `_run_typed()` with `result_type=SkepticResult`, and agent_id renamed from `"skeptic_v1"` to `"skeptic"` across all operational references.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Migrate SkepticEvaluator to _run_typed(), rename agent_id | 78a76ba9 |
| 2 | Propagate agent_id rename to all operational references | c229ff8f |
| 3 | Update unit + integration tests | aaaf55b9 |

## What Was Built

**Task 1 - SkepticEvaluator migration:**
- Added `result_type: ClassVar[type[BaseModel]] = SkepticResult` to opt into `_run_typed()`
- Replaced `_llm_generate_structured()` call + `if result is None` guard with single `await self._run_typed(context, prompt=prompt, system=_SYSTEM_MESSAGE, max_tokens=500)`
- Renamed `agent_id = "skeptic_v1"` to `agent_id = "skeptic"` (D-15 AGENT-ID version suffix removed)
- Transfer function unchanged: `multiplier = (1.0 - failure_probability) * llm_confidence`
- Moved `LLMProviderChain` import to `TYPE_CHECKING` - avoids instructor/mistral broken import in tests
- The line-135 docstring referencing prompt-version `"skeptic_v1"` preserved (it identifies a prompt template, not the agent)
- No parallel class, no feature gate

**Task 2 - Rename propagation:**
- `services/alpha_swarm.py`: `_SWARM_AGENT_TO_TRANSFORM["skeptic_v1"]` -> `["skeptic"]`
- `src/api/routes/ai_stats.py`: `_AGENT_DISPLAY["skeptic_v1"]` -> `["skeptic"]`
- `tools/validate_skeptic.py`: help text example updated from `skeptic_v1` to `skeptic`

**Task 3 - Test updates:**
- `test_skeptic_agent.py`: Added `test_skeptic_evaluator_agent_id_and_result_type` (agent_id == "skeptic", result_type is SkepticResult), `test_compute_transfer_function_via_run_typed` (mocked _run_typed -> correct multiplier), `test_compute_neutral_on_validation_failure` (pydantic ValidationError -> neutral AgentOutput). Line 23 `ACTIVE_VERSION = "skeptic_v1"` monkeypatch preserved (selects prompt template, not agent id).
- `test_alpha_swarm.py`: All AGENT-ID `"skeptic_v1"` renamed to `"skeptic"`; expected `_SWARM_AGENT_TO_TRANSFORM` dict updated.
- `test_swarm_graduation_loop.py`: Function renamed `test_graduation_loop_promotes_skeptic_end_to_end`; all `component_name='skeptic'` SQL literals updated.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] LLMProviderChain moved to TYPE_CHECKING**
- **Found during:** Task 3 (test execution)
- **Issue:** `skeptic_agent.py` imported `LLMProviderChain` at module level, triggering the instructor -> mistral import chain which is broken in the current environment. This prevented all new SkepticEvaluator tests from collecting.
- **Fix:** Moved `from src.core.llm.chain import LLMProviderChain` under `if TYPE_CHECKING:`. With `from __future__ import annotations` already present, all type annotations are lazy strings so no runtime import is needed.
- **Files modified:** `src/intelligence/ai/alpha/skeptic_agent.py`
- **Commit:** aaaf55b9 (included in Task 3 commit)

**2. [Rule 1 - Bug] Instance patching for _run_typed in tests**
- **Found during:** Task 3
- **Issue:** `monkeypatch.setattr(SkepticEvaluator, "_run_typed", ...)` failed because `_run_typed` is defined on `BaseAIWorker`, not `SkepticEvaluator`. setattr can't add it to the subclass.
- **Fix:** Patched on the instance directly: `evaluator._run_typed = AsyncMock(...)`.
- **Files modified:** `tests/unit/services/test_skeptic_agent.py`
- **Commit:** aaaf55b9

**3. [Rule 1 - Bug] ValidationError capture in neutral-on-failure test**
- **Found during:** Task 3
- **Issue:** `try/except ValidationError as exc: validation_error = exc` silently showed the error output; `pytest.raises` is the correct pattern to collect without re-raising.
- **Fix:** Used `with pytest.raises(ValidationError) as exc_info:` and `validation_error = exc_info.value`.
- **Files modified:** `tests/unit/services/test_skeptic_agent.py`
- **Commit:** aaaf55b9

## Test Results

- `tests/unit/services/test_skeptic_agent.py`: 10 passed (7 pre-existing + 3 new)
- `tests/unit/services/test_alpha_swarm.py`: 28 failed (pre-existing instructor/mistral broken import, not caused by this plan), 1 passed (same as baseline)
- `tests/unit/` (excluding pre-broken API/core collection modules): 3979 passed, 31 skipped

## Self-Check: PASSED

All 7 modified files exist. All 3 task commits verified (78a76ba9, c229ff8f, aaaf55b9).
