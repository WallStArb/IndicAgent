---
phase: 121-lifecycle-replay-validation
plan: "04"
subsystem: intelligence/trading
tags: [macro-context, signal-capture, shadow-features, data-labeling]
dependency_graph:
  requires: [121-03]
  provides: [macro-regime-labels-in-shadow-dict]
  affects: [signal_ledger.features_snapshot, Phase-126-replay]
tech_stack:
  added: []
  patterns: [None-on-absent-capture, bare-features-get]
key_files:
  created:
    - tests/unit/intelligence/test_macro_context_plugin.py
    - .planning/todos/pending/024-ungated-macro-frame.md
  modified:
    - src/intelligence/trading/confidence_utils.py
    - src/intelligence/context/macro_context.py
    - src/intelligence/CLAUDE.md
    - tests/unit/intelligence/trading/test_capture_signal_features.py
    - tests/unit/intelligence/test_macro_context_schema.py
decisions:
  - "Use bare features.get() with no default for all 5 new macro fields — None means unavailable per D-06; 0.0 default would corrupt training data"
  - "EQ_INDEX gate defect (macro suppressed for non-EQ symbols) recorded as todo 024, deferred — fix requires decoupling macro_data merge from cross_asset_data merge"
metrics:
  duration_minutes: 15
  completed: "2026-06-13"
  tasks_completed: 2
  files_changed: 7
---

# Phase 121 Plan 04: Pre-Replay Compute Refinements (Macro Labeling + Data Flow Verification) Summary

One-liner: Added 5 MacroContextPlugin fields (ftq_score, ftq_regime, yield_curve_slope, yield_curve_regime, corr_z) to the 30-key shadow dict in capture_signal_features(), corrected the MacroContextPlugin docstring, and traced the complete macro data flow including an EQ_INDEX scope constraint and defect.

## Tasks Completed

### Task 1: Verify macro data flow and correct MacroContextPlugin docstring

**Status:** Complete (docstring was pre-corrected; trace and defect documentation produced here)

**Macro data flow — 7-step trace:**

1. **corr_z source:** `cross_asset_analyzer.py` writes `result["corr_z"]` into the cross_asset payload published to `topic_cross_asset`. `intelligence_pipeline.py` routes that payload via `_cache_mgr.update_cross_asset(tf, payload)`, so corr_z lands in `cache_snapshot.cross_asset_data[tf]`.

2. **ftq/yield_curve source:** `macro_analyzer.py` publishes `{timeframe, yield_curve_slope, yield_curve_regime}` and `{timeframe, ftq_score, ftq_regime}` to `topic_macro_signals`. `intelligence_pipeline.py` extracts only the 4 keys (yield_curve_slope, yield_curve_regime, ftq_score, ftq_regime — note: corr_z is NOT in the macro topic) and routes via `_cache_mgr.update_macro(tf, macro_fields)`. **Critical:** `update_macro` stores by tf only — the publisher's symbol (ZN, TLT) is dropped. The cache entry is global per-timeframe, not per-symbol.

3. **The merge:** `feature_pipeline_executor.py:206-207` builds `frames["cross_asset"] = {**cross_asset_data.get(tf, {"ready": False})}` then `.update(macro_data.get(tf, {}))`. This merges both sources into one dict, so `MacroContextPlugin` sees `corr_z` (from cross_asset_data) AND ftq/yield_curve (from macro_data) together when both producers have published.

4. **EQ_INDEX scope constraint:** The merge at `feature_pipeline_executor.py:205` is gated by `if resolve_eq_index_base(symbol) is not None:`. `resolve_eq_index_base` returns non-None ONLY for full contract symbols whose base is in `{ES, NQ, RTY, YM}`. Therefore `frames["cross_asset"]` is populated ONLY for EQ_INDEX contract symbols. For every other symbol, `frames.get("cross_asset")` is absent/empty, `MacroContextPlugin.compute_full` returns `{}`, and all 5 macro fields are None in the shadow dict.

5. **Confirmed defect (todo 024):** `macro_analyzer` publishes from `MACRO_RATE_FUTURES` (ZN, ZT) and `MACRO_FTQ_INSTRUMENTS` (TLT, SPY) — none are EQ_INDEX symbols. The cache stores macro data globally per-tf (symbol is dropped at ingest), making it available for all symbols in `cache_snapshot.macro_data[tf]`. However, the merge into `frames["cross_asset"]` is gated on EQ_INDEX, so non-EQ_INDEX instruments (CL, GC, ZN as a traded contract, etc.) receive no macro context. This is a data suppression defect. **Todo 024** written at `.planning/todos/pending/024-ungated-macro-frame.md` — fix: remove EQ_INDEX guard from the `macro_data.update()` call while keeping it only for `cross_asset_data` which IS EQ_INDEX-scoped.

6. **corr_z=0.0 ambiguity (D-06 concern):** `cross_asset_analyzer.py:467` stores `corr_z = 0.0` for EQ_INDEX symbols without a lead relationship. When captured via `features.get("corr_z")`, this 0.0 is ambiguous between "zero correlation" and "no lead instrument." Must be resolved before corr_z is used in regime-segmented training. Not fixed here.

7. **End-to-end bridge confirmed:** `MacroContextPlugin.compute_full(frames)` returns `{ftq_score, ftq_regime, yield_curve_slope, yield_curve_regime, corr_z}` when `frames["cross_asset"]["ready"]` is True. `executor.run_tier("i4", ...)` merges this output into `tiered["i4"]`, which is passed as `I4Context(**tiered.get("i4", {}))` in `feature_pipeline_executor.py:300`. `build_flat_features(event)` iterates `event.i4.model_dump()` with None filtering (`feature_flattening.py:89-91`), so all 5 macro fields land in `frames["features"]` when non-None. `capture_signal_features(features, ...)` reads them via `features.get("ftq_score")` etc. **D-10 confirmed:** `macro_ctx_plugin.name` registered in `TIER_I4` at `register_plugins.py:515`. **D-11 confirmed:** all 5 I4Context fields (`yield_curve_slope`, `yield_curve_regime`, `ftq_score`, `ftq_regime`, `corr_z`) present at `schemas.py:496-501`.

**Docstring correction verified:**
- `grep -n "feature_pipeline_executor" macro_context.py` returns lines 7 and 36.
- `grep -n "ALL symbols" macro_context.py` returns nothing.
- `grep -n "EQ_INDEX" macro_context.py` returns the corrected scope notes.

### Task 2: Add 5 macro fields to capture_signal_features() shadow dict

**Status:** Complete

**Changes made:**

- `src/intelligence/trading/confidence_utils.py`: Added 5 new keys to the shadow dict immediately after `eq_pairs_confirming`, using bare `features.get()` with no default (None-on-absent per D-06). Added comment attributing Phase 121 Wave 2 / D-10.
- Module docstring updated: "17 keys" -> "30 keys" with full breakdown (8 I6 CTF base+momentum + 8 I6 CTF extended + 9 I4 macro + 3 exhaustion + 2 metadata).
- Function docstring updated: "Shadow dict with 17 keys" -> "Shadow dict with 30 keys: 9 I4 macro + 16 I6 CTF + 3 exhaustion + 2 metadata".
- `src/intelligence/CLAUDE.md` table row: "15 keys: 2 metadata, 6 I6 CTF, 4 I4 macro, 3 exhaustion" -> "30 keys: 2 metadata, 16 I6 CTF (8 base+momentum, 8 extended), 9 I4 macro, 3 exhaustion".

**Test updates:**
- `test_shadow_key_count_non_exempt_is_25` -> asserts `len(shadow) == 30`
- `test_shadow_key_count_exempt_is_25` -> asserts `len(shadow) == 30`
- `test_capture_signal_features_all_fields_present` -> expected_keys set updated with 5 new macro fields (30 total)
- Added `test_macro_fields_present_when_provided` — all 5 fields captured when in features
- Added `test_macro_fields_none_when_absent` — all 5 fields are None when absent (D-06 behavior)
- `test_macro_context_schema.py` updated with `test_i4_context_has_macro_context_fields` — asserts all 5 I4Context macro fields exist and default to None (D-11 coverage)
- Created `tests/unit/intelligence/test_macro_context_plugin.py` — 4 tests: ready=True returns all 5 fields; ready=False returns {}; missing cross_asset key returns {}; None field values preserved not coerced to 0.0

**Confidence unchanged:** The 5 new keys are appended to the shadow dict only. `compose_confidence()` and the confidence-returning path are not touched. Verified by inspecting the diff — no changes to `existing_confidence`, `compose_confidence()`, or any clamp.

**Key count consistency verified:**
- Module docstring: "30 keys" (updated from stale "17")
- Function docstring: "30 keys" (updated from stale "17")
- `src/intelligence/CLAUDE.md`: "30 keys" (updated from stale "15")

## Deviations from Plan

None - plan executed exactly as written.

## Test Results

22 targeted tests passed (0 failures in the 3 modified/created test files).
Full suite: 4630 passed, 42 pre-existing failures (all pre-exist before this plan: signal_replay_auditor, api, config, scripts, lifecycle_tracker, signal_ledger, trade_framer, vwap_deviation — confirmed by running suite against the pre-plan stash).

## Commits

- `62826346` docs(121-04): correct MacroContextPlugin docstring; add todo 024 ungated-macro-frame
- `7cedf5aa` feat(121-04): add 5 MacroContextPlugin fields to capture_signal_features shadow dict

## Self-Check: PASSED

Files verified:
- `src/intelligence/trading/confidence_utils.py` — exists, contains "ftq_score", "30 keys"
- `src/intelligence/context/macro_context.py` — exists, contains "feature_pipeline_executor", no "ALL symbols"
- `src/intelligence/CLAUDE.md` — exists, contains "30 keys"
- `tests/unit/intelligence/test_macro_context_plugin.py` — exists (4 tests)
- `.planning/todos/pending/024-ungated-macro-frame.md` — exists

Commits verified:
- `7cedf5aa` present in git log
- `62826346` present in git log
