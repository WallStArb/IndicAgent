---
phase: 084-base-agent-hardening
plan: 02
subsystem: infra
tags: [pydantic, base-writer, dlq, otel, validation]

# Dependency graph
requires:
  - phase: 084-01
    provides: BaseAgent class attribute configuration and circuit breaker infra
provides:
  - BaseWriterAgent.payload_model ClassVar for per-subclass Pydantic schema declaration
  - Pydantic validation gate in _run() routing ValidationError to DLQ before _parse_payload
  - _do_flush() re-raise contract with buffer intact on failure
  - Three new unit tests verifying INFRA-01 and INFRA-02
affects:
  - 085-persistence-writer-migration

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "payload_model = MyModel on writer subclass triggers automatic Pydantic validation before _parse_payload"
    - "_do_flush() raises on flush failure; buffer stays intact; caller is responsible for retry"
    - "type(self).payload_model (class-level lookup) avoids instance attribute shadowing"

key-files:
  created: []
  modified:
    - src/core/agent/base_writer.py
    - tests/unit/test_base_writer_agent.py

key-decisions:
  - "payload_model uses ClassVar[type[BaseModel] | None] with None default for full backward compatibility"
  - "_parse_payload signature stays dict — BaseModel instance passed at runtime when payload_model declared (documented in docstring only)"
  - "_do_flush re-raise is unconditional after _flush_errors_total.add(1) — callers must handle exception"

patterns-established:
  - "INFRA-01: Writer subclasses opt-in to schema validation via payload_model class attribute; base handles DLQ routing automatically"
  - "INFRA-02: _do_flush always re-raises on failure; buffer-preserved-on-error is guaranteed by success-path-only buffer.clear()"

requirements-completed: [INFRA-01, INFRA-02]

# Metrics
duration: 8min
completed: 2026-05-16
---

# Phase 084 Plan 02: Base Writer Agent Contracts Summary

**Pydantic payload_model gate and _do_flush re-raise contract on BaseWriterAgent, enabling Phase 085 writer migration with automatic DLQ routing and no silent exception swallowing.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-16T19:15:00Z
- **Completed:** 2026-05-16T19:23:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added `payload_model: ClassVar[type[BaseModel] | None] = None` to BaseWriterAgent; subclasses declare once, get automatic Pydantic validation for free
- Inserted validation gate in `_run()` using `type(self).payload_model` (class-level to prevent instance shadowing); ValidationError routes to DLQ via `_maybe_route_to_dlq`, increments `_parse_failures_total`, and continues the consume loop (does not raise, does not buffer)
- `_do_flush()` except block now ends with bare `raise` after `_flush_errors_total.add(1)`; buffer is preserved because `_buffer.clear()` is only on the success path
- Updated two existing tests that previously expected swallowed exceptions to wrap with `pytest.raises(RuntimeError)` 
- Added three new tests: `test_payload_model_default_is_none`, `test_pydantic_validation_error_routes_to_dlq`, `test_pydantic_validation_success_passes_validated_model_to_parse`
- All 19 tests pass; ruff clean on both files

## Task Commits

1. **Task 1: Add Pydantic payload_model gate and re-raise in _do_flush** - `59b140d4` (feat)
2. **Task 2: Update existing flush tests and add Pydantic gate tests** - `d1a93461` (test)

## Files Created/Modified
- `src/core/agent/base_writer.py` - payload_model ClassVar, Pydantic gate in _run(), raise in _do_flush except block
- `tests/unit/test_base_writer_agent.py` - two test updates + three new Pydantic gate tests

## Decisions Made
- `payload_model` uses `ClassVar[type[BaseModel] | None]` with `None` default so all existing subclasses continue to work without modification (backward compatible opt-in)
- `_parse_payload` abstract method signature stays `dict` at the base level for source compatibility; documented in docstring that subclasses declaring `payload_model` receive a `BaseModel` instance at runtime
- `_do_flush` re-raise is unconditional - callers are responsible for handling the exception (teardown absorbs it gracefully since `_teardown` calls `_do_flush` only when buffer is non-empty)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None - both changes were straightforward modifications to existing code with clear patterns from the PATTERNS.md document.

## Next Phase Readiness
- INFRA-01 and INFRA-02 complete; Phase 085 persistence writer migration can now adopt `payload_model` declarations and rely on automatic DLQ routing
- The `_do_flush` re-raise contract means Phase 085 writers that previously swallowed exceptions will now surface errors; callers will need to handle or log them

---
*Phase: 084-base-agent-hardening*
*Completed: 2026-05-16*
