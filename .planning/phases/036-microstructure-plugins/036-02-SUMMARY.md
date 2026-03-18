---
phase: 036-microstructure-plugins
plan: "02"
subsystem: intelligence/trading
tags: [i7-plugins, ofi, cvd, microstructure, shadow-mode, tdd]
dependency_graph:
  requires: ["036-01"]
  provides: ["trad_OFIContinuation", "trad_OFIDivergence", "trad_OFISpike", "trad_CVDDivergence", "trad_CVDSpike", "trad_DeltaExhaustion", "trad_DualDivergence"]
  affects: ["register_plugins.py", "aggregator.py", "signal_generator_service.py"]
tech_stack:
  added: []
  patterns: ["IS_SHADOW plugin-level shadow flag", "N-bar confirmation state tracking", "dual-gate divergence (both OFI AND CVD)"]
key_files:
  created:
    - src/intelligence/trading/ofi_continuation.py
    - src/intelligence/trading/ofi_divergence.py
    - src/intelligence/trading/ofi_spike.py
    - src/intelligence/trading/cvd_divergence.py
    - src/intelligence/trading/cvd_spike.py
    - src/intelligence/trading/delta_exhaustion.py
    - src/intelligence/trading/dual_divergence.py
    - tests/unit/intelligence/trading/test_ofi_plugins.py
    - tests/unit/intelligence/trading/test_cvd_plugins.py
    - tests/unit/intelligence/trading/test_dual_divergence.py
  modified:
    - src/intelligence/register_plugins.py
    - src/intelligence/trading/aggregator.py
    - services/signal_generator_service.py
    - tests/unit/intelligence/test_i7_registration.py
    - tests/unit/intelligence/test_plugin_registry.py
decisions:
  - "IS_SHADOW class attribute on DualDivergencePlugin checked by service via getattr() — all entries from shadow plugins written as is_shadow=True"
  - "OFIContinuation uses _state for N=5 consecutive bar tracking; CVDDivergence uses _state for N=3 confirmation"
  - "OFISpike and CVDSpike are stateless (read pre-computed z-score from I1)"
  - "DeltaExhaustion gate: abs(cvd_spike_z) > 1.5 AND price_change < 0.3*ATR (lower z-score threshold than spike plugins to catch more exhaustion events)"
  - "TREND_SETUPS updated with trad_OFIContinuation only (other 6 are mean_reversion or any)"
metrics:
  duration_minutes: 10
  completed_date: "2026-03-18"
  tasks_completed: 2
  tasks_total: 2
  files_created: 10
  files_modified: 5
---

# Phase 36 Plan 02: OFI+CVD I7 Plugins Summary

7 new I7 trading plugins consuming OFI and CVD microstructure I1 features, all registered in TIER_I7 with TDD coverage; DualDivergence starts in shadow mode.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create 3 OFI + 3 CVD I7 plugins with tests | 347dddc | 6 plugin files + 2 test files |
| 2 | DualDivergence shadow plugin + register all 7 + update counts | 141d263 | dual_divergence.py + register_plugins.py + aggregator.py + signal_generator_service.py + 3 test file updates |

## What Was Built

### 7 New I7 Plugins

| Plugin | File | regime_type | Gate | Direction |
|--------|------|-------------|------|-----------|
| trad_OFIContinuation | ofi_continuation.py | trend | ofi_ewma_20 same sign for 5 consecutive bars | sign(ofi_ewma_20) |
| trad_OFIDivergence | ofi_divergence.py | mean_reversion | abs(ofi_divergence) >= 1.5 | sign(ofi_divergence) |
| trad_OFISpike | ofi_spike.py | any | abs(ofi_spike_z) > 2.0 | sign(ofi_spike_z) |
| trad_CVDDivergence | cvd_divergence.py | mean_reversion | cvd_divergence != 0, N=3 bar confirm | -sign(price_dir), dual_divergence flag |
| trad_CVDSpike | cvd_spike.py | any | abs(cvd_spike_z) > 2.0 | sign(cvd_spike_z) |
| trad_DeltaExhaustion | delta_exhaustion.py | mean_reversion | abs(cvd_spike_z)>1.5 AND price_change<0.3*ATR | opposite of CVD direction |
| trad_DualDivergence | dual_divergence.py | mean_reversion | abs(ofi_div)>=1.0 AND abs(cvd_div)>=1.0, N=3 confirm, IS_SHADOW=True | sign(ofi_divergence) |

### Registration Updates

- `TIER_I7` extended from 28 to 35 plugins
- Total registered plugins: 113 → 120 (27 indicators + 93 patterns)
- `TREND_SETUPS` updated: added `trad_OFIContinuation`
- `signal_generator_service.py`: IS_SHADOW class attribute check for plugin-level shadow mode

### Shadow Mechanism

`DualDivergencePlugin.IS_SHADOW = True` — checked by signal_generator_service after entry building:
```python
for entry in entries:
    plugin_instance = registry.patterns.get(entry.setup_plugin)
    if plugin_instance is not None and getattr(plugin_instance, "IS_SHADOW", False):
        entry.is_shadow = True
```
This extends the Phase 35 Kalman shadow mechanism to support plugin-level shadow declarations.

## Test Coverage

- `test_ofi_plugins.py`: 27 tests (OFIContinuation, OFIDivergence, OFISpike)
- `test_cvd_plugins.py`: 27 tests (CVDDivergence, CVDSpike, DeltaExhaustion)
- `test_dual_divergence.py`: 10 tests (DualDivergence shadow plugin)
- `test_i7_registration.py`: updated counts (35 I7 plugins, 120 total)
- `test_plugin_registry.py`: updated TIER_I7 assertion (28→35)
- All 70 new/updated tests pass

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

Files verified:
- FOUND: src/intelligence/trading/ofi_continuation.py
- FOUND: src/intelligence/trading/ofi_divergence.py
- FOUND: src/intelligence/trading/ofi_spike.py
- FOUND: src/intelligence/trading/cvd_divergence.py
- FOUND: src/intelligence/trading/cvd_spike.py
- FOUND: src/intelligence/trading/delta_exhaustion.py
- FOUND: src/intelligence/trading/dual_divergence.py

Commits verified:
- FOUND: 347dddc (Task 1: 6 OFI+CVD plugins)
- FOUND: 141d263 (Task 2: DualDivergence + registration)
