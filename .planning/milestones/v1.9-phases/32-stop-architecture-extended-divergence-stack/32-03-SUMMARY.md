---
phase: 32-stop-architecture-extended-divergence-stack
plan: "03"
subsystem: intelligence
tags: [divergence, macd, cmf, obv, i5-plugins, i7-plugins, weighted-score, feature-logging]

# Dependency graph
requires:
  - phase: 32-01
    provides: GARCH-adaptive stops, trade_framer.py centralized, signal_ledger 54 fields

provides:
  - MACDDivergencePlugin (patt_MACDDivergence) — MACD histogram peak/trough divergence I5 plugin
  - CMFDivergencePlugin (patt_CMFDivergence) — CMF linreg slope divergence I5 plugin
  - VolumeDivergencePlugin extended with obv_div_bullish/bearish/strength from internal OBV series
  - I5Patterns schema +9 fields (macd_div_*, obv_div_*, cmf_div_*)
  - DivergenceStackPlugin rewritten: 5-input weighted score replacing 2-input AND-gate
  - Always-log: div_weighted_score, div_n_agreeing, per-input scores/age_bars/magnitudes on every bar
  - intelligence_features.i7 JSONB enriched with divergence_scoring block on every bar

affects: [signal_generator_service, feature_writer_service, intelligence_features, ML training data]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DIVERGENCE_WEIGHTS module-level dict for hot-tunable input weights without redeploy"
    - "Always-log base_output pattern: return scoring fields on EVERY compute_full call regardless of signal fire"
    - "divergence_scoring metadata block in _build_i7_payload() for always-log I7 fields to intelligence_features"

key-files:
  created:
    - src/intelligence/patterns/macd_divergence.py
    - src/intelligence/patterns/cmf_divergence.py
    - tests/unit/test_macd_divergence.py
    - tests/unit/test_cmf_divergence.py
    - tests/unit/test_divergence_stack.py
  modified:
    - src/intelligence/patterns/volume_divergence.py
    - src/intelligence/trading/divergence_stack.py
    - src/intelligence/schemas.py
    - src/intelligence/register_plugins.py
    - services/signal_generator_service.py
    - tests/unit/intelligence/test_cis_plugins.py
    - tests/unit/intelligence/test_i5_new_plugins.py
    - tests/unit/intelligence/test_i7_registration.py

key-decisions:
  - "5-input weighted gate (RSI 0.30, MACD 0.25, vol 0.20, OBV 0.15, CMF 0.10) replaces 2-input AND-gate — ~40% recall expansion with quality gate (n_agreeing >= 3 + score > 0.40)"
  - "DivergenceStack always-log fields (div_weighted_score, per-input scores, age_bars, magnitudes) returned on EVERY compute_full call for ML threshold optimization"
  - "divergence_scoring metadata block added to _build_i7_payload() so always-log fields reach intelligence_features.i7 JSONB even on no-signal bars"
  - "obv_div_* computed independently from OBV cumulative series via linreg, NOT aliased from vol_div_* (same values, different derivation paths for code clarity)"
  - "DIVERGENCE_WEIGHTS as module-level dict — tunable without code deploy"
  - "TIER_I5 grows from 14 to 16; total plugin count grows from 104 to 106"

patterns-established:
  - "Always-log pattern: base_output dict built unconditionally; signal fields merged in on gate pass; empty signal fields on gate miss"
  - "Metadata block pattern in _build_i7_payload(): divergence_scoring JSON alongside signals_out list"

requirements-completed: [DIV-01, DIV-02, DIV-03, DIV-04]

# Metrics
duration: 14min
completed: 2026-03-17
---

# Phase 32 Plan 03: Extended Divergence Stack Summary

**5-input weighted divergence convergence (MACD + CMF + OBV new I5 plugins + DivergenceStack rewrite) with always-log scoring routed to intelligence_features.i7 JSONB on every bar**

## Performance

- **Duration:** 14 min
- **Started:** 2026-03-17T~11:00:00Z
- **Completed:** 2026-03-17T11:14:00Z
- **Tasks:** 2 (TDD)
- **Files modified:** 13

## Accomplishments

- Created MACDDivergencePlugin and CMFDivergencePlugin as new I5 pattern plugins; both use linreg/peak-trough approaches consistent with existing divergence plugins
- Extended VolumeDivergencePlugin with obv_div_bullish/bearish/strength from the internal OBV cumulative series via independent linreg slope computation
- Added 9 new fields to I5Patterns (macd_div_*, obv_div_*, cmf_div_*) with extra=forbid still enforced; validate_schema_coverage() passes
- Rewrote DivergenceStackPlugin from 2-input AND-gate to 5-input weighted convergence score (DIVERGENCE_WEIGHTS dict); gate: score > 0.40 AND n_agreeing >= 3
- All scoring + age_bars + magnitude fields logged on EVERY bar — Renaissance "instrument everything" principle
- div_weighted_score and div_n_agreeing flow to intelligence_features.i7 JSONB via _build_i7_payload() divergence_scoring block

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: failing tests for MACD/CMF plugins** - `61719b8` (test)
2. **Task 1 GREEN: MACD/CMF plugins + OBV extension + schema + registration** - `7369a63` (feat)
3. **Task 2 RED: failing tests for DivergenceStack 5-input weighted rewrite** - `e23884c` (test)
4. **Task 2 GREEN: DivergenceStack rewrite + i7 always-log routing + test fixes** - `c2b9cc6` (feat)

## Files Created/Modified

- `src/intelligence/patterns/macd_divergence.py` — MACDDivergencePlugin: MACD histogram peak/trough divergence detection
- `src/intelligence/patterns/cmf_divergence.py` — CMFDivergencePlugin: CMF linreg slope divergence detection
- `src/intelligence/patterns/volume_divergence.py` — +obv_div_* outputs from internal OBV cumulative series
- `src/intelligence/trading/divergence_stack.py` — Full rewrite: 5-input weighted score, LOCKED DESIGN removed
- `src/intelligence/schemas.py` — I5Patterns +9 fields (3 per new plugin); docstring count updated to 79
- `src/intelligence/register_plugins.py` — macd_div_plugin + cmf_div_plugin instantiated and added to TIER_I5
- `services/signal_generator_service.py` — _build_i7_payload() enriched with divergence_scoring metadata block
- `tests/unit/test_macd_divergence.py` — MACD plugin attribute/behavior/edge-case tests
- `tests/unit/test_cmf_divergence.py` — CMF plugin attribute/behavior/edge-case tests
- `tests/unit/test_divergence_stack.py` — 21 tests covering 5-input gate, always-log, age tracking, direction
- `tests/unit/intelligence/test_cis_plugins.py` — TestDivergenceStack updated for 5-input formula (dual-gate tests replaced)
- `tests/unit/intelligence/test_i5_new_plugins.py` — TIER_I5 count updated 14 → 16
- `tests/unit/intelligence/test_i7_registration.py` — total plugin count updated 104 → 106

## Decisions Made

- Chose `_build_i7_payload()` divergence_scoring block approach for always-log fields to intelligence_features (cleanest path — no AggregatedResult schema change needed since DivergenceStack always returns base_output even on no-signal bars and this propagates via all_plugin_outputs)
- obv_div_* computed independently from OBV series even though values match vol_div_* — self-documenting, future-proof if vol computation changes
- DIVERGENCE_WEIGHTS as module-level constants (not dataclass fields) for hot-reload capability per CONTEXT.md

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated stale count tests for 2 new I5 plugins**
- **Found during:** Task 2 (final test suite run)
- **Issue:** test_tier_i5_has_14_plugins and test_total_plugin_count had hardcoded counts from before Task 1 added 2 plugins. Tests failing with 16 != 14 and 106 != 104.
- **Fix:** Updated counts to 16 and 106 respectively with updated docstrings
- **Files modified:** tests/unit/intelligence/test_i5_new_plugins.py, tests/unit/intelligence/test_i7_registration.py
- **Verification:** Both tests pass after update
- **Committed in:** c2b9cc6

**2. [Rule 1 - Bug] Updated TestDivergenceStack tests for 5-input gate in test_cis_plugins.py**
- **Found during:** Task 2 (final test suite run)
- **Issue:** test_dual_bullish_fires_long and test_dual_bearish_fires_short tested the old 2-input AND-gate behavior (direction=1 with only RSI+vol). New 5-input gate requires n_agreeing >= 3, so 2-input tests expected confidence > 0.0 but got 0.0.
- **Fix:** Updated tests to use 3 agreeing inputs (RSI+MACD+vol) matching the new gate. test_confidence_formula updated from old `0.4*rsi + 0.4*vol + 0.2` formula to new `min(1.0, weighted_score / 0.60)` formula.
- **Files modified:** tests/unit/intelligence/test_cis_plugins.py
- **Verification:** All 7 TestDivergenceStack tests pass
- **Committed in:** c2b9cc6

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bug fixes — stale tests from old 2-input design)
**Impact on plan:** Both fixes essential for test suite correctness after planned architectural change. No scope creep.

## Issues Encountered

- Pre-existing failures in test_signals_route.py, test_lifecycle_freshness.py, test_signal_lifecycle_service.py, test_historical_backfill.py, test_feature_writer_config.py were confirmed as pre-existing (failed identically before any 32-03 changes). Out of scope per deviation rules.

## Next Phase Readiness

- TIER_I5 = 16, TIER_I7 = 23, total plugins = 106
- validate_schema_coverage() passes with I5Patterns at 79 fields
- DivergenceStack always-log fields flowing to intelligence_features.i7 JSONB on every bar — ML threshold optimization data accumulating immediately
- Phase 34 (AVWAP + Volume Profile) and Phase 35 (Calibration + Kalman) can proceed

---
*Phase: 32-stop-architecture-extended-divergence-stack*
*Completed: 2026-03-17*
