# Code Quality Findings - I1-I7 Intelligence Plugins

**Date:** 2026-02-28 / 2026-03-01
**Scope:** src/intelligence/ (I1-I7 plugins)
**Total Issues:** 206 lint issues + 8 complexity concerns

---

## Summary

| Category | Count | Priority |
|----------|--------|----------|
| O(N²/O(N³) complexity | 8 | High |
| range(len(x)) anti-patterns | 20 | Medium |
| Magic numbers | 30+ | Low |
| Line too long | 5+ | Low |
| Too many branches/statements | 4 | Medium |
| Ambiguous variables | 2 | Low |

---

## 1. O(N²) and O(N³) Complexity Issues (HIGH PRIORITY)

### 1.1 head_shoulders.py - Triple-Nested Loops (O(N³))
**File:** `src/intelligence/patterns/head_shoulders.py`
**Lines:** 66-94, 121-139
**Issue:** Triple-nested for loops iterating through peaks/troughs indices

```python
for h_pos in range(1, len(peaks) - 1):           # Outer loop O(N)
    for rs_pos in range(h_pos + 1, ...):          # Middle loop O(N)
        for ls_pos in range(h_pos - 1, ..., -1):   # Inner loop O(N)
            # O(N³) total complexity
```

**Impact:** With 100+ bars, this becomes millions of iterations. Head & Shoulders pattern detection runs on every bar.

**Fix:** Pre-filter candidates, use numpy vectorization, or limit search window.

---

### 1.2 aggregator.py - Nested Loop Over Signals (O(N×M))
**File:** `src/intelligence/trading/aggregator.py`
**Lines:** 193-197
**Issue:** Nested loop over matching signals and their supporting_factors

```python
for sig in matching:                     # O(N) where N = active signals (~9)
    for factor in sig.get("supporting_factors", []):  # O(M) where M = factors per signal
        if factor not in seen:              # O(K) where K = seen set size
```

**Impact:** With 9 signals × 10 factors = 90 iterations per aggregation run.

**Fix:** Use set union/difference instead of nested loop with set lookup.

---

### 1.3 cross_timeframe.py - Nested Over Intel Objects (O(N×M))
**File:** `src/intelligence/confluence/cross_timeframe.py`
**Lines:** 218-232
**Issue:** Double-nested loops over `other_intel.values()` (3-4 timeframes)

```python
for div_key, sign in [...] (2 iterations):
    for intel in other_intel.values():  # 3-4 timeframes × 2 keys = 6-8 iterations
        # nested access and checks
```

**Impact:** Runs on every bar across all timeframes.

**Fix:** Pre-compute values, use dictionary comprehension.

---

### 1.4 Additional Nested Loops (Medium Priority)

| File | Lines | Depth | Description |
|-------|--------|--------|-------------|
| `patterns/double_top_bottom.py` | 63, 100 | 2 (O(N²)) - Peak/trough iteration |
| `patterns/rsi_divergence.py` | 80 | 2 (O(N²)) - Divergence scan |
| `patterns/volume_divergence.py` | 31 | 2 (O(N²)) - Volume scan |
| `smart_money/liquidity_pools.py` | 176 | 2 (O(N²)) - Pool matching |
| `smart_money/supply_demand_zones.py` | 88, 120 | 2 (O(N²)) - Zone iteration |
| `smart_money/fair_value_gap.py` | 74 | 2 (O(N²)) - FVG detection |
| `smart_money/liquidity_sweeps.py` | 67, 91 | 2 (O(N²)) - Sweep detection |
| `indicators/rsi.py` | 55, 103 | 2 (O(N²)) - RSI calculation |
| `indicators/mfi.py` | 66 | 2 (O(N²)) - MFI calculation |
| `indicators/stochastic_rsi.py` | 47 | 2 (O(N²)) - StochRSI |

---

## 2. Anti-Pattern: `range(len(x))` (MEDIUM PRIORITY)

Using `range(len(x))` instead of direct iteration is less Pythonic and slightly slower.

### Examples Found (20+ instances):

```python
# src/intelligence/context/garch_volatility.py:58
for i in range(len(log_returns)):

# src/intelligence/indicators/rsi.py:55
for i in range(p, len(deltas)):

# src/intelligence/patterns/double_top_bottom.py:63
for p2_pos in range(len(peaks) - 1, 0, -1):

# src/intelligence/patterns/head_shoulders.py:66
for h_pos in range(1, len(peaks) - 1):
```

**Fix:** Use `enumerate()` or iterate directly:
```python
for i, val in enumerate(log_returns):  # Better
for p2_pos, peak in reversed(list(enumerate(peaks))[:-1]):  # For reversed
```

---

## 3. Too Many Branches/Statements (MEDIUM PRIORITY)

### 3.1 trend_regime.py - Too Many Branches (18)
**File:** `src/intelligence/context/trend_regime.py:27`
**Issue:** Function has 18 branches > 12 limit

**Fix:** Extract smaller helper functions, use lookup tables.

### 3.2 volatility_regime.py - Too Many Branches (13)
**File:** `src/intelligence/context/volatility_regime.py:29`
**Issue:** 13 branches > 12 limit

### 3.3 ma_composites.py - Too Many Statements (58)
**File:** `src/intelligence/composites/ma_composites.py:49`
**Issue:** Function has 58 statements > 50 limit

**Fix:** Break into smaller functions.

### 3.4 parabolic_sar.py - Too Many Statements (51)
**File:** `src/intelligence/indicators/parabolic_sar.py:31`

---

## 4. Code Style Issues (LOW PRIORITY)

### 4.1 Line Too Long (E501)

| File | Line | Length |
|-------|-------|---------|
| `indicators/chandelier.py` | 58 | 103 |
| `indicators/cmf.py` | 66 | 101 |
| `trading/momentum_breakout.py` | 109 | 112 |
| `trading/trade_framer.py` | 45 | 126 |
| `llm_providers.py` | 44, 50, 92, 127 | 101-105 |

### 4.2 Ambiguous Variable Names (E741)

| File | Line | Variable |
|-------|-------|----------|
| `indicators/chandelier.py` | 84 | `l` (looks like `1`) |
| `indicators/cmf.py` | 66 | `l` |

### 4.3 Avoid Using `elif` Instead of `else` + `if`

| File | Lines | Issue |
|-------|--------|--------|
| `indicators/parabolic_sar.py` | 69, 81, 119, 131 | `else: if` should be `elif` |

---

## 5. Magic Numbers (LOW PRIORITY)

30+ instances of hardcoded values that should be named constants:

### Notable Examples:

```python
# garch_volatility.py - Confidence intervals
2, 20, 25, 75, 95, 1e-10, 1e-15

# trend_regime.py - Thresholds
0.5, 0.1, -0.1, -0.5

# volatility_regime.py - Percentiles
0.20, 0.80, 0.95, 1.05

# kalman_trend.py
6, 2
```

**Fix:** Define module-level constants:
```python
CONFIDENCE_95 = 0.95
CONFIDENCE_75 = 0.75
TREND_THRESHOLD = 0.5
```

---

## Recommended Actions

### Phase 1: High Priority (Performance)
1. Refactor `head_shoulders.py` triple-nested loops
2. Optimize `aggregator.py` set operations
3. Vectorize cross_timeframe loops where possible

### Phase 2: Medium Priority (Maintainability)
4. Replace `range(len(x))` with `enumerate()` or direct iteration
5. Extract functions to reduce branch count in trend_regime/volatility_regime
6. Break up long functions in ma_composites/parabolic_sar

### Phase 3: Low Priority (Style)
7. Define constants for magic numbers
8. Fix line length issues
9. Rename ambiguous variables (`l` → `level` or similar)

---

## Notes

- Total files scanned: ~70 Python files across I1-I7
- 206 ruff issues found (includes style, refactoring, errors)
- 8 files have nested loop depth ≥ 2 (potential O(N²) concerns)
- 1 file has triple-nested loops (O(N³) - head_shoulders.py)
