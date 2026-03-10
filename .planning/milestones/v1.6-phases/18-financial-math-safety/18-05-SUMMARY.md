---
phase: 18-financial-math-safety
plan: 05
subsystem: api
tags: [llm, providers, timeout, settings, configuration]

# Dependency graph
requires:
  - phase: 18-financial-math-safety
    provides: Settings.llm_timeout_sec configurable timeout field (plan 18-02)
provides:
  - All four LLM providers (OpenRouter, Anthropic, ZAI, Ollama) accept configurable timeout from Settings
affects: [ai_narrative_service, llm_providers, llm_chain]

# Tech tracking
tech-stack:
  added: []
  patterns: [All LLM provider __init__ methods accept optional timeout: float | None = None defaulting to _default_llm_timeout()]

key-files:
  created: []
  modified:
    - src/intelligence/llm_providers.py

key-decisions:
  - "Follow ZAIProvider pattern: timeout: float | None = None in __init__, self.timeout = timeout or _default_llm_timeout() in body"

patterns-established:
  - "LLM provider timeout pattern: all providers expose timeout in __init__ with Settings-backed default via _default_llm_timeout()"

requirements-completed: [API-04]

# Metrics
duration: 1min
completed: 2026-03-08
---

# Phase 18 Plan 05: LLM Provider Configurable Timeout Summary

**All four LLM providers (OpenRouterProvider, AnthropicProvider, ZAIProvider, OllamaProvider) now expose instance-level timeout in __init__ defaulting to Settings.llm_timeout_sec via _default_llm_timeout()**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-08T16:34:54Z
- **Completed:** 2026-03-08T16:35:47Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Added `timeout: float | None = None` parameter to OpenRouterProvider.__init__
- Added `timeout: float | None = None` parameter to AnthropicProvider.__init__
- Added `timeout: float | None = None` parameter to OllamaProvider.__init__
- All four providers now store `self.timeout = timeout or _default_llm_timeout()`, consistent with ZAIProvider

## Task Commits

Each task was committed atomically:

1. **Task 1: Add timeout parameter to OpenRouterProvider, AnthropicProvider, and OllamaProvider** - `f947597` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `src/intelligence/llm_providers.py` - Added timeout parameter + self.timeout storage to OpenRouterProvider, AnthropicProvider, OllamaProvider

## Decisions Made
None - followed plan as specified. Pattern was already established by ZAIProvider.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All LLM providers now consistently use Settings.llm_timeout_sec as default timeout
- Ready for plan 18-06 or subsequent gap closure plans

---
*Phase: 18-financial-math-safety*
*Completed: 2026-03-08*
