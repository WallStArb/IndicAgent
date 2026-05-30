---
phase: 094-litellm-backend
plan: "01"
subsystem: llm
tags: [litellm, llm-backend, circuit-breaker, tdd, ollama]
dependency_graph:
  requires: []
  provides:
    - LiteLLMBackend class (src/core/llm/litellm_backend.py)
    - litellm>=1.40.0,<2.0.0 dependency
  affects:
    - src/core/llm/chain.py (LLMProviderChain._inner compatible backend)
tech_stack:
  added:
    - litellm>=1.40.0,<2.0.0
  patterns:
    - TDD (RED-GREEN cycle)
    - Module-level circuit breakers (shared state, not per-instance)
    - Side-effect attributes (last_provider_id, last_token_usage) instead of tuple returns
key_files:
  created:
    - src/core/llm/litellm_backend.py
    - tests/unit/test_litellm_backend.py
  modified:
    - requirements.txt
decisions:
  - "Used src.observability.circuit_breaker.CircuitBreaker (not PluginCircuitBreaker) for allow_request()/record_success()/record_failure() manual-tracking API (per CLAUDE.md Phase 086 note)"
  - "Removed importlib.reload() from tests that patch acompletion — reload rebinds from litellm, bypassing patch on module namespace"
  - "CircuitBreakerConfig constants kept as _OLLAMA_CB_CONFIG/_REMOTE_CB_CONFIG for spec documentation even though CircuitBreaker uses scalar params"
metrics:
  duration_minutes: 6
  completed_date: "2026-05-29"
  tasks_completed: 3
  files_created: 2
  files_modified: 1
---

# Phase 094 Plan 01: LiteLLMBackend Summary

**One-liner:** LiteLLMBackend wrapping litellm.acompletion with Ollama think=False/num_ctx kwargs, think-tag stripping, per-provider-type circuit breakers, and str|None return matching LLMChain interface.

## What Was Built

`LiteLLMBackend` is a drop-in compatible backend for `LLMProviderChain._inner` that replaces the per-provider `OllamaProvider`/`OpenRouterProvider` classes with LiteLLM's unified `acompletion()` interface.

**Key design decisions:**
- `generate()` returns `str | None` (never a tuple) - matches `LLMChain.generate()` exactly so `_generate_inner()` can read `self._inner.last_provider_id` as a side-effect attribute
- Module-level `_OLLAMA_CB` and `_REMOTE_CB` are shared across all instances - prevents fresh-breaker bypass attacks
- `_build_extra_kwargs()` passes `think=False` and `options.num_ctx` for Ollama providers - preserves behavior from old `OllamaProvider`
- `_strip_thinking_tags()` defense-in-depth for `<think>...</think>` removal
- `litellm.telemetry = False` and `success_callback = []` prevent prompt leakage to external services

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Install LiteLLM | 15ab1072 | requirements.txt |
| 2 | Write failing unit tests | b05ed7f1 | tests/unit/test_litellm_backend.py |
| 3 | Implement LiteLLMBackend | e7f73cbd | src/core/llm/litellm_backend.py, tests/unit/test_litellm_backend.py |

## Verification Results

- All 10 unit tests pass
- 4062 existing unit tests unaffected (0 new failures)
- `generate()` has zero tuple return sites (grep confirmed)
- `litellm.telemetry = False` and `litellm.success_callback = []` present in `_configure_litellm()`
- Class docstring declares NOT thread-safe, one instance per LLMProviderChain
- `litellm>=1.40.0,<2.0.0` in requirements.txt; v1.86.2 installed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Used CircuitBreaker instead of PluginCircuitBreaker**
- **Found during:** Task 3
- **Issue:** Plan spec said `PluginCircuitBreaker(CircuitBreakerConfig(...))` but the described interface (`allow_request()`, `record_success()`, `record_failure()`) belongs to `src.observability.circuit_breaker.CircuitBreaker`, not `PluginCircuitBreaker`. `PluginCircuitBreaker` has `_should_use_fallback()` and async `_record_success()/_record_failure()` - incompatible with manual tracking pattern.
- **Fix:** Used `CircuitBreaker` from `src.observability.circuit_breaker` which has the exact manual-tracking API described in CLAUDE.md Phase 086 note. `CircuitBreakerConfig` constants preserved as module-level docs.
- **Files modified:** src/core/llm/litellm_backend.py
- **Commit:** e7f73cbd

**2. [Rule 1 - Bug] Removed importlib.reload() from tests patching acompletion**
- **Found during:** Task 3 (GREEN phase - 3 of 10 tests failed)
- **Issue:** Tests used `importlib.reload(mod)` inside `patch("...acompletion")` context. Reload re-imports `acompletion` from litellm, binding the real function in the module namespace and bypassing the patch.
- **Fix:** Removed `importlib.reload()` from tests that patch `acompletion`. Module-level circuit breakers start CLOSED so test isolation is maintained without reload.
- **Files modified:** tests/unit/test_litellm_backend.py
- **Commit:** e7f73cbd

**3. [Rule 3 - Blocking] Symlinked .venv into worktree for pre-commit hook**
- **Found during:** Task 2 commit
- **Issue:** Pre-commit hook searches for `$REPO_ROOT/.venv/bin/ruff` but worktree has no `.venv`. `which ruff` also fails. Hook blocked commits.
- **Fix:** `ln -sf /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a4f8dec55f382f4a8/.venv` - symlink lets hook find ruff/black.
- **Files modified:** (symlink only, not tracked)

## Self-Check: PASSED

- `src/core/llm/litellm_backend.py` exists: FOUND
- `tests/unit/test_litellm_backend.py` exists: FOUND
- `requirements.txt` contains `litellm>=1.40.0,<2.0.0`: FOUND (line 50)
- Commits 15ab1072, b05ed7f1, e7f73cbd: FOUND in git log
- All 10 unit tests: PASSED
