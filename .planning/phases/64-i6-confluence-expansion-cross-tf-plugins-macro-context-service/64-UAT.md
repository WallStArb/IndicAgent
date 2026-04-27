---
status: complete
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
source:
  - 64-00-SUMMARY.md
  - 64-01-GAPCLOSURE-SUMMARY.md
  - 64-02-GAPCLOSURE-SUMMARY.md
  - 64-03A-REVISED-SUMMARY.md
  - 64-03B-SUMMARY.md
  - 64-03-GAPCLOSURE-SUMMARY.md
  - 64-04-SUMMARY.md
started: 2026-04-27T00:00:00Z
updated: 2026-04-27T17:40:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Unit Tests Pass
expected: Running `.venv/bin/pytest tests/unit/ -v -k "backtest or validate or momentum_divergence or cross_tf or macro_compute or yield_curve"` returns all tests passing — approximately 82 total across: backtest infrastructure (11), CrossTFMomentumDivergence (15), 4 additional cross-TF plugins (27), yield curve (6), MacroComputeAgent (23).
result: issue
reported: "2 tests failed in test_backtest_i6_plugin.py — mock data used wrong column keys (i2_events/i3_patterns/i4_context/i5_patterns) instead of actual DB column names (i2/i3/i4/i5). Fixed in test file. 103/103 pass after fix."
severity: minor

### 2. I6Confluence Schema Has New ctf_* Fields
expected: `I6Confluence.model_fields` includes 10 new gradient/regime fields added by Phase 64.
result: pass

### 3. All 5 Cross-TF Plugins Registered in TIER_I6
expected: TIER_I6 includes all 6 plugin names (original + 5 new from Phase 64).
result: pass

### 4. MacroComputeAgent Imports Without Errors
expected: `import services.macro_compute_agent` prints OK; grep for TODO/pass stubs returns 0.
result: pass

### 5. macro_features Table Has FTQ Columns
expected: `\d macro_features` shows ftq_score, ftq_regime alongside yield_curve_slope, yield_curve_regime.
result: pass

### 6. Backtest Scripts Compile and Accept --help
expected: All 5 backtest/validation scripts compile cleanly with py_compile.
result: pass

### 7. validate_i6_backtest D-25 Gate Has VALIDATED/TWEAK/KILL Decisions
expected: ValidationResults dataclass has `decision` field; CLI --help works.
result: pass

## Summary

total: 7
passed: 6
issues: 1
pending: 0
skipped: 0

## Gaps

- truth: "Unit tests for backtest_i6_plugin.py use correct DB column names (i2, i3, i4, i5)"
  status: fixed
  reason: "Mock data used i2_events/i3_patterns/i4_context/i5_patterns — wrong keys, tool uses i2/i3/i4/i5 matching actual intelligence_features schema. Fixed inline."
  severity: minor
  test: 1
  artifacts:
    - tests/unit/tools/test_backtest_i6_plugin.py
  missing: []
