---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
plan: 03B
subsystem: macro-factors / intelligence-pipeline
tags: [macro, pipeline-integration, topic_macro_signals, frames, cross_asset]
status: complete
completed: 2026-04-28
review_cycle: 2
review_finding_resolved: "HIGH — macro cache overwrite fixed: setdefault().update() replaces direct assignment"

# Dependency graph
requires:
  - phase: 64-03A
    provides: MacroComputeAgent publishing to topic_macro_signals
depends_on: ["64-03A"]
provides:
  - intelligence_pipeline_agent subscribes to topic_macro_signals
  - _macro_cache holding latest yield_curve + ftq fields per timeframe (merge semantics)
  - frames["cross_asset"] enriched with macro factors at frame-build time

key-files:
  modified:
    - services/intelligence_pipeline_agent.py
    - tests/unit/test_intelligence_pipeline_agent.py

key-decisions:
  - "Separate _macro_cache dict (not merged into _cross_asset_cache) — avoids corrupting cross_asset payload on update"
  - "Merge happens at frame-build time via dict spread — zero-copy, no mutation of cache"
  - "Explicit field whitelist: yield_curve_slope, yield_curve_regime, ftq_score, ftq_regime — no wildcard update"
  - "topic_macro_signals added to subscription list alongside topic_cross_asset"
  - "setdefault().update() merge semantics: both YC and FTQ coexist in same tf entry"
  - "FTQ factor was delivered in a prior execution (MacroComputeAgent extended during 03A/03B-FTQ); pipeline integration was the remaining gap"

history:
  - "03B-FTQ (executed 2026-04-27): Extended MacroComputeAgent with FTQ computation (compute_flight_to_quality)"
  - "03B-pipeline (executed 2026-04-27): Wired macro_signals topic into intelligence_pipeline_agent (original plan)"
  - "03B-REVISED (executed 2026-04-28): Fixed HIGH-severity cache overwrite bug from cross-AI review cycle 2"
---

# Phase 64 Plan 03B: Pipeline Macro Integration Summary (REVISED)

**Macro factors (yield curve, FTQ) are now available to I7 plugins via `frames["cross_asset"]` with correct merge semantics.**

## What Was Built

### Original execution (2026-04-27)

1. **Import**: Added `topic_macro_signals` to `stream_keys` imports.
2. **Subscription** (`_setup()`): Added `topic_macro_signals(self.settings.env_name)` to the topics list.
3. **Message handler** (`_process_loop()`): Added `_macro_topic` branch with `_macro_cache`.
4. **Frame injection** (`_build_frames()`): Merged macro cache into `frames["cross_asset"]`.

### Revised fix (2026-04-28) — Cross-AI Review HIGH finding

**Bug fixed:** `self._macro_cache[tf] = {...}` was a full replacement. When a FTQ message arrived after a YC message (same tf), the YC fields (`yield_curve_slope`, `yield_curve_regime`) were silently discarded.

**Fix applied:**
```python
# BEFORE (broken): full replacement
self._macro_cache[tf] = {k: payload[k] for k in (...) if k in payload}

# AFTER (correct): merge semantics
self._macro_cache.setdefault(tf, {}).update(
    {k: payload[k] for k in (...) if k in payload}
)
```

`setdefault(tf, {})` creates the dict if absent; `.update(...)` merges new keys without wiping existing ones. Both YC and FTQ now coexist for the same timeframe.

## Tests

All 37 pipeline tests pass. Added `TestMacroCacheMergeSemantics` class (4 tests):
- `test_yc_survives_subsequent_ftq_message` — primary regression test
- `test_ftq_survives_subsequent_yc_message` — symmetric case
- `test_multiple_tf_entries_independent` — no cross-tf leakage
- `test_setdefault_update_used_not_direct_assignment` — source-code assertion

## Self-Check: PASSED

- [x] `topic_macro_signals` imported
- [x] Subscription list updated (5 topics)
- [x] `_macro_cache` initialized in `__init__`
- [x] `_macro_topic` handler in `_process_loop`
- [x] `_macro_cache.setdefault(tf, {}).update(...)` — NOT direct assignment
- [x] `frames["cross_asset"]` merges macro data at build time
- [x] `frames["cross_asset_5m"]` merges macro data at build time
- [x] 37 pipeline tests passing (including 4 new regression tests)
- [x] Cross-AI review HIGH finding resolved

---
*Phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service*
*Plan: 03B (pipeline integration + cache fix)*
*Original: 2026-04-27 | Revised: 2026-04-28*
