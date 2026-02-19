# Chart Pattern Detection — Design Document

**Date:** 2026-02-19
**Status:** Approved — ready for implementation planning
**Tier:** I5 Patterns
**Plugins:** `patt_DoubleTB`, `patt_HeadShoulders`, `patt_TriangleWedge`
**Directory:** `src/intelligence/patterns/`

---

## Context

Three new pattern plugins for classical chart pattern recognition. They sit at I5 (Pattern tier),
operating on swing point sequences derived from OHLCV. They join the existing 5 pattern plugins in
`src/intelligence/patterns/`.

The I3 `SwingDetectorPlugin` outputs only scalar "most recent swing" values — not a list. These
plugins therefore re-derive swing sequences independently using `find_peaks` / `find_troughs` from
`src/intelligence/utils.py`, consistent with how `RSIDivergencePlugin` operates.

---

## Core Design Decision: Two-Stage Swing Filtering

All three plugins share a **two-stage swing detection pipeline**:

### Phase 1 — Structural
`find_peaks(high, n=5)` / `find_troughs(low, n=5)` — vectorized, same `neighbor=5` as existing
SwingDetector and RSIDivergence plugins.

### Phase 2 — Significance Filter
A single O(N) forward pass that drops consecutive swing pairs where:
- Price difference `< price * amplitude_threshold` (default `0.002` = 0.2%), **AND**
- Bar distance `< min_swing_bars` (default `8` bars)

This collapses cluster-noise into one clean pivot per swing — eliminates false double-tops from
1-minute futures noise where two consecutive bars hit nearly the same high. This is the technique
used in professional pattern libraries.

### Shared Helper
All three plugins call a private static method:

```python
@staticmethod
def _filter_swings(
    indices: list[int],
    prices: np.ndarray,
    amplitude_thr: float = 0.002,
    min_bars: int = 8,
) -> list[int]:
    """Two-stage significance filter: removes noise swings that are too close
    in price and time. Returns filtered list of bar indices."""
```

This helper is defined independently in each plugin (not a shared utility import) to keep plugins
self-contained per project convention.

---

## Plugin 1: `patt_DoubleTB` (Double Top / Double Bottom)

**File:** `src/intelligence/patterns/double_top_bottom.py`
**Class:** `DoubleTBPlugin`

### Algorithm
1. `find_peaks(high, n=5)` → significance filter → `filtered_highs` (list of bar indices)
2. `find_troughs(low, n=5)` → significance filter → `filtered_lows`
3. **Double Top:** Take the two most recent filtered_highs. Check:
   - Price difference `< peak_tolerance` (default `0.003` = 0.3%)
   - A filtered_low exists **between** the two peak bar indices (neckline)
   - Neckline = low price at that trough index
   - Confirmed when `close < neckline`
   - Target = `peak_avg - (peak_avg - neckline)` (measured move below neckline)
4. **Double Bottom:** Mirror — two troughs with a peak between, confirmed above neckline

### Pattern State Logic
Each `compute_full` call re-evaluates from scratch (stateless between bars). State transitions
(`forming` → `confirmed`) are encoded in the integer output value.

### Outputs
```python
outputs = frozenset({
    "dt_db_pattern",    # 0=none, 1=double_top_forming, 2=double_top_confirmed,
                        # 3=double_bottom_forming, 4=double_bottom_confirmed
    "dt_db_neckline",   # Neckline price level (0.0 if no pattern)
    "dt_db_target",     # Measured move target price (0.0 if no pattern)
    "dt_db_confidence", # 0-1: symmetry score based on peak price difference and
                        # time spacing between peaks
})
```

### Confidence Score
`confidence = 1.0 - (abs(peak1 - peak2) / peak_avg / peak_tolerance)` clamped to [0, 1].
More symmetric peaks → higher confidence. Bonus for time symmetry (peaks equidistant from trough).

### Parameters (dataclass fields)
```python
neighbor: int = 5
amplitude_thr: float = 0.002
min_swing_bars: int = 8
peak_tolerance: float = 0.003
min_lookback: int = 60
```

---

## Plugin 2: `patt_HeadShoulders` (Head & Shoulders)

**File:** `src/intelligence/patterns/head_shoulders.py`
**Class:** `HeadShouldersPlugin`

### Algorithm
1. `find_peaks(high, n=5)` → significance filter → `filtered_highs`
2. `find_troughs(low, n=5)` → significance filter → `filtered_lows`
3. **Regular H&S (bearish):** Take last 3 filtered_highs as [left_shoulder, head, right_shoulder]:
   - `head > left_shoulder` by at least `head_extend_pct` (default `0.03` = 3%)
   - `head > right_shoulder` by at least `head_extend_pct`
   - Left and right shoulders within `shoulder_sym_pct` (default `0.05` = 5%) of each other
   - Find the two filtered_lows between [left_shoulder, head] and [head, right_shoulder] → left_trough, right_trough
4. **Sloped Neckline:** Straight line through `(left_trough_bar, left_trough_price)` and
   `(right_trough_bar, right_trough_price)`. Neckline price at any bar:
   `neckline = left_trough_price + slope * (current_bar - left_trough_bar)`
5. **Confirmation:** `close < neckline_at_current_bar`
6. **ATR-normalized breakout distance:**
   `hs_neckline_distance = (neckline_at_bar - close) / atr` — positive = broke below
7. **Inverse H&S (bullish):** Mirror on troughs/peaks
8. **Target:** `head_price - (head_price - neckline_at_head_bar)` projected from neckline

### Outputs
```python
outputs = frozenset({
    "hs_pattern",            # 0=none, 1=hs_forming, 2=hs_confirmed,
                             # 3=ihs_forming, 4=ihs_confirmed
    "hs_neckline",           # Neckline price at current bar (sloped)
    "hs_target",             # Measured move target
    "hs_confidence",         # 0-1: shoulder symmetry score
    "hs_neckline_distance",  # (neckline - close) / ATR — continuous breakout strength
})
```

### ATR Calculation
Simple 14-bar ATR computed inline from the OHLCV window. No dependency on the I1 ATR plugin
(avoids cross-plugin data coupling in `compute_full`).

### Parameters (dataclass fields)
```python
neighbor: int = 5
amplitude_thr: float = 0.002
min_swing_bars: int = 8
shoulder_sym_pct: float = 0.05
head_extend_pct: float = 0.03
atr_period: int = 14
min_lookback: int = 80
```

---

## Plugin 3: `patt_TriangleWedge` (Triangles & Wedges)

**File:** `src/intelligence/patterns/triangle_wedge.py`
**Class:** `TriangleWedgePlugin`

### Algorithm
1. `find_peaks(high, n=5)` → significance filter → `filtered_highs` (need ≥ 2)
2. `find_troughs(low, n=5)` → significance filter → `filtered_lows` (need ≥ 2)
3. **Upper trendline:** Linear regression over `(bar_idx, high_price)` at filtered_highs points
   → `slope_h`, `intercept_h`, `r2_upper`
4. **Lower trendline:** Linear regression over `(bar_idx, low_price)` at filtered_lows points
   → `slope_l`, `intercept_l`, `r2_lower`

### Classification (slope tolerance `0.0001` price/bar)
| Pattern | Condition | Bias |
|---|---|---|
| Ascending triangle | `slope_h ≈ 0`, `slope_l > tol` | +1 (bullish) |
| Descending triangle | `slope_h < -tol`, `slope_l ≈ 0` | -1 (bearish) |
| Symmetrical triangle | `slope_h < -tol`, `slope_l > tol` | 0 (continuation) |
| Rising wedge | `slope_h > tol`, `slope_l > tol`, `slope_l > slope_h` | -1 (bearish) |
| Falling wedge | `slope_h < -tol`, `slope_l < -tol`, `slope_h < slope_l` | +1 (bullish) |

### Apex and Convergence
- **Apex bars:** `(intercept_l - intercept_h) / (slope_h - slope_l)` — bar index where lines meet
  (valid only when `slope_h != slope_l`)
- **Convergence ratio:** Primary confidence driver:
  ```
  initial_width = upper_trendline(first_bar) - lower_trendline(first_bar)
  current_width = upper_trendline(last_bar) - lower_trendline(last_bar)
  convergence = 1 - (current_width / initial_width)   # clamped [0, 1]
  ```

### Confidence Score
`confidence = convergence_ratio * sqrt(r2_upper * r2_lower)`

R² measures fit quality; convergence ratio measures whether lines are actually tightening.
A pattern with high R² but no convergence is not a real triangle.

### Outputs
```python
outputs = frozenset({
    "tri_pattern",       # 0=none, 1=ascending, 2=descending, 3=symmetrical,
                         # 4=rising_wedge, 5=falling_wedge
    "tri_upper_slope",   # Upper trendline slope (price/bar)
    "tri_lower_slope",   # Lower trendline slope (price/bar)
    "tri_apex_bars",     # Bars until trendlines converge (0 if diverging)
    "tri_breakout_bias", # -1 to +1 expected breakout direction
    "tri_confidence",    # convergence_ratio * sqrt(r2_upper * r2_lower)
})
```

### Parameters (dataclass fields)
```python
neighbor: int = 5
amplitude_thr: float = 0.002
min_swing_bars: int = 8
slope_tolerance: float = 0.0001
min_swing_points: int = 2
min_lookback: int = 60
```

---

## Shared Conventions

| Property | Value |
|---|---|
| `supports_incremental` | `False` (all three — re-scan swing sequence each bar) |
| `compute_next` | Delegates to `compute_full` (same as `RSIDivergencePlugin`) |
| `inputs` | `(InputSpec(symbol=".*", timeframe="1m", lookback=120),)` |
| `capability_tags` | `frozenset({"pattern", "chart"})` |
| Output on insufficient data | `{}` (empty dict) |
| Numeric outputs | `round(..., 4)` consistent with rest of codebase |
| No external dependencies | No JSON config files — parameters as dataclass fields |

---

## Registration

Add to `src/intelligence/register_plugins.py` after existing pattern registrations:

```python
# Imports
from .patterns.double_top_bottom import plugin as double_tb_plugin
from .patterns.head_shoulders import plugin as head_shoulders_plugin
from .patterns.triangle_wedge import plugin as triangle_wedge_plugin

# In register_all_plugins():
registry.register_pattern(double_tb_plugin)
registry.register_pattern(head_shoulders_plugin)
registry.register_pattern(triangle_wedge_plugin)
```

---

## Test Strategy

**Target: 15 tests total (~5 per plugin)**

Each plugin needs:
1. Returns `{}` when insufficient data (< `min_lookback` bars)
2. Detects the primary pattern (synthesized OHLCV with known peak/trough structure)
3. Confirms pattern when price crosses neckline/trendline
4. Returns `pattern=0` on flat/random data with no pattern
5. Confidence score in valid range [0, 1]

**Synthetic data approach:** Construct numpy arrays with hand-crafted peaks/troughs at known
indices. Do not use random data — deterministic test inputs only.

---

## Files to Create / Modify

| Action | File |
|---|---|
| Create | `src/intelligence/patterns/double_top_bottom.py` |
| Create | `src/intelligence/patterns/head_shoulders.py` |
| Create | `src/intelligence/patterns/triangle_wedge.py` |
| Create | `tests/unit/test_double_top_bottom.py` |
| Create | `tests/unit/test_head_shoulders.py` |
| Create | `tests/unit/test_triangle_wedge.py` |
| Modify | `src/intelligence/register_plugins.py` |

**Plugin count after:** 45 total (42 + 3)
**Test count after:** ~381 (366 + 15)

---

## Complexity Estimate

- `patt_DoubleTB`: ~90 lines
- `patt_HeadShoulders`: ~120 lines (sloped neckline + ATR adds complexity)
- `patt_TriangleWedge`: ~100 lines (linear regression inline)
- Tests: ~200 lines total
- Total new code: ~510 lines
