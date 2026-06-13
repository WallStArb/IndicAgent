---
phase: 121-lifecycle-replay-validation
plan: "03"
subsystem: intelligence-pipeline
tags: [atr-hardening, macro-context, i4-tier, i6-confluence, data-integrity]
dependency_graph:
  requires: [121-01]
  provides: [atr-early-return-guards, get_atr_valid, MacroContextPlugin, I4Context-macro-fields]
  affects: [i6-confluence-scores, i4-context-output, intelligence_features.i4]
tech_stack:
  added: [MacroContextPlugin]
  patterns: [early-return-guard, strict-accessor, dataclass-plugin]
key_files:
  created:
    - src/intelligence/context/macro_context.py
  modified:
    - src/intelligence/trading/atr_utils.py
    - src/intelligence/confluence/confluence_smc.py
    - src/intelligence/confluence/cross_tf_sr_confluence.py
    - src/intelligence/trading/zone_engine.py
    - src/intelligence/confluence/cross_timeframe.py
    - src/intelligence/schemas.py
    - src/intelligence/register_plugins.py
    - tests/unit/intelligence/test_i7_registration.py
decisions:
  - "D-07: I6 confluence uses early-return (not raise) on missing ATR — graceful degradation over loud failure"
  - "D-08: get_atr_valid raises ValueError — I7 strict accessor only, not for I6"
  - "D-09: zone_engine.py guard already correct — comment only added"
  - "D-10: One MacroContextPlugin reads all 5 macro fields from frames['cross_asset'] — one source, one node"
  - "D-11: yield_curve_slope/regime added to I4Context (were orphaned in ShadowTransitionEvent); ftq_score/regime activated; corr_z added"
  - "D-12: Macro fields flow through I4Context JSONB to intelligence_features.i4 — no DB migration"
metrics:
  duration_minutes: 10
  completed: "2026-06-13"
  tasks_completed: 3
  files_changed: 8
  files_created: 1
---

# Phase 121 Plan 03: ATR Hardening + MacroContextPlugin Summary

ATR silent-corruption eliminated from I6 confluence via early-return guards; five macro cross-asset fields wired into I4Context via new MacroContextPlugin.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | ATR hardening — early-return guards + get_atr_valid | 590f7691 | atr_utils.py, confluence_smc.py, cross_tf_sr_confluence.py, zone_engine.py |
| 2 | MacroContextPlugin — create, activate I4Context fields, register TIER_I4 | 14bc58ab | macro_context.py (new), schemas.py, register_plugins.py |
| 3 | Registration completions, cross_timeframe fix, test update | 919733b7 | cross_timeframe.py, register_plugins.py, schemas.py, test_i7_registration.py |

## Exact Edits Made

### Task 1: ATR Hardening

**atr_utils.py — `get_atr_valid` added after `get_atr_with_floor_from_frames`:**
```python
def get_atr_valid(features: dict[str, Any]) -> float:
    """Strict ATR accessor for I7 plugin use. Raises ValueError when ATR is None/zero."""
    atr = get_atr(features)
    if not atr:
        raise ValueError(f"ATR unavailable or non-positive: {features.get('atr_14')!r}")
    return atr
```

**confluence_smc.py — `score_fvg_alignment` and `score_ob_alignment` (same pattern):**

Before: `atr = get_atr(features) or 0.0` / `if cur_trend == 0 or atr <= 0: return 0.0, {}`

After:
```python
atr = get_atr(features)
if not atr:
    return {}, {}
if cur_trend == 0:
    return 0.0, {}
```

**cross_tf_sr_confluence.py — `compute_full` inner loop:**

Before: `atr = get_atr(intel) or 1.0`

After:
```python
atr = get_atr(intel)
if not atr:
    continue
```

**zone_engine.py — clarifying comment (no code change):**

```python
atr = get_atr_with_floor(features, symbol)  # symbol-variant API: frames not in scope here; symbol read from features dict
```

### Task 2: MacroContextPlugin

**macro_context.py created** — `MacroContextPlugin` dataclass reads all 5 fields from `frames["cross_asset"]` when `xa.get("ready")` is truthy. Returns `{}` when not ready. No EQ_INDEX guard (macro context is instrument-agnostic).

**schemas.py — I4Context additions:**
- Added `yield_curve_slope: float | None = None`
- Added `yield_curve_regime: str | None = None`
- Added `ftq_score: float | None = None` (was commented out)
- Added `ftq_regime: str | None = None` (was commented out)
- Added `corr_z: float | None = None` (new)
- Docstring updated: added `MacroContext (5 fields)` entry, Total 93 → 98

**register_plugins.py:**
- Import added: `from .context.macro_context import plugin as macro_ctx_plugin`
- Added to `TIER_I4` list
- Added to I4 wave plugin list in `register_all_plugins()`
- Added `registry.register_pattern(macro_ctx_plugin)`
- Added to `I4_WAVE_A`

### Task 3: Bug Fix During Testing

**cross_timeframe.py — normalise ATR early-return from score_fvg/ob_alignment:**

`score_fvg_alignment` now returns `({}, {})` when ATR is missing. The caller unpacks this as `fvg_score = {}`, `fvg_tf_contribs = {}`. Added normalisation:
```python
if not isinstance(fvg_score, float):
    fvg_score = 0.0
```
Same for `ob_score`. Ensures `i6_fvg_tf_alignment` and `i6_ob_tf_alignment` remain float in the output dict.

**test_i7_registration.py — total plugin count 133 → 134** (MacroContextPlugin added to registry).

## Final pytest Result

- 4623 passed, 36 skipped, 42 failed
- 42 failures are all pre-existing (test_signal_ledger insert params, test_trade_framer zone naming, test_vwap_deviation, test_pipeline_reset module not found, test_run_historical_pipeline psycopg2 mock, test_signal_replay_auditor lifecycle outcomes)
- Baseline before this plan: 53 failures (4612 passed). Net improvement: -11 failures, +11 passed.
- No regressions introduced.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] score_fvg_alignment/score_ob_alignment return type mismatch in cross_timeframe.py**
- **Found during:** Task 3 (unit test run)
- **Issue:** `score_fvg_alignment` returns `({}, {})` tuple when ATR is missing; unpacking assigns `fvg_score = {}` (dict not float); `i6_fvg_tf_alignment` stored as `{}` instead of `0.0`
- **Fix:** Added `if not isinstance(fvg_score, float): fvg_score = 0.0` normalisation in cross_timeframe.py
- **Files modified:** `src/intelligence/confluence/cross_timeframe.py`
- **Commit:** 919733b7

**2. [Rule 2 - Missing registration] MacroContextPlugin not added to registry.register_pattern() or I4_WAVE_A**
- **Found during:** Task 3 (plugin_validator and wave_invariants tests)
- **Issue:** TIER_I4 list had macro_ctx_plugin but the plugin was not registered in the pattern registry or the execution wave list
- **Fix:** Added `registry.register_pattern(macro_ctx_plugin)`, added to `I4_WAVE_A`, added to I4 wave in `register_all_plugins()`
- **Files modified:** `src/intelligence/register_plugins.py`
- **Commit:** 919733b7

**3. [Rule 1 - Schema] yield_curve_slope/yield_curve_regime were orphaned in ShadowTransitionEvent, not in I4Context**
- **Found during:** Task 3 (plugin_validator schema coverage check)
- **Issue:** `MacroContextPlugin.outputs` includes `yield_curve_slope` and `yield_curve_regime`, but these fields existed only in `ShadowTransitionEvent` (a different dataclass), not in `I4Context`. Plugin validator caught the gap.
- **Fix:** Added both fields to `I4Context`; updated docstring Total 93→96→98
- **Files modified:** `src/intelligence/schemas.py`
- **Commit:** 919733b7

## Self-Check: PASSED

Files exist:
- `src/intelligence/context/macro_context.py` - FOUND
- `src/intelligence/trading/atr_utils.py` (get_atr_valid) - FOUND

Commits exist:
- `590f7691` - FOUND (ATR hardening)
- `14bc58ab` - FOUND (MacroContextPlugin)
- `919733b7` - FOUND (registration + test fixes)
