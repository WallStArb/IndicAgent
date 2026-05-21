---
phase: 093-mathematical-correctness-audit
plan: "02"
subsystem: correctness-tests
tags:
  - testing
  - correctness
  - pandas-ta
  - indicators
  - reference-validation
dependency_graph:
  requires:
    - 093-01 (conftest fixtures and assert_close_to_reference helper)
  provides:
    - tests/unit/intelligence/correctness/test_atr_reference.py
    - tests/unit/intelligence/correctness/test_bollinger_reference.py
    - tests/unit/intelligence/correctness/test_macd_reference.py
    - tests/unit/intelligence/correctness/test_rsi_reference.py
    - tests/unit/intelligence/correctness/test_stochastic_reference.py
    - tests/unit/intelligence/correctness/test_mfi_reference.py
    - tests/unit/intelligence/correctness/test_cci_reference.py
    - tests/unit/intelligence/correctness/test_williams_r_reference.py
    - tests/unit/intelligence/correctness/test_adx_reference.py
    - tests/unit/intelligence/correctness/test_vwap_reference.py
    - .planning/phases/093-mathematical-correctness-audit/093-ATR-WILDER-INVESTIGATION.md
  affects:
    - 093-03-PLAN.md (uses same correctness/ infrastructure)
tech_stack:
  added: []
  patterns:
    - per-indicator warmup_bars empirically determined (not theoretical)
    - direct formula reference for indicators with pandas-ta bugs (CCI)
    - single-session fixture for session-anchored indicators (VWAP)
key_files:
  created:
    - tests/unit/intelligence/correctness/test_atr_reference.py
    - tests/unit/intelligence/correctness/test_bollinger_reference.py
    - tests/unit/intelligence/correctness/test_macd_reference.py
    - tests/unit/intelligence/correctness/test_rsi_reference.py
    - tests/unit/intelligence/correctness/test_stochastic_reference.py
    - tests/unit/intelligence/correctness/test_mfi_reference.py
    - tests/unit/intelligence/correctness/test_cci_reference.py
    - tests/unit/intelligence/correctness/test_williams_r_reference.py
    - tests/unit/intelligence/correctness/test_adx_reference.py
    - tests/unit/intelligence/correctness/test_vwap_reference.py
    - .planning/phases/093-mathematical-correctness-audit/093-ATR-WILDER-INVESTIGATION.md
  modified: []
decisions:
  - "ATR warmup_bars=150 (not 28): presma vs min_periods seeding difference requires 130+ bars to decay below 1e-6"
  - "RSI warmup_bars=250 (not 14): SMA-seed vs pure-ewm seeding takes 237 bars to converge on trending data"
  - "MACD warmup_bars=200 (not 35): EMA seeding takes 124 bars for signal line to reach atol=1e-4"
  - "ADX warmup_bars=250 (not 28): double-Wilder seeding takes 224 bars to converge to atol=1e-4"
  - "CCI uses direct formula reference (not pandas-ta): pandas-ta cci() has operator precedence bug computing tp - mean_tp/(c*mad) instead of (tp-mean_tp)/(c*mad)"
  - "Stochastic uses smooth_k=1 in pandas-ta call: our plugin computes fast %K; smooth_k=3 would add extra %K smoothing step we don't implement"
  - "Bollinger uses ddof=0 and talib=False in pandas-ta call: our plugin uses population std (ddof=0); pandas-ta defaults to ddof=1"
  - "VWAP tested with single 390-bar session fixture: avoids session boundary ambiguity between implementations"
metrics:
  duration: "~13 minutes"
  completed: "2026-05-21"
  tasks_completed: 3
  files_created: 11
  files_modified: 0
---

# Phase 093 Plan 02: Indicator Reference-Validation Tests Summary

**One-liner:** Ten Tier-1 indicator reference tests against pandas-ta prove mathematical correctness via empirically-determined warmup windows; discovered and documented pandas-ta CCI formula bug requiring direct-formula reference substitution.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | ATR reference test + Wilder convention investigation | f796968c | test_atr_reference.py, 093-ATR-WILDER-INVESTIGATION.md |
| 2 | Reference tests for Bollinger, MACD, RSI, Stochastic, MFI | 91f58763 | 5 test files |
| 3 | Reference tests for CCI, Williams %R, ADX, VWAP | 69fe3520 | 4 test files |

## What Was Built

### Ten Reference-Validation Test Files

Each test file contains a `Test<Indicator>Reference` class with at least 2 test methods (trending + ranging fixtures). All 28 tests pass.

| Indicator | File | atol | warmup_bars | Reference |
|-----------|------|------|-------------|-----------|
| ATR | test_atr_reference.py | 1e-6 | 150 | pandas_ta.atr(length=14) |
| Bollinger | test_bollinger_reference.py | 1e-6 | 20 | pandas_ta.bbands(ddof=0, talib=False) |
| MACD | test_macd_reference.py | 1e-4 | 200 | pandas_ta.macd(talib=False) |
| RSI | test_rsi_reference.py | 1e-6 | 250 | pandas_ta.rsi(talib=False) |
| Stochastic | test_stochastic_reference.py | 1e-6 | 14 | pandas_ta.stoch(smooth_k=1) |
| MFI | test_mfi_reference.py | 1e-6 | 14 | pandas_ta.mfi(length=14) |
| CCI | test_cci_reference.py | 1e-6 | 20 | Direct Lambert formula (see below) |
| Williams %R | test_williams_r_reference.py | 1e-6 | 14 | pandas_ta.willr(length=14) |
| ADX | test_adx_reference.py | 1e-4 | 250 | pandas_ta.adx(talib=False) |
| VWAP | test_vwap_reference.py | 1e-4 | 0 | pandas_ta.vwap() (single session) |

### ATR Wilder Convention Investigation

`093-ATR-WILDER-INVESTIGATION.md` documents:
- Both implementations use alpha=1/N (Wilder's convention), NOT span=N (standard EMA)
- seeding differs: pandas-ta uses `presma=True` (SMA seed at bar N-1); our code uses pandas ewm `min_periods=N` initialization
- Empirical decay analysis: seeding error drops below 1e-6 after ~130 bars trending, ~150 bars ranging
- Industry verification: TradingView, TA-Lib, MT4/5, Welles Wilder 1978 all use alpha=1/N

### Bounded Oscillator Range Tests

RSI, Stochastic (%K and %D), and MFI include output-range assertions:
- RSI: [0, 100] with 1e-9 floating-point tolerance
- Stochastic %K and %D: [0, 100]
- MFI: [0, 100]
- Williams %R: [-100, 0] (documents sign convention)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug Discovery] Warmup bars empirically determined to be larger than plan specified**
- **Found during:** Tasks 1-3 (ATR, RSI, MACD, ADX)
- **Issue:** Plan specified warmup_bars=28 for ATR, 14 for RSI, 35 for MACD, 28 for ADX — all insufficient for 1e-6 or 1e-4 tolerance due to EWM seeding differences between implementations
- **Fix:** Used empirically correct warmup values: ATR=150, RSI=250, MACD=200, ADX=250. Documented seeding difference analysis in ATR investigation doc and test docstrings.
- **Files modified:** All 4 affected test files

**2. [Rule 1 - Bug Discovery] pandas-ta CCI formula bug**
- **Found during:** Task 3 (CCI investigation)
- **Issue:** `pandas_ta.cci()` computes `tp - mean_tp / (c * mad)` (wrong precedence) instead of `(tp - mean_tp) / (c * mad)`. The bug causes values 10,000x larger than correct CCI.
- **Fix:** Substituted pandas-ta reference with a direct Python implementation of the Lambert (1980) CCI formula. Test docstring documents the bug and explains the substitution.
- **Files modified:** test_cci_reference.py

**3. [Rule 1 - Convention Mismatch] Stochastic smooth_k parameter**
- **Found during:** Task 2 (Stochastic investigation)
- **Issue:** pandas-ta stoch() defaults to smooth_k=3 (slow stochastic: smooths %K before computing %D). Our plugin computes fast stochastic (raw %K, SMA3 for %D).
- **Fix:** Call pandas-ta with smooth_k=1 to disable %K pre-smoothing. Documents the convention in test docstring.
- **Files modified:** test_stochastic_reference.py

**4. [Rule 1 - Convention Mismatch] Bollinger ddof convention**
- **Found during:** Task 2 (Bollinger investigation)
- **Issue:** pandas-ta bbands() defaults to ddof=1 (sample std with Bessel's correction). Our plugin uses ddof=0 (population std).
- **Fix:** Call pandas-ta with ddof=0 and talib=False. Documents the convention in test docstring.
- **Files modified:** test_bollinger_reference.py

## Self-Check

### Checking created files exist
- tests/unit/intelligence/correctness/test_atr_reference.py: FOUND
- tests/unit/intelligence/correctness/test_bollinger_reference.py: FOUND
- tests/unit/intelligence/correctness/test_macd_reference.py: FOUND
- tests/unit/intelligence/correctness/test_rsi_reference.py: FOUND
- tests/unit/intelligence/correctness/test_stochastic_reference.py: FOUND
- tests/unit/intelligence/correctness/test_mfi_reference.py: FOUND
- tests/unit/intelligence/correctness/test_cci_reference.py: FOUND
- tests/unit/intelligence/correctness/test_williams_r_reference.py: FOUND
- tests/unit/intelligence/correctness/test_adx_reference.py: FOUND
- tests/unit/intelligence/correctness/test_vwap_reference.py: FOUND
- .planning/phases/093-mathematical-correctness-audit/093-ATR-WILDER-INVESTIGATION.md: FOUND

### Checking commits exist
- f796968c (Task 1 — ATR + investigation): FOUND
- 91f58763 (Task 2 — Bollinger/MACD/RSI/Stoch/MFI): FOUND
- 69fe3520 (Task 3 — CCI/WilliamsR/ADX/VWAP): FOUND

### Checking verification criteria
- pytest tests/unit/intelligence/correctness/: 28 tests collected, 28 passed
- ls test_*_reference.py | wc -l: 10
- 093-ATR-WILDER-INVESTIGATION.md exists: YES
- all reference test files contain warmup_bars: YES (all show non-zero count)

## Self-Check: PASSED
