---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
plan: 01-GAPCLOSURE
subsystem: intelligence/confluence
tags: [i6, confluence, cross-timeframe, momentum, gradient, ml-features]
requires: [64-00]
provides: [ctf_momentum_divergence, ctf_momentum_regime]
affects: [intelligence_features, signal_ledger._shadow, I6Confluence schema]
tech-stack:
  added: [numpy.tanh gradient scoring]
  patterns: [CrossTimeframeConfluencePlugin dataclass pattern, module-level plugin instance]
key-files:
  created:
    - src/intelligence/confluence/cross_tf_momentum_divergence.py
    - tests/unit/intelligence/test_cross_tf_momentum_divergence.py
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/register_plugins.py
    - src/intelligence/trading/confidence_utils.py
decisions:
  - "capture_signal_features() reads from flat features dict (not frames['intel_i6']) — matches actual implementation, not plan interface spec"
  - "Plugin does not inherit from CrossTimeframeConfluencePlugin — uses same dataclass pattern but standalone class to avoid inheriting unused outputs/logic"
  - "TIER_I6 is a list[str] (plugin names), not list[type] — followed existing string-name pattern"
metrics:
  duration: 3m 52s
  completed: 2026-04-27
  tasks_completed: 4
  files_modified: 5
---

# Phase 64 Plan 01-GAPCLOSURE: CrossTFMomentumDivergence Plugin Summary

**One-liner:** CrossTFMomentumDivergencePlugin with np.tanh() gradient scoring from I2 events + I4 RSI/MACD, producing ctf_momentum_divergence [-1,+1] and 5-label regime for ML training.

## What Was Built

A new I6 confluence plugin that detects momentum bias divergence between higher timeframes (1h/4h) and lower timeframes (5m/15m). The plugin:

1. Reads I2 momentum event directions and I4 RSI/MACD values per TF from `frames`
2. Computes per-TF bias: `event_bias * 0.4 + rsi_alignment * 0.3 + macd_alignment * 0.3`
3. Averages HTF biases (1h, 4h) and LTF biases (5m, 15m) separately
4. Computes divergence = HTF_bias - LTF_bias, normalized via `np.tanh()` for soft saturation
5. Classifies regime into 5 categories per D-06: `aligned_htf_bull`, `aligned_htf_bear`, `pullback`, `bounce`, `mixed`

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 - Plugin | a5f31844 | feat(64-01): create CrossTFMomentumDivergencePlugin |
| 2 - Schema | 6c0670fd | feat(64-01): extend I6Confluence schema |
| 3 - Register | f085a758 | feat(64-01): register in TIER_I6 |
| 4 - Shadow | 9702c8fe | feat(64-01): extend capture_signal_features() |
| 5 - Tests | 807af0c9 | test(64-01): 15 unit tests |
| Lint | 144c08dc | style(64-01): fix ruff issues |

## Files Created / Modified

| File | Action | Description |
|------|--------|-------------|
| `src/intelligence/confluence/cross_tf_momentum_divergence.py` | Created | Plugin with full gradient implementation |
| `src/intelligence/schemas.py` | Modified | Added ctf_momentum_divergence + ctf_momentum_regime to I6Confluence |
| `src/intelligence/register_plugins.py` | Modified | Import, TIER_I6, validate_schema_coverage, register_all_plugins |
| `src/intelligence/trading/confidence_utils.py` | Modified | Extended shadow dict with 2 new momentum fields |
| `tests/unit/intelligence/test_cross_tf_momentum_divergence.py` | Created | 15 unit tests, all passing |

## Success Criteria Verification

| Criterion | Status |
|-----------|--------|
| Plugin with FULL np.tanh() gradient (not stub) | PASS |
| Follows CrossTimeframeConfluencePlugin pattern | PASS |
| ctf_momentum_divergence [-1,+1] | PASS |
| ctf_momentum_regime 5 categorical labels | PASS |
| I6Confluence schema extended | PASS |
| Plugin registered in TIER_I6 | PASS |
| validate_schema_coverage() passes | PASS |
| _shadow capture extended | PASS |
| 15 unit tests all pass | PASS |

## Deviations from Plan

### Auto-corrected Implementation Details

**1. [Rule 2 - Missing Critical Functionality] Plugin does not inherit CrossTimeframeConfluencePlugin**

- **Found during:** Task 1 — reading actual cross_timeframe.py
- **Issue:** Plan said "Extends CrossTimeframeConfluencePlugin" but that class has 12 outputs, weights, and scoring logic unrelated to momentum divergence. Inheriting it would import all those outputs and confuse the schema validator.
- **Fix:** Created standalone dataclass following the same pattern (dataclass fields: name, outputs, min_lookback, supports_incremental, capability_tags, inputs, _state; compute_full/compute_next methods; module-level plugin instance).
- **Files modified:** `cross_tf_momentum_divergence.py`
- **Note:** Plan interface spec still satisfied — same structural pattern, just not a subclass.

**2. [Rule 1 - Bug] capture_signal_features() signature mismatch in plan spec**

- **Found during:** Task 4 — reading actual confidence_utils.py
- **Issue:** Plan interface spec showed `capture_signal_features(signal, bar, frames)` reading from `frames["intel_i6"]`. Actual signature is `capture_signal_features(features, direction, profile_name, existing_confidence)` reading from a flat features dict.
- **Fix:** Extended actual function to read `ctf_momentum_divergence` and `ctf_momentum_regime` from the flat `features` dict, consistent with how all other ctf_* fields are captured.
- **Files modified:** `confidence_utils.py`

**3. [Rule 2 - Missing] TIER_I6 is list[str] not list[type]**

- **Found during:** Task 3 — reading actual register_plugins.py
- **Issue:** Plan said to add `CrossTFMomentumDivergencePlugin` class to TIER_I6. Actual TIER_I6 is a list of plugin name strings.
- **Fix:** Added `ctf_momentum_div_plugin.name` string to TIER_I6 list; also added plugin instance to validate_schema_coverage() and register_all_plugins() following ctf_plugin pattern.
- **Files modified:** `register_plugins.py`

## Known Stubs

None — full gradient implementation, no stubs.

## Threat Flags

None — no new network endpoints, auth paths, or trust boundary changes. Plugin is pure in-process compute, DB-ignorant.

## Self-Check: PASSED

All created files exist on disk. All task commits verified in git log. 15/15 unit tests pass.
