---
phase: 45
plan: 01
subsystem: intelligence/trading
tags: [confluence, shadow-capture, i6, i7, ml-foundation]
dependency_graph:
  requires: []
  provides: [capture_confluence_features, ConfluenceWeightProfile, FAMILY_PROFILES, ctf_fvg_alignment, ctf_ob_alignment]
  affects: [src/intelligence/trading/confidence_utils.py, src/intelligence/confluence/cross_timeframe.py, src/intelligence/schemas.py]
tech_stack:
  added: []
  patterns: [frozen-dataclass, pure-data-capture, shadow-dict, feature-aliasing]
key_files:
  created:
    - tests/unit/test_capture_confluence_features.py
  modified:
    - src/intelligence/trading/confidence_utils.py
    - src/intelligence/confluence/cross_timeframe.py
    - src/intelligence/schemas.py
decisions:
  - "capture_confluence_features() does zero confidence modification — pure data capture for Phase 49 ML (D-03)"
  - "ConfluenceWeightProfile weights all 0.0 placeholder — Phase 49 fills non-zero values from ML training"
  - "ctf_fvg/ob_alignment are aliases for i6_fvg/ob_tf_alignment — i6_* preserved for backward compat"
  - "capture_confluence_features() reads ctf_fvg_alignment with fallback to i6_fvg_tf_alignment for pre-45-01 frames"
  - "exempt_exhaustion profile sets exhaustion fields to None — DeltaExhaustion is the exhaustion detector (D-09)"
metrics:
  duration_seconds: 132
  completed_date: "2026-03-22"
  tasks_completed: 2
  files_modified: 3
  files_created: 1
---

# Phase 45 Plan 01: Confluence Feature Capture Infrastructure Summary

**One-liner:** Shadow capture infrastructure with `capture_confluence_features()`, `ConfluenceWeightProfile` dataclass, 6 family profiles, and `ctf_fvg_alignment`/`ctf_ob_alignment` exposed from I6 cross_timeframe output.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add capture_confluence_features() + ConfluenceWeightProfile | 1472e7d | confidence_utils.py, test_capture_confluence_features.py |
| 2 | Expose ctf_fvg_alignment + ctf_ob_alignment from cross_timeframe.py | 4791d16 | cross_timeframe.py, schemas.py |

## What Was Built

### Task 1: confidence_utils.py extensions

Three new exports added to `src/intelligence/trading/confidence_utils.py`:

1. **`ConfluenceWeightProfile`** — frozen dataclass with 7 fields (`name` + 6 weight fields all `0.0`). Interface contract for Phase 49 weight learning. Immutable by design.

2. **`FAMILY_PROFILES`** — dict of 6 profiles: `trend`, `mean_reversion`, `smc`, `microstructure`, `session`, `exempt_exhaustion`. Maps family names to `ConfluenceWeightProfile` instances.

3. **`capture_confluence_features(features, direction, profile_name, existing_confidence) -> dict`** — pure data capture, zero confidence modification. Returns 11-key shadow dict (D-07 schema). Reads from `frames["features"]` with safe `.get()` defaults. Maps `ctf_fvg_alignment` ← `i6_fvg_tf_alignment` (with fallback to `ctf_fvg_alignment` once Task 2 is live).

### Task 2: I6 output fields

- `cross_timeframe.py`: Added `ctf_fvg_alignment` and `ctf_ob_alignment` to both `outputs` frozenset and `compute_full()` return dict. Values are aliases for the existing `i6_fvg_tf_alignment` / `i6_ob_tf_alignment` scores.
- `schemas.py`: Added `ctf_fvg_alignment: float | None = None` and `ctf_ob_alignment: float | None = None` to `I6Confluence` schema. Old `i6_*` fields preserved.

## Verification Results

```
pytest tests/unit/test_capture_confluence_features.py -xvs: 7 passed
ruff check confidence_utils.py: All checks passed
grep -c "capture_confluence_features" confidence_utils.py: 2
grep -c "ctf_fvg_alignment" cross_timeframe.py: 2
grep -c "ctf_fvg_alignment" schemas.py: 1
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

`ConfluenceWeightProfile` weights are intentionally all `0.0` (Phase 45 design). Phase 49 fills non-zero values from ML training. This is by design, not a missing implementation.

## Self-Check: PASSED

Files created:
- `tests/unit/test_capture_confluence_features.py` — EXISTS
- `src/intelligence/trading/confidence_utils.py` (modified) — EXISTS

Commits:
- `1472e7d` — feat(45-01): add capture_confluence_features() + ConfluenceWeightProfile
- `4791d16` — feat(45-01): expose ctf_fvg_alignment + ctf_ob_alignment
