# 010 — Feature Factory Technical Debt (Remainder)

**Priority: Low — Issues 1-5 shipped in Phase 139. Issue 0 is a quick standalone win. Issue 6 is a separate phase (gates 004 Part B).**

---

## Issue 0 — Replace scipy.stats.skew with numpy rolling skewness (quick win)

**File:** `src/intelligence/feature_factory.py` — `_skewness()` / `_rolling_stat_z()`

**Failure mode:** `_rolling_stat_z` calls `scipy.stats.skew` 2000 times per `compute()`
call (once per bar in the rolling window). Scipy's `axis_nan_policy_wrapper` +
`inspect.getfullargspec` overhead dominates: 2.5s of 3.0s total per call at 2000-bar window.

**Fix:**
```python
def _skewness(arr: np.ndarray) -> float:
    n = len(arr)
    if n < 3:
        return 0.0
    mean = arr.mean()
    std = arr.std()
    if std < 1e-10:
        return 0.0
    return float(np.mean(((arr - mean) / std) ** 3))
```

Expected speedup: 260ms → ~40ms per `compute()` call (6-7x) at 2000-bar window.
Drop scipy import if no other users remain in feature_factory.py.
Also check `ret_acf1_z` for similar scipy usage.

---

## Issue 1 — O(D×N) reprocessing in `update_cross_asset` / `_build_cross_asset_series`

**File:** `services/backfill_feature_factory.py:232-246` and
`src/intelligence/feature_cache.py:194-237` (`update_cross_asset`)

**Failure mode:** `_build_cross_asset_series` calls `cache.update_cross_asset(spy_bars[:spy_end], ...)`
once per trading date D. Each call re-materializes the full growing bar slice as a numpy
array and re-computes `np.diff`, `np.log`, `np.std` over the entire prefix. This is
O(D×N) total — ~780k close reads for a 5-year daily series. At 58 symbols this
dominates corpus run time.

The `FeatureCache` already stores `_spy_realized_vol_history` as a `deque`. The entire
purpose is to avoid reprocessing history. The current code ignores it by passing full
slices on every call.

**Fix:** Add an incremental API:
```python
def update_cross_asset_bar(self, spy_bar, tlt_bar, shy_bar, config) -> None:
    # vix_z: append one realized vol sample to deque — O(1)
    # flight_quality: two consecutive bars sufficient — O(1)
    # yield_slope_z: append one log-return ratio to deque — O(1)
```

`_build_cross_asset_series` iterates dates once and calls `update_cross_asset_bar`
with the single new bar, advancing cursors by 1 rather than re-slicing.

---

## Issue 2 — Two implementations of Wilder RSI that will diverge

**Files:** `src/intelligence/feature_cache.py:245-261` (`_rsi_simple`) and
`services/backfill_feature_factory.py:268-284` (`_build_ctf_series` inline RSI loop)

**Failure mode:** Same algorithm, two implementations. They are currently identical.
They will diverge the moment a numerical edge case is found and fixed in one place.

**Fix:** Promote to a shared series function:
```python
def _wilder_rsi_series(closes: np.ndarray, period: int) -> np.ndarray:
    """Wilder RSI for every bar. Values before period+1 bars are 50.0."""
    ...

def _rsi_simple(closes: np.ndarray, period: int) -> float:
    return float(_wilder_rsi_series(closes, period)[-1])
```

`_build_ctf_series` replaces its inline loop with `_wilder_rsi_series`. Also makes
`_build_ctf_series` fully vectorized — no Python RSI loop per bar.

---

## Issue 3 — Three parallel date lists with silent misalignment risk

**File:** `services/backfill_feature_factory.py:224-246`

**Failure mode:** `spy_dates`, `tlt_dates`, `shy_dates` are three independent lists
used in lock-step. If any future refactor filters one list, the three indexes become
misaligned silently — introducing look-ahead bias without any error or log message.

**Fix:** Single aligned structure:
```python
symbol_bars = {"spy": spy_bars, "tlt": tlt_bars, "shy": shy_bars}
symbol_dates = {k: [b["ts"].date() for b in v] for k, v in symbol_bars.items()}
```

Or build a single `dict[date, dict[str, dict]]` aligning all three by date before any
loop — making misalignment structurally impossible.

---

## Issue 4 — `compute_batch` populates 10 fields that the caller overwrites (post-injection altitude)

**Files:** `src/intelligence/feature_factory.py` (compute_batch) and
`services/backfill_feature_factory.py:828-840` (`dataclasses.replace` injection)

**Failure mode:** `compute_batch` builds a complete `FeatureVector` from cache, which
holds zeros for 10 cross-asset/CTF fields in batch path. The service then silently
replaces them via `dataclasses.replace`. Any future consumer of `compute_batch` that
does not apply the injection receives vectors with zeros in 10 fields — no error, no
warning. Silent wrong answer.

**Fix:** Extend `compute_batch` to accept optional external snapshots:
```python
def compute_batch(
    bars, symbol, tf, cache, config,
    warm_up_bars=252,
    cross_asset_by_date=None,  # date → (vix_z, flight_quality, yield_slope_z)
    ctf_by_ts=None,            # ts → (ctf_momentum, ctf_vwap_align, ctf_regime_align)
    ctf_ts_list=None,
) -> list[tuple[datetime, FeatureVector]]:
```

Inside the per-bar loop, read from external snapshots when provided. The service
passes snapshots and deletes the `dataclasses.replace` block.

---

## Issue 5 — `MIN_WINDOW = 50` APR violation in `compute_batch`

**File:** `src/intelligence/feature_factory.py:1246`

**Failure mode:** Hardcoded constant controlling bar window for CCI, Aroon, vol_ratio,
CMF, range_position. If any constituent APR-backed period is tuned, `MIN_WINDOW` does
not update. Features silently use stale window size.

**Fix:** Derive from existing config:
```python
MIN_WINDOW = max(
    config.cci_slow_period,
    config.aroon_slow_period,
    config.vol_long_bars,
    config.cmf_period,
    config.range_position_window,
)
```

Current value of 50 is already the correct max — no recomputation of existing vectors
required.

---

## Execution Order

1. Issue 5 (MIN_WINDOW) — trivial, no API surface change
2. Issue 2 (`_wilder_rsi_series`) — adds shared helper; batch RSI vectorized
3. Issue 3 (parallel lists) — structural fix inside `_build_cross_asset_series`
4. Issue 4 (compute_batch API) — add optional params; delete post-injection in service
5. Issue 1 (O(D×N)) — incremental `update_cross_asset_bar`; depends on Issue 3
6. Issue 0 (scipy.stats.skew) — independent, can ship first or last

Issue 4 must be resolved before P3 executes — the post-injection pattern is fragile
enough that a refactor during P3 mid-run would corrupt the training corpus.

---

## Issue 6 — `compute()` elimination (deferred — separate phase, pre-Phase-140)

`compute()` and `compute_batch()` are two complete, independent implementations of
identical financial math. A numerical fix in one path silently misses the other.

Deferred because: the live pipeline calls `compute()` with a persistent `FeatureCache`
advanced incrementally between bars. Making `compute()` a wrapper over `compute_batch()`
requires solving cache advancement semantics without risking live pipeline regressions.

**Fix when scoped:** redesign cache advancement to be idempotent or position-aware, then
`compute()` becomes `compute_batch(bars, ..., warm_up_bars=len(bars)-1)[-1]`.
Gate: Issue 4 complete, benchmark confirms sub-10ms per-bar latency.
