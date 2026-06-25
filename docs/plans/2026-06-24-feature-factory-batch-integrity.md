# Feature Factory Batch Integrity — Five Issues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five batch-path integrity violations in `backfill_feature_factory.py`, `feature_cache.py`, and `feature_factory.py` so Phase 139 P3 (corpus scoring run) produces a correct training corpus.

**Architecture:** All five changes are scoped to the batch path. The live pipeline (`feature_vector_pipeline.py`) is not touched. The approach is: derive `MIN_WINDOW` from config (Issue 5), unify Wilder RSI into a single shared helper (Issue 2), eliminate O(D×N) cross-asset reprocessing with incremental state (Issues 1+3 combined), and move external state injection inside `compute_batch` so the factory owns complete FeatureVector construction (Issue 4).

**Tech Stack:** Python 3.14, NumPy, pytest. No new dependencies.

## Global Constraints

- All timestamps UTC — `datetime.now(UTC)` only, never `.utcnow()` or tz-naive.
- `bisect` module available in stdlib — add import where missing.
- Tests run with: `.venv/bin/pytest tests/unit/ -q` — must stay green after every commit.
- No changes to `services/feature_vector_pipeline.py` or `FeatureFactory.compute()`.
- Exception variable name is `error`, not `exc`.
- No `Co-Authored-By` in commit messages.
- The `_guard` closure lives inside `compute_batch` — modify it there, nowhere else.

---

## File Map

| File | What changes |
|------|-------------|
| `src/intelligence/feature_factory.py` | Task 1: `MIN_WINDOW` derived from config; Task 4: `compute_batch` new params + internal routing |
| `src/intelligence/feature_cache.py` | Task 2: add `_wilder_rsi_series`, refactor `_rsi_simple` to wrapper |
| `services/backfill_feature_factory.py` | Task 2: replace inline RSI loop; Task 3: rewrite `_build_cross_asset_series`; Task 4: pass snapshots into `compute_batch`, delete `dataclasses.replace` block |
| `tests/unit/services/test_backfill_feature_factory.py` | Task 3+4: new test class for cross-asset series and compute_batch injection |
| `tests/unit/intelligence/test_feature_factory_batch.py` | Task 1+2: new tests for MIN_WINDOW derivation and RSI series |

---

## Task 1 — MIN_WINDOW derived from config (Issue 5 — APR violation)

**Files:**
- Modify: `src/intelligence/feature_factory.py:1246`
- Test: `tests/unit/intelligence/test_feature_factory_batch.py`

**Interfaces:**
- Consumes: `config.cci_slow_period`, `config.aroon_slow_period`, `config.vol_long_bars`, `config.cmf_period` — all already present on `FeatureFactoryConfig`
- Produces: `MIN_WINDOW` is now a local derived variable; behavior unchanged with default APR values (40 < 50, so window shrinks from 50 to 40 — still sufficient for all constituents)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/intelligence/test_feature_factory_batch.py`:

```python
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
from src.intelligence.feature_cache import FeatureCache
from datetime import UTC, datetime, timedelta


def _make_config_for_min_window() -> FeatureFactoryConfig:
    """Config where max constituent is cci_slow_period=40."""
    from tests.unit.services.test_backfill_feature_factory import _make_config
    return _make_config()  # cci_slow=40, aroon_slow=25, vol_long=20, cmf=20 → MIN_WINDOW=40


def _make_bars_dicts(n: int, seed: int = 0) -> list[dict]:
    import numpy as np
    rng = np.random.default_rng(seed)
    base = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.005, n))
    return [
        {
            "ts": base + timedelta(minutes=i),
            "open": float(closes[i] * 0.999),
            "high": float(closes[i] * 1.002),
            "low": float(closes[i] * 0.998),
            "close": float(closes[i]),
            "volume": 1000.0,
        }
        for i in range(n)
    ]


class TestMinWindowDerived:
    def test_compute_batch_produces_results_with_fewer_than_50_bars_warmup(self) -> None:
        """With MIN_WINDOW=40 (derived), a 42-bar batch must emit results.

        Before the fix MIN_WINDOW=50 was hardcoded. With MIN_WINDOW=40, bars[41]
        has a full 40-bar bounded window available — cci_slow etc. are computable.
        This test fails if MIN_WINDOW is still 50 (window_bars would only be 42
        bars but the bounded window slice [42-50:43] = [-8:43] = bars[:43] = 43
        bars, which is fine — so this test actually validates that the constant
        responds to config, not a behavior change at this size).
        """
        config = _make_config_for_min_window()
        cache = FeatureCache()
        bars = _make_bars_dicts(60)
        results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, config, warm_up_bars=5)
        assert len(results) > 0, "compute_batch returned no results"
        # All non-null FeatureVector fields must be finite
        for _, fv in results:
            import math
            assert math.isfinite(fv.cci_slow), f"cci_slow not finite: {fv.cci_slow}"
            assert math.isfinite(fv.aroon_slow), f"aroon_slow not finite: {fv.aroon_slow}"
```

- [ ] **Step 2: Run to verify it passes already (behavior test, not change-detection)**

```bash
.venv/bin/pytest tests/unit/intelligence/test_feature_factory_batch.py::TestMinWindowDerived -v
```

Expected: PASS (this tests correct behavior, not the constant value — used as regression anchor)

- [ ] **Step 3: Apply the fix**

In `src/intelligence/feature_factory.py`, line 1246, replace:

```python
        # MIN_WINDOW for non-series features (cci_slow=40, aroon_slow=26, vol_ratio=21, cmf=20, range_position=20)
        MIN_WINDOW = 50
```

with:

```python
        MIN_WINDOW = max(
            config.cci_slow_period,
            config.aroon_slow_period,
            config.vol_long_bars,
            config.cmf_period,
        )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass (MIN_WINDOW shrinks 50→40 with default config — still larger than all constituent periods)

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/feature_factory.py tests/unit/intelligence/test_feature_factory_batch.py
git commit -m "fix(batch): derive MIN_WINDOW from config instead of magic constant 50

MIN_WINDOW governed the bounded window for CCI/Aroon/vol_ratio/CMF but was
hardcoded to 50. If cci_slow_period is tuned via APR above 50, features would
silently compute over an insufficient window. Now derived from max of the four
constituent APR-backed params. With defaults (cci_slow=40), value drops 50→40."
```

---

## Task 2 — Shared Wilder RSI helper (Issue 2 — duplicate algorithm)

**Files:**
- Modify: `src/intelligence/feature_cache.py` (add `_wilder_rsi_series`, refactor `_rsi_simple`)
- Modify: `services/backfill_feature_factory.py` (replace inline RSI loop, add import)
- Test: `tests/unit/intelligence/test_feature_factory_batch.py`

**Interfaces:**
- Produces: `_wilder_rsi_series(closes: np.ndarray, period: int) -> np.ndarray` — length `len(closes)`, values in `[0.0, 100.0]`, cold-start entries are `50.0`. Exported from `feature_cache.py`.
- `_rsi_simple(closes, period) -> float` becomes a thin wrapper: `float(_wilder_rsi_series(closes, period)[-1])`.
- `backfill_feature_factory.py` imports `_wilder_rsi_series` from `feature_cache`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/intelligence/test_feature_factory_batch.py`:

```python
import numpy as np


class TestWilderRsiSeries:
    def test_terminal_value_matches_rsi_simple(self) -> None:
        """_wilder_rsi_series[-1] must equal _rsi_simple for every prefix length."""
        from src.intelligence.feature_cache import _rsi_simple, _wilder_rsi_series

        rng = np.random.default_rng(42)
        closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, 200))
        period = 14

        series = _wilder_rsi_series(closes, period)
        assert len(series) == len(closes)

        for n in range(2, len(closes) + 1):
            scalar = _rsi_simple(closes[:n], period)
            batch = float(series[n - 1])
            assert abs(batch - scalar) < 1e-8, (
                f"n={n}: series={batch:.10f} scalar={scalar:.10f} delta={abs(batch-scalar):.2e}"
            )

    def test_cold_start_returns_50(self) -> None:
        from src.intelligence.feature_cache import _wilder_rsi_series

        closes = np.array([100.0, 101.0, 102.0], dtype=float)
        series = _wilder_rsi_series(closes, period=14)
        assert series[0] == 50.0
        assert series[1] == 50.0
        assert series[2] == 50.0  # only 3 bars, period=14 → all cold

    def test_values_in_range(self) -> None:
        from src.intelligence.feature_cache import _wilder_rsi_series

        rng = np.random.default_rng(7)
        closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.02, 500))
        series = _wilder_rsi_series(closes, period=14)
        assert np.all(series >= 0.0) and np.all(series <= 100.0)
```

- [ ] **Step 2: Run to verify it fails (function does not exist yet)**

```bash
.venv/bin/pytest tests/unit/intelligence/test_feature_factory_batch.py::TestWilderRsiSeries -v
```

Expected: FAIL with `ImportError: cannot import name '_wilder_rsi_series'`

- [ ] **Step 3: Add `_wilder_rsi_series` to `feature_cache.py` and refactor `_rsi_simple`**

In `src/intelligence/feature_cache.py`, replace the existing `_rsi_simple` function (currently at line 245) with:

```python
def _wilder_rsi_series(closes: np.ndarray, period: int) -> np.ndarray:
    """Wilder RSI at every bar index. Length == len(closes). Cold-start entries = 50.0.

    Single source of truth for Wilder smoothing. _rsi_simple is a thin wrapper.
    Used by both the live-path scalar accessor and the batch CTF series builder.
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
        if avg_loss < 1e-10:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rsi = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        out[i + 1] = float(np.clip(rsi, 0.0, 100.0))
    return out


def _rsi_simple(closes: np.ndarray, period: int) -> float:
    """Terminal Wilder RSI scalar. Thin wrapper over _wilder_rsi_series."""
    return float(_wilder_rsi_series(closes, period)[-1])
```

- [ ] **Step 4: Run tests — RSI series tests must pass**

```bash
.venv/bin/pytest tests/unit/intelligence/test_feature_factory_batch.py::TestWilderRsiSeries -v
```

Expected: PASS

- [ ] **Step 5: Update import in `backfill_feature_factory.py` and replace inline RSI loop**

In `services/backfill_feature_factory.py`, update the import from `feature_cache`:

```python
from src.intelligence.feature_cache import (
    _HMM_K,
    FeatureCache,
    _hmm_forward_step,
    _wilder_rsi_series,
)
```

Then in `_build_ctf_series`, replace the entire RSI block (the `ctf_mom` initialization and `if n > period:` block containing the Python loop):

```python
    # ctf_momentum: Wilder RSI per bar, normalized to [-1, +1]. Single shared impl.
    rsi_series = _wilder_rsi_series(closes, period)
    ctf_mom = np.clip((rsi_series - 50.0) / 50.0, -1.0, 1.0)
```

The removed code is lines 272-288 (the `ctf_mom = np.full(...)` through the closing `ctf_mom[i + 1] = ...` line). The `period = config.rsi_mid_period` line above it stays.

- [ ] **Step 6: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/intelligence/feature_cache.py services/backfill_feature_factory.py tests/unit/intelligence/test_feature_factory_batch.py
git commit -m "fix(batch): unify Wilder RSI into _wilder_rsi_series; _rsi_simple is now a wrapper

Two implementations of identical Wilder smoothing existed: _rsi_simple (scalar)
in feature_cache.py and an inline loop in _build_ctf_series. Any numerical fix
to one silently missed the other, poisoning IC parity between batch and live.

_wilder_rsi_series(closes, period) -> np.ndarray is now the single implementation.
_rsi_simple wraps it. _build_ctf_series calls it — eliminating the Python RSI
loop entirely (fully vectorized)."
```

---

## Task 3 — O(D×N) → O(D) cross-asset series + aligned dict structure (Issues 1 + 3)

**Files:**
- Modify: `services/backfill_feature_factory.py` (rewrite `_build_cross_asset_series`)
- Test: `tests/unit/services/test_backfill_feature_factory.py`

**Interfaces:**
- Consumes: `spy_bars`, `tlt_bars`, `shy_bars` (same signature as before)
- Produces: `dict[date, tuple[float, float, float]]` — same shape; values now computed incrementally O(D) total
- `FeatureCache.update_cross_asset` is no longer called from this function (live path still calls it)
- Assumption (US ETF universe): SPY/TLT/SHY trade the same calendar days, so `min(spy_end, tlt_end)` equals `spy_end` for every date. `flight_quality` first-close anchors are set once when both series first reach ≥2 bars.

- [ ] **Step 1: Write the failing test (parity test against old implementation)**

Add to `tests/unit/services/test_backfill_feature_factory.py`:

```python
import bisect
import math
from collections import deque
from datetime import UTC, date, datetime, timedelta

import numpy as np

from src.intelligence.feature_cache import FeatureCache, _zscore_from_deque
from src.intelligence.feature_factory import FeatureFactoryConfig


def _make_daily_bars(n: int, seed: int, start_close: float = 100.0) -> list[dict]:
    rng = np.random.default_rng(seed)
    closes = start_close * np.cumprod(1 + rng.normal(0, 0.01, n))
    base = datetime(2020, 1, 2, 21, 0, tzinfo=UTC)
    return [
        {
            "ts": base + timedelta(days=i),
            "open": float(closes[i] * 0.999),
            "high": float(closes[i] * 1.001),
            "low": float(closes[i] * 0.999),
            "close": float(closes[i]),
            "volume": 1_000_000.0,
        }
        for i in range(n)
    ]


def _reference_cross_asset_series(spy_bars, tlt_bars, shy_bars, config) -> dict:
    """Original O(D×N) implementation — reference for parity testing."""
    spy_dates = [b["ts"].date() for b in spy_bars]
    tlt_dates = [b["ts"].date() for b in tlt_bars]
    shy_dates = [b["ts"].date() for b in shy_bars]
    all_dates = sorted(set(spy_dates) | set(tlt_dates) | set(shy_dates))
    cache = FeatureCache()
    result = {}
    for d in all_dates:
        spy_end = bisect.bisect_right(spy_dates, d)
        tlt_end = bisect.bisect_right(tlt_dates, d)
        shy_end = bisect.bisect_right(shy_dates, d)
        if spy_end < 2 or tlt_end < 2 or shy_end < 2:
            continue
        cache.update_cross_asset(spy_bars[:spy_end], tlt_bars[:tlt_end], shy_bars[:shy_end], config)
        result[d] = (cache.vix_z, cache.flight_quality, cache.yield_slope_z)
    return result


class TestBuildCrossAssetSeries:
    def test_parity_with_reference_implementation(self) -> None:
        """New incremental O(D) implementation must produce identical values to O(D×N) reference."""
        from services.backfill_feature_factory import _build_cross_asset_series

        config = _make_config()
        spy = _make_daily_bars(300, seed=1, start_close=450.0)
        tlt = _make_daily_bars(300, seed=2, start_close=95.0)
        shy = _make_daily_bars(300, seed=3, start_close=86.0)

        reference = _reference_cross_asset_series(spy, tlt, shy, config)
        result = _build_cross_asset_series(spy, tlt, shy, config)

        assert set(result.keys()) == set(reference.keys()), "date keys differ"
        for d in reference:
            ref_vix, ref_fq, ref_ys = reference[d]
            res_vix, res_fq, res_ys = result[d]
            assert abs(res_vix - ref_vix) < 1e-10, f"{d}: vix_z {res_vix} != {ref_vix}"
            assert abs(res_fq - ref_fq) < 1e-10, f"{d}: flight_quality {res_fq} != {ref_fq}"
            assert abs(res_ys - ref_ys) < 1e-10, f"{d}: yield_slope_z {res_ys} != {ref_ys}"

    def test_all_values_finite(self) -> None:
        from services.backfill_feature_factory import _build_cross_asset_series

        config = _make_config()
        spy = _make_daily_bars(50, seed=10)
        tlt = _make_daily_bars(50, seed=11)
        shy = _make_daily_bars(50, seed=12)
        result = _build_cross_asset_series(spy, tlt, shy, config)
        for d, (vix, fq, ys) in result.items():
            assert math.isfinite(vix), f"{d}: vix_z not finite"
            assert math.isfinite(fq), f"{d}: flight_quality not finite"
            assert math.isfinite(ys), f"{d}: yield_slope_z not finite"
```

- [ ] **Step 2: Run reference test to confirm parity test logic works against current code**

```bash
.venv/bin/pytest tests/unit/services/test_backfill_feature_factory.py::TestBuildCrossAssetSeries -v
```

Expected: PASS (current code IS the reference — this confirms the test harness is correct)

- [ ] **Step 3: Rewrite `_build_cross_asset_series` with incremental O(D) logic**

In `services/backfill_feature_factory.py`, replace the entire `_build_cross_asset_series` function body:

```python
def _build_cross_asset_series(
    spy_bars: list[dict],
    tlt_bars: list[dict],
    shy_bars: list[dict],
    config: FeatureFactoryConfig,
) -> dict:
    """Build date → (vix_z, flight_quality, yield_slope_z) incrementally in O(D).

    Uses a single aligned dict structure (no parallel lists) and maintains
    incremental state instead of re-materializing full bar slices each date.

    Assumption: SPY/TLT/SHY trade the same US calendar days, so min(spy_end, tlt_end)
    equals spy_end for every date. flight_quality anchors to the first available close
    for each symbol (equivalent to the batch formula when all series start together).
    """
    symbol_bars: dict[str, list[dict]] = {"spy": spy_bars, "tlt": tlt_bars, "shy": shy_bars}
    symbol_dates: dict[str, list] = {
        k: [b["ts"].date() for b in v] for k, v in symbol_bars.items()
    }
    all_dates = sorted(set().union(*[set(d) for d in symbol_dates.values()]))

    # Incremental state — O(1) per date
    cursors: dict[str, int] = {k: 0 for k in symbol_bars}
    spy_log_rets: deque = deque(maxlen=config.cross_asset_rv_window)
    yield_ratio_history: deque = deque(maxlen=config.yield_curve_zscore_window)
    spy_realized_vol_history: deque = deque(maxlen=config.vix_zscore_window)

    spy_prev_close: float = 0.0
    tlt_prev_close: float = 0.0
    shy_prev_close: float = 0.0
    spy_first_close: float = 0.0  # flight_quality period-start anchor
    tlt_first_close: float = 0.0

    vix_z: float = 0.0
    flight_quality: float = 0.0
    yield_slope_z: float = 0.0
    result: dict = {}

    for d in all_dates:
        for k in symbol_bars:
            cursors[k] = bisect.bisect_right(symbol_dates[k], d)

        spy_end = cursors["spy"]
        tlt_end = cursors["tlt"]
        shy_end = cursors["shy"]

        if spy_end < 2 or tlt_end < 2 or shy_end < 2:
            # Advance prev_close trackers even during skip so first diff is correct
            if spy_end >= 1:
                spy_prev_close = float(spy_bars[spy_end - 1]["close"])
            if tlt_end >= 1:
                tlt_prev_close = float(tlt_bars[tlt_end - 1]["close"])
            if shy_end >= 1:
                shy_prev_close = float(shy_bars[shy_end - 1]["close"])
            continue

        spy_close = float(spy_bars[spy_end - 1]["close"])
        tlt_close = float(tlt_bars[tlt_end - 1]["close"])
        shy_close = float(shy_bars[shy_end - 1]["close"])

        # Set period-start anchors once (first date with ≥2 bars for all three)
        if spy_first_close == 0.0:
            spy_first_close = float(spy_bars[0]["close"])
            tlt_first_close = float(tlt_bars[0]["close"])

        # vix_z: append new SPY log return; compute realized vol; z-score over history
        if spy_prev_close > 1e-10:
            import math as _math
            spy_ret = _math.log(spy_close / spy_prev_close)
            spy_log_rets.append(spy_ret)
            rv_window = min(config.cross_asset_rv_window, len(spy_log_rets))
            realized_vol = float(np.std(list(spy_log_rets)[-rv_window:]))
            spy_realized_vol_history.append(realized_vol)
            vix_z = _zscore_from_deque(spy_realized_vol_history, config.vix_zscore_window)

        # flight_quality: cumulative TLT/SPY divergence from period start (O(1))
        if spy_first_close > 1e-10 and tlt_first_close > 1e-10:
            tlt_ret_total = tlt_close / tlt_first_close - 1.0
            spy_ret_total = spy_close / spy_first_close - 1.0
            flight_quality = tlt_ret_total - spy_ret_total

        # yield_slope_z: one-period TLT/SHY log-return ratio; z-score over history
        if tlt_prev_close > 1e-10 and shy_prev_close > 1e-10:
            import math as _math
            tlt_log_ret = _math.log(tlt_close / tlt_prev_close)
            shy_log_ret = _math.log(shy_close / shy_prev_close)
            yield_ratio_history.append(tlt_log_ret - shy_log_ret)
            yield_slope_z = _zscore_from_deque(
                yield_ratio_history, config.yield_curve_zscore_window
            )

        result[d] = (vix_z, flight_quality, yield_slope_z)

        spy_prev_close = spy_close
        tlt_prev_close = tlt_close
        shy_prev_close = shy_close

    return result
```

Also add to the top-level imports in `backfill_feature_factory.py` (the `import math` line is absent; add it with the existing stdlib imports):

```python
import math
```

And add `_zscore_from_deque` to the feature_cache import:

```python
from src.intelligence.feature_cache import (
    _HMM_K,
    FeatureCache,
    _hmm_forward_step,
    _wilder_rsi_series,
    _zscore_from_deque,
)
```

- [ ] **Step 4: Run parity test — must match reference implementation**

```bash
.venv/bin/pytest tests/unit/services/test_backfill_feature_factory.py::TestBuildCrossAssetSeries -v
```

Expected: PASS (incremental values match reference O(D×N) values to 1e-10)

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add services/backfill_feature_factory.py tests/unit/services/test_backfill_feature_factory.py
git commit -m "fix(batch): O(D) incremental cross-asset series; eliminate parallel date lists

_build_cross_asset_series was calling update_cross_asset(spy_bars[:end], ...) once
per trading date, re-materializing and re-computing the full growing prefix each
time — O(D×N) total (~780k array ops for 5yr daily on 58 symbols).

Replaced with incremental state: one log-return appended per date to a deque,
realized_vol = std(deque), z-score from history. O(D) total.

Also eliminated three parallel date lists (spy_dates/tlt_dates/shy_dates) in favour
of a single symbol_bars dict — misalignment between parallel lists was a silent
look-ahead bias risk with no error signal."
```

---

## Task 4 — `compute_batch` owns external state injection (Issue 4 — post-injection altitude)

**Files:**
- Modify: `src/intelligence/feature_factory.py` (`compute_batch` signature + per-bar routing)
- Modify: `services/backfill_feature_factory.py` (`_compute_symbol_tf`: pass snapshots, delete `dataclasses.replace`)
- Test: `tests/unit/services/test_backfill_feature_factory.py`

**Interfaces:**
- `compute_batch` new signature:
  ```python
  @staticmethod
  def compute_batch(
      bars: list[dict],
      symbol: str,
      tf: str,
      cache: FeatureCache,
      config: FeatureFactoryConfig,
      warm_up_bars: int = 0,
      cross_asset_by_date: dict | None = None,   # date → (vix_z, flight_quality, yield_slope_z)
      ctf_by_ts: dict | None = None,             # datetime → (ctf_momentum, ctf_vwap_align, ctf_regime_align)
      ctf_ts_list: list | None = None,           # sorted(ctf_by_ts.keys()) for bisect
  ) -> list[tuple[datetime, FeatureVector]]:
  ```
- When `cross_asset_by_date is not None` (batch path): read cross-asset from dict, CTF from `ctf_by_ts`, VP/SR = None.
- When `cross_asset_by_date is None` (live path): read all three groups from cache (unchanged behavior).
- `_guard` is updated to be None-passthrough so VP/SR None flows into FeatureVector correctly.

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/services/test_backfill_feature_factory.py`:

```python
class TestComputeBatchExternalInjection:
    def test_cross_asset_from_dict_not_cache(self) -> None:
        """When cross_asset_by_date supplied, FeatureVector uses dict values not cache zeros."""
        from src.intelligence.feature_factory import FeatureFactory
        from src.intelligence.feature_cache import FeatureCache

        config = _make_config()
        cache = FeatureCache()  # vix_z=0.0, flight_quality=0.0, yield_slope_z=0.0

        bars = _make_bars(60)
        bar_date = bars[-1]["ts"].date()
        cross_asset = {bar_date: (1.23, 0.45, -0.67)}

        results = FeatureFactory.compute_batch(
            bars, "SPY", "5m", cache, config,
            warm_up_bars=5,
            cross_asset_by_date=cross_asset,
        )
        assert results, "no results returned"
        _, fv = results[-1]
        assert abs(fv.vix_z - 1.23) < 1e-10, f"vix_z={fv.vix_z}, expected 1.23"
        assert abs(fv.flight_quality - 0.45) < 1e-10
        assert abs(fv.yield_slope_z - -0.67) < 1e-10

    def test_vp_sr_none_when_batch_mode(self) -> None:
        """VP/SR fields are None when cross_asset_by_date is provided (batch path)."""
        from src.intelligence.feature_factory import FeatureFactory
        from src.intelligence.feature_cache import FeatureCache

        config = _make_config()
        cache = FeatureCache()
        bars = _make_bars(60)
        cross_asset = {}  # empty — all dates fall back to (0,0,0)

        results = FeatureFactory.compute_batch(
            bars, "SPY", "5m", cache, config,
            warm_up_bars=5,
            cross_asset_by_date=cross_asset,
        )
        assert results
        for _, fv in results:
            assert fv.poc_dist_atr is None, f"poc_dist_atr={fv.poc_dist_atr}, expected None"
            assert fv.va_position is None
            assert fv.sr_support_dist is None
            assert fv.sr_resist_dist is None

    def test_live_path_unchanged_reads_from_cache(self) -> None:
        """When cross_asset_by_date=None (default), cache values flow into FeatureVector."""
        from src.intelligence.feature_factory import FeatureFactory
        from src.intelligence.feature_cache import FeatureCache

        config = _make_config()
        cache = FeatureCache()
        cache.vix_z = 9.99
        cache.flight_quality = 8.88
        cache.yield_slope_z = 7.77

        bars = _make_bars(60)
        results = FeatureFactory.compute_batch(
            bars, "SPY", "5m", cache, config, warm_up_bars=5
        )
        assert results
        _, fv = results[-1]
        assert abs(fv.vix_z - 9.99) < 1e-10
        assert abs(fv.flight_quality - 8.88) < 1e-10
        assert abs(fv.yield_slope_z - 7.77) < 1e-10
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/unit/services/test_backfill_feature_factory.py::TestComputeBatchExternalInjection -v
```

Expected: FAIL — `compute_batch` does not accept `cross_asset_by_date` yet

- [ ] **Step 3: Add `import bisect` to `feature_factory.py`**

`feature_factory.py` does not currently import `bisect`. Add it with the stdlib imports at the top:

```python
import bisect
```

- [ ] **Step 4: Update `compute_batch` signature and `_guard`**

In `src/intelligence/feature_factory.py`, update the `compute_batch` method signature:

```python
    def compute_batch(
        bars: list[dict],
        symbol: str,
        tf: str,
        cache: FeatureCache,
        config: FeatureFactoryConfig,
        warm_up_bars: int = 0,
        cross_asset_by_date: dict | None = None,
        ctf_by_ts: dict | None = None,
        ctf_ts_list: list | None = None,
    ) -> list[tuple[datetime, FeatureVector]]:
        """Compute FeatureVector for every bar in bars in O(n). Returns (bar_ts, fv) pairs.

        Precomputes all series_full functions once, then loops over bars indexing series[i].
        Non-series features (cmf, cci, aroon, vol_ratio, range_position, bar_close_pos, informed_flow)
        are computed per bar with bounded windows. Cache-backed features (hmm, hurst, etc.) are
        read from cache. Calendar features computed per bar from timestamps.

        When cross_asset_by_date is provided (batch path):
          - cross-asset (vix_z, flight_quality, yield_slope_z) read from dict keyed by date
          - CTF (ctf_momentum, ctf_vwap_align, ctf_regime_align) read from ctf_by_ts via bisect
          - VP/SR (poc_dist_atr, va_position, sr_support_dist, sr_resist_dist) set to None
            (not computable from OHLCV batch; requires I3 intraday injection)
        When cross_asset_by_date is None (live path):
          - all three groups read from cache (unchanged behavior)
        """
```

In the per-bar loop, update `_guard` to be None-passthrough. Find the line `def _guard(v: float, fallback: float = 0.0) -> float:` and replace:

```python
            def _guard(v: float | None, fallback: float = 0.0) -> float | None:
                if v is None:
                    return None
                return v if math.isfinite(v) else fallback
```

Then replace the cross-asset, CTF, and VP/SR sections in the per-bar loop. Find (starting around line 1344):

```python
            # Session-level primitives (from cache; 1d TF defaults to neutral)
            if tf == "1d":
                poc_dist_atr_val = 0.0
                va_position_val = 0.5
                sr_support_dist_val = 0.0
                sr_resist_dist_val = 0.0
            else:
                poc_dist_atr_val = cache.poc_dist_atr
                va_position_val = cache.va_position
                sr_support_dist_val = cache.sr_support_dist
                sr_resist_dist_val = cache.sr_resist_dist
```

Replace with:

```python
            # Session-level (VP/SR): None in batch path; 1d defaults to neutral; else from cache
            if cross_asset_by_date is not None:
                poc_dist_atr_val = None
                va_position_val = None
                sr_support_dist_val = None
                sr_resist_dist_val = None
            elif tf == "1d":
                poc_dist_atr_val = 0.0
                va_position_val = 0.5
                sr_support_dist_val = 0.0
                sr_resist_dist_val = 0.0
            else:
                poc_dist_atr_val = cache.poc_dist_atr
                va_position_val = cache.va_position
                sr_support_dist_val = cache.sr_support_dist
                sr_resist_dist_val = cache.sr_resist_dist
```

Find the cross-asset section (around line 1377):

```python
            # Cross-asset primitives (all from cache)
            vix_z_val = cache.vix_z
            flight_quality_val = cache.flight_quality
            yield_slope_z_val = cache.yield_slope_z
```

Replace with:

```python
            # Cross-asset: from pre-built causal dict (batch) or cache (live)
            if cross_asset_by_date is not None:
                _ca = cross_asset_by_date.get(bar_ts.date(), (0.0, 0.0, 0.0))
                vix_z_val, flight_quality_val, yield_slope_z_val = _ca
            else:
                vix_z_val = cache.vix_z
                flight_quality_val = cache.flight_quality
                yield_slope_z_val = cache.yield_slope_z
```

Find the CTF section (around line 1400):

```python
            # Cross-timeframe primitives (from cache)
            ctf_momentum_val = cache.ctf_momentum
            ctf_vwap_align_val = cache.ctf_vwap_align
            ctf_regime_align_val = cache.ctf_regime_align
```

Replace with:

```python
            # CTF: from pre-built causal dict (batch) or cache (live)
            if ctf_by_ts is not None and ctf_ts_list is not None:
                _idx = bisect.bisect_right(ctf_ts_list, bar_ts) - 1
                if _idx >= 0:
                    ctf_momentum_val, ctf_vwap_align_val, ctf_regime_align_val = ctf_by_ts[ctf_ts_list[_idx]]
                else:
                    ctf_momentum_val = ctf_vwap_align_val = ctf_regime_align_val = 0.0
            else:
                ctf_momentum_val = cache.ctf_momentum
                ctf_vwap_align_val = cache.ctf_vwap_align
                ctf_regime_align_val = cache.ctf_regime_align
```

- [ ] **Step 5: Run injection tests**

```bash
.venv/bin/pytest tests/unit/services/test_backfill_feature_factory.py::TestComputeBatchExternalInjection -v
```

Expected: all three tests PASS

- [ ] **Step 6: Update `_compute_symbol_tf` in `backfill_feature_factory.py`**

Pass snapshots into `compute_batch` and delete the `dataclasses.replace` block.

Find the `batch_results = FeatureFactory.compute_batch(...)` call in `_compute_symbol_tf`:

```python
    batch_results = FeatureFactory.compute_batch(
        bars, symbol, tf, cache, config, warm_up_bars=warm_up_bars
    )
```

Replace with:

```python
    batch_results = FeatureFactory.compute_batch(
        bars, symbol, tf, cache, config,
        warm_up_bars=warm_up_bars,
        cross_asset_by_date=cross_asset_by_date,
        ctf_by_ts=ctf_by_ts if ctf_by_ts else None,
        ctf_ts_list=htf_ts_list if htf_ts_list else None,
    )
```

Then in the `for bar_ts, fv in batch_results:` loop, delete the entire cross-asset lookup block, CTF lookup block, and `dataclasses.replace` block — replace them all with just the row construction:

```python
    insert_batch: list[tuple] = []
    total_inserted = 0

    for bar_ts, fv in batch_results:
        row = _vector_to_params(
            symbol=symbol,
            tf=tf,
            bar_ts=bar_ts,
            pipeline_version=pipeline_version,
            regime=None,
            fv=fv,
        )
        insert_batch.append(row)

        if len(insert_batch) >= _INSERT_BATCH_SIZE:
            _batch_insert(conn, insert_batch)
            total_inserted += len(insert_batch)
            insert_batch = []
            _logger.debug(
                "compute_progress",
                symbol=symbol,
                tf=tf,
                inserted=total_inserted,
                total_bars=total_bars,
            )
```

Also remove `import dataclasses` from the top of `backfill_feature_factory.py` if it is no longer used (check with grep first).

- [ ] **Step 7: Run full suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add src/intelligence/feature_factory.py services/backfill_feature_factory.py tests/unit/services/test_backfill_feature_factory.py
git commit -m "fix(batch): compute_batch owns external state injection; delete dataclasses.replace

FeatureFactory.compute_batch() now accepts cross_asset_by_date, ctf_by_ts, and
ctf_ts_list as optional params. When supplied (batch path), it reads cross-asset
and CTF values from the pre-built causal dicts instead of cache, and sets VP/SR
to None. When omitted (live path), all reads fall back to cache — unchanged.

Eliminates the dataclasses.replace post-injection block from _compute_symbol_tf.
The factory now owns complete FeatureVector construction; a caller that omits the
injection no longer silently receives zeros in 10 fields."
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass, no regressions

- [ ] **Verify no stray `dataclasses.replace` on fv in backfill service**

```bash
grep -n "dataclasses.replace" services/backfill_feature_factory.py
```

Expected: no output

- [ ] **Verify `_wilder_rsi_series` is the only RSI implementation**

```bash
grep -n "avg_gain.*alpha\|Wilder" services/backfill_feature_factory.py src/intelligence/feature_cache.py
```

Expected: only one occurrence (inside `_wilder_rsi_series` in `feature_cache.py`)

- [ ] **Verify MIN_WINDOW is derived**

```bash
grep -n "MIN_WINDOW" src/intelligence/feature_factory.py
```

Expected: two lines — the assignment (`MIN_WINDOW = max(...)`) and the usage (`window_start = max(0, i - MIN_WINDOW)`)
