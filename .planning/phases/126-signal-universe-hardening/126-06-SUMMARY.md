---
phase: "126"
plan: "06"
subsystem: "intelligence-pipeline"
tags: ["pipeline-annotation", "ecl", "signal-schema", "zone-friction", "context-features"]
dependency_graph:
  requires: ["126-00", "126-02"]
  provides: ["pipeline-layer annotation", "zone_friction_score in flat_features", "SIGNAL_SCHEMA_VERSION v4"]
  affects: ["signal_processor.py", "signal_schema.py", "confidence_utils.py", "all 35 I7 plugins"]
tech_stack:
  added: []
  patterns:
    - "Pipeline-layer ECL annotation: _annotate_signal() stamps full flat_features snapshot before any gate"
    - "Tier sub-model field ownership: zone_friction_score lives in SMCContext (all inputs are SMC-derived)"
    - "Deprecation-not-deletion: capture_signal_features() retained for one cycle, not deleted"
key_files:
  created:
    - "tests/unit/intelligence/test_pipeline_annotation.py"
  modified:
    - "src/intelligence/pipeline/signal_processor.py"
    - "src/intelligence/schemas.py"
    - "src/intelligence/trading/signal_schema.py"
    - "src/intelligence/trading/confidence_utils.py"
    - "src/intelligence/plugins/base.py"
    - "src/intelligence/CLAUDE.md"
    - "src/intelligence/trading/supply_demand_setup.py (+ 34 other I7 plugins)"
    - "tests/unit/intelligence/test_i6_confluence_enforcement.py"
    - "tests/unit/intelligence/test_i7_extrinsic_contract.py"
    - "tests/unit/intelligence/test_ofi_divergence.py"
    - "tests/unit/intelligence/test_orb_plugins.py"
    - "tests/unit/intelligence/test_pattern_completion.py"
    - "tests/unit/intelligence/trading/test_dual_divergence.py"
decisions:
  - "zone_friction_score tier: SMCContext (not I3 or I6) - all inputs (demand/supply freshness, strength, dist_atr) are produced by smc_SupplyDemandZones and live in that sub-model"
  - "capture_signal_features() deprecated not deleted - retained for replay tooling compatibility per D-10"
  - "features_snapshot removed entirely from make_signal_from_frame() - zone_source was always None since TradeFrame has no .features field"
metrics:
  duration: "~90 minutes (continuation session)"
  completed: "2026-06-15"
  tasks_completed: 3
  files_modified: 48
---

# Phase 126 Plan 06: Pipeline-Layer Annotation Summary

Pipeline-layer ECL annotation (context_features as full flat_features snapshot, ctf_score, ctf_confirmed, zone_friction_score) stamped uniformly on every I7 signal by _annotate_signal() in signal_processor.py. Annotation is no longer per-plugin.

## What Was Done

### Task 1: Audit flat_features + formalize zone_friction_score in a tier

Audited `build_flat_features()` output against `capture_signal_features()` keys:

**Present in flat_features:**
- `ctf_score` + 17 CTF sub-scores (via I6Confluence sub-model)
- `exhaustion_score`, `exhaustion_side`, `exhaustion_bars` (via I2Events)
- `vix_z`, `vix_level`, `ftq_score`, `yield_curve_slope`, `corr_z` (via I4Context)

**Absent (newly formalized):**
- `zone_friction_score` - was computed only inside `supply_demand_setup.py`, never persisted to a tier sub-model

**Tier decision: SMCContext.** All inputs (`demand_freshness`, `demand_strength`, `demand_dist_atr`, and supply equivalents) are produced by `smc_SupplyDemandZones` and already present in `SMCContext`. The metric is a derived composite of SMC inputs, not a confluence or structure calculation.

Formula: `freshness * strength * (1 / (1 + dist_atr))` for the nearest active zone (demand or supply, whichever is closer). `max(zf_demand, zf_supply)` when both present.

Added `zone_friction_score: float | None = None` to `SMCContext` in `schemas.py`. Implemented computation at end of `smc_SupplyDemandZonesPlugin.compute_full()`. The field now flows into `flat_features` automatically via `build_flat_features()` iteration over tier sub-models.

**Commit:** `15101377`

### Task 2: Implement _annotate_signal() in signal_processor.py

Added to `src/intelligence/pipeline/signal_processor.py`:

```python
_SURFACED_ECL_FIELDS: tuple[str, ...] = (
    "ctf_score",
    "ctf_confirmed",  # derived from ctf_score, not read from flat_features
    "zone_friction_score",
)

def _annotate_signal(sig: dict, flat_features: dict) -> None:
    sig["context_features"] = flat_features  # full snapshot
    ctf_score = float(_ctf_raw) if (_ctf_raw := flat_features.get("ctf_score")) is not None else None
    sig["ctf_score"] = ctf_score
    sig["ctf_confirmed"] = (abs(ctf_score) >= MIN_CTF_SCORE) if ctf_score is not None else None
    sig["zone_friction_score"] = flat_features.get("zone_friction_score")
```

Wired immediately after `pre_quality_confidence` stamping and before alpha decay/gates in `process()`. Even regime-suppressed signals carry full context for ML training integrity.

**Commit:** `21115e90`

### Task 3: Strip plugins, clean schema, delete enforcement, bump version, write tests

**STEP 4 - Strip:** Removed `capture_signal_features()` calls and imports from all 35 I7 plugin files. Also removed dead ECL extraction blocks (ctf_score/ctf_confirmed/zone_friction_score local variables) and unused `get_min_ctf_score` imports.

**STEP 5 - Clean make_signal_from_frame():** Removed kwargs `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `context_features`, `features_snapshot`. ECL fields now initialized to `None`/`{}` by `make_signal_from_frame()` and overwritten by `_annotate_signal()`. `zone_source` was always `None` (TradeFrame has no `.features` field; `features_snapshot` was always passed as `None` from all call sites) - set directly to `None` with a comment.

**STEP 6 - Delete enforcement:** Removed `requires_i6_confluence` attribute from all 35 plugin dataclasses. Removed `requires_i6_confluence: ClassVar[bool]` from `PatternPlugin` Protocol. Removed enforcement check from `validate_tier()` in `plugins/base.py`. `grep -r "_I7_I6_EXEMPT\|requires_i6_confluence" src/ tests/` = empty.

**STEP 7 - Deprecate:** Added deprecation comment block at top of `capture_signal_features()` in `confidence_utils.py`.

**STEP 8 - Bump version:** `SIGNAL_SCHEMA_VERSION = "v4"` with changelog comment.

**STEP 9 - Tests:** Created `tests/unit/intelligence/test_pipeline_annotation.py` with 12 tests + AST sweep (64 parametrized cases):
- `test_annotate_sets_context_features_to_full_snapshot` - identity check, not equality
- `test_annotate_ctf_score_float`, `*_none_when_absent`
- `test_annotate_ctf_confirmed_*` - true/false/negative/none
- `test_annotate_zone_friction_score_*` - present/absent/zero-distinct-from-None
- `test_extensibility_new_key_appears_in_context_features_automatically` - key extensibility
- `test_no_plugin_calls_capture_signal_features[*]` - AST sweep over all trading/ files

Updated 6 existing test files to reflect Phase 126-06 contracts.

**Commit:** `cb3b9bc5`

## Test Results

- Before Plan 06: 116 failures (baseline, pre-existing from zone_too_narrow gate in Plan 01)
- After Plan 06: 97 failures (-19: the requires_i6_confluence sweep tests are now gone)
- New tests added: 64 passed, 1 skipped (confidence_utils.py exempted from AST sweep)
- No new failures introduced

## Deviations from Plan

**1. [Rule 1 - Bug] microstructure_utils.py had dangling ctf_score reference**
- Found during: Task 3 commit (pre-commit hook, ruff F821)
- Issue: ECL strip script removed the `ctf_score` variable assignment but the conditional `if ctf_score is not None: supporting.append(...)` survived
- Fix: Removed the two orphaned lines
- Files modified: `src/intelligence/trading/microstructure_utils.py`
- Commit: `cb3b9bc5`

**2. [Rule 1 - Bug] zone_friction_score was never computed anywhere**
- Found during: Task 1 investigation
- Issue: `supply_demand_setup.py` read `features.get("zone_friction_score")` but no tier plugin ever computed it - it was always None
- Fix: Implemented computation in `smc_SupplyDemandZonesPlugin.compute_full()` and added the field to `SMCContext` schema
- Files modified: `src/intelligence/schemas.py`, `src/intelligence/features/smc_context/supply_demand_zones.py`
- Commit: `15101377`

**3. [Deviation] features_snapshot removed entirely rather than kept for zone_source**
- Plan said: "verify zone_source flows through the TradeFrame result; if so, remove features_snapshot entirely"
- Verified: `features_snapshot` was passed as `None` from every plugin call site (TradeFrame has no `.features` field, so `(features_snapshot or {}).get("zone_source")` was always `None`)
- Decision: removed `features_snapshot` kwarg entirely; `zone_source` initialized to `None` with a comment noting lifecycle_tracker sets it at activation
- Files modified: `src/intelligence/trading/signal_schema.py`

## Self-Check

Created files:
- tests/unit/intelligence/test_pipeline_annotation.py: FOUND
- .planning/phases/126-signal-universe-hardening/126-06-SUMMARY.md: FOUND (this file)

Commits:
- 15101377: feat(126-06): formalize zone_friction_score in SMCContext tier: FOUND
- 21115e90: feat(126-06): implement _annotate_signal() pipeline annotation in signal_processor: FOUND
- cb3b9bc5: refactor(126-06): strip capture_signal_features from all plugins, delete requires_i6_confluence: FOUND

Key invariants verified:
- `grep -rn "capture_signal_features" src/intelligence/trading/` - only definition in confidence_utils.py and changelog comment in signal_schema.py
- `grep -rn "ctf_score=|context_features=" src/intelligence/trading/` - empty
- `grep -r "_I7_I6_EXEMPT|requires_i6_confluence" src/ tests/` - empty
- `SIGNAL_SCHEMA_VERSION = "v4"` - confirmed
- `_annotate_signal` wired in signal_processor.py process() before gates - confirmed

## Self-Check: PASSED
