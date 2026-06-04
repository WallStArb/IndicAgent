---
phase: 095-pydantic-ai-agents
plan: 02
subsystem: llm
tags: [litellm, ollama, response_format, json_schema, structured_output, chain, pydantic-ai]

requires:
  - phase: 094-litellm-instructor
    provides: LiteLLMBackend and LLMProviderChain baseline implementation

provides:
  - response_format parameter on LLMProviderChain.generate() and LiteLLMBackend.generate()
  - Conditional acompletion() kwarg injection (only when response_format is not None)
  - Cache bypass for structured calls (response_format != None skips cache get/put)
  - Full unit test coverage for both backend and chain layers

affects: [095-03-LLMAdapter, any caller of chain.generate() or litellm_backend.generate()]

tech-stack:
  added: []
  patterns:
    - Conditional kwarg injection - add to dict only when not None, never pass None explicitly
    - Cache bypass pattern - guard both cache get and put with the same condition

key-files:
  created:
    - tests/unit/core/test_llm_response_format.py
  modified:
    - src/core/llm/litellm_backend.py
    - src/core/llm/chain.py

key-decisions:
  - "response_format forwarded to acompletion() via conditional dict insert, not unconditional kwarg - preserves byte-for-byte default path"
  - "Semantic cache skipped for structured calls (response_format is not None) on both get and put paths - structured outputs should not be cached"
  - "Audit trail (_publish_audit) preserved for structured calls - not gated by response_format"
  - "Test instructor stub via sys.modules injection before import - works around broken mistralai transitive import in installed instructor version"

patterns-established:
  - "Conditional kwarg injection: build kwargs dict, then `if value is not None: kwargs[key] = value` before passing **kwargs to third-party call"
  - "Cache bypass: add `and condition is None` to both cache get and cache put guards using same variable"

requirements-completed:
  - AGENT-EXEC-01

duration: 12min
completed: 2026-05-31
---

# Phase 095 Plan 02: response_format threading through LLM chain Summary

**`response_format: dict | None = None` threaded from LLMProviderChain.generate() through LiteLLMBackend.generate() to acompletion() conditionally, with cache bypass and full unit test coverage at both layers**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-31T09:00:00Z
- **Completed:** 2026-05-31T09:12:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- `LiteLLMBackend.generate()` accepts `response_format: dict | None = None`; passes it to `acompletion()` only when non-None so the default code path is byte-for-byte unchanged
- `LLMProviderChain.generate()` and `_generate_inner()` accept and forward `response_format`; semantic cache is bypassed (both get and put) when response_format is non-None; audit trail preserved
- 4 unit tests cover both the backend and chain layers, including the presence and absence paths

## Task Commits

1. **Task 1: Thread response_format through LiteLLMBackend.generate()** - `9c559caa` (feat)
2. **Task 2: Thread response_format through LLMProviderChain.generate()** - `96c48184` (feat)
3. **Task 3: Unit tests for response_format threading** - `01d964b8` (test)

## Files Created/Modified

- `src/core/llm/litellm_backend.py` - Added `response_format` param to `generate()`; conditional injection into `extra` dict before `acompletion()` call
- `src/core/llm/chain.py` - Added `response_format` to `generate()` and `_generate_inner()`; cache get/put guarded with `and response_format is None`; forwarded to `self._inner.generate()`
- `tests/unit/core/test_llm_response_format.py` - 4 async tests covering backend pass-through, backend omission, chain forwarding, chain None default

## Decisions Made

- Conditional dict insert rather than unconditional kwarg: `if response_format is not None: extra["response_format"] = response_format` - avoids passing `response_format=None` to acompletion() which may differ from omitting it entirely
- Cache skipped for structured calls on both sides (get and put) - structured outputs are deterministic given the schema and should not be served from a semantic cache
- Audit trail runs unconditionally - structured LLM calls need the same traceability as unstructured ones

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `instructor` package has a broken transitive import (`mistralai.Mistral` not found) in the installed version. `litellm_backend.py` imports instructor at module level, which causes collection errors for any test that imports the module. Resolved by stubbing `sys.modules["instructor"]` and sub-modules before importing the module under test. This is a pre-existing environment issue; documented in test file.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 03 (LLMAdapter) can now call `chain.generate(..., response_format=schema)` to enforce grammar-constrained output at generation time via Ollama
- All callers that omit `response_format` are unaffected - zero behavioral change to existing code

---
*Phase: 095-pydantic-ai-agents*
*Completed: 2026-05-31*
