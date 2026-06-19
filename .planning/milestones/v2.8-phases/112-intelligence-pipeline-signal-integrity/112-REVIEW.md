---
phase: "112"
status: "issues_found"
critical_count: 3
warning_count: 6
info_count: 4
reviewed_at: "2026-06-02T21:30:00Z"
depth: standard
files_reviewed: 21
files_reviewed_list:
  - src/intelligence/schemas.py
  - src/intelligence/pipeline/state_manager.py
  - services/feature_writer.py
  - src/persistence/repository/signal_ledger_repository.py
  - src/intelligence/trading/cis_scorer.py
  - src/intelligence/pipeline/signal_processor.py
  - src/intelligence/pipeline/quality_gate.py
  - src/intelligence/pipeline/ranker.py
  - src/intelligence/trading/aggregator.py
  - src/intelligence/setup_performance_updater.py
  - src/intelligence/trading/signal_schema.py
  - services/signal_tracker.py
  - services/lifecycle_writer.py
  - src/intelligence/pipeline/executor.py
  - src/intelligence/pipeline/output_queue.py
  - src/intelligence/pipeline/per_key_worker_manager.py
  - src/intelligence/pipeline/feature_flattening.py
  - services/intelligence_pipeline.py
  - src/intelligence/services/ml_signal_training_materializer.py
  - src/intelligence/ml/confidence_calibrator.py
  - services/signal_metrics_analyzer.py
---

# Phase 112: Code Review Report

**Reviewed:** 2026-06-02T21:30:00Z
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Phase 112 is a large, well-structured integrity fix spanning contamination boundaries, calibration architecture (Design B), signal lifecycle forensics, pipeline architecture, and latency improvements. The implementation is generally sound: the feature_schema_version contamination boundary is wired end-to-end, the CIS-level isotonic calibration (Design B) is architecturally cleaner than the previous per-signal approach, PERF-03 state migration is enforced at startup, and the two-queue OutputQueue is a correct implementation of weighted-fair drain.

Three critical defects were found across correctness and data integrity dimensions. Six warnings capture logic gaps and code quality issues that will cause silent misbehavior or maintenance debt.

---

## Critical Issues

### CR-01: `raw_cis is None` check is unreachable — `CISScorer.score()` always returns a float

**File:** `src/intelligence/pipeline/signal_processor.py:297`

**Issue:** `CISScorer.score()` computes `cis_score = clamp(cis_raw)` where `clamp()` always returns a float — it never returns `None`. The check `if raw_cis is None` at line 297 is dead code. This is a bug because any condition that *should* produce a null CIS (e.g., all-zero input, degenerate features) silently produces a valid-looking `0.0` that bypasses the intended DLQ path. The comment at line 294 says "CIS score absent (scorer returned None)" but the scorer's return type is `float`, not `float | None`.

The `cis_score` field on `CISResult` is typed `float` (not `float | None`), confirming this check can never fire. The entire DLQ branch from lines 297–320 is dead.

**Fix:** Either:
1. Remove the dead-code block entirely and document that a zero CIS score is treated as a "no fire" signal (direction=0), not a DLQ condition — the existing `direction == 0` path already handles this correctly; or
2. If truly wanting a DLQ on degenerate inputs, add a real guard condition before calling `score()` (e.g., `if not raw_signals: return DLQ`) or change `CISResult.cis_score` to `float | None` and make `score()` return `None` on clearly invalid feature sets.

The current code gives a false sense of safety — engineers reading this believe there is a guard here, but there is not.

---

### CR-02: `_build_plugin_circuit_breakers()` instantiates breakers with `failure_threshold=3, enabled=False` but `_get_plugin_cb()` lazy-inits new breakers with `failure_threshold=10, enabled=True` — inconsistent circuit breaker behavior on restart

**File:** `services/intelligence_pipeline.py:226-247` and `src/intelligence/pipeline/executor.py:270-275`

**Issue:** At startup, `_build_plugin_circuit_breakers()` creates one `CircuitBreaker(failure_threshold=3, timeout_sec=300, enabled=False)` per plugin and passes this dict to `PluginExecutor`. These are shadow-mode breakers — they record failures but never trip. However, `PluginExecutor._get_plugin_cb()` (executor.py:269-275) lazy-initializes a NEW `CircuitBreaker(failure_threshold=10, timeout_sec=60, enabled=True)` for any plugin_name NOT already in `self._plugin_circuit_breakers`.

Because `_build_plugin_circuit_breakers()` only iterates `TIER_I1 + TIER_I2 + ... + TIER_I7`, any plugin that appears in the cache but not in those lists (e.g. plugins added post-deploy that are in the registry but not yet in a TIER constant, or I7 plugins that are in the registry under a different name) will receive a live, enabled breaker (`enabled=True, threshold=10`) instead of the intended shadow-mode breaker. The two initialization paths have irreconcilably different defaults:
- Startup path: `failure_threshold=3, timeout_sec=300, enabled=False`
- Lazy-init path: `failure_threshold=10, timeout_sec=60, enabled=True`

Even for the correctly pre-populated breakers, if a plugin trips three times in 300s its breaker opens while the comment at line 232 claims shadow mode is "live routing unaffected." The comment is contradicted by the 3-failure threshold.

**Fix:** Align the lazy-init defaults in `_get_plugin_cb()` with the intent. If shadow mode is intended, set `enabled=False` in the lazy-init path as well. If live circuit breakers are intended, document that the startup path's `enabled=False` creates shadow breakers only as an initial observation phase and remove the misleading comment.

```python
# executor.py:270-275 — align defaults with startup path or document divergence
def _get_plugin_cb(self, plugin_name: str) -> CircuitBreaker:
    cb = self._plugin_circuit_breakers.get(plugin_name)
    if cb is None:
        # Lazy-init: MUST match failure_threshold and enabled from _build_plugin_circuit_breakers.
        # Currently diverges: startup uses threshold=3/disabled, lazy-init uses threshold=10/enabled.
        cb = CircuitBreaker(failure_threshold=10, timeout_sec=60, enabled=True)
        self._plugin_circuit_breakers[plugin_name] = cb
    return cb
```

---

### CR-03: `confidence_calibrator.py` trains on `cis_score` labeled as `confidence` — cross-contaminates the calibration pipeline with the wrong signal feature

**File:** `src/intelligence/ml/confidence_calibrator.py:74-82`

**Issue:** The calibration query at line 74 selects `cis_score AS confidence` from `signal_ledger_full`. However, `confidence` in this context is supposed to be the per-signal plugin confidence value — the value that Design B intends to calibrate and that is stamped onto the winner as `calibrated_confidence`. Using `cis_score` (a bar-level aggregate in `[-1.0, +1.0]`) as the x-axis for isotonic regression produces calibration curves on the wrong distribution:

- `cis_score` is the raw weighted bucket score, range `[-1, +1]`
- Plugin confidence values are `[0.10, 0.95]` (clamped by `compose_confidence()`)
- Isotonic regression trained on `cis_score` produces `np.interp` outputs that when applied to plugin confidence values (passed in `[0.10, 0.95]`) produce nonsensical results because the input domain of the trained curve is `[-1, +1]`

The result: `_apply_cis_calibration()` in `CISScorer` receives the filtered CIS (in `[-1, +1]`) and calls `np.interp(filtered_cis, breakpoints, values)` where `breakpoints` were derived from `cis_score` values in `[-1, +1]` — this part is actually consistent. The issue is that `run_calibration_update` labels the column `confidence` but it is `cis_score`, and stores it in the `confidence_calibration` table which is keyed by `(plugin_name, timeframe)` — suggesting it was originally designed to hold per-plugin calibration curves.

If the Design B intent is that calibration curves are keyed by `("_cis_", tf, symbol)` and trained on the aggregate CIS score, then:
1. The column alias in the query should be `cis_score AS x_input` (not `AS confidence`) to avoid confusion
2. The `confidence_calibration` table schema and callers must handle a `"_cis_"` sentinel plugin name
3. The current trained key `(plugin_name, timeframe)` does not include `symbol` — `CISScorer._apply_cis_calibration` looks up `("_cis_", tf, symbol)` and `("_cis_", tf, "*")` but the trained keys are `(plugin_name, timeframe)` tuples (no symbol), so the lookup will always miss

The consequence is that `cis_result.calibrated_cis` will be `None` for every bar (because `_calibration_curves` is always empty — the trained curves are never loaded into a format that the scorer's lookup can find), and `calibrated_confidence` is never stamped on the winner signal.

**Fix:** The calibrator must train CIS-level curves keyed by `("_cis_", tf, symbol)` and write them to a table or format that `CacheManager` loads and passes to `CISScorer.set_calibration_curves()`. The current table `confidence_calibration` (keyed by `(plugin_name, timeframe)`) appears to be the per-plugin table from Design A, not the CIS-level table that Design B requires. This is a data pipeline disconnect that makes the entire Design B calibration path a no-op.

---

## Warnings

### WR-01: `apply_quality_gate()` signature has `thresholds: dict` as second positional arg but call site passes `features: dict`

**File:** `src/intelligence/pipeline/quality_gate.py:89` and `src/intelligence/pipeline/signal_processor.py:342-348`

**Issue:** `apply_quality_gate(signals, thresholds, *, tf, ...)` expects `thresholds` as its second positional argument — a dict with keys `hurst_quality`, `entropy_quality`, `drift_penalty`. But `signal_processor.py:342` calls:

```python
quality_gated = await apply_quality_gate(
    raw_signals,
    features,        # <-- this is the flat features dict, NOT thresholds
    tf=tf,
    ...
)
```

`features` is the flat feature dict (keys: `rsi_14`, `macd_histogram`, etc.), not a thresholds dict. The gate will call `float(features.get("hurst_quality", 1.0))` which returns `1.0` (key absent), and similarly `1.0` for `entropy_quality` and `drift_penalty` — making the entire quality multiplier computation a no-op (`quality_multiplier = min(1.0, 1.0) = 1.0`, `quality_score = 1.0 * 1.0 = 1.0`, confidence is unchanged).

The quality gate silently never degrades signal confidence. If `hurst_quality` and `entropy_quality` are actually stored in `features` under those exact keys, the gate accidentally works — but this is fragile and unintentional. The intended `thresholds` dict (from `cache_snapshot`) is never passed.

**Fix:** Pass `cache_snapshot` quality thresholds explicitly:
```python
quality_gated = await apply_quality_gate(
    raw_signals,
    {
        "hurst_quality": features.get("hurst_trend_quality", 1.0),
        "entropy_quality": features.get("entropy_quality", 1.0),
        "drift_penalty": cache_snapshot.drift_penalties.get(symbol, 1.0),
    },
    tf=tf,
    recorder=self._transform_recorder,
    min_confidence=getattr(self._settings, "SIGNAL_MIN_PUBLISHABLE_CONFIDENCE", 0.12),
)
```

---

### WR-02: `_compute_perf_multipliers()` returns inverted ranking but the comment/docstring contradicts itself

**File:** `src/intelligence/setup_performance_updater.py:99-125`

**Issue:** The docstring at line 100 says:
> `Best performer: rank=n-1 → multiplier = 0.5 (LOWEST — sorts first in ascending adjusted_rank)`

But the formula at line 122 is `m = 0.5 + ((n - 1 - rank) / n)` where `sorted_plugins` is sorted ascending by Sharpe (rank 0 = worst, rank n-1 = best). For the best performer at `rank = n-1`: `m = 0.5 + ((n-1-(n-1))/n) = 0.5 + 0 = 0.5`. For the worst performer at `rank = 0`: `m = 0.5 + ((n-1)/n) ≈ 1.5`.

So best Sharpe → multiplier 0.5, worst Sharpe → multiplier ~1.5. Under ascending sort in `ranker.py` (`adjusted_rank = perf_multiplier`, lower = higher priority), the best performer has rank 0.5 (lowest, wins). This is intentionally inverted and the docstring header says so correctly. However the module docstring at lines 16-20 also says this but uses confusingly contradictory language:
> `Best performer: rank=n-1 → multiplier = 0.5 (LOWEST — sorts first in ascending adjusted_rank)`

The confusion is `rank=n-1` (highest rank in sort order) maps to `multiplier=0.5` (lowest adjusted_rank for selection). This is correct but the dual-use of "rank" (sort rank vs selection priority) will mislead future maintainers.

Additionally: with `n=1` the function returns `(1.0, sample_size)` — the single plugin gets multiplier `1.0` regardless of its Sharpe quality. This is a silent fallback that ignores actual performance when there is only one eligible setup. The warm-up penalty (0.5) is also lower than this neutral value, meaning a new unvalidated setup (sample_size=0, penalty=0.5) will out-rank a single validated setup (sample_size>=30, multiplier=1.0) under ascending sort. This may be intentional but is undocumented.

**Fix:** Add a comment clarifying the n=1 case behavior and whether the warm-up penalty intentionally out-ranks the neutral single-setup multiplier. The formula itself appears correct for the n>1 case.

---

### WR-03: `output_queue.py` drain loop raises the first publish exception after processing all items, but already called `task_done()` on all items including failures

**File:** `src/intelligence/pipeline/output_queue.py:319-356`

**Issue:** In the publish loop at line 321, `task_done()` is called in the `finally` block for EVERY item, including failed ones. Then at line 355, `if first_exc is not None: raise first_exc`. When an exception is raised, the item has already been marked `task_done()` on the queue. The item is effectively dropped — the exception propagates up to whoever called the drain loop, which triggers `return_exceptions=True` in `_run`'s `asyncio.gather`, so the drain loop dies silently.

This means a single Kafka publish failure can kill the drain loop permanently (all subsequent enqueued items will be stuck until the service restarts). The `return_exceptions=True` in `gather` means the main loop log at lines 402-408 will log it as `task.failed_silent`, but the OutputQueue itself stops draining.

The correct behavior should be to log the error and continue draining, not raise and terminate the loop.

**Fix:** Remove the `raise first_exc` at the end of the drain loop iteration. The `_publish_failures` counter and error log inside the try block are sufficient observability. The loop must be resilient to individual publish failures:
```python
# Remove the re-raise at line 355:
# if first_exc is not None:
#     raise first_exc
```

---

### WR-04: `_load_signal()` accepts ISO timestamps with bare `+00:00` offset but not bare `Z` from all callers

**File:** `services/signal_tracker.py:351-354`

**Issue:** The timestamp parsing at lines 351-354 handles the `Z` suffix via `.replace("Z", "+00:00")` before calling `datetime.fromisoformat()`. However, `format_iso_ts()` from `service_utils.py` (per CLAUDE.md) always emits `Z`-suffix timestamps. This conversion is correct. But `bar_ts` from the i7.signals envelope at line 433:

```python
"timestamp": sig.get("timestamp") or payload.get("bar_ts", ""),
```

`bar_ts` is formatted with `format_iso_ts(bar_ts)` in `signal_processor.py:560` which produces a `Z`-suffix string. The `fromisoformat` replacement handles this. No issue here.

However: `activated_at` in the canonical dict (line 389) is stored as a raw value from `raw.get("activated_at")` without timestamp normalization. If `activated_at` arrives as an ISO string from Kafka (which it will, since it was serialized with `format_iso_ts`), it is stored as a string in the canonical dict. When `_add_to_active_index` at line 550 does `state.activated_at = canonical["activated_at"]`, this sets `activated_at` to a string instead of a `datetime`. Any downstream code comparing `state.activated_at` to a datetime will fail or silently compare incompatible types.

**Fix:** Normalize `activated_at` in `_load_signal()` the same way `timestamp` is normalized:
```python
activated_at_raw = raw.get("activated_at")
if isinstance(activated_at_raw, str) and activated_at_raw:
    try:
        canonical["activated_at"] = datetime.fromisoformat(activated_at_raw.replace("Z", "+00:00"))
    except ValueError:
        canonical["activated_at"] = None
else:
    canonical["activated_at"] = activated_at_raw
```

---

### WR-05: `_cis_kalman_update()` in `signal_processor.py` is dead code — Kalman is now owned by `CISScorer`

**File:** `src/intelligence/pipeline/signal_processor.py:76-84`

**Issue:** The standalone `_cis_kalman_update()` function at lines 76-84 implements a Kalman update step. After the Design B migration, all Kalman computation was moved into `CISScorer._apply_cis_kalman()`. This module-level function is no longer called anywhere in `signal_processor.py` or its callers. It is dead code that increases maintenance surface — future developers may mistakenly think it is still in use or may edit it instead of the active version in `cis_scorer.py`.

**Fix:** Remove `_cis_kalman_update()` from `signal_processor.py`. If it is needed as a utility function elsewhere, it should be imported from `cis_scorer.py` or moved to a shared utility module.

---

### WR-06: `feature_flattening.py` injects BB aliases even when the underlying I1 field is `None`

**File:** `src/intelligence/pipeline/feature_flattening.py:83-85`

**Issue:** `build_flat_features()` at lines 83-85 unconditionally writes BB alias keys:
```python
f["bb_middle"] = event.i1.bb_20_2_mid
f["bb_upper"] = event.i1.bb_20_2_upper
f["bb_lower"] = event.i1.bb_20_2_lower
```

These are written regardless of whether the underlying fields are `None`. Earlier in the function (lines 79-81), `None` values are filtered out (`if v is not None: f[k] = v`). But the alias injection bypasses this filter, so `f["bb_middle"]` will be `None` when `bb_20_2_mid` is `None`.

Downstream consumers that call `self._fval(f, "bb_middle", default=0.0)` handle this correctly (the `_fval` method returns the default on `None`). However, the inconsistency between the non-None-filtered tier data and the explicitly-None alias injection is a code quality issue that will confuse consumers that do `f.get("bb_middle")` without a None check.

**Fix:** Apply the same None filter to aliases:
```python
if event.i1.bb_20_2_mid is not None:
    f["bb_middle"] = event.i1.bb_20_2_mid
if event.i1.bb_20_2_upper is not None:
    f["bb_upper"] = event.i1.bb_20_2_upper
if event.i1.bb_20_2_lower is not None:
    f["bb_lower"] = event.i1.bb_20_2_lower
```

---

## Info

### IN-01: `signal_processor.py` imports `_HMM_REGIME_LABEL` with `noqa: F401` but never uses it

**File:** `src/intelligence/pipeline/signal_processor.py:27-29`

**Issue:** `_HMM_REGIME_LABEL` is imported from `feature_flattening` with a comment `# noqa: F401 — kept for any local references (none currently)`. The import exists only to avoid a linter warning about an unused import. The comment itself says there are no local references. This is a deferred-cleanup pattern that clutters the import section.

**Fix:** Remove the import. If external callers depend on `signal_processor._HMM_REGIME_LABEL`, they should import from `feature_flattening` directly.

---

### IN-02: `setup_performance_updater._compute_perf_multipliers` comment says "Inverted so best Sharpe gets lowest multiplier" but the intent is the opposite of the description

**File:** `src/intelligence/setup_performance_updater.py:16-20`

**Issue:** The module docstring comment (lines 16-20) reads:
> `Best performer: rank=n-1 → multiplier = 0.5 (LOWEST — sorts first in ascending adjusted_rank)`
> `Worst performer: rank=0 → multiplier approaches 1.5 (sorts last)`

The word "inverted" is used with "best Sharpe gets lowest multiplier" — but a lower multiplier means it sorts FIRST (wins) under ascending `adjusted_rank` sort. So the best performer wins. The word "inverted" is technically accurate (multiplier is inverted from intuition where "higher = better") but reading the comment in isolation is confusing.

**Fix:** Rewrite the comment to say explicitly: "Ascending `adjusted_rank` sort selects the MINIMUM value first. Best Sharpe → multiplier=0.5 → ranks first. Worst Sharpe → multiplier~1.5 → ranks last."

---

### IN-03: `ml_signal_training_materializer.py` passes `SIGNAL_SCHEMA_VERSION` (a text constant `"v2"`) as `$1` but the INSERT uses `$1::text` for `signal_schema_version` — harmless but misleading comment

**File:** `src/intelligence/services/ml_signal_training_materializer.py:183, 268`

**Issue:** `result = await conn.execute(sql, SIGNAL_SCHEMA_VERSION)` passes the version string `"v2"` as the `$1` bind parameter. The SQL uses `$1::text` for the `signal_schema_version` column. This is correct. The note in the SUMMARY.md says `SIGNAL_SCHEMA_VERSION` is a text constant `"v2"` (different from the integer `FEATURE_SCHEMA_VERSION = 2`). No actual bug, but the variable name at the call site is slightly misleading because the same SQL file also uses `feature_schema_version >= 2` (integer comparison) elsewhere. Worth a clarifying comment.

**Fix:** Add an inline comment at the call site: `await conn.execute(sql, SIGNAL_SCHEMA_VERSION)  # "v2" text; distinct from integer FEATURE_SCHEMA_VERSION`

---

### IN-04: `lifecycle_writer.py` uses `assert self._db is not None` and `assert self._repo is not None` in production code paths

**File:** `services/lifecycle_writer.py:171, 187`

**Issue:** `assert` statements are stripped in Python's optimized mode (`-O`/`-OO`). `_flush_exit_items` at line 171 uses `assert self._db is not None` and `_flush_batch` at line 187 uses `assert self._repo is not None`. If the service is ever run with Python `-O` flag, these guards silently disappear and the code will raise `AttributeError` or `NoneType` errors at the point of actual use rather than at the guard.

**Fix:** Replace with explicit checks:
```python
if self._db is None:
    raise RuntimeError("LifecycleWriter._db not initialized")
if self._repo is None:
    raise RuntimeError("LifecycleWriter._repo not initialized")
```

---

_Reviewed: 2026-06-02T21:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
