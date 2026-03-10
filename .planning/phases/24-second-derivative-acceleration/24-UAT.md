---
status: diagnosed
phase: 24-second-derivative-acceleration
source: 24-01-SUMMARY.md, 24-02-SUMMARY.md, 24-03-SUMMARY.md, 24-04-SUMMARY.md, 24-05-SUMMARY.md, 24-06-SUMMARY.md
started: 2026-03-10T12:50:00Z
updated: 2026-03-10T13:00:00Z
---

## Current Test

[testing complete]

## Tests

## Tests

### 1. Full Unit Test Suite
expected: Run .venv/bin/pytest tests/unit/ -v — all 1482 tests pass, zero failures
result: pass

### 2. Plugin Registration Validation
expected: Start indicator_service and market_analysis_service. Both should start without crashes. validate_tier() should find all 25 TIER_I1 plugins, 11 TIER_I2 plugins, 8 TIER_I3 plugins. Services should log plugin counts on startup.
result: pass

### 3. Dashboard Signals Page Loads
expected: Open dashboard at http://localhost:3000, navigate to Signals panel. Page should load without errors. Signal cards should display normally (signals may be sparse until pipeline warms up).
result: pass

### 4. Ruff Code Quality Check
expected: Run .venv/bin/ruff check . from project root. Only known E501 line-too-long errors (non-blocking) should appear. No new errors from files modified in phase 24.
result: pass

### 5. Intelligence Features in Live Pipeline
expected: After waiting ~50 minutes for pipeline warmup (signal generator needs 50+ live 1m bars), intelligence_features table should contain rows with new fields: hma_20, rsi_curvature, macd_hist_slope, price_accel, hma_slope, hma_accel, exhaustion_score, exhaustion_side, exhaustion_bars, accel_regime, accel_score, accel_agreement, struct_energy, struct_accel_bias, swing_amplitude_ratio, swing_amplitude_expanding.
result: issue
reported: "market_analysis_service running but not consuming - 0 consumers in group, 0 new intelligence_features rows in 50 minutes since restart. Latest intelligence_features row from 2026-03-09, service restarted 2026-03-10 09:47:51."
severity: blocker

## Summary

total: 5
passed: 4
issues: 1
pending: 0
skipped: 0

## Gaps

- truth: "market_analysis_service consumes from indicator streams and writes new intelligence features (hma_20, exhaustion_score, accel_regime, struct_energy, etc.) to intelligence_features table"
  status: failed
  reason: "User reported: market_analysis_service running but not consuming - 0 consumers in group, 0 new intelligence_features rows in 50 minutes since restart. Latest intelligence_features row from 2026-03-09, service restarted 2026-03-10 09:47:51."
  severity: blocker
  test: 5
  root_cause: "I3Structure Pydantic schema missing 6 field declarations for SwingMomentum outputs: swing_amplitude_ratio, swing_amplitude_expanding, swing_velocity_bars, swing_velocity_trend, struct_energy, struct_accel_bias. Schema has extra='forbid', so every IntelligenceEvent validation fails and gets dropped (market_analysis_service.py line 453)."
  artifacts:
    - path: "src/intelligence/schemas.py"
      line: "149-240"
      issue: "I3Structure class needs 6 new field declarations for SwingMomentum plugin outputs"
  missing:
    - "Add to I3Structure class: swing_amplitude_ratio: float | None = None"
    - "Add to I3Structure class: swing_amplitude_expanding: int | None = None"
    - "Add to I3Structure class: swing_velocity_bars: float | None = None"
    - "Add to I3Structure class: swing_velocity_trend: Literal[\"accelerating\", \"decelerating\", \"stable\"] | None = None"
    - "Add to I3Structure class: struct_energy: float | None = None"
    - "Add to I3Structure class: struct_accel_bias: Literal[-1, 0, 1] | None = None"
    - "Update docstring on line 152 to reflect 8 I3 plugins (was 7) and 75 fields (was 69)"
  debug_session: ".planning/debug/resolved/market-analysis-not-consuming.md"
