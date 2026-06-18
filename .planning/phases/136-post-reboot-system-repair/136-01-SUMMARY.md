---
phase: 136-post-reboot-system-repair
plan: "01"
subsystem: intelligence-trading
tags: [signal-schema, plugin-utils, validation, telemetry, w5, w6]
dependency_graph:
  requires: []
  provides: [ValidationResult, validate_signal_with_reason, atr_ratio_error_strings]
  affects: [executor.py, signal_writer.py, plugin_utils.py]
tech_stack:
  added: []
  patterns: [NamedTuple-with-bool, epsilon-guard, structured-log-reason]
key_files:
  created: []
  modified:
    - src/intelligence/trading/plugin_utils.py
    - src/intelligence/trading/signal_schema.py
    - src/intelligence/pipeline/executor.py
    - services/signal_writer.py
    - tests/unit/intelligence/test_signal_schema.py
decisions:
  - "ValidationResult.__bool__ delegates to .valid — all boolean call sites work unchanged"
  - "_ATR_EPSILON = 1e-8 placed at module level with comment explaining zero-ATR bars"
  - "signal_writer attaches _validation_reason to DLQ payload rather than adding a separate log call"
metrics:
  duration: "~10 minutes"
  completed: "2026-06-18"
  tasks_completed: 3
  files_modified: 5
---

# Phase 136 Plan 01: W5/W6 Signal Schema + Plugin Utils Repair Summary

**One-liner:** ValidationResult NamedTuple with per-failure reason codes added to validate_signal; ATR ratio label fix and epsilon guard added to plugin_utils stop-correction paths.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | W6 — ATR ratio label + epsilon guard | dd9f1aa5 | src/intelligence/trading/plugin_utils.py |
| 2 | W5 — ValidationResult NamedTuple | f89e9a65 | src/intelligence/trading/signal_schema.py |
| 3 | W5 — Executor/writer reason logging + test updates | e65a148b | executor.py, signal_writer.py, test_signal_schema.py |

## What Was Built

### W6: plugin_utils ATR ratio fix

Added `_ATR_EPSILON = 1e-8` module-level constant. Both `ValueError` messages in `validate_stop_against_zone` now interpolate `original_inside_distance / max(atr, _ATR_EPSILON)` so the reported number is a dimensionless ATR ratio. The threshold comparison `original_inside_distance > atr * 3.0` is unchanged. A zero-ATR bar now produces a large finite ratio in the error message rather than a `ZeroDivisionError`.

### W5: ValidationResult NamedTuple

`ValidationResult(NamedTuple)` with `valid: bool`, `reason: str`, and `__bool__(self) -> bool` returning `self.valid`. Placed above `validate_signal` in signal_schema.py.

`validate_signal` signature changed from `-> bool` to `-> ValidationResult`. All 8 failure paths return specific reason literals: `not_dict`, `missing_fields`, `type_mismatch`, `confidence_oor`, `direction_invalid`, `targets_empty`, `stop_geometry`, `target_geometry`. Success returns `ValidationResult(True, "")`.

### W5: Call site updates

- `executor.py`: `result = validate_signal(sig)` / `if not result:` / `reason=result.reason` added to `schema_violation` error log.
- `signal_writer.py`: ValidationResult captured per-signal; `_validation_reason` attached to DLQ payload for diagnosability.
- `test_signal_schema.py`: `is True`/`is False` identity assertions replaced with `bool()` checks and `.reason` assertions. `ValidationResult` imported.

## Verification

- `pytest tests/unit/intelligence/test_signal_schema.py tests/unit/intelligence/test_emit_signal_validation.py tests/unit/intelligence/test_plugin_utils.py`: 43 passed
- `ruff check` on all 4 modified source files: clean
- No call site treats `validate_signal` return as multi-element truthy tuple in boolean condition

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

### Files exist
- [x] src/intelligence/trading/plugin_utils.py — contains `_ATR_EPSILON = 1e-8`, 2x `max(atr, _ATR_EPSILON)`
- [x] src/intelligence/trading/signal_schema.py — contains `class ValidationResult(NamedTuple):`, `"not_dict"`, `__bool__`
- [x] src/intelligence/pipeline/executor.py — contains `reason=result.reason`
- [x] tests/unit/intelligence/test_signal_schema.py — updated

### Commits exist
- [x] dd9f1aa5 — W6 plugin_utils
- [x] f89e9a65 — W5 ValidationResult
- [x] e65a148b — W5 executor/writer/tests

## Self-Check: PASSED
