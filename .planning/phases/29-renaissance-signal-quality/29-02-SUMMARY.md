---
phase: 29-renaissance-signal-quality
plan: 02
subsystem: signal-quality
tags: [cis-scorer, signal-generator, quality-gates, tdd, qual-04, qual-05, qual-06]
dependency_graph:
  requires: [29-01]
  provides: [QUAL-04, QUAL-05, QUAL-06]
  affects: [signal_generator_service, cis_scorer, intelligence_features]
tech_stack:
  added: []
  patterns:
    - timestamp-based cooldown gate (vs counter-based) — avoids call-count brittleness
    - additive supplemental sub-terms within existing bucket methods — no weight rebalancing required
key_files:
  created: []
  modified:
    - src/intelligence/trading/cis_scorer.py
    - services/signal_generator_service.py
    - tests/unit/intelligence/test_cis_scorer.py
    - tests/unit/service_tests/test_signal_generator_service.py
decisions:
  - _filter_setup_cooldown uses timestamp-based bars_elapsed (not decrement-per-call) — consistent with existing _check_gate pattern and avoids brittleness when test/caller invokes with non-sequential timestamps
  - rel_volume supplemental weight 0.05 (not redistributed from existing) — keeps existing sub-term weights stable; additive approach confirmed by CONTEXT.md
  - killzone +0.05 active / -0.01 dead session — asymmetric: boost liquidity windows without heavily penalizing off-hours
  - _setup_cooldown stores fire timestamp (not bars_left int) — enables timestamp-based comparison matching _check_gate convention
metrics:
  duration: "12 minutes"
  completed: "2026-03-13"
  tasks_completed: 2
  files_modified: 4
---

# Phase 29 Plan 02: Per-setup Cooldown + rel_volume + Killzone CIS Wire-ins Summary

Wire three signal quality gates (QUAL-04/05/06) using data already present in the pipeline: no new data sources required, only new connections.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 (RED) | CIS QUAL-05/06 failing tests | 0273008 | tests/unit/intelligence/test_cis_scorer.py |
| 1 (GREEN) | CIS rel_volume + killzone sub-terms | e7b17bc | src/intelligence/trading/cis_scorer.py |
| 2 (RED) | Cooldown gate failing tests | 1e87732 | tests/unit/service_tests/test_signal_generator_service.py |
| 2 (GREEN) | Per-setup cooldown implementation | b1d1da3 | services/signal_generator_service.py |

## What Was Built

### QUAL-05: rel_volume sub-term in CIS momentum bucket
`cis_scorer._momentum()` now reads `rel_volume` from the features dict (default=1.0 so missing data contributes exactly 0). Maps `[0,2] → [-0.05, +0.05]` via `clamp((rel_vol - 1.0) / 1.0)`. High-volume bars nudge momentum score upward; low-volume bars suppress it. The sub-term is additive (supplemental) — existing 5 sub-terms unchanged.

### QUAL-06: killzone sub-term in CIS regime bucket
`cis_scorer._regime()` now reads `in_london_killzone` and `in_ny_killzone` from features. Active killzone (max > 0.5) adds +0.05 to regime bucket; dead session (both 0) subtracts 0.01. Uses `max()` to handle simultaneous active killzones gracefully.

### QUAL-04: Per-setup cooldown gate in signal_generator_service
`_SIGNAL_COOLDOWN_BARS` constant: `{"1m": 3, "5m": 2, "15m": 2, "1h": 2}`.

`_setup_cooldown` dict keyed by `(symbol, tf, setup_plugin, direction)` storing the fire timestamp. At each bar, `_filter_setup_cooldown()` checks `bars_elapsed = (timestamp - fired_at) / tf_seconds` — if `< cooldown_bars`, the signal is stripped before entering the aggregator.

The filter runs immediately after `_run_setup_plugins()` and before `aggregate()`, ensuring blocked signals never enter the alpha decay path. The gate is per-setup-plugin, so `trad_TrendFollowing` cooldown never affects `trad_MeanReversion`.

## Test Results

- 8 new tests: 3 for QUAL-05 (momentum rel_volume), 3 for QUAL-06 (regime killzone), 6 for QUAL-04 (cooldown gate)
- Full suite: **1565 passing** (no regressions)

## Deviations from Plan

### Auto-fixed: Counter-based → timestamp-based cooldown
- **Found during:** Task 2 (GREEN) — expiry test failing
- **Issue:** Plan specified decrement-per-call counter but test invoked `_filter_setup_cooldown` at bar N then bar N+3 directly (2 calls, not 3) expecting expiry
- **Fix:** Changed `_setup_cooldown` value from `bars_left: int` to `fired_at: datetime`; computes `bars_elapsed` from timestamp difference — consistent with existing `_check_gate` pattern
- **Files modified:** services/signal_generator_service.py
- **Rule:** Rule 1 (bug fix)

## Self-Check: PASSED

- SUMMARY.md: FOUND at .planning/phases/29-renaissance-signal-quality/29-02-SUMMARY.md
- Commit e7b17bc (CIS scorer): FOUND
- Commit b1d1da3 (cooldown gate): FOUND
- 1565 tests passing (no regressions)
