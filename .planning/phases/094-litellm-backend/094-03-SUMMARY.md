---
phase: 094-litellm-backend
plan: "03"
subsystem: llm
tags: [instructor, structured-output, pydantic, tdd, swarm-agents, circuit-breaker]
dependency_graph:
  requires:
    - 094-01 (LiteLLMBackend class with circuit breakers)
    - 094-02 (LLMProviderChain backed by LiteLLMBackend)
  provides:
    - LiteLLMBackend.generate_structured() with multi-provider fallback
    - LLMProviderChain.generate_structured() with audit on both success and failure paths
    - BaseAIAgent._llm_generate_structured() returning (BaseModel | None, call_id)
    - SkepticResult, CorrelationResult, CounterfactualResult, RegimeCoherenceResult BaseModels
  affects:
    - src/core/llm/litellm_backend.py (generate_structured, _instructor_client)
    - src/core/llm/chain.py (generate_structured with H1 audit correctness)
    - src/core/ai/base_agent.py (_llm_generate_structured mirroring _llm_generate)
    - src/intelligence/ai/alpha/skeptic_prompts.py (SkepticResult, delete _validate_skeptic_fields)
    - src/intelligence/ai/alpha/skeptic_agent.py (migrated to _llm_generate_structured)
    - src/intelligence/ai/alpha/correlation_agent.py (CorrelationResult, migrated)
    - src/intelligence/ai/alpha/counterfactual_agent.py (CounterfactualResult, migrated)
    - src/intelligence/ai/alpha/regime_coherence_agent.py (RegimeCoherenceResult, migrated)
tech_stack:
  added:
    - instructor>=1.0.0,<2.0.0 (Pydantic-based structured output for LiteLLM)
  patterns:
    - TDD (RED-GREEN cycle for all generate_structured() tests)
    - Instructor structured output via create_with_completion() for token usage capture
    - max_retries=1 enforcement (120s latency_budget_ms with ~50s/call models)
    - Module-level circuit breakers shared across generate() and generate_structured()
    - Pydantic BaseModel with field_validator for float clamping and list coercion
    - Migration order: Skeptic first as reference, then 3 remaining agents
key_files:
  created: []
  modified:
    - requirements.txt
    - src/core/llm/litellm_backend.py
    - src/core/llm/chain.py
    - src/core/ai/base_agent.py
    - src/intelligence/ai/alpha/skeptic_prompts.py
    - src/intelligence/ai/alpha/skeptic_agent.py
    - src/intelligence/ai/alpha/correlation_agent.py
    - src/intelligence/ai/alpha/counterfactual_agent.py
    - src/intelligence/ai/alpha/regime_coherence_agent.py
    - tests/unit/test_litellm_backend.py
    - tests/unit/services/test_skeptic_agent.py
    - tests/unit/services/test_correlation_agent.py
    - tests/unit/services/test_counterfactual_agent.py
    - tests/unit/services/test_regime_coherence_agent.py
    - tools/duplicate_test_allowlist.txt
decisions:
  - "Used instructor>=1.0.0,<2.0.0 (v1.x) -- v0.x upper bound in plan was revised because PyPI only offers v1.x as stable; create_with_completion() is available in v1.x"
  - "max_retries=1 enforced in generate_structured() -- instructor default is 3, but 3 x ~50s = 150s > 120s latency_budget_ms of all swarm agents"
  - "failure_reason column does not exist in llm_calls schema -- field is emitted in audit payload but not persisted; future migration needed"
  - "Skeptic migrated first as reference implementation, then 3 remaining agents one-by-one to limit blast radius"
  - "Narrative agent explicitly excluded -- returns prose, not JSON; instructor adds no value"
metrics:
  duration_minutes: 75
  tasks_completed: 10
  tasks_total: 10
  files_modified: 15
  completed_date: "2026-05-29"
---

# Phase 094 Plan 03: Instructor Structured Output Summary

Instructor-based structured output integrated into the LiteLLM stack; 4 swarm agents migrated from ad-hoc JSON parsing to typed Pydantic models; parse failure rate baseline captured at 3.70%.

## What Was Built

**LiteLLMBackend.generate_structured()** - multi-provider fallback structured output method:
- Iterates ALL providers with same fallback semantics as `generate()` (H2 fixed)
- Uses `create_with_completion()` to capture `(model, raw_completion)` for token usage (H3 fixed)
- Passes `max_retries=1` -- not instructor default 3 (120s budget constraint documented in code)
- Sets `last_failure_reason` on every non-success path: `circuit_open`, `all_providers_exhausted`, `instructor_validation_failed`, `provider_error` (M3)
- Calls `cb.record_failure()` on exception using same module-level `_OLLAMA_CB`/`_REMOTE_CB` as `generate()` (M6)

**LLMProviderChain.generate_structured()** - chain facade:
- `_publish_audit()` called on BOTH success and failure paths (H1 fixed)
- Failure path: `succeeded=False`, `parse_success=False`, `failure_reason` from backend
- `extra_audit` parameter with same semantics as `generate()` (M4)
- `llm.instructor_retries` span attribute set on every call

**BaseAIAgent._llm_generate_structured()** - agent method:
- Mirrors `_llm_generate()` exactly (same audit context, span setup, smc regime extraction)
- Returns `(BaseModel | None, call_id)` for `_report_parse_failure()` support
- `extra_audit` kwarg for additional audit fields (M4)

**4 Pydantic BaseModel result classes:**
- `SkepticResult` (skeptic_prompts.py): failure_probability, confidence, risk_factors, reasoning
- `CorrelationResult` (correlation_agent.py): coherence_score, confidence, contradicting_assets, reasoning
- `CounterfactualResult` (counterfactual_agent.py): plausibility, confidence, validation_conditions, invalidation_conditions, reasoning
- `RegimeCoherenceResult` (regime_coherence_agent.py): regime_fit, confidence, mismatches, reasoning

All BaseModels share the same validator pattern:
- Float fields clamped to [0.0, 1.0] via `@field_validator`
- List fields coerced to `list[str]` (non-list wrapped in `[str(v)]`)
- String fields coerced from any type

## Parse Failure Rate

**Baseline (7-day pre-migration):**
- Total calls: 18,369
- Parse failures: 679
- Failure rate: 3.70%

**Post-migration (1-hour window):**
- Total calls: 0 (insufficient data -- services just restarted)
- Comparison: DEFERRED -- re-check after next alpha_swarm cycle (~30 min)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] instructor v1.x API used instead of v0.x**
- **Found during:** Task 2
- **Issue:** Plan specified `instructor>=0.6.0,<1.0.0` but PyPI only offers v1.x as stable; v0.x is unavailable. The `create_with_completion()` interface is available in v1.x with the same semantics.
- **Fix:** Used `instructor>=1.0.0,<2.0.0`; verified `create_with_completion()` available before proceeding
- **Files modified:** requirements.txt
- **Commit:** bab32bb8

**2. [Rule 3 - Blocking] test_skeptic_agent.py imported deleted `_validate_skeptic_fields`**
- **Found during:** Task 7
- **Issue:** Existing test file imported the function that was deleted as part of the migration
- **Fix:** Rewrote test file to test `SkepticResult` BaseModel with equivalent coverage
- **Files modified:** tests/unit/services/test_skeptic_agent.py
- **Commit:** 3b979626

**3. [Rule 3 - Blocking] test_correlation_agent.py, test_counterfactual_agent.py, test_regime_coherence_agent.py imported deleted validators**
- **Found during:** Task 8
- **Issue:** All three test files imported deleted `_validate_*_fields` functions
- **Fix:** Rewrote all three test files to test new BaseModel classes with equivalent coverage
- **Files modified:** tests/unit/services/test_correlation_agent.py, test_counterfactual_agent.py, test_regime_coherence_agent.py
- **Commit:** d0b442df

**4. [Rule 3 - Blocking] Duplicate test names blocked pre-commit hook**
- **Found during:** Task 8 commit
- **Issue:** New `test_result_*` test names in 3 files triggered the `check_duplicate_tests` pre-commit hook
- **Fix:** Added `test_result_*` patterns to `tools/duplicate_test_allowlist.txt` (intentional structural duplicates for agent family pattern tests)
- **Files modified:** tools/duplicate_test_allowlist.txt
- **Commit:** d0b442df

### Schema Gap (Deferred)

**failure_reason column not in llm_calls schema:**
The `failure_reason` field is emitted in the audit payload via `_publish_audit()` but the `llm_calls` table does not yet have this column. The DB writer silently ignores unknown fields. A future migration is needed to persist this field for M3 failure taxonomy queries.

## Commits

| Hash | Message |
|------|---------|
| bab32bb8 | chore(094-03): add instructor>=1.0.0,<2.0.0 to requirements |
| 0bc3bea9 | test(094-03): add failing tests for generate_structured() -- H2, H3, M6 |
| 5c46f227 | feat(094-03): add generate_structured() to LiteLLMBackend -- H1, H2, H3 |
| 955bb4b7 | feat(094-03): add generate_structured() to LLMProviderChain and BaseAIAgent |
| 3b979626 | feat(094-03): migrate Skeptic agent to instructor structured output (M5 ref impl) |
| d0b442df | feat(094-03): migrate Correlation, Counterfactual, RegimeCoherence to instructor (M5) |

## Verification Results

- `pytest tests/unit/ -v` exits 0; 4049 passed, 31 skipped
- All 19 tests in `test_litellm_backend.py` pass (11 from Plans 01-02 + 8 from this plan)
- Import smoke test prints "All imports OK"
- `grep -rn "_validate_skeptic_fields\|_validate_correlation_fields\|_validate_counterfactual_fields\|_validate_regime_coherence_fields" src/` returns zero matches
- `grep -n "_llm_generate_structured\|generate_structured" src/intelligence/ai/narrative/narrative_agent.py` returns zero matches (narrative unchanged)
- Both `indicagent-alpha-swarm` and `indicagent-intelligence-pipeline` restarted to `active (running)`
- No instructor, import-error, or AttributeError messages in alpha_swarm log
