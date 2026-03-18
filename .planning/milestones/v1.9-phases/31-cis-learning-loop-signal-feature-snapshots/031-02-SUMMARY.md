---
phase: 31-cis-learning-loop-signal-feature-snapshots
plan: 02
subsystem: intelligence
tags: [logistic-regression, weight-updater, binary-labels, cluster-segmentation, cis-weights]

# Dependency graph
requires:
  - phase: 31-01
    provides: cis_weights.asset_cluster column, signal_ledger.is_shadow column

provides:
  - "WIN_OUTCOMES frozenset (target_1, target_1_2, target_full)"
  - "ASSET_CLUSTER_MAP: 21 symbols across eq_index/commodity/rates/crypto/ag clusters"
  - "get_asset_cluster() helper function"
  - "compute_new_weights() trains on binary outcome labels (not signal_quality proxy)"
  - "_write_weights_to_db() helper with per-(asset_cluster, timeframe) version counter"
  - "run_weight_update() trains global + per-cluster models when cluster N >= 100"
  - "is_shadow = FALSE filter on DB query"
  - "WeightUpdateResult.win_rate replaces signal_quality_mean"

affects:
  - "Phase 35 (CIS Kalman): reads cis_weights by asset_cluster"
  - "market_analysis_service: CISScorer.update_weights() hot-swap"
  - "signal_generator_service: weight refresh loop"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Binary outcome labels: frozenset membership test (outcome in WIN_OUTCOMES)"
    - "Cluster segmentation: defaultdict grouping by (cluster, timeframe) before per-group training"
    - "Per-cluster version counter: MAX(version) WHERE asset_cluster=$1 AND timeframe=$2"

key-files:
  created: []
  modified:
    - "src/intelligence/weight_updater.py"
    - "tests/unit/intelligence/test_weight_updater.py"

key-decisions:
  - "Used frozenset for WIN_OUTCOMES for O(1) membership test"
  - "Global model always trained first; per-cluster only when N >= MIN_SAMPLES_FULL (100)"
  - "ASSET_CLUSTER_MAP has 21 entries (not 22 — plan had counting error in success criteria)"
  - "symbol column retained as 'global' in cis_weights INSERT for backward compatibility; asset_cluster is the new segmentation key"
  - "Symbols not in ASSET_CLUSTER_MAP (ETFs, FX, VX) contribute to global model only — they do not create 'global' cluster-specific rows"

patterns-established:
  - "Cluster training pattern: group rows by (cluster, tf), skip clusters < 100 samples, train + write separately"
  - "is_shadow filter: always add is_shadow = FALSE to any signal_ledger query used for training"

requirements-completed:
  - LEARN-02
  - LEARN-04

# Metrics
duration: 4min
completed: 2026-03-17
---

# Phase 31 Plan 02: Binary Win Labels + Cluster Segmentation Summary

**LogisticRegression weight updater upgraded from signal_quality proxy to true binary win/loss outcome labels with per-(asset_cluster, timeframe) segmentation across 5 futures/crypto clusters**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-17T01:28:26Z
- **Completed:** 2026-03-17T01:32:52Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Replaced crude `signal_quality >= mean` proxy target with binary `outcome in WIN_OUTCOMES` labels — learner now optimizes directly on trade outcomes
- Added `ASSET_CLUSTER_MAP` (21 futures/crypto symbols, 5 clusters) and `get_asset_cluster()` so cluster context is always available
- `run_weight_update()` now trains global + per-cluster models: ES/NQ weights no longer contaminated by BTC volatility regimes
- `is_shadow = FALSE` filter ensures shadow-mode signal experiments never pollute the training dataset
- `WeightUpdateResult` gains `win_rate`, `asset_cluster`, `timeframe`; `signal_quality_mean` removed
- 38 tests covering all behavior: binary label correctness, degenerate handling, cluster training thresholds, shadow filter

## Task Commits

Both tasks were implemented in a single unified commit (Tasks 1 and 2 are structurally coupled — binary labels and cluster segmentation both live in `weight_updater.py`):

1. **Task 1: Binary win labels + ASSET_CLUSTER_MAP** - `78236fe` (feat)
2. **Task 2: Cluster-segmented training + DB write with asset_cluster** - `78236fe` (feat, same commit)

**Plan metadata:** (committed below)

## Files Created/Modified

- `src/intelligence/weight_updater.py` - Binary outcome labels, WIN_OUTCOMES, ASSET_CLUSTER_MAP, get_asset_cluster(), WeightUpdateResult with win_rate, _write_weights_to_db() helper, per-cluster training in run_weight_update()
- `tests/unit/intelligence/test_weight_updater.py` - Complete rewrite: 38 tests covering binary labels, asset cluster map, WeightUpdateResult fields, shadow filter, cluster training thresholds, version counter

## Decisions Made

- **Frozenset for WIN_OUTCOMES**: O(1) membership test; immutable at module level
- **21 symbols, not 22**: Plan's success criteria stated "22 base symbols" but counting eq_index(4) + commodity(7) + rates(4) + crypto(3) + ag(3) = 21; test corrected to match reality
- **Global model always first**: Trains and writes before per-cluster loop; if global returns None (< 50 signals), early-return without running cluster loop
- **ETF/FX/VX symbols → global only**: `get_asset_cluster()` returns 'global' for unmapped symbols; in `run_weight_update`, the cluster loop `continue`s when `cluster == "global"` — these symbols boost the global model but never create a named cluster row
- **symbol='global' backward compatibility**: `cis_weights.symbol` column retained as 'global' in all inserts; `asset_cluster` is the actual segmentation key used for weight lookups

## Deviations from Plan

None — plan executed exactly as written. The only minor deviation was correcting the symbol count from 22 to 21 in the test assertion (plan had a counting error in success criteria).

## Issues Encountered

- Pre-existing `test_signals_route.py::test_get_signals_base_symbol_resolved` failure exists before this plan; out of scope per deviation rules

## Next Phase Readiness

- Phase 31 Plan 03 (signal_features writer) can proceed — weight_updater is production-ready with binary labels
- `CISScorer.update_weights()` hot-swap path unchanged — service-layer integration requires no changes
- When Phase 35 (Kalman CIS) reads cis_weights, it can filter by `asset_cluster='eq_index'` to get cluster-specific weights

## Self-Check: PASSED

- `src/intelligence/weight_updater.py`: FOUND
- `tests/unit/intelligence/test_weight_updater.py`: FOUND
- `.planning/phases/31-cis-learning-loop-signal-feature-snapshots/031-02-SUMMARY.md`: FOUND
- Commit `78236fe`: FOUND

---
*Phase: 31-cis-learning-loop-signal-feature-snapshots*
*Completed: 2026-03-17*
