---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
plan: 03B
subsystem: macro-factors / intelligence-pipeline
tags: [macro, pipeline-integration, topic_macro_signals, frames, cross_asset]
status: complete
completed: 2026-04-27

# Dependency graph
requires:
  - phase: 64-03A
    provides: MacroComputeAgent publishing to topic_macro_signals
depends_on: ["64-03A"]
provides:
  - intelligence_pipeline_agent subscribes to topic_macro_signals
  - _macro_cache holding latest yield_curve + ftq fields per timeframe
  - frames["cross_asset"] enriched with macro factors at frame-build time

key-files:
  modified:
    - services/intelligence_pipeline_agent.py

key-decisions:
  - "Separate _macro_cache dict (not merged into _cross_asset_cache) — avoids corrupting cross_asset payload on update"
  - "Merge happens at frame-build time via dict spread — zero-copy, no mutation of cache"
  - "Explicit field whitelist: yield_curve_slope, yield_curve_regime, ftq_score, ftq_regime — no wildcard update"
  - "topic_macro_signals added to subscription list alongside topic_cross_asset"
  - "FTQ factor was delivered in a prior execution (MacroComputeAgent extended during 03A/03B-FTQ); pipeline integration was the remaining gap"

history:
  - "03B-FTQ (executed 2026-04-27): Extended MacroComputeAgent with FTQ computation (compute_flight_to_quality)"
  - "03B-pipeline (executed 2026-04-27): This plan — wired macro_signals topic into intelligence_pipeline_agent"
---

# Phase 64 Plan 03B: Pipeline Macro Integration Summary

**Macro factors (yield curve, FTQ) are now available to I7 plugins via `frames["cross_asset"]`.**

## What Was Built

### `services/intelligence_pipeline_agent.py` (3 surgical changes)

1. **Import**: Added `topic_macro_signals` to `stream_keys` imports.

2. **Subscription** (`_setup()`): Added `topic_macro_signals(self.settings.env_name)` to the topics list alongside `topic_cross_asset`.

3. **Message handler** (`_process_loop()`): Added `_macro_topic` branch — stores whitelisted macro fields into `self._macro_cache[tf]`.

4. **Frame injection** (`_build_frames()`): Changed `frames["cross_asset"]` construction from direct cache lookup to a merged dict — cross_asset cache spread first, then macro cache overlay. Same pattern for `frames["cross_asset_5m"]`.

## History

The original 03B execution mistakenly delivered FTQ computation (extending MacroComputeAgent) rather than pipeline integration. The FTQ work was valid and needed, but the pipeline integration — the gap that prevented macro factors from reaching I7 — was left open. This execution closes that gap.

## Tests

All 40 existing pipeline tests pass after changes. No new tests added (existing tests exercise `_build_frames()` and would catch regression in cross_asset injection).

## Self-Check: PASSED

- [x] `topic_macro_signals` imported
- [x] Subscription list updated (5 topics)
- [x] `_macro_cache` initialized in `__init__`
- [x] `_macro_topic` handler in `_process_loop`
- [x] `frames["cross_asset"]` merges macro data at build time
- [x] `frames["cross_asset_5m"]` merges macro data at build time
- [x] 40 pipeline tests passing

---
*Phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service*
*Plan: 03B (pipeline integration)*
*Completed: 2026-04-27*
