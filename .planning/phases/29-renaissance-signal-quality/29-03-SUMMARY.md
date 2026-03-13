---
phase: 29-renaissance-signal-quality
plan: 03
subsystem: signal-generator / signal-lifecycle
tags: [alpha-decay, freshness-decay, signal-quality, qual-02, qual-03, tdd]
dependency_graph:
  requires: [29-02]
  provides: [QUAL-02 alpha decay, QUAL-03 freshness decay]
  affects: [signal_generator_service, signal_lifecycle_service]
tech_stack:
  added: []
  patterns: [exponential-decay, linear-confidence-multiplier, in-memory-no-db-mutation]
key_files:
  created: []
  modified:
    - services/signal_generator_service.py
    - services/signal_lifecycle_service.py
decisions:
  - "Alpha decay applied to signal confidence BEFORE calling aggregate() — not inside it (QUAL-02 Pitfall 2 from RESEARCH.md)"
  - "FRESHNESS_HALF_LIFE_BARS uses per-TF values: 1m=20, 5m=10, 15m=6, 1h=4"
  - "_setup_last_fire keyed by (symbol, tf, plugin, direction) — orthogonal to _setup_cooldown"
  - "Freshness decay is in-memory only — original confidence in signal_ledger never mutated (ML ground truth)"
metrics:
  duration: ~15 min
  completed: "2026-03-13T09:01:40Z"
  tasks_completed: 2
  files_modified: 2
  tests_added: 10
  tests_total: 1580
---

# Phase 29 Plan 03: Alpha Decay + Signal Freshness Decay Summary

**One-liner:** Exponential freshness decay (QUAL-03) and linear alpha decay (QUAL-02) applied in-memory — signals diminish in value rather than expire, preserving every observation as labeled training data.

## Tasks Completed

| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| RED  | Add failing tests for QUAL-02 alpha decay (test_aggregator.py) + QUAL-03 freshness decay (test_lifecycle_freshness.py) | af09f12 | done |
| GREEN | Implement QUAL-02 `_apply_alpha_decay()` + `ALPHA_HALF_LIFE_BARS` in signal_generator_service; QUAL-03 `_compute_freshness_decay()` + `FRESHNESS_HALF_LIFE_BARS` in signal_lifecycle_service | 8c74a60 | done |

## What Was Built

### QUAL-02: Alpha Decay (signal_generator_service.py)

Added `ALPHA_HALF_LIFE_BARS` constant and `_apply_alpha_decay()` module-level function:

- Keyed by `(symbol, tf, setup_plugin, direction)` in `self._setup_last_fire`
- Each bar, `bars_since` is incremented for all tracked (symbol, tf) entries
- Before `aggregate()`, each signal's confidence is multiplied by `max(0.0, 1.0 - bars_since / half_life)`
- On publish, `bars_since` resets to 0 for the published setup/direction
- Values: 1m=10 bars, 5m=6, 15m=4, 1h=3 (starting values, data-driven tuning after 90 days)

### QUAL-03: Freshness Decay (signal_lifecycle_service.py)

Added `FRESHNESS_HALF_LIFE_BARS` constant and `_compute_freshness_decay()` function:

- Uses exponential formula: `freshness = exp(-log(2)/half_life * bars_since)`
- At `bars_since=0`: freshness=1.0; at `bars_since=half_life`: freshness≈0.5
- Designed for use in active signal evaluation loop as `effective_confidence = stored * freshness`
- Original confidence in `signal_ledger` is NEVER mutated — ground truth for ML training
- Values: 1m=20 bars, 5m=10, 15m=6, 1h=4

## Test Results

- `tests/unit/service_tests/test_lifecycle_freshness.py`: 10 tests (5 `TestFreshnessDecayComputation` + 5 `TestEffectiveConfidenceComputation`)
- `tests/unit/intelligence/test_aggregator.py`: 5 new `TestAlphaDecay` tests added
- Full suite: **1580 passing** (no regressions)

## Deviations from Plan

None — plan executed exactly as written.

- Both test files (`test_lifecycle_freshness.py` and `TestAlphaDecay` in `test_aggregator.py`) were already present (committed as RED in prior session `af09f12`)
- Both implementation targets were uncommitted GREEN work in the working tree
- This execution committed the GREEN implementation as a single atomic commit

## Self-Check

- `services/signal_generator_service.py`: FOUND
- `services/signal_lifecycle_service.py`: FOUND
- `ALPHA_HALF_LIFE_BARS` in signal_generator_service: FOUND
- `_apply_alpha_decay()` in signal_generator_service: FOUND
- `FRESHNESS_HALF_LIFE_BARS` in signal_lifecycle_service: FOUND
- `_compute_freshness_decay()` in signal_lifecycle_service: FOUND
- Commit af09f12 (RED tests): FOUND
- Commit 8c74a60 (GREEN implementation): FOUND
- 1580 tests passing: VERIFIED

## Self-Check: PASSED
