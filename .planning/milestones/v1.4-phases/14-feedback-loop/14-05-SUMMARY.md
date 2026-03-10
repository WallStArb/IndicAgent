---
phase: 14-feedback-loop
plan: "05"
subsystem: aggregator
tags: [feed-03, aggregation, performance-ranking, tdd]
dependency_graph:
  requires: [14-04]
  provides: [FEED-03-complete]
  affects: [signal_generator_service, aggregator]
tech_stack:
  added: []
  patterns: [perf_multiplier-as-primary-sort-key, setup-priority-tiebreaker]
key_files:
  created: []
  modified:
    - src/intelligence/trading/aggregator.py
    - tests/unit/intelligence/test_aggregator_perf.py
decisions:
  - "_build_all_ranked() uses perf_multiplier as primary sort key (not composite_rank * perf_multiplier)"
  - "No-weights fallback: adjusted_rank = -SETUP_PRIORITY so ascending sort preserves priority order"
  - "Tiebreaker within equal multipliers: negate SETUP_PRIORITY so higher-priority setup sorts first"
  - "_rank_tiebreak internal key stripped from returned signal dicts"
metrics:
  duration: "~30m (interrupted by rate limit mid-execution)"
  completed_date: "2026-03-07"
  tasks_completed: 3
  files_modified: 2
  tests_added: 3
  tests_total: 1236
---

# Phase 14 Plan 05: _build_all_ranked() Perf-Multiplier Primary Sort Key Summary

FEED-03 permanently closed by redesigning `_build_all_ranked()` so the perf_multiplier from `_compute_perf_multipliers()` is the primary sort key — eliminating the structural formula bug where a high-SETUP_PRIORITY underperformer could mathematically outrank a low-SETUP_PRIORITY outperformer.

## What Was Built

The old formula `adjusted_rank = composite_rank * perf_multiplier` was fundamentally broken: because `composite_rank` is assigned 1-based by SETUP_PRIORITY descending, a high-priority setup always gets `composite_rank=1`. Even with the inverted multiplier (best Sharpe=0.5), LSR (priority=5, composite_rank=1) with worst Sharpe got `adjusted_rank = 1 × 1.5 = 1.5`, while MeanReversion (priority=1, composite_rank=5) with best Sharpe got `adjusted_rank = 5 × 0.5 = 2.5`. Under ascending sort, LSR won — wrong.

The fix: when `perf_weights` is non-empty, `adjusted_rank = perf_multiplier` directly (best Sharpe=0.5 sorts first). SETUP_PRIORITY is used only as a tiebreaker via a `_rank_tiebreak = -priority` internal key. When no `perf_weights`, falls back to `adjusted_rank = -SETUP_PRIORITY` so ascending sort still puts the highest-priority setup first.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RED — failing e2e tests | 9206f00 | tests/unit/intelligence/test_aggregator_perf.py |
| 2 | GREEN — redesign _build_all_ranked() | 20df6c4 | src/intelligence/trading/aggregator.py |
| 3 | REFACTOR — ruff cleanup | fe65ef3 | tests/unit/intelligence/test_aggregator_perf.py |

## Verification

```
Multipliers: {'trad_LiquiditySweepReclaim': 1.3, 'trad_MTFAlignment': 1.1,
              'trad_TrendFollowing': 0.9, 'trad_SqueezeExpansion': 0.7,
              'trad_MeanReversion': 0.5}
Ranking: ['trad_MeanReversion', 'trad_SqueezeExpansion', 'trad_TrendFollowing',
          'trad_MTFAlignment', 'trad_LiquiditySweepReclaim']
PASS: best-Sharpe setup ranks first, worst-Sharpe ranks last (all 5 setups)
PASS: no-weights fallback preserves SETUP_PRIORITY order
1236 passed, 184 warnings
All ruff checks passed!
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] E501 line-too-long in test assertion message**
- **Found during:** Task 3 (REFACTOR)
- **Issue:** f-string in `test_e2e_worst_sharpe_ranks_last_regardless_of_setup_priority` was 104 chars (limit 100)
- **Fix:** Extracted `result[-1]['setup_plugin']` into local `got` variable
- **Files modified:** tests/unit/intelligence/test_aggregator_perf.py
- **Commit:** fe65ef3

## Key Decisions Made

1. **perf_multiplier as primary sort key:** When `perf_weights` is present, `adjusted_rank = perf_multiplier` directly. The old `composite_rank * perf_multiplier` formula was structurally unsound because SETUP_PRIORITY dominated the product for high-priority setups.

2. **No-weights fallback uses negative priority:** `adjusted_rank = -SETUP_PRIORITY` so the ascending sort contract is preserved in both paths — no conditional sort direction needed.

3. **_rank_tiebreak internal key:** Stored on signal dicts during sort, stripped before returning. Avoids exposing implementation detail to callers while enabling tuple-sort tiebreaking.

4. **`test_build_all_ranked_outperformer_promoted` updated:** Changed from manually crafted `{MR: 0.5, LSR: 1.5}` weights to `_compute_perf_multipliers()` output. This tests the real integration path rather than synthetic values.

## Self-Check: PASSED

- FOUND: src/intelligence/trading/aggregator.py
- FOUND: tests/unit/intelligence/test_aggregator_perf.py
- FOUND: .planning/phases/14-feedback-loop/14-05-SUMMARY.md
- FOUND commit 9206f00 (RED)
- FOUND commit 20df6c4 (GREEN)
- FOUND commit fe65ef3 (REFACTOR)
