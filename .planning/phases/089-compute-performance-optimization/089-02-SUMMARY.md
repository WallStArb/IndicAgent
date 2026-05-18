---
phase: 089-compute-performance-optimization
plan: 02
subsystem: intelligence-pipeline
tags: [pydantic, model_construct, performance, allocation, feature-pipeline]

requires:
  - phase: 089-01
    provides: FeaturePipelineExecutor extracted, PluginExecutor.run_i7_complete added

provides:
  - PERF-01: single _build_features_from_event call site in executor.py
  - PERF-05: None filtering at merge site in run_i1/run_tier; no comprehensions at IntelligenceEvent construction
  - PERF-02: flat features dual-write retained with full consumer audit (79 read sites across plugins)
  - PERF-08: BarMessage.model_construct on hot path (_parse_bar)
  - PERF-09: gap flag as explicit parameter; bar.model_copy eliminated

affects:
  - 089-03
  - 089-04
  - 089-05
  - 089-06

tech-stack:
  added: []
  patterns:
    - "None-filtering at merge site: filter at collection boundary, not at consumer call"
    - "model_construct for trusted internal producers with ValueError/TypeError fallback"
    - "Gap flag as explicit parameter through call chain instead of object mutation"

key-files:
  created:
    - tests/unit/pipeline/__init__.py
    - tests/unit/pipeline/test_feature_pipeline_executor.py
  modified:
    - src/intelligence/pipeline/executor.py
    - src/intelligence/pipeline/feature_pipeline_executor.py
    - services/intelligence_pipeline_agent.py

key-decisions:
  - "PERF-02 flat features retained: 79 read-only consumers across plugin tree; removal would break I2-I7 plugins"
  - "PERF-08 fallback path: model_construct primary, full validation on TypeError/ValueError to surface schema violations via DLQ"
  - "PERF-09 gap flag placement: frames['__gap__'] in FeaturePipelineExecutor for future plugin access"

duration: 8min
completed: 2026-05-18
---

# Phase 089 Plan 02: Allocation Overhead Elimination Summary

**Per-bar allocations eliminated: single _build_features_from_event call, no tier comprehensions at IntelligenceEvent construction, model_construct on hot path, gap flag as parameter instead of model_copy**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-18T20:35:10Z
- **Completed:** 2026-05-18T20:42:49Z
- **Tasks:** 3 (PERF-01+05, PERF-02, PERF-08+09)
- **Files modified:** 5 (executor.py, feature_pipeline_executor.py, intelligence_pipeline_agent.py, + 2 test files created)

## Per-bar Latency Metric (D-13)

The `intelligence_pipeline_pipeline_latency_ms` gauge is a cumulative add-only gauge. The pipeline service was not running live during this window. Structural wins are verified by code inspection:

- PERF-01: `grep -c "_build_features_from_event(" executor.py` = 1 (was already 1 from Plan 01 D-20)
- PERF-05: 7 None-filtering comprehensions at IntelligenceEvent construction removed; None now filtered at `run_i1`/`run_tier` merge sites
- PERF-08: Pydantic model validation (field coercion, type checking, default application) eliminated for each bar parse
- PERF-09: One `model_copy()` allocation per gap bar eliminated (model_copy clones entire Pydantic model)

## PERF-02 Audit Result

**Flat features dual-write RETAINED.** Consumer audit found 79 read-only call sites across the plugin tree.

Write sites (2):
- `src/intelligence/pipeline/executor.py:460` - `features = frames.setdefault("features", {})`
- `src/intelligence/pipeline/feature_pipeline_executor.py:200` - `frames["features"] = dict(i1_result)` (I1 seed)

Read consumers (sample, 79 total):
- All I2 composite plugins (acceleration_regime, exhaustion_score, ma_composites, etc.)
- All I3 structure plugins (market_profile, session_levels, fibonacci_zones, etc.)
- All I4 context plugins (kalman_trend, momentum_context, trend_regime, etc.)
- All I5 pattern plugins (candlestick_patterns, confluence, mtf_volatility, etc.)
- All SMC context plugins (bos_choch, breaker_blocks, hmm_regime, etc.)
- All I6 confluence plugins (cross_timeframe, cross_tf_sr_confluence)
- All I7 trading plugins (trend_following, mean_reversion, squeeze_expansion, etc.)

`/tmp/perf02_audit.txt` contains the full evidence file.

## PERF-09 Audit Result (gap_preceding readers)

`/tmp/perf09_audit.txt` - no pipeline reads of `bar.gap_preceding` found in `src/intelligence/`. Remaining references:
- `src/core/schemas/bar_message.py` - field definition (retained for ingestion/HTF aggregation)
- `src/core/bar_accumulator.py` - set at ingestion, not read by pipeline
- `services/bar_aggregator_agent.py` - propagates from payload at HTF aggregation
- `services/bar_writer_agent.py` - persists to DB

Gap flag now flows as `frames["__gap__"]` from `FeaturePipelineExecutor.run(bar, cache_snapshot, gap=gap)`.

## Accomplishments

- Eliminated 7 per-bar None-filtering comprehensions at IntelligenceEvent construction (PERF-05)
- Moved None filtering to `run_i1`/`run_tier` merge sites - runs once at plugin output boundary
- BarMessage.model_construct on hot path eliminates Pydantic validation per bar (PERF-08)
- bar.model_copy() eliminated by threading gap as explicit bool parameter (PERF-09)
- Behavioral equivalence unit test confirms PERF-05 produces same model_dump output

## Task Commits

1. **Task 1: PERF-01+05 - features cached once + pre-filtered tier dicts** - `6dd9daa8` (feat)
2. **Task 2: PERF-02 - audit flat features dual-write** - No code change (documentation-only; dual-write retained)
3. **Task 3: PERF-08+09 - model_construct on hot path + gap flag as parameter** - `a4793454` (feat)

## Files Created/Modified

- `src/intelligence/pipeline/executor.py` - PERF-05: None filter at run_i1/run_tier merge site
- `src/intelligence/pipeline/feature_pipeline_executor.py` - PERF-05: direct tier dict construction; PERF-09: gap kwarg + frames["__gap__"]
- `services/intelligence_pipeline_agent.py` - PERF-08: model_construct + fallback; PERF-09: gap as parameter
- `tests/unit/pipeline/__init__.py` - new test package
- `tests/unit/pipeline/test_feature_pipeline_executor.py` - 3 tests: PERF-05 equivalence (x2), PERF-01 single call site

## Decisions Made

- **PERF-02 retained**: 79 read-only consumers of `frames["features"]` across plugin tree - removal would break all I2-I7 plugins that read the flat features dict. Acceptance criterion (b) applies.
- **model_construct fallback**: falls back to full `BarMessage(**msg)` validation on `ValueError/TypeError` to preserve DLQ error surfacing for malformed messages.
- **Gap flag in frames**: `frames["__gap__"]` placement allows future plugins to access gap signal without changing the bar object or adding another parameter level.

## Deviations from Plan

### Auto-fixed Issues

None - plan executed exactly as written. PERF-02 used the documented alternative completion path (consumer audit + retention with justification).

## Issues Encountered

- Pre-commit hook requires `.venv` at worktree root. Created symlink `.venv -> /home/bg/dev/indicagent/.venv` in the worktree to satisfy hook path resolution.

## Next Phase Readiness

- Plan 03 (Wave 1 parallel - CacheManager optimization) can proceed independently
- Plan 04 (executor.py refactoring) can proceed - executor.py is clean and tested
- All PERF-0X allocation wins are in place; latency reduction visible on next live run

## Self-Check: PASSED

All key files exist and commits are verified:
- `src/intelligence/pipeline/executor.py` - FOUND
- `src/intelligence/pipeline/feature_pipeline_executor.py` - FOUND
- `services/intelligence_pipeline_agent.py` - FOUND
- `tests/unit/pipeline/test_feature_pipeline_executor.py` - FOUND
- `.planning/phases/089-compute-performance-optimization/089-02-SUMMARY.md` - FOUND
- Commit `6dd9daa8` (PERF-01+05) - FOUND
- Commit `a4793454` (PERF-08+09) - FOUND
