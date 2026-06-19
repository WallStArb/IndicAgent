---
phase: 122-production-hardening
plan: 01
subsystem: intelligence-schemas
tags: [schema, i2-events, pydantic, validation, composite-plugins]
dependency_graph:
  requires: []
  provides: [I2Events-strict-contract, I2-validate_schema_coverage]
  affects: [intelligence_pipeline, register_plugins, test_i2_schema]
tech_stack:
  added: []
  patterns: [pydantic-extra-forbid, validate_schema_coverage-tier-check]
key_files:
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/register_plugins.py
    - tests/unit/intelligence/test_i2_schema.py
  created:
    - tests/unit/intelligence/test_schemas.py
key_decisions:
  - D-01: I2Events field count = 45 (34 existing - 8 MACD + 19 composite)
  - D-02: Replace extra='allow' with extra='forbid' on I2Events
  - D-03: Enable I2 validation in register_plugins.py validate_schema_coverage()
metrics:
  duration_seconds: 210
  completed_date: 2026-06-12
  tasks_completed: 3
  tasks_total: 3
  files_modified: 4
---

# Phase 122 Plan 01: I2Events Schema Contract Summary

I2Events rewritten to 45-field strict contract (extra="forbid"), 8 dead MACD fields removed, 19 composite plugin fields added, and I2 tier validation enabled at startup.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewrite I2Events schema to 45-field strict contract | 27c466b6 | src/intelligence/schemas.py |
| 2 | Enable I2 schema validation in register_plugins.py | c9a19180 | src/intelligence/register_plugins.py |
| 3 | Add I2Events schema contract tests | 8f62dc04 | tests/unit/intelligence/test_schemas.py, test_i2_schema.py |

## What Was Built

**Task 1 - I2Events rewrite:**
- Removed 8 MACD field declarations (macd_cross_bullish, macd_cross_bearish, macd_cross_bars_ago, macd_hist_positive, macd_hist_turning_up, macd_negative_support_test, macd_price_divergence_bullish, macd_price_divergence_bearish) - these belong to I3Structure.struct_MACDEvents
- Added 19 composite plugin fields across 4 plugins: cmp_MomentumAccel (9), cmp_DerivativeOscillator (4), cmp_ExhaustionScore (3), cmp_AccelerationRegime (3)
- Replaced `extra="allow"` with `extra="forbid"` - any undeclared field now raises pydantic.ValidationError
- Field count: 34 existing - 8 MACD + 19 composite = 45 total

**Task 2 - validate_schema_coverage:**
- Added `I2Events` import to register_plugins.py
- Added I2 as first entry in `tier_checks` list with all 10 I2 plugins
- Removed "I2 are skipped (extra='allow')" from docstring
- `validate_schema_coverage()` now crashes startup if any I2 plugin emits an undeclared field

**Task 3 - Tests:**
- Created `test_schemas.py` with `TestI2EventsSchema` (5 tests): field count assertion, extra field rejection, all 19 composite fields accepted, empty construction
- Rewrote `test_i2_schema.py`: assert all 8 removed MACD fields are absent, assert composite fields present, assert ValidationError on undeclared fields
- 22 tests pass; 40 pre-existing failures in unrelated test files (test_run_historical_pipeline.py, test_pipeline_reset.py, test_signal_replay_auditor.py)

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

**Files exist:**
- `src/intelligence/schemas.py` - FOUND (modified)
- `src/intelligence/register_plugins.py` - FOUND (modified)
- `tests/unit/intelligence/test_schemas.py` - FOUND (created)
- `tests/unit/intelligence/test_i2_schema.py` - FOUND (modified)

**Commits exist:**
- 27c466b6 - FOUND: feat(122-01): rewrite I2Events to 45-field strict contract
- c9a19180 - FOUND: feat(122-01): enable I2 schema validation in register_plugins
- 8f62dc04 - FOUND: test(122-01): add I2Events schema contract tests

**Verification results:**
- `I2Events.model_fields` count: 45
- `I2Events(macd_cross_bullish=1.0)` raises ValidationError: PASS
- `I2Events(rsi_accel=0.1, exhaustion_side="long")` succeeds: PASS
- `validate_schema_coverage()` after `register_all_plugins()`: OK

## Self-Check: PASSED
