# I1-I5 Uplift: Correctness Fixes + High-Value Additions

> **Date:** 2026-02-17
> **Status:** APPROVED
> **Scope:** Approach A — correctness fixes + Supertrend + GARCH + Trend Confluence

---

## Motivation

Before the Signal Orchestrator starts collecting data into the signal_ledger, the I1-I5 foundation must be correct. Bugs in indicators corrupt training data permanently. Additionally, three high-value plugins are missing that would significantly improve I7 trading setup quality.

### Key Finding: `compute_next()` Is Dead Code

The `intelligence_processor_service.py` always calls `compute_full()` for every plugin on every bar. No service ever calls `compute_next()`. All incremental state management (`_seed_state`, rolling buffers, Wilder's smoothing state) is unused in production. This is acknowledged in the service comments as acceptable ("I1 is <1ms total"), but means the I3/I5 Python-loop peak detection is the real bottleneck (10-25ms per bar).

---

## Section 1: Correctness Fixes

### 1a. VWAP Session Reset + Standard Deviation Bands

**Problem:** VWAP accumulates from the start of the data window with no session boundary reset. For multi-day data, VWAP is wrong. Additionally, VWAP standard deviation bands (institutional mean-reversion levels) are missing.

**Fix:**
- Detect session boundaries from bar timestamps (date comparison)
- On date change: reset `cum_pv`, `cum_vol`, `cum_tp_sq_vol` to zero
- Fallback: if no timestamp available, current behavior (no reset)
- Add volume-weighted standard deviation calculation:
  ```
  variance = cum_tp_sq_vol / cum_vol - vwap^2
  std = sqrt(variance)
  ```
- New incremental accumulator: `cum_tp_sq_vol = sum(tp^2 * vol)`

**New outputs:**
```
vwap           # (existing, now session-aware)
vwap_upper_1   # vwap + 1 * std
vwap_lower_1   # vwap - 1 * std
vwap_upper_2   # vwap + 2 * std
vwap_lower_2   # vwap - 2 * std
vwap_std        # the volume-weighted standard deviation itself
```

**File:** `src/intelligence/indicators/vwap.py` (modify existing)

### 1b. Fix `is_num()` to Reject NaN

**Problem:** `is_num()` returns `True` for `float('nan')`. Confluence and MomentumContext use it to validate feature values before scoring. NaN from upstream division-by-zero flows silently into scores.

**Fix:**
```python
import math

def is_num(x: Any) -> bool:
    return isinstance(x, int | float) and math.isfinite(x)
```

Using `math.isfinite()` rejects both NaN and Inf.

**File:** `src/intelligence/utils.py` (modify existing)

### 1c. TrendRegime Feature Consumption

**Problem:** TrendRegime computes SMA-20/50 from scratch via `np.mean(close[-20:])` instead of reading `features["sma_20"]` and `features["sma_50"]` from the upstream MovingAverages plugin. Wasteful and potentially inconsistent.

**Fix:** Read from features dict first, fall back to direct computation:
```python
sma20 = features.get("sma_20") if features else None
if sma20 is None:
    sma20 = float(np.mean(close[-self.sma_fast:]))
# Same for sma50
```

**File:** `src/intelligence/context/trend_regime.py` (modify existing)

### 1d. ADX Deduplication

**Problem:** `compute_full()` calls `_adx_np()` (runs full Wilder's smoothing computation), then calls `_seed_state()` which runs the exact same computation again to extract internal state. Double work.

**Fix:** Refactor `_adx_np()` to return both output values AND internal state dict. Eliminate `_seed_state()` entirely. Single pass.

**File:** `src/intelligence/indicators/adx.py` (modify existing)

### 1e. Vectorize `find_peaks` / `find_troughs`

**Problem:** Current implementation uses nested Python `all()`/`any()` generators with O(n*k) Python-level comparisons. For n=120, k=5, that's ~1200 Python comparisons per call. Used by SwingDetector, TrendStructure, RSIDivergence — the main I3/I5 bottleneck.

**Fix:** Replace with numpy array comparisons:
```python
def find_peaks(data: np.ndarray, n: int) -> list[int]:
    result = np.ones(len(data) - 2 * n, dtype=bool)
    strict = np.zeros(len(data) - 2 * n, dtype=bool)
    center = data[n : len(data) - n]
    for j in range(1, n + 1):
        left = data[n - j : len(data) - n - j]
        right = data[n + j : len(data) - n + j]
        result &= (center >= left) & (center >= right)
        strict |= (center > left) | (center > right)
    indices = np.where(result & strict)[0] + n
    return indices.tolist()
```

~10 vectorized numpy ops instead of ~1200 Python comparisons. Estimated 50-100x speedup for this function.

**File:** `src/intelligence/utils.py` (modify existing)

### 1f. Unify Peak Detection in SupportResistance

**Problem:** SupportResistance uses its own `np.max(high[i-w:i+w+1])` windowed peak detection instead of the shared `find_peaks`/`find_troughs` from utils.py. Two parallel implementations of the same concept with subtly different semantics.

**Fix:** Refactor SupportResistance to use the shared (now vectorized) `find_peaks`/`find_troughs`. Adjust window parameter mapping: `window=10` maps to `neighbor=10` in the shared functions.

**File:** `src/intelligence/structure/support_resistance.py` (modify existing)

---

## Section 2: New Plugins

### 2a. Supertrend (I1 — Technical Indicator)

**Purpose:** ATR-based binary trend direction. Ratcheting band that only moves in the trend's favor. Flips direction on price crossover.

**Algorithm:**
```
basic_upper = hl2 + multiplier * ATR
basic_lower = hl2 - multiplier * ATR

final_upper = min(basic_upper, prev_final_upper) if prev_close <= prev_final_upper
final_lower = max(basic_lower, prev_final_lower) if prev_close >= prev_final_lower

direction flips: close < final_lower → -1, close > final_upper → +1
```

**Parameters:** `period=10, multiplier=3.0` (configurable)

**Outputs:**
```
supertrend_value   # active band price level
supertrend_dir     # +1 (bullish) or -1 (bearish)
```

**Incremental:** Yes, O(1). State: `(prev_final_upper, prev_final_lower, prev_direction, prev_close)` + ATR state.

**Consumes:** Reads `features["atr_14"]` from upstream when available. Computes ATR from OHLCV for cold-start `compute_full()`.

**File:** `src/intelligence/indicators/supertrend.py`

**Registration:** Add to `register_plugins.py` as indicator. Add `"Supertrend"` to `I1_PLUGINS` list in `intelligence_processor_service.py`.

### 2b. GARCH(1,1) Volatility Forecast (I4 — Context Classification)

**Purpose:** Forecasts next-bar conditional volatility. Answers "is volatility expanding or contracting?" — forward-looking complement to the backward-looking VolatilityRegime.

**Algorithm:**
```
epsilon = log(close / prev_close)
sigma2 = omega + alpha * epsilon^2 + beta * prev_sigma2

Default parameters (1m futures bars):
  omega = 0.00001
  alpha = 0.10
  beta  = 0.85
```

**Outputs:**
```
garch_sigma         # conditional volatility forecast (sqrt of sigma2)
garch_vol_ratio     # garch_sigma / realized_vol_20 (>1 = expanding)
garch_vol_regime    # 0=low, 1=normal, 2=high, 3=extreme (percentile-based)
garch_shock         # epsilon^2 / sigma2 (standardized shock, >3 = unusual)
```

**Incremental:** Yes, O(1). State: `(prev_sigma2, prev_close, sigma_history_deque)`.

**Realized vol dependency:** For `garch_vol_ratio`, needs a 20-bar realized volatility (std of log returns). Maintain a rolling deque of the last 20 log returns in state.

**File:** `src/intelligence/context/garch_volatility.py`

**Registration:** Add to `register_plugins.py` as pattern. Add `"ctx_GARCHVolatility"` to `I4_PLUGINS` list in `intelligence_processor_service.py`.

**Reference:** Full spec at `docs/plans/future-indicators-backlog.md` lines 10-65.

### 2c. Trend Confluence (I5 — Pattern Detection)

**Purpose:** Aggregates trend-following signals into a single [-1, +1] score. Counterpart to the existing mean-reversion Confluence plugin.

**Consumes from `features` dict:**

| Signal | Source | Scoring |
|--------|--------|---------|
| `sma_20_gt_50` | MAComposite (I2) | +1 if present and true, -1 if false |
| `adx_14` + `plus_di_14` / `minus_di_14` | ADX (I1) | +1 if ADX>20 and +DI>-DI, -1 if ADX>20 and -DI>+DI, skip if ADX<20 |
| `swing_pattern` | SwingDetector (I3) | direct pass-through (+1/0/-1) |
| `macd_histogram_12_26_9` | MACD (I1) | +1 if positive, -1 if negative |
| `supertrend_dir` | Supertrend (I1, new) | direct pass-through (+1/-1) |
| `trend_regime` | TrendRegime (I4) | direct pass-through (already [-1, +1]) |

**Outputs:**
```
trend_confluence_score       # mean of available signal scores [-1, +1]
trend_confluence_n_signals   # how many signals contributed
trend_confluence_agreement   # fraction of signals matching majority sign
trend_confluence_strength    # abs(score) * agreement — conviction metric
```

**File:** `src/intelligence/patterns/trend_confluence.py`

**Registration:** Add to `register_plugins.py` as pattern. Add `"TrendConfluence"` to `I5_PLUGINS` list in `intelligence_processor_service.py`.

---

## Deferred Items (Flagged for Future)

### Incremental Pipeline
The service always calls `compute_full()`. Switching to `compute_next()` for incremental plugins would enable:
- RSIDivergence to accumulate RSI history from upstream instead of recomputing
- VolumeDivergence to accumulate OBV history from upstream
- VolatilityRegime to consume upstream ATR/BB instead of recomputing
- General I1 speedup (minor since I1 is already <1ms)

This is a service-level architectural change, not a plugin change.

### Feature History in Pipeline
Adding `frames["feature_history"]` (rolling window of past N computed features per key) would eliminate the need for plugins to maintain their own history buffers. Enables cleaner feature chaining for series-dependent plugins.

---

## Files Changed

### Modified (6)
- `src/intelligence/indicators/vwap.py` — session reset + SD bands
- `src/intelligence/utils.py` — `is_num` NaN check + vectorized peaks/troughs
- `src/intelligence/context/trend_regime.py` — consume upstream SMAs
- `src/intelligence/indicators/adx.py` — deduplicate computation
- `src/intelligence/structure/support_resistance.py` — use shared peak detection
- `src/intelligence/register_plugins.py` — register 3 new plugins

### New (3)
- `src/intelligence/indicators/supertrend.py`
- `src/intelligence/context/garch_volatility.py`
- `src/intelligence/patterns/trend_confluence.py`

### Service Updates (1)
- `services/intelligence_processor_service.py` — add new plugins to tier lists

### Tests (3-4 new files)
- `tests/unit/intelligence/test_supertrend.py`
- `tests/unit/intelligence/test_garch_volatility.py`
- `tests/unit/intelligence/test_trend_confluence.py`
- `tests/unit/intelligence/test_utils_vectorized.py` (vectorized peaks/troughs)

### Total Estimate
- ~6 modified files, ~4 new files, ~3-4 test files
- ~400 lines new code, ~100 lines modified
- ~40-50 new tests
