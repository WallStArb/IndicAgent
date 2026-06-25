---
title: Feature Factory Batch — Five Deferred Correctness & Architecture Issues
created: 2026-06-24
source: /simplify review of Phase 139 batch path changes
priority: high
---

# Context

During the Phase 139 P1/P2 implementation of `backfill_feature_factory.py`,
`feature_cache.py`, and `feature_factory.py`, the simplify review identified five
issues that were deferred as "out of scope." They are not out of scope. At Renaissance,
these categories of issue — quadratic work in a data pipeline, duplicated algorithm
implementations, misaligned parallel structures, silent data overwrites, and APR
violations — are treated as integrity failures, not style notes. A system that computes
wrong answers silently or degrades quadratically as the corpus grows fails the prime
directive: data quality over model complexity.

Each issue is documented below with the affected code, the failure mode, and the
minimum-correct fix. All five must be addressed before Phase 139 P3 (corpus scoring run)
executes — because P3 writes the training corpus that feeds IC discovery and IC scores.
Wrong values baked into `feature_vectors` at corpus-scale cannot be efficiently
retroactively corrected.

---

## Issue 1 — O(D×N) reprocessing in `update_cross_asset` / `_build_cross_asset_series`

**File:** `services/backfill_feature_factory.py:232-246` and
`src/intelligence/feature_cache.py:194-237` (the `update_cross_asset` method)

**Failure mode:** `_build_cross_asset_series` calls `cache.update_cross_asset(spy_bars[:spy_end], ...)` once per trading date D. Each call re-materializes the full growing bar slice as a numpy array (`np.array([b["close"] for b in spy_bars])`) and re-computes `np.diff`, `np.log`, `np.std` over the entire prefix. This is O(D×N) total — approximately 1250 × 625 = ~780k close reads, log calls, and standard deviations for a 5-year daily series. At 58 symbols this is the dominant cost of the corpus run.

**Why it is wrong by Renaissance standards:** The `FeatureCache` already stores `_spy_realized_vol_history` as a `deque` — an append-only incremental structure. The entire purpose of that deque is to avoid reprocessing history. The current code ignores it for `_build_cross_asset_series` by passing full slices on every call, converting deque-based O(1) amortized updates into O(N) per-date work.

**Root cause:** `update_cross_asset` accepts full bar lists (`list[dict]`) and re-derives everything from them. It was designed for the live-path "call once with current full history" use case, not for the incremental batch case.

**Minimum correct fix:**

Add an incremental API alongside the existing full-history one:

```python
# src/intelligence/feature_cache.py
def update_cross_asset_bar(
    self,
    spy_bar: dict,
    tlt_bar: dict,
    shy_bar: dict,
    config: FeatureFactoryConfig,
) -> None:
    """Append one new bar per symbol; update vix_z, flight_quality, yield_slope_z incrementally."""
    # vix_z: append one realized vol sample to deque — O(1)
    # flight_quality: two consecutive bars sufficient — O(1)
    # yield_slope_z: append one log-return ratio to deque — O(1)
```

Then `_build_cross_asset_series` iterates dates once and calls `update_cross_asset_bar`
with the single new bar at each date, advancing `spy_end`/`tlt_end`/`shy_end` by 1 rather
than re-slicing. The result dict is built from the cache state after each single-bar update.

**Note on `flight_quality`:** The current implementation computes TLT/SPY relative return over
`n = min(len(tlt_bars), len(spy_bars))` bars — re-reading the entire history each call. This
is also O(N) per date. The incremental path only needs to store the previous bar's close for each
symbol, making the update O(1).

**Verification:** corpus run wall-clock time on 58 symbols; `perf stat` on the batch process
before and after.

---

## Issue 2 — Two implementations of Wilder RSI that will diverge

**Files:** `src/intelligence/feature_cache.py:245-261` (`_rsi_simple`) and
`services/backfill_feature_factory.py:268-284` (`_build_ctf_series` inline RSI loop)

**Failure mode:** `_rsi_simple` computes a single terminal RSI scalar. `_build_ctf_series`
inlines the identical Wilder smoothing loop to build a per-bar RSI array. Both implement the
same algorithm with the same `alpha = 1/period` EWMA. They are currently identical. They will
diverge the moment a numerical edge case is found and fixed in one place — the other
silently produces different values. IC scores computed from batch features will then differ
from live-path features at the margin.

**Why it is wrong by Renaissance standards:** One algorithm, one implementation. Duplicated
finance math is a data integrity violation because fix propagation is never guaranteed. The
batch corpus and the live pipeline must produce byte-identical feature values for the same
inputs — anything less poisons the IC measurement.

**Minimum correct fix:**

Promote `_rsi_simple` to emit a per-bar series, and make the scalar version a thin wrapper:

```python
# src/intelligence/feature_cache.py

def _wilder_rsi_series(closes: np.ndarray, period: int) -> np.ndarray:
    """Wilder RSI for every bar index. Returns array of length len(closes).
    Values before period+1 bars are 50.0 (cold start neutral).
    """
    n = len(closes)
    out = np.full(n, 50.0, dtype=float)
    if n < period + 1:
        return out
    deltas = np.diff(closes.astype(float))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    alpha = 1.0 / period
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(gains)):
        avg_gain = alpha * float(gains[i]) + (1.0 - alpha) * avg_gain
        avg_loss = alpha * float(losses[i]) + (1.0 - alpha) * avg_loss
        rsi = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss) if avg_loss > 1e-10 else (100.0 if avg_gain > 0 else 50.0)
        out[i + 1] = float(np.clip(rsi, 0.0, 100.0))
    return out


def _rsi_simple(closes: np.ndarray, period: int) -> float:
    """Terminal Wilder RSI scalar. Thin wrapper over _wilder_rsi_series."""
    return float(_wilder_rsi_series(closes, period)[-1])
```

Then `_build_ctf_series` replaces its inline loop:

```python
rsi_series = _wilder_rsi_series(closes, period)
ctf_mom = np.clip((rsi_series - 50.0) / 50.0, -1.0, 1.0)
# (no per-bar loop needed)
```

This eliminates the duplicate and makes the batch vectorized (no Python loop for RSI).

---

## Issue 3 — Three parallel date lists with silent misalignment risk

**File:** `services/backfill_feature_factory.py:224-246`

**Failure mode:** `spy_dates`, `tlt_dates`, `shy_dates` are three independent lists built
with the same comprehension pattern, then used in lock-step with parallel `bisect_right`
calls. If any future refactor filters one list (e.g., drops weekends for one symbol, applies
a date-range filter, or reorders for a different query sort), the three indexes become
misaligned silently. The bisect would return a wrong end index and `cache.update_cross_asset`
would receive a slice that ends at the wrong bar — introducing look-ahead bias without any
error or log message.

**Why it is wrong by Renaissance standards:** Parallel lists keyed by the same implicit index
are banned at Renaissance-grade systems because the invariant (all three lists share the same
index space) is enforced only by convention, not by the type system or data structure. Look-ahead
bias introduced silently is the worst category of data error in an IC pipeline.

**Minimum correct fix:**

Use a single aligned structure:

```python
# In _build_cross_asset_series (after Issue 1 incremental refactor):
# Each symbol's bars stay in their own list but are accessed via a shared cursor dict.

symbol_bars = {
    "spy": spy_bars,
    "tlt": tlt_bars,
    "shy": shy_bars,
}
symbol_dates = {k: [b["ts"].date() for b in v] for k, v in symbol_bars.items()}
# cursor[symbol] is the current bisect end index — advanced uniformly per date.
```

Or, if the full-history slice API is retained, build a single `dict[date, dict[str, dict]]`
that aligns all three symbols by date before any loop, making misalignment structurally impossible.

---

## Issue 4 — Post-injection altitude: `FeatureFactory.compute_batch` populates 7 fields that the caller overwrites

**Files:** `src/intelligence/feature_factory.py` (compute_batch loop, lines ~1370-1410) and
`services/backfill_feature_factory.py:828-840` (the `dataclasses.replace` injection)

**Failure mode:** `compute_batch` builds a complete `FeatureVector` reading
`cache.vix_z`, `cache.flight_quality`, `cache.yield_slope_z`, `cache.ctf_momentum`,
`cache.ctf_vwap_align`, `cache.ctf_regime_align`, `cache.poc_dist_atr`, `cache.va_position`,
`cache.sr_support_dist`, `cache.sr_resist_dist` from the cache. In the batch path, the cache
holds zeros for all 10 of these (the cache was never populated with correct values for each
historical bar). The backfill service then silently replaces them via `dataclasses.replace`.

The critical failure mode: **any future consumer of `compute_batch` that does not apply the
injection receives feature vectors with zeros in 10 fields, with no error, no warning, and no
way to detect the problem.** IC scores computed on those features will be biased toward zero on
all cross-asset and CTF dimensions — exactly the fields that carry macro regime signal.

**Why it is wrong by Renaissance standards:** Silent wrong answers are worse than loud crashes
(CLAUDE.md design mindset). The batch service is patching factory output — it has assumed
responsibility for correctness that belongs in the factory. This creates a hidden contract
between caller and factory that is not expressed in the API signature.

**Minimum correct fix:**

Extend `compute_batch` to accept optional external snapshots:

```python
@staticmethod
def compute_batch(
    bars: list[dict],
    symbol: str,
    tf: str,
    cache: FeatureCache,
    config: FeatureFactoryConfig,
    warm_up_bars: int = 252,
    cross_asset_by_date: dict | None = None,      # date → (vix_z, flight_quality, yield_slope_z)
    ctf_by_ts: dict | None = None,                # ts → (ctf_momentum, ctf_vwap_align, ctf_regime_align)
    ctf_ts_list: list | None = None,              # sorted keys for bisect lookup
) -> list[tuple[datetime, FeatureVector]]:
```

Inside the per-bar loop, when `cross_asset_by_date` is provided, read from it instead of
from `cache`. Same for `ctf_by_ts`. The factory owns the complete FeatureVector construction;
the service passes in pre-computed externals and trusts the factory to apply them correctly.

VP/SR fields (`poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist`) remain
`None` in batch path — document this explicitly in the signature docstring as a known
limitation requiring I3 intraday injection unavailable in batch.

**Migration path:** add the optional parameters with `None` defaults; existing callers
(live path) continue to pass `None` and use cache. Batch caller passes the snapshots.
The `dataclasses.replace` block in `_compute_symbol_tf` is then deleted.

---

## Issue 5 — `MIN_WINDOW = 50` APR violation in `compute_batch`

**File:** `src/intelligence/feature_factory.py:1246`

**Code:**
```python
# MIN_WINDOW for non-series features (cci_slow=40, aroon_slow=26, vol_ratio=21, cmf=20, range_position=20)
MIN_WINDOW = 50
```

**Failure mode:** This is a hardcoded constant that controls the bar window for CCI, Aroon,
vol_ratio, CMF, and range_position. Per CLAUDE.md: "Module-level constants and inline magic
numbers are architecture violations." The comment even lists the config-backed values it is
derived from — confirming the correct derivation is known but not applied.

If any of `cci_slow_period`, `aroon_slow_period`, `vol_long_bars`, `cmf_period` is tuned
via APR, `MIN_WINDOW` does not update — features are computed over a window that no longer
matches the operator's intent. No error is raised; features silently use stale window size.

**Why it is wrong by Renaissance standards:** APR exists precisely to ensure that all tunable
numeric values are operator-visible and change-tracked. A constant that overrides APR-backed
parameters without being itself APR-backed is an architecture violation that will cause
silent miscalculation when parameters are tuned in production.

**Minimum correct fix:**

No new APR key is needed. Derive from existing config:

```python
# In compute_batch, replace the constant with a derived value:
MIN_WINDOW = max(
    config.cci_slow_period,
    config.aroon_slow_period,
    config.vol_long_bars,
    config.cmf_period,
    config.range_position_window,  # verify APR key name
)
```

This is purely mechanical — all referenced config values are already APR-backed. The window
self-updates when any constituent is tuned. The current value of 50 is already the correct
maximum (cci_slow=40 per APR), so no recomputation of existing vectors is required.

---

## Execution Order

These must be addressed in this order to avoid inter-dependencies:

1. **Issue 5** (MIN_WINDOW) — trivial, no API surface change, no test impact
2. **Issue 2** (`_wilder_rsi_series`) — adds the shared helper; batch RSI loop becomes vectorized
3. **Issue 3** (parallel lists) — structural fix inside `_build_cross_asset_series`
4. **Issue 4** (compute_batch API) — add optional params; delete post-injection in service
5. **Issue 1** (O(D×N)) — incremental `update_cross_asset_bar`; depends on Issue 3 structure

All five can be executed as a single phase plan (one plan, one commit) before Phase 139 P3
is run. P3 must not execute until Issue 4 is resolved — the post-injection pattern is fragile
enough that a refactor during P3 execution would corrupt the training corpus mid-run.

---

---

## Issue 6 — `FeatureFactory.compute()` elimination (deferred — separate phase, pre-Phase-140)

**Files:** `src/intelligence/feature_factory.py`, `services/feature_vector_pipeline.py`

**The violation:** `FeatureFactory.compute()` and `FeatureFactory.compute_batch()` are two complete, independent implementations of identical financial math — every series helper (`_rsi_series_full`, `_atr_series_full`, `_momentum_z_series_full`, etc.) is called from both. A numerical fix in one path silently misses the other. IC scores computed from batch backfill can diverge from live-path scores on the same bar. This is a first-order data integrity violation.

**Why deferred:** The live pipeline (`feature_vector_pipeline.py`) calls `compute()` with a persistent `FeatureCache` that is advanced incrementally between bars (`cache.advance_bar` inside the loop). Making `compute()` a wrapper over `compute_batch()` requires solving cache advancement semantics: `compute_batch()` advances the cache for every bar in its input, so calling it with the full bar history on every live bar would advance the cache `len(bars)` times per bar, corrupting weekly VWAP accumulation and HMM duration counts. This cannot be fixed in the same session as a corpus backfill without risking live pipeline regressions.

**The correct fix (when scoped):**

1. Redesign cache advancement to be idempotent or position-aware — the cache tracks its own `last_advanced_bar_ts` and `advance_bar` skips already-processed bars.
2. `compute()` becomes: `FeatureFactory.compute_batch(bars, ..., warm_up_bars=len(bars)-1)[-1]`
3. Alternatively: extract the series-computation kernel into a shared `_compute_series(bars, config)` that both `compute()` and `compute_batch()` call — so the math is unified without changing cache advancement semantics.
4. Delete `compute()` once the live pipeline is verified to produce identical results via `compute_batch()`.

**Gate before starting:** Issue 4 from this todo must be complete (compute_batch owns state injection). Then benchmark `compute_batch()` on the live path's bounded bar history (typically 500 bars) to confirm O(n) vectorized ops are fast enough for sub-10ms per-bar latency.

**Verification:** `test_feature_factory_batch_parity.py` — extend to cover all series helpers; confirm `compute()` and `compute_batch()[-1]` produce values within 1e-10 for the same inputs before `compute()` is deleted.

---

## Related Refinements (same session)

- **`_build_ctf_series` vectorized RSI** (from Issue 2): eliminating the Python RSI loop
  makes `_build_ctf_series` fully vectorized. Benchmark before/after for 5-year 5m series.
- **`flight_quality` O(N) → O(1) incremental** (from Issue 1): store `_spy_prev_close` and
  `_tlt_prev_close` in `FeatureCache`; single-bar update replaces the rolling-window re-read.
- **`update_cross_asset` deprecation path**: once `update_cross_asset_bar` exists, the
  full-history method should be marked for removal after the live-path wiring is confirmed.
  The two-API situation creates the same divergence risk as Issue 2.
- **Verify `_hmm_forward_step` mutates in-place**: `obs_buf` pre-allocation (applied in this
  session) assumes `_hmm_forward_step` does not retain a reference to the passed array.
  Confirm with a read of `_hmm_forward_step` in `feature_cache.py` — if it stores `obs`,
  the pre-alloc fix silently corrupts state.
