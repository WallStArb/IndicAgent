---
phase: 106-foundation-hardening
plan: 01
subsystem: infra
tags: [dead-code, llm, settings, base-agent, template]

requires: []
provides:
  - Deleted ShadowRecorder archived stub (src/core/ml/shadow.py gone)
  - Deleted GuardrailsValidator no-op class and its dead branch in chain.py
  - Removed 7 dead Settings fields (LLM_RATE_LIMIT_RPM/TPM, SHADOW_CORRELATION_THRESHOLD, SHADOW_MIN_SAMPLES, LANGFUSE_HOST, MLFLOW_TRACKING_URI, SWARM_QUEUE_TIMEOUT_MS)
  - TEMPLATE_agent now routes LLM calls through the audited _llm_generate wrapper
  - BaseAIAgent.__init__ declares self._llm so unwired subclasses fail clearly
affects: [107-infrastructure-hygiene, 094-litellm-instructor, 095-pydantic-ai]

tech-stack:
  added: []
  patterns:
    - "Dead code deletion: verify zero callers via grep before deleting any file"
    - "Remove consumers before deleting the file to avoid orphan import crashes"
    - "TEMPLATE_agent pattern: _llm_generate not self._llm.generate() — audit trail by default"
    - "BaseAIAgent._llm: None default so missing wiring fails at first LLM call not attribute access"

key-files:
  created: []
  modified:
    - src/core/ml/__init__.py
    - src/core/llm/chain.py
    - src/config/settings.py
    - tests/unit/services/test_alpha_swarm_agent.py
    - src/intelligence/ai/TEMPLATE_agent.py
    - src/core/ai/base_agent.py
  deleted:
    - src/core/ml/shadow.py
    - src/core/llm/guardrails.py

key-decisions:
  - "Leave LLM_GUARDRAILS_REJECTIONS counter definition in metrics.py — harmless, out of scope"
  - "Use TYPE_CHECKING guard for LLMProviderChain import in base_agent.py to avoid circular imports"
  - "Add _report_parse_failure(call_id) to TEMPLATE_agent parse-fail path — matches skeptic_agent pattern"

requirements-completed: [FOUND-01]

duration: 15min
completed: 2026-05-24
---

# Phase 106 Plan 01: Foundation Hardening — Dead Code Deletion + AI Base Layer Fixes Summary

**Deleted ShadowRecorder (archived Phase 78) and GuardrailsValidator (never-populated no-op), removed 7 dead Settings fields, and fixed structural LLM audit defects in TEMPLATE_agent and BaseAIAgent**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-05-24T20:50:00Z
- **Completed:** 2026-05-24T20:53:30Z
- **Tasks:** 5
- **Files modified:** 6 (plus 2 deleted)

## Accomplishments

- Deleted 2 archived/dead files: `src/core/ml/shadow.py` (ShadowRecorder, archived Phase 78) and `src/core/llm/guardrails.py` (GuardrailsValidator, `_schemas` never populated so `has_schema()` always returns False — dead branch)
- Removed the dead `_guardrails.has_schema(...)` branch from `chain._generate_inner()` and all guardrails imports from chain.py; chain.py imports cleanly
- Removed 7 dead Settings fields with zero production callers confirmed via grep; removed matching dead test kwarg in alpha_swarm test fixture; Settings() instantiates cleanly; 29/29 alpha_swarm tests pass
- Fixed TEMPLATE_agent: replaced `self._llm.generate()` with `self._llm_generate(context, ...)` + proper `call_id` unpacking and `_report_parse_failure()` on parse failures — all agents copied from template inherit the LLM audit trail
- Fixed BaseAIAgent: declared `self._llm: LLMProviderChain | None = None` in `__init__`; subclasses overwrite it; unwired subclasses now fail with a clear error at first LLM call

## Task Commits

1. **Task 1: Delete ShadowRecorder archived stub** - `7f0fb919` (chore)
2. **Task 2: Remove GuardrailsValidator dead branch then delete guardrails.py** - `a9e03b58` (chore)
3. **Task 3: Remove 6 dead Settings fields and fix SWARM_QUEUE_TIMEOUT_MS test** - `9b43f0a7` (chore)
4. **Task 4: Fix TEMPLATE_agent LLM-audit bypass** - `66657f9f` (fix)
5. **Task 5: Declare self._llm on BaseAIAgent.__init__** - `9c55786d` (fix)

## Files Created/Modified

- `src/core/ml/shadow.py` - DELETED (archived ShadowRecorder, zero callers)
- `src/core/ml/__init__.py` - Removed 2-line comment referencing deleted shadow.py
- `src/core/llm/guardrails.py` - DELETED (no-op GuardrailsValidator, zero live callers)
- `src/core/llm/chain.py` - Removed GuardrailsValidator import, _guardrails singleton, dead has_schema branch, LLM_GUARDRAILS_REJECTIONS import; updated docstring
- `src/config/settings.py` - Removed 7 dead fields: LLM_RATE_LIMIT_RPM, LLM_RATE_LIMIT_TPM, SHADOW_CORRELATION_THRESHOLD, SHADOW_MIN_SAMPLES, LANGFUSE_HOST, MLFLOW_TRACKING_URI, SWARM_QUEUE_TIMEOUT_MS
- `tests/unit/services/test_alpha_swarm_agent.py` - Removed dead SWARM_QUEUE_TIMEOUT_MS=250 kwarg from test fixture
- `src/intelligence/ai/TEMPLATE_agent.py` - Replaced self._llm.generate() with self._llm_generate(); added call_id unpacking; added _report_parse_failure() on parse failure
- `src/core/ai/base_agent.py` - Added LLMProviderChain to TYPE_CHECKING imports; declared self._llm: LLMProviderChain | None = None in __init__

## Decisions Made

- Left `LLM_GUARDRAILS_REJECTIONS` counter definition in `metrics.py` — removing it overlaps Phase 105 (metrics audit) scope and the counter is harmless as an unused definition
- Used `TYPE_CHECKING` guard for `LLMProviderChain` import in `base_agent.py` — avoids circular import risk since chain.py imports from core.ai.*
- Added `_report_parse_failure(call_id)` to the TEMPLATE_agent parse-fail path to match the skeptic_agent canonical pattern exactly

## Deviations from Plan

None - plan executed exactly as written. All deletions preceded by grep verification confirming zero active callers.

## Issues Encountered

- Worktree had no `.venv` symlink; pre-commit hook looks for `${REPO_ROOT}/.venv/bin/ruff`. Created symlink from worktree to main project `.venv` to satisfy the hook. This is expected worktree setup.
- Collection errors for `test_trade_framer.py` and `test_winner_selector.py` in batch run — both pass individually and are pre-existing issues unrelated to this plan's changes.
- 57 pre-existing test failures across the suite (contract_resolution, base_writer, ai_context, etc.) confirmed pre-existing by checking with no local changes staged.

## Next Phase Readiness

- All touched modules import cleanly; full overall import verification passes
- 3996/4057 tests pass (57 pre-existing failures, 4 collection warnings unrelated to this plan)
- Ruff reports no new unused-import errors
- Phase 106-02 and remaining plans can proceed; dead code is gone

---
*Phase: 106-foundation-hardening*
*Completed: 2026-05-24*
