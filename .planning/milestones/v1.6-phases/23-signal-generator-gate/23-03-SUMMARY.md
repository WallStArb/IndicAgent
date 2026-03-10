---
phase: 23-signal-generator-gate
plan: "03"
subsystem: signal-generator
tags: [cleanup, dead-code, inputspec, documentation]
dependency_graph:
  requires: [23-01, 23-02]
  provides: [inputspec-cleanup, 4h-1d-exclusion]
  affects: [src/intelligence/trading, services/market_analysis_service, services/signal_generator_service]
tech_stack:
  added: []
  patterns: ["mechanical sed batch edit for multi-file one-liner cleanup"]
key_files:
  created: []
  modified:
    - src/intelligence/trading/candlestick_pattern_setup.py
    - src/intelligence/trading/choch_reversal.py
    - src/intelligence/trading/divergence_stack.py
    - src/intelligence/trading/fvg_fill.py
    - src/intelligence/trading/gap_analysis_setup.py
    - src/intelligence/trading/liquidity_hunt.py
    - src/intelligence/trading/liquidity_sweep_reclaim.py
    - src/intelligence/trading/mean_reversion.py
    - src/intelligence/trading/momentum_breakout.py
    - src/intelligence/trading/mtf_alignment.py
    - src/intelligence/trading/pattern_completion.py
    - src/intelligence/trading/regime_transition.py
    - src/intelligence/trading/session_extremes_setup.py
    - src/intelligence/trading/squeeze_expansion.py
    - src/intelligence/trading/supply_demand_setup.py
    - src/intelligence/trading/trend_following.py
    - src/intelligence/trading/vwap_deviation.py
    - services/market_analysis_service.py
    - services/signal_generator_service.py
decisions:
  - "InputSpec.timeframe='.*' confirms dead-code nature: field defined but never enforced; '.*' makes intent explicit"
  - "fvg_fill.py carries the canonical explanation comment for timeframe='.*' — one file as reference, not all 17"
  - "4h/1d exclusion documented in both service configs as day-trading scope boundary"
metrics:
  duration: 157
  completed_date: "2026-03-10"
  tasks_completed: 2
  files_modified: 19
---

# Phase 23 Plan 03: InputSpec Cleanup and 4h/1d Exclusion Documentation Summary

Dead-code cleanup removing misleading `InputSpec(timeframe="1m")` from all 17 I7 plugins, replaced with `".*"` to reflect that the field is never enforced by the registry or service, plus explicit 4h/1d scope documentation in both service configs.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Update InputSpec timeframe to ".*" on all 17 I7 plugins | cd7d105 | 17 trading plugin files |
| 2 | Add 4h/1d exclusion comments to service config sections | 86d671c | market_analysis_service.py, signal_generator_service.py |

## What Was Built

**Task 1 — InputSpec dead-code cleanup:**
Used a single `sed -i` batch command to replace `timeframe="1m"` with `timeframe=".*"` across all 17 I7 plugin files simultaneously. Confirmed with grep post-edit: zero matches for `timeframe="1m"` in `src/intelligence/trading/`. Added a two-line explanatory comment above the `inputs` declaration in `fvg_fill.py` as the canonical reference explaining why `".*"` is correct.

**Task 2 — 4h/1d exclusion documentation:**
Added identical three-line comment blocks directly above the `"timeframes": ["1m", "5m", "15m", "1h"]` line in `_load_config()` of both `market_analysis_service.py` (line 153) and `signal_generator_service.py` (line 437). Comment clearly states day-trading focus, explains why 4h/1d are too slow for intraday entries, and calls out the extension path for swing-trading scope.

## Verification

- `grep -r 'timeframe="1m"' src/intelligence/trading/` returns zero matches
- `grep -c "4h and 1d intentionally excluded" services/market_analysis_service.py` returns 1
- `grep -c "4h and 1d intentionally excluded" services/signal_generator_service.py` returns 1
- `fvg_fill.py` contains two-line comment explaining `timeframe=".*"` is correct
- Full unit suite: 1430 tests passed, no regressions
- Ruff: no new errors introduced (pre-existing E501 on `_update_gate` signature in signal_generator_service.py is baseline, documented in Phase 23-02 decisions)

## Deviations from Plan

None — plan executed exactly as written. Batch sed approach confirmed effective for all 17 files in a single command.

## Self-Check: PASSED

- FOUND: src/intelligence/trading/fvg_fill.py
- FOUND: services/market_analysis_service.py
- FOUND: services/signal_generator_service.py
- FOUND: commit cd7d105
- FOUND: commit 86d671c
