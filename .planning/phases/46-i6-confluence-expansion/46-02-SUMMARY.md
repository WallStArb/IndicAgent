---
phase: 46-i6-confluence-expansion
plan: "02"
subsystem: intelligence
tags: [i6, confluence, vix, cross-asset, schema, ml-features]
dependency_graph:
  requires: []
  provides: [CONF-04, CONF-05, CONF-06]
  affects: [src/intelligence/schemas.py, src/intelligence/confluence/cross_timeframe.py]
tech_stack:
  added: []
  patterns: [None-for-missing data, active_pair key routing for spread selection]
key_files:
  created:
    - tests/unit/test_cross_timeframe_confluence.py
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/confluence/cross_timeframe.py
decisions:
  - "New fields are float|None = None, not float with 0.0 default — per D-03, never substitutes 0.0 for missing upstream data"
  - "ctf_score formula is bit-for-bit unchanged — new fields are independent columns per D-02"
  - "active_pair routing: ES_NQ → es_nq_spread_z; all other pairs → es_rty_spread_z"
  - "ctf_eq_pairs_confirming explicitly cast to float() for schema type consistency"
metrics:
  duration: "2 minutes"
  completed: "2026-03-22"
  tasks_completed: 2
  files_changed: 3
---

# Phase 46 Plan 02: I6Confluence VIX and Cross-Asset Fields Summary

**One-liner:** Extended I6Confluence schema with 4 raw ML feature fields (ctf_vix_level, ctf_vix_z, ctf_eq_spread_z, ctf_eq_pairs_confirming) and wired CrossTimeframeConfluencePlugin to emit them from frames["vix"] and frames["cross_asset"].

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add 4 new fields to I6Confluence schema | e706548 | src/intelligence/schemas.py |
| 2 (RED) | Failing tests for new field emission | 0be4f93 | tests/unit/test_cross_timeframe_confluence.py |
| 2 (GREEN) | Emit new fields from CrossTimeframeConfluencePlugin | d6de22c | src/intelligence/confluence/cross_timeframe.py |

## What Was Built

### Schema Extension (src/intelligence/schemas.py)

Added 4 new `float | None = None` fields to `I6Confluence` after `i6_i2_event_score`:

- `ctf_vix_level`: raw VIX close level; all symbols
- `ctf_vix_z`: VIX z-score vs 20-bar rolling mean; all symbols
- `ctf_eq_spread_z`: dominant EQ pair spread z-score; EQ_INDEX only
- `ctf_eq_pairs_confirming`: 0.0-2.0 confirming pairs; EQ_INDEX only

Docstring updated from `(10 fields)` to `(16 fields)`.

### Plugin Update (src/intelligence/confluence/cross_timeframe.py)

Updated `CrossTimeframeConfluencePlugin`:

1. Added 4 new field names to the `outputs` frozenset
2. In `compute_full()`, before the return statement: reads `frames.get("vix", {})` and `frames.get("cross_asset", {})`, populates new fields when `ready=True`, sets `None` when unavailable or `ready=False`
3. EQ pair routing: `active_pair == "ES_NQ"` → `es_nq_spread_z`; otherwise → `es_rty_spread_z`
4. `ctf_score` formula (`W_TREND * trend_alignment + ...`) is unchanged

### Tests (tests/unit/test_cross_timeframe_confluence.py)

8 new tests covering all 8 behaviors from the plan:
- VIX ready → fields populated
- VIX not-ready → None
- VIX key absent → None
- cross_asset ES_NQ pair → es_nq_spread_z used
- cross_asset ES_RTY pair → es_rty_spread_z used
- cross_asset not-ready → None
- cross_asset key absent → None
- ctf_score bit-for-bit identical with/without new frames

## Verification Results

- `.venv/bin/pytest tests/unit/test_cross_timeframe_confluence.py -v` → 8/8 passed
- `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -v` → 20/20 passed (no regressions)
- Schema import: `I6Confluence(ctf_vix_level=18.5, ctf_vix_z=-0.3)` succeeds
- `W_TREND/W_STRUCTURE/W_REGIME/W_PATTERN` weights unchanged from pre-phase values
- `.venv/bin/ruff check src/intelligence/confluence/cross_timeframe.py` → all checks passed

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all 4 new fields are wired to real upstream data sources (frames["vix"] and frames["cross_asset"]). Fields return None when upstream data is unavailable, which is the correct behavior per D-03.

## Self-Check: PASSED

- src/intelligence/schemas.py contains `ctf_vix_level`: confirmed
- src/intelligence/confluence/cross_timeframe.py contains `ctf_vix_level`: confirmed
- tests/unit/test_cross_timeframe_confluence.py exists: confirmed
- Commits e706548, 0be4f93, d6de22c: confirmed in git log
