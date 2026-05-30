---
phase: 094-litellm-backend
plan: "02"
subsystem: llm
tags: [litellm, llm-backend, chain-wiring, provider-cleanup, tdd]
dependency_graph:
  requires:
    - 094-01 (LiteLLMBackend class)
  provides:
    - LLMProviderChain backed by LiteLLMBackend
    - OllamaProvider/OpenRouterProvider/LLMChain deleted from providers.py
  affects:
    - src/core/llm/chain.py (LLMProviderChain._inner is now LiteLLMBackend)
    - src/core/llm/providers.py (dead classes removed)
    - src/core/llm/__init__.py (old exports removed)
tech_stack:
  added: []
  patterns:
    - TDD (RED wire-up test first, then GREEN after chain.py edit)
    - No-op close() for library-managed connection pools
key_files:
  created: []
  modified:
    - src/core/llm/chain.py
    - src/core/llm/providers.py
    - src/core/llm/__init__.py
    - tests/unit/test_litellm_backend.py
    - tests/unit/intelligence/test_llm_providers.py
decisions:
  - "close() is now a no-op pass — LiteLLM manages its own HTTP pool; no provider objects to close"
  - "Rate-limiter keys use slash-format matching LiteLLM (settings.LLM_RATE_LIMITS keys must be slash-format)"
  - "providers.py retains no production code — becomes an empty stub with a deprecation comment"
  - "TestAlphaAgentSystemMessages kept in test_llm_providers.py; all other tests deleted"
  - "Model pull (nemotron-3-nano:4b not installed) treated as infrastructure gap, not a code bug"
metrics:
  duration_minutes: 8
  completed_date: "2026-05-29"
  tasks_completed: 5
  files_created: 0
  files_modified: 5
---

# Phase 094 Plan 02: LiteLLM Wire-Up Summary

**One-liner:** LLMProviderChain wired to LiteLLMBackend; OllamaProvider/OpenRouterProvider/LLMChain deleted; rate-limiter keys confirmed slash-format; services restarted clean.

## What Was Built

`LLMProviderChain` now delegates directly to `LiteLLMBackend(settings)` instead of building a list of `OllamaProvider`/`OpenRouterProvider` instances and passing them to `LLMChain`. The old provider classes and their supporting utilities have been removed from `providers.py`, which now serves as an empty stub. The `__init__.py` exports only `LLMProviderChain`.

**Key changes:**
- `chain.py`: replaced `LLMChain` import + `_build_providers` method + `self._inner = LLMChain(providers)` with `self._inner = LiteLLMBackend(settings)` directly
- `close()` is a no-op pass (LiteLLM manages its own HTTP connection pool internally)
- `last_provider_id` docstring updated to slash-format (`ollama/nemotron-3-nano:4b`)
- Rate-limiter lookup unchanged: reads slash-format keys from `settings.LLM_RATE_LIMITS`; no hardcoded colon-format keys existed
- `providers.py`: 453 lines of `OllamaProvider`, `OpenRouterProvider`, `LLMChain`, `_call_llm_with_circuit_breaker`, `_OpenAICompatProvider` and helpers deleted
- `test_llm_providers.py`: 18 tests covering deleted classes removed; `TestAlphaAgentSystemMessages` (4 tests) kept

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add wire-up test (RED) | 72655110 | tests/unit/test_litellm_backend.py |
| 2 | Update chain.py — swap LLMChain for LiteLLMBackend | fd4804d4 | src/core/llm/chain.py |
| 3 | Delete dead provider classes and update tests | 766ff007 | src/core/llm/providers.py, src/core/llm/__init__.py, tests/unit/intelligence/test_llm_providers.py |
| 4 | Smoke test LiteLLMBackend against live Ollama | (no commit — verification only) | — |
| 5 | Restart services and verify | (no commit — runtime verification) | — |

## Verification Results

- `grep "LLMChain\|OllamaProvider\|OpenRouterProvider" src/core/llm/chain.py` returns 0 matches
- `grep "LiteLLMBackend" src/core/llm/chain.py` shows import + construction
- `git grep 'class OllamaProvider\|class OpenRouterProvider\|class LLMChain' -- src/` returns 0 matches
- All 11 `test_litellm_backend.py` tests pass (10 from Plan 01 + new wire-up test)
- Full unit suite: 4041 passed, 31 skipped, 0 failures (vs 4059 passed before - reduction is 18 deleted tests)
- Live smoke test: `SMOKE TEST PASSED` with `provider: ollama/nemotron-3-nano:4b`, `result: {"ok": true}`, `tokens: {'prompt_tokens': 61, 'completion_tokens': 6, 'total_tokens': 67}`
- All three services (`indicagent-intelligence-pipeline`, `indicagent-alpha-swarm`, `indicagent-narrative-compute`) show `Active: active (running)`
- No LiteLLM import errors or OllamaProvider/OpenRouterProvider references in logs

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] nemotron-3-nano:4b not installed in Ollama**
- **Found during:** Task 4
- **Issue:** `ollama list` showed model not present; smoke test returned `None` with `OllamaException - {"error":"model 'nemotron-3-nano:4b' not found"}`
- **Fix:** `docker exec ollama ollama pull nemotron-3-nano:4b` to install; waited until `ollama list` confirmed it before re-running smoke test
- **Files modified:** (no code changes — infrastructure only)
- **Commit:** (no commit needed)

**2. [Rule 3 - Blocking] .venv symlink missing in worktree**
- **Found during:** Pre-execution setup
- **Issue:** Same as Plan 01 — worktree has no .venv, pre-commit hook needs ruff/black
- **Fix:** `ln -sf /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a5d88154696b8eef2/.venv`
- **Files modified:** (symlink only, not tracked)

**3. [Out of scope] Pre-existing BarMessage attribute error in intelligence-pipeline**
- `'BarMessage' object has no attribute 'tf'` errors (6872 occurrences) appear in intelligence_pipeline_agent.log
- Pre-existing before this phase; unrelated to LLM changes
- Logged to deferred items; not fixed

### Out-of-Scope Items Noted

The `BarMessage 'tf' attribute` error appears to be a pre-existing bar replay issue unrelated to Phase 094 LLM work. Not investigated or fixed.

## Self-Check: PASSED

- `src/core/llm/chain.py` exists and imports LiteLLMBackend: FOUND
- `src/core/llm/providers.py` exists with no class definitions: FOUND
- `src/core/llm/__init__.py` exports only LLMProviderChain: FOUND
- Commits 72655110, fd4804d4, 766ff007: FOUND in git log
- All 11 unit tests: PASSED
- Three services active (running): CONFIRMED
