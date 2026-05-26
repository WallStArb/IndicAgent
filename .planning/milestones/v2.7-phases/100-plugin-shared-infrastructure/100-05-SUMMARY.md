---
phase: 100-plugin-shared-infrastructure
plan: "05"
subsystem: intelligence-plugins
tags: [plugin-migration, get-main-df, ohlcv-extraction, incremental-plugins]
dependency_graph:
  requires: [100-01]
  provides: [PLUGIN-INFRA-04-adoption]
  affects: [i1-indicators, intelligence-pipeline]
tech_stack:
  added: []
  patterns: [get_main_df-guard-pattern, update_ema-shared-utility]
key_files:
  modified:
    - src/intelligence/features/i1_indicators/bollinger.py
    - src/intelligence/features/i1_indicators/moving_averages.py
    - src/intelligence/features/i1_indicators/macd.py
    - src/intelligence/features/i1_indicators/roc_ppo.py
    - src/intelligence/features/i1_indicators/ac_oscillator.py
    - src/intelligence/features/i1_indicators/cci.py
decisions:
  - "AccelerationRegime skipped: reads frames[features] not frames[main] - pure I2 feature aggregator with no OHLCV access"
  - "Multi-line if df is None guard used instead of single-line: ruff E701 rejects single-line if x: return {} style"
metrics:
  duration: ~15 minutes
  completed: "2026-05-21"
  tasks_completed: 2
  files_modified: 6
---

# Phase 100 Plan 05: I1/I2 Plugin get_main_df() Migration Summary

Migrated 6 I1 indicator plugins to use `get_main_df()` shared utility for OHLCV DataFrame extraction, eliminating duplicated `frames.get("main")` guard logic.

## What Was Built

All 6 targeted I1 indicator plugins now use `get_main_df(frames, self.min_lookback)` instead of inline `frames.get("main")` + manual length checks. MACD and ROC_PPO also use `update_ema()` for EMA update steps, replacing inline alpha-multiply patterns.

### Plugins Migrated

| Plugin | File | Changes |
|--------|------|---------|
| BollingerBands | bollinger.py | get_main_df in compute_full + compute_next; removed dead code after return |
| MovingAverages | moving_averages.py | get_main_df in compute_full, _seed_state, compute_next |
| MACD | macd.py | get_main_df in compute_full, _seed_state, compute_next; update_ema for 3 EMA updates |
| ROC_PPO | roc_ppo.py | get_main_df in compute_full, _seed_state, compute_next; update_ema for PPO EMAs |
| ACOscillator | ac_oscillator.py | get_main_df in compute_full and compute_next |
| CCI | cci.py | get_main_df in compute_full, _seed_state, compute_next |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed dead code in BollingerPlugin.compute_next**
- **Found during:** Task 1
- **Issue:** Lines 110-139 in original bollinger.py were unreachable (after `return out` on line 109). Dead code duplicated a different incremental update strategy.
- **Fix:** Removed unreachable block; kept the active implementation before the return.
- **Files modified:** bollinger.py
- **Commit:** 5623c2b0

### AccelerationRegime Skipped (Semantic Mismatch)

The plan specified migrating `AccelerationRegime` to `get_main_df()`. However, the actual plugin at `src/intelligence/composites/acceleration_regime.py` reads from `frames["features"]` (computed I1 features), not `frames["main"]` (raw OHLCV). It has `inputs: tuple = ()` and no OHLCV access. Applying `get_main_df()` would be semantically incorrect - the function guards the `"main"` key specifically.

**Decision:** Skip AccelerationRegime migration. It correctly has no `frames.get("main")` calls and needs no change.

**Note:** The plan also referenced path `src/intelligence/features/i2_composites/acceleration_regime.py` which does not exist. The actual file is `src/intelligence/composites/acceleration_regime.py`.

### Ruff E701 Prevents Single-Line Guard Format

The plan's verification greps expected `if df is None: return {}` on a single line. Ruff rule E701 (multiple statements on one line) blocks this style. Guards use the standard two-line format:
```python
if df is None:
    return {}
```
This is semantically equivalent and passes all lint/format checks.

## Verification Results

```
# 6 plugins have get_main_df import
grep -r "from src.intelligence.plugins.mixins import get_main_df" src/intelligence/features/i1_indicators/ | wc -l
→ 6

# 0 remaining frames.get("main") in all 6 migrated files
grep -r 'frames.get("main")' [all 6 files] | wc -l
→ 0

# None guards present in all files (2-3 per file)
→ bollinger: 2, moving_averages: 3, macd: 3, cci: 3, roc_ppo: 3, ac_oscillator: 2

# update_ema used in MACD and ROC_PPO
→ macd: 4 uses, roc_ppo: 4 uses
```

## Test Results

83 plugin-related unit tests pass including:
- `tests/unit/intelligence/test_ac_oscillator.py`
- `tests/unit/intelligence/test_plugin_mixins.py`
- `tests/unit/intelligence/test_plugin_incremental.py`
- `tests/unit/intelligence/correctness/test_bollinger_reference.py`
- `tests/unit/intelligence/correctness/test_macd_reference.py`
- `tests/unit/intelligence/correctness/test_cci_reference.py`

8 pre-existing unrelated failures unchanged (MACompositePlugin, output_queue, service_contract_resolution tests).

## Commits

| Hash | Description |
|------|-------------|
| 5623c2b0 | feat(100-05): migrate Bollinger, MovingAverages, MACD to get_main_df() |
| dcb1eaaf | feat(100-05): migrate ROC_PPO, AC Oscillator, CCI to get_main_df() |

## Self-Check: PASSED

All 6 source files found. Both task commits found (5623c2b0, dcb1eaaf).
