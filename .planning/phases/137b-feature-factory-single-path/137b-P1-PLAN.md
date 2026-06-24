---
phase: 138-feature-factory-single-path
plan: P1
type: execute
wave: 1
depends_on: []
files_modified:
  - src/intelligence/feature_factory.py
autonomous: true

must_haves:
  truths:
    - "_gap_z_series_full(opens, highs, lows, closes, period, zscore_window) exists in feature_factory.py and returns np.ndarray of same length as closes"
    - "FeatureFactory.compute() has no precomputed parameter — signature is compute(bars, symbol, tf, cache, config)"
    - "All 19 precomputed feature blocks replaced with direct _*_series_full(arrays, ...)[-1] calls"
    - "15 scalar functions deleted: _rolling_zscore, _ofi_z, _cvd_accumulate, _cvd_slope_z, _volume_z, _momentum_z, _atr_z, _amihud_illiq_z, _high_52w_dist, _ret_skew_z, _ret_acf1_z, _rolling_stat_z, _vwap_dev_sigma, _gap_z, _rsi_wilder (scalar streaming variant)"
    - "_atr_wilder kept with comment: '# Reference implementation — used in tests only.'"
    - "FeatureFactory.compute_batch() static method exists with signature matching the spec"
    - "compute_batch() calls each _*_series_full once per call, loops bars[1..n], returns list[tuple[datetime, FeatureVector]]"
    - ".venv/bin/pytest tests/unit/ -q GREEN"
  artifacts:
    - path: "src/intelligence/feature_factory.py"
      provides: "_gap_z_series_full, compute() without precomputed, compute_batch(), 15 scalar functions deleted"
      contains: "_gap_z_series_full"
  key_links:
    - from: "FeatureFactory.compute()"
      to: "_*_series_full functions"
      via: "Every series-backed feature calls _*_series_full(bounded_arrays, ...)[-1] — no conditional bypass"
      pattern: "_series_full"
    - from: "FeatureFactory.compute_batch()"
      to: "_*_series_full functions"
      via: "Calls each series function once over full array, indexes series[i] per bar — O(n) total"
      pattern: "compute_batch"
---

<objective>
Eliminate the dual-path design in FeatureFactory. The `precomputed` dict is a stringly-typed bypass
that allows batch and streaming to diverge silently. After this plan, there is only one math path:
every feature computes via its `_*_series_full` function. Streaming calls it with a bounded window
and takes `[-1]`. Batch calls it once over the full array and indexes per bar.

Three concrete changes:
1. Add `_gap_z_series_full` (the one series variant that doesn't exist yet).
2. Rewrite `compute()`: remove `precomputed` param; replace 19 conditional branches with direct
   `_*_series_full[-1]` calls; delete 15 now-dead scalar functions.
3. Add `FeatureFactory.compute_batch()`: the O(n) batch path that replaces `_precompute_series`.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@docs/plans/2026-06-23-feature-factory-single-path-refactor.md
@src/intelligence/feature_factory.py
@CLAUDE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add _gap_z_series_full</name>
  <files>src/intelligence/feature_factory.py</files>
  <read_first>
    - src/intelligence/feature_factory.py lines 660-700 (_precompute_series gap computation — this is the logic to encapsulate)
    - src/intelligence/feature_factory.py lines 438-530 (_atr_series_full and _rolling_zscore_series — signature and pattern to follow)
    - src/intelligence/feature_factory.py lines 305-320 (_gap_z scalar function — the algorithm it encapsulates)
    - docs/plans/2026-06-23-feature-factory-single-path-refactor.md (spec — Layer 1 section)
  </read_first>
  <action>
    Add `_gap_z_series_full` to feature_factory.py, immediately after `_vwap_dev_sigma_series_full`
    (which is the last series_full function before the FeatureFactory class definition).

    The function encapsulates the gap computation currently inline in `_precompute_series`
    (backfill_feature_factory.py lines ~680-700). Signature:

        def _gap_z_series_full(
            opens: np.ndarray,
            highs: np.ndarray,
            lows: np.ndarray,
            closes: np.ndarray,
            period: int,
            zscore_window: int,
        ) -> np.ndarray:

    Algorithm (extracted from `_precompute_series`):
    1. atr_core = _atr_series_full(highs, lows, closes, period)  # length = n-1
    2. atr_for_gap = atr_core[:-1]  # length = n-2; atr_for_gap[j] = ATR(j+2 bars)
    3. gap_raw = (opens[2:] - closes[1:-1]) / np.where(atr_for_gap > 1e-10, atr_for_gap, 1.0)
    4. gap_z_core = _rolling_zscore_series(np.concatenate([[0.0], gap_raw]), zscore_window)
    5. return np.concatenate([[0.0], gap_z_core])  # length = n; gap_z[i] = gap_z at bar i

    The returned array has length == len(closes), matching the convention of all other
    `_*_series_full` functions.

    Add a one-line docstring: "Gap-z series: ATR-normalized open gap, rolling z-scored."
  </action>
  <acceptance_criteria>
    - `grep -c "_gap_z_series_full" src/intelligence/feature_factory.py` returns >= 1
    - `.venv/bin/python -c "from src.intelligence.feature_factory import _gap_z_series_full; import numpy as np; arr = np.random.randn(100) + 100; r = _gap_z_series_full(arr, arr, arr, arr, 14, 20); assert len(r) == 100; print('ok')"` exits 0
    - `.venv/bin/ruff check src/intelligence/feature_factory.py` passes
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from src.intelligence.feature_factory import _gap_z_series_full; import numpy as np; r = _gap_z_series_full(np.ones(50)+100, np.ones(50)+101, np.ones(50)+99, np.ones(50)+100, 14, 20); print('length:', len(r), '  ok')"</verify>
  <done>_gap_z_series_full added to feature_factory.py; returns array of length == len(closes).</done>
</task>

<task type="auto">
  <name>Task 2: Remove precomputed from compute() and delete 15 scalar functions</name>
  <files>src/intelligence/feature_factory.py</files>
  <read_first>
    - src/intelligence/feature_factory.py lines 1045-1400 (full compute() method — all 19 precomputed branches)
    - src/intelligence/feature_factory.py lines 235-780 (all scalar streaming functions — 15 to delete)
    - docs/plans/2026-06-23-feature-factory-single-path-refactor.md (spec — Layer 2 section and Dead Code Deleted table)
  </read_first>
  <action>
    Two changes to feature_factory.py:

    **A. Rewrite compute() — 19 feature blocks.**

    Remove the `precomputed: dict | None = None` parameter from the function signature.

    For each of the 19 `if precomputed is not None and "key" in precomputed:` blocks, replace the
    entire `if / else` branch with a single direct call to the series_full equivalent.
    The bounded history window already passed to compute() provides the arrays.

    Extract numpy arrays once at the top of compute() (before feature computation starts).
    Pattern: `closes = np.array([b["close"] for b in bars], dtype=float)` etc.
    These replace the per-block inline array construction.

    Replacement mapping (left = old precomputed key, right = new direct call):
    - "atr" + "atr_z"       → atr_series = _atr_series_full(highs, lows, closes, config.adx_period)
                               atr_val = float(atr_series[-1]) if len(atr_series) > 0 else 0.0
                               atr_z_val = float(_rolling_zscore_series(np.concatenate([[0.0], atr_series]), config.momentum_zscore_window)[-1])
    - "rel_volume"           → _rel_volume_series_full(volumes, config.volume_zscore_window)[-1]
    - "gap_z"                → _gap_z_series_full(opens, highs, lows, closes, config.adx_period, config.momentum_zscore_window)[-1]
    - "ofi_z"                → _ofi_z_series_full(closes, highs, lows, volumes, config.ofi_zscore_window)[-1]
    - "cvd_slope_z"          → _cvd_slope_z_series_full(closes, volumes, config.cvd_slope_bars, config.momentum_zscore_window)[-1]
    - "volume_z"             → _volume_z_series_full(volumes, config.volume_zscore_window)[-1]
    - "momentum_z_fast"      → _momentum_z_series_full(closes, config.momentum_window_fast, config.momentum_zscore_window)[-1]
    - "momentum_z_mid"       → _momentum_z_series_full(closes, config.momentum_window_mid, config.momentum_zscore_window)[-1]
    - "momentum_z_slow"      → _momentum_z_series_full(closes, config.momentum_window_slow, config.momentum_zscore_window)[-1]
    - "momentum_reversal_z"  → _momentum_reversal_z_series_full(closes, config.momentum_zscore_window)[-1]
    - "vwap_dev_sigma"       → _vwap_dev_sigma_series_full(opens, highs, lows, closes, volumes)[-1]
    - "rsi_fast/mid/slow"    → _rsi_series_full(closes, period)[-1] for each of fast/mid/slow
    - "amihud_illiq_z"       → _amihud_illiq_z_series_full(closes, volumes, config.amihud_zscore_window)[-1]
    - "high_52w_dist"        → _high_52w_dist_series_full(closes, config.high_52w_window)[-1]
    - "ret_skew_z"           → _ret_skew_z_series_full(closes, config.ret_skew_window, config.momentum_zscore_window)[-1]
    - "ret_acf1_z"           → _ret_acf1_z_series_full(closes, config.ret_acf_lags, config.momentum_zscore_window)[-1]

    Read the existing `if precomputed` blocks carefully before replacing — each `else` branch
    shows the existing scalar implementation and the config keys it uses. Mirror the config
    attribute names exactly. Do not change the feature computation semantics.

    **B. Delete 15 scalar functions.**

    After rewriting compute(), these functions are unreachable. Delete them in full:
    - `_rolling_zscore` (lines ~235-250)
    - `_gap_z` (lines ~305-320)
    - `_ofi_z` (lines ~328-344)
    - `_cvd_accumulate` (lines ~345-365)
    - `_cvd_slope_z` (lines ~367-382)
    - `_volume_z` (lines ~383-395)
    - `_momentum_z` (lines ~402-416)
    - `_atr_z` (lines ~510-525)
    - `_vwap_dev_sigma` (lines ~553-600; the scalar version — NOT the series version)
    - `_amihud_illiq_z` (lines ~706-718; the scalar version — NOT the series version)
    - `_high_52w_dist` (lines ~720-733; the scalar version — NOT the series version)
    - `_rolling_stat_z` (lines ~735-750)
    - `_ret_skew_z` (lines ~759-766; the scalar version — NOT the series version)
    - `_ret_acf1_z` (lines ~768-775; the scalar version — NOT the series version)
    - `_rsi_wilder` is NOT in the delete list — keep it with comment "# Reference implementation — used in tests only."

    IMPORTANT: read the line numbers from the file before deleting — verify each function
    ends before the next function begins. Use grep to locate exact boundaries.
  </action>
  <acceptance_criteria>
    - `grep -c "precomputed" src/intelligence/feature_factory.py` returns 0
    - `grep -c "def _rolling_zscore\b" src/intelligence/feature_factory.py` returns 0
    - `grep -c "def _gap_z\b" src/intelligence/feature_factory.py` returns 0
    - `grep -c "def _ofi_z\b" src/intelligence/feature_factory.py` returns 0
    - `grep -c "def _cvd_accumulate\b" src/intelligence/feature_factory.py` returns 0
    - `grep -c "def _cvd_slope_z\b" src/intelligence/feature_factory.py` returns 0
    - `grep -c "def _volume_z\b" src/intelligence/feature_factory.py` returns 0
    - `grep -c "def _momentum_z\b" src/intelligence/feature_factory.py` returns 0
    - `grep -c "def _atr_z\b" src/intelligence/feature_factory.py` returns 0
    - `grep -c "def _rolling_stat_z\b" src/intelligence/feature_factory.py` returns 0
    - `grep -c "def _rsi_wilder\b" src/intelligence/feature_factory.py` returns 1 (kept)
    - `grep -c "# Reference implementation" src/intelligence/feature_factory.py` returns 1
    - `.venv/bin/python -c "import inspect; from src.intelligence.feature_factory import FeatureFactory; sig = inspect.signature(FeatureFactory.compute); assert 'precomputed' not in sig.parameters, 'precomputed still present'; print('compute signature ok:', list(sig.parameters.keys()))"` exits 0
    - `.venv/bin/pytest tests/unit/intelligence/ -q` GREEN
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from src.intelligence.feature_factory import FeatureFactory; import inspect; print(inspect.signature(FeatureFactory.compute))"</verify>
  <done>compute() has no precomputed parameter; all 19 blocks replaced with _*_series_full[-1]; 15 scalar functions deleted; _atr_wilder kept with reference comment.</done>
</task>

<task type="auto">
  <name>Task 3: Add FeatureFactory.compute_batch() static method</name>
  <files>src/intelligence/feature_factory.py</files>
  <read_first>
    - src/intelligence/feature_factory.py (FeatureFactory class definition — find end of compute() to place compute_batch() after it)
    - services/backfill_feature_factory.py lines 665-810 (_precompute_series + _compute_symbol_tf loop — compute_batch() encapsulates this logic)
    - docs/plans/2026-06-23-feature-factory-single-path-refactor.md (spec — Layer 3 section with full compute_batch internals)
    - src/intelligence/feature_cache.py (FeatureCache.refresh_regime and advance_bar signatures)
  </read_first>
  <action>
    Add `compute_batch()` as a static method of FeatureFactory, immediately after `compute()`.

    Signature:
        @staticmethod
        def compute_batch(
            bars: list[dict],
            symbol: str,
            tf: str,
            cache: FeatureCache,
            config: FeatureFactoryConfig,
            warm_up_bars: int = 0,
        ) -> list[tuple[datetime, FeatureVector]]:

    Docstring (one line): "Compute FeatureVector for every bar in bars in O(n). Returns (bar_ts, fv) pairs."

    Internal implementation:
    1. Guard: if len(bars) < 2, return [].
    2. Extract numpy arrays once: opens, highs, lows, closes, volumes from all bars.
    3. Precompute all series — call each _*_series_full once:
       - atr_series = _atr_series_full(highs, lows, closes, config.adx_period)
       - atr_padded = np.concatenate([[0.0], atr_series])  # length = n
       - atr_z_series = _rolling_zscore_series(atr_padded, config.momentum_zscore_window)
       - gap_z_series = _gap_z_series_full(opens, highs, lows, closes, config.adx_period, config.momentum_zscore_window)
       - rel_volume_series = _rel_volume_series_full(volumes, config.volume_zscore_window)
       - ofi_z_series = _ofi_z_series_full(closes, highs, lows, volumes, config.ofi_zscore_window)
       - cvd_slope_z_series = _cvd_slope_z_series_full(closes, volumes, config.cvd_slope_bars, config.momentum_zscore_window)
       - volume_z_series = _volume_z_series_full(volumes, config.volume_zscore_window)
       - momentum_z_fast_series = _momentum_z_series_full(closes, config.momentum_window_fast, config.momentum_zscore_window)
       - momentum_z_mid_series = _momentum_z_series_full(closes, config.momentum_window_mid, config.momentum_zscore_window)
       - momentum_z_slow_series = _momentum_z_series_full(closes, config.momentum_window_slow, config.momentum_zscore_window)
       - momentum_reversal_z_series = _momentum_reversal_z_series_full(closes, config.momentum_zscore_window)
       - vwap_dev_sigma_series = _vwap_dev_sigma_series_full(opens, highs, lows, closes, volumes)
       - rsi_fast_series = _rsi_series_full(closes, config.rsi_fast_period)
       - rsi_mid_series = _rsi_series_full(closes, config.rsi_mid_period)
       - rsi_slow_series = _rsi_series_full(closes, config.rsi_slow_period)
       - amihud_illiq_z_series = _amihud_illiq_z_series_full(closes, volumes, config.amihud_zscore_window)
       - high_52w_dist_series = _high_52w_dist_series_full(closes, config.high_52w_window)
       - ret_skew_z_series = _ret_skew_z_series_full(closes, config.ret_skew_window, config.momentum_zscore_window)
       - ret_acf1_z_series = _ret_acf1_z_series_full(closes, config.ret_acf_lags, config.momentum_zscore_window)
    4. MIN_WINDOW = 50 (local constant, not APR — covers non-series features: cci_slow=40, aroon_slow=26,
       vol_ratio=21, cmf=20, range_position=20).
    5. results: list[tuple[datetime, FeatureVector]] = []
    6. Loop i in range(1, len(bars)):
       a. Periodically refresh regime:
          if i % config.regime_cache_refresh_bars == 0:
              window_start = max(0, i - MIN_WINDOW)
              cache.refresh_regime(bars[window_start:i+1], config)
       b. Skip warm-up:
          if i < warm_up_bars:
              cache.advance_bar(bar_ts, hi, lo, cl, vol)
              continue
       c. Build bounded window for non-series features:
          window_start = max(0, i - MIN_WINDOW)
          window = bars[window_start:i+1]
       d. Call compute() on the bounded window (non-series features — cmf, cci, aroon, vol_ratio,
          range_position, bar_close_pos, informed_flow — are computed inside compute()).
          But instead of calling the full compute(), build the FeatureVector by:
          - Getting series-backed values from series[i] (already computed above)
          - Getting non-series values by calling compute(window, symbol, tf, cache, config)
          NOTE: compute() on the bounded window is the correct approach — it handles all
          cache reads, calendar features, session features, CTF features, and the non-series
          features in one call. The performance win comes from NOT calling _*_series_full
          inside that compute() call (they're already computed). But since compute() now
          always calls _*_series_full, compute_batch() cannot reuse compute() as-is.

          CORRECT IMPLEMENTATION: Do NOT call compute() inside the loop.
          Instead, build the FeatureVector directly using the precomputed series values and
          calling ONLY the non-series scalar paths for cmf, cci x3, aroon x2, vol_ratio,
          range_position, bar_close_pos, informed_flow. Read compute() to find these
          scalar computations (they don't have series_full equivalents) and replicate them.
          For cache-backed features (hmm, hurst, garch, vix_z, ctf, session), read them
          from the cache object directly as compute() does.

          Read compute() carefully to find all non-series feature computations and cache reads.
          Replicate them in the loop body. This is the only correct approach — calling compute()
          in the loop would undo the O(n) precompute benefit.
       e. bar_ts = bars[i]["ts"]
       f. cache.advance_bar(bar_ts, bars[i]["high"], bars[i]["low"], bars[i]["close"], bars[i]["volume"])
       g. results.append((bar_ts, fv))
    7. return results
  </action>
  <acceptance_criteria>
    - `grep -c "def compute_batch" src/intelligence/feature_factory.py` returns 1
    - `.venv/bin/python -c "import inspect; from src.intelligence.feature_factory import FeatureFactory; sig = inspect.signature(FeatureFactory.compute_batch); params = list(sig.parameters.keys()); assert params == ['bars','symbol','tf','cache','config','warm_up_bars'], f'wrong params: {params}'; print('compute_batch signature ok')"` exits 0
    - `.venv/bin/python -c "
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
from src.intelligence.feature_cache import FeatureCache
import datetime, math

# Build 100 minimal bars
bars = [{'open': 100+i*0.01, 'high': 101+i*0.01, 'low': 99+i*0.01, 'close': 100+i*0.01, 'volume': 1000+i, 'ts': datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(minutes=i)} for i in range(100)]
cfg = FeatureFactoryConfig()
cache = FeatureCache()
results = FeatureFactory.compute_batch(bars, 'SPY', '5m', cache, cfg, warm_up_bars=0)
assert len(results) == 99, f'expected 99, got {len(results)}'
bar_ts, fv = results[0]
assert hasattr(fv, 'momentum_z_fast'), 'FeatureVector missing momentum_z_fast'
assert math.isfinite(fv.momentum_z_fast), 'momentum_z_fast not finite'
print('compute_batch smoke test: ok, N results =', len(results))
"` exits 0
    - `.venv/bin/pytest tests/unit/intelligence/ -q` GREEN
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from src.intelligence.feature_factory import FeatureFactory; print(FeatureFactory.compute_batch.__doc__)"</verify>
  <done>FeatureFactory.compute_batch() implemented; precomputes all 19 series once; loops bars building FeatureVector from series[i] + non-series scalar calls + cache reads; returns list[(bar_ts, FeatureVector)].</done>
</task>

</tasks>

<verification>
- _gap_z_series_full exists, returns ndarray of length == len(closes)
- compute() signature: (bars, symbol, tf, cache, config) — no precomputed
- All 19 precomputed branches replaced with _*_series_full[-1] calls
- 15 scalar functions deleted; _atr_wilder kept with reference comment
- compute_batch() static method exists with correct signature
- compute_batch() smoke test passes: 100 bars -> 99 (bar_ts, FeatureVector) pairs, all finite
- .venv/bin/pytest tests/unit/intelligence/ -q GREEN
</verification>

<success_criteria>
- All 3 task acceptance criteria pass
- .venv/bin/pytest tests/unit/ -q GREEN
- .venv/bin/ruff check src/intelligence/feature_factory.py passes
</success_criteria>

<output>
After completion, create `.planning/phases/137b-feature-factory-single-path/137b-P1-SUMMARY.md` documenting:
- Functions added: _gap_z_series_full
- Functions deleted (15 scalar functions)
- compute() parameter removed: precomputed
- compute_batch() added
- Test results
</output>
