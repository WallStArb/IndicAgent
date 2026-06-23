---
phase: "138"
plan: "perf"
subsystem: "feature_factory / backfill"
tags: ["performance", "vectorization", "atr", "batch"]
dependency_graph:
  requires: ["138-P1", "138-P5", "138-P6"]
  provides: ["138-corpus-run-unblocked"]
  affects: ["backfill_feature_factory", "feature_factory"]
tech_stack:
  added: []
  patterns: ["vectorized O(n) precompute before per-bar loop", "precomputed kwarg on stateless compute()"]
key_files:
  created: ["tests/unit/test_batch_feature_parity.py"]
  modified: ["src/intelligence/feature_factory.py", "services/backfill_feature_factory.py"]
decisions:
  - "precomputed= kwarg is optional (None = streaming, dict = batch) — live pipeline is unchanged"
  - "_atr_series_full uses same EWM seed as _atr_wilder, verified bit-for-bit identical per prefix"
  - "_rolling_zscore_series uses expanding window min(zw, i+1) to match streaming's min(zw, len) semantics"
  - "gap_raw_padded: prepend 0.0 before _rolling_zscore_series to align effective window with streaming"
  - "scipy.stats.skew in _rolling_stat_z identified as dominant bottleneck (83% of compute() time) - deferred"
metrics:
  duration: "~35min (including profiling and correctness work)"
  completed: "2026-06-23"
  tasks_completed: 3
  files_changed: 3
---

# Phase 138 Perf: ATR/gap_z O(n²) Vectorization Summary

Eliminated O(n²) ATR/gap_z inner loops in the backfill batch path. VUG 5m
(469k bars) blocked corpus run; fix converts repeated per-bar Wilder ATR
recomputation into a single O(n) pass before the loop.

## What Was Done

### 1. Two new module-level helpers in `src/intelligence/feature_factory.py`

`_atr_series_full(highs, lows, closes, period)` - O(n) Wilder ATR series.
Uses a single EWM pass from bar 0 forward, zeroing positions where `n < period+1`
(matching `_atr_wilder` semantics exactly; verified bit-for-bit identical per prefix).

`_rolling_zscore_series(arr, window)` - O(n) rolling z-score series.
Uses expanding window `min(window, i+1)` at position `i` to match
`_zscore_last(series, min(window, len(series)))` semantics used in the streaming path.
Cumulative-sum implementation: O(n) total vs O(n x window) naive.

### 2. `FeatureFactory.compute()` signature extended

Added optional `precomputed: dict | None = None` kwarg. When provided, `atr`,
`atr_z`, and `gap_z` are taken from the dict instead of recomputed. Live pipeline
passes `precomputed=None` (default) - no behavior change.

### 3. `services/backfill_feature_factory.py` precompute block

After `compute_bars_loaded`, before the per-bar loop: compute `_atr_padded`
(length = total_bars, `_atr_padded[i] = _atr_wilder(bars[0..i])`), `_atr_z_full`,
`_gap_raw_padded`, and `_gap_z_full` once in O(n). Each bar passes these as
`precomputed={"atr": ..., "atr_z": ..., "gap_z": ...}`.

Index alignment for gap_z:
- Streaming at bar `i` uses `_atr_wilder(highs[:i])` (ATR of i bars) = `_atr_core[i-2]`
- `_gap_raw_padded` has a leading 0.0 so that `_rolling_zscore_series` at index `j+1`
  uses effective window `min(zw, j+2) = min(zw, i)`, matching streaming's window

### 4. Parity test `tests/unit/test_batch_feature_parity.py`

N=500 synthetic bars (< _READ_CHUNK_BARS=2000). Compares all FeatureVector float
fields between streaming (precomputed=None) and batch (precomputed from vectorized
helpers) paths. Tolerance 1e-8. All 101 unit tests pass.

## Performance Numbers

| Case | Calls/sec |
|------|-----------|
| No precomputed (2000-bar window) | 3.3 |
| With precomputed (2000-bar window) | 3.9 (+18%) |

Precompute steps (469k bars): `_atr_series_full` = 0.04s, `_rolling_zscore_series` = 0.23s.
Total precompute overhead: ~0.3s for the full VUG 5m corpus.

## Deferred Items (out of scope)

**Dominant bottleneck: `scipy.stats.skew` in `_rolling_stat_z`** (83% of compute()
time at 2000-bar window). `_rolling_stat_z` calls `scipy.stats.skew` once per bar
over a rolling window of bars. At 2000 bars this is 2000 `scipy.stats.skew` calls per
`compute()` invocation. Python inspection overhead in scipy accounts for 2.5s of 3.0s
per call. Replacing with a pure-numpy rolling skewness computation would reduce compute()
from ~260ms to ~40ms per bar (6-7x speedup). Tracked in `.planning/todos/`.

## Self-Check

- `src/intelligence/feature_factory.py`: FOUND
- `services/backfill_feature_factory.py`: FOUND
- `tests/unit/test_batch_feature_parity.py`: FOUND
- Commit `9da19956`: FOUND

## Self-Check: PASSED
