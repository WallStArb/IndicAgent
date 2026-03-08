---
phase: 18-financial-math-safety
plan: 02
type: execute
wave: 1
depends_on: []
completed_at: "2026-03-08T14:15:49Z"
duration_minutes: 3
tags:
  - configuration
  - timeouts
  - pydantic-settings
---

# Phase 18 Plan 02: Configurable Timeouts Summary

Added configurable timeout settings for IBKR and LLM providers to the Settings class, enabling runtime configuration of API timeouts without code changes.

## One-Liner

Added `ib_timeout_sec` (20.0s default) and `llm_timeout_sec` (60.0s default) with environment variable overrides for production hardening.

## Completed Tasks

| Task | Name | Commit | Files |
| ---- | ----- | ------ | ----- |
| 1 | Add ib_timeout_sec to Settings class | 991ce9d | src/config/settings.py |
| 2 | Add llm_timeout_sec to Settings class | d58c33d | src/config/settings.py |

## Key Deliverables

### `src/config/settings.py`

Added two new fields to the `Settings` class:

1. **`ib_timeout_sec: float = Field(default=20.0, ...)`**
   - Default timeout: 20.0 seconds for IBKR API operations
   - Environment variables: `IBKR_TIMEOUT_SEC` (preferred), `IB_TIMEOUT_SEC` (legacy), `ib_timeout_sec`
   - Description: Timeout for connect requests to IBKR TWS

2. **`llm_timeout_sec: float = Field(default=60.0, ...)`**
   - Default timeout: 60.0 seconds for LLM provider API calls
   - Environment variables: `LLM_TIMEOUT_SEC`, `llm_timeout_sec`
   - Applies to: Ollama, ZAI, OpenRouter, Anthropic providers

## Deviations from Plan

None - plan executed exactly as written.

## Success Criteria Met

- [x] Settings().ib_timeout_sec returns 20.0 by default
- [x] Settings().llm_timeout_sec returns 60.0 by default
- [x] Environment variable IBKR_TIMEOUT_SEC overrides ib_timeout_sec
- [x] Environment variable LLM_TIMEOUT_SEC overrides llm_timeout_sec

## Verification Tests

All automated tests passed:
- Default values: ib_timeout_sec=20.0, llm_timeout_sec=60.0
- IBKR_TIMEOUT_SEC=30.0 overrides default
- LLM_TIMEOUT_SEC=90.0 overrides default

## Technical Notes

- Uses `AliasChoices` for flexible environment variable naming (matching existing pattern in `ib_host`/`ib_port`)
- Timeout values are `float` type for sub-second precision if needed
- No code changes required in consuming services (ibkr.py, llm_providers.py) — values accessed via Settings
- Settings follow pydantic-settings best practices with validation_alias

## Renaissance Framing

"Degrade gracefully, adapt automatically" — By exposing these timeouts via environment variables, operators can tune them for network conditions without code deployments. If a provider becomes slower in production, increase the timeout via config change only.

## Related Files

- `src/config/settings.py` — Modified
- `src/providers/ibkr.py` — Can consume via `settings.ib_timeout_sec` (future work)
- `src/intelligence/llm_providers.py` — Can consume via `settings.llm_timeout_sec` (future work)

## Commits

- 991ce9d: feat(18-02): add ib_timeout_sec to Settings class
- d58c33d: feat(18-02): add llm_timeout_sec to Settings class
