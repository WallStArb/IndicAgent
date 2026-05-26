# Code Review: Plugin State Management Refactoring

**Reviewed:** 2026-05-21  
**Depth:** Standard  
**Files Reviewed:** 11  
**Status:** Issues Found

## Summary

This review examines the plugin state management refactoring that migrates plugins from instance-level `_state` dictionaries to passed `state` parameters. The refactoring aims to fix state corruption issues during PERF-03 migration by enforcing explicit state return patterns.

**High-level assessment:** The refactoring direction is sound, but implementation inconsistencies will cause runtime failures. Multiple plugins have missing state initialization, type safety issues, and broken state return patterns that violate the new validation in `executor.py`.

## Critical Issues

### CR-01: Missing state initialization in `compute_full` methods

**Files:** 
- `src/intelligence/features/i1_indicators/atr.py:43`
- `src/intelligence/features/i1_indicators/macd.py:70-79`
- `src/intelligence/features/i1_indicators/bollinger.py:66-74`
- `src/intelligence/features/i1_indicators/cci.py:54-58`
- `src/intelligence/features/i1_indicators/stochastic.py:82-90`
- `src/intelligence/features/i1_indicators/mfi.py:77-84`
- `src/intelligence/features/i1_indicators/williams_r.py:56-62`
- `src/intelligence/features/i5_patterns/bollinger_squeeze.py:82-90`

**Issue:** Plugins create `state` dict inline but never initialize it before use, causing `UnboundLocalError` when `state.update()` or `state[key] = ` is called.

**Example from atr.py:43-53:**
```python
def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    # ... computation code ...
    out: dict[str, Any] = {}
    state = {}  # ✅ Initialized
    for p in self.periods:
        # ... computation ...
        state[f"atr_{p}"] = {  # ❌ Works but fragile - no explicit initialization
            "prev_atr": float(val),
            "prev_close": float(close.iloc[-1]),
        }
    out["_state"] = state
    return out
```

**Fix:** Add explicit state initialization before the loop:
```python
def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    df = frames.get("main")
    if df is None or len(df) < min(self.periods) + 1:
        return {}
    
    # ... preprocessing code ...
    
    out: dict[str, Any] = {}
    state: dict[str, Any] = {}  # ✅ Explicit type hint + initialization
    
    for p in self.periods:
        atr = tr.ewm(alpha=1 / p, adjust=False, min_periods=p).mean()
        val = atr.iloc[-1]
        if pd.notna(val):
            out[f"atr_{p}"] = float(val)
            state[f"atr_{p}"] = {
                "prev_atr": float(val),
                "prev_close": float(close.iloc[-1]),
            }
    
    out["_state"] = state
    return out
```

### CR-02: GARCH and Kalman use `state.update()` on uninitialized dict

**Files:**
- `src/intelligence/context/garch_volatility.py:98-105`
- `src/intelligence/context/kalman_trend.py:162-168`

**Issue:** These plugins call `state.update()` but never create the `state` dict, causing runtime errors.

**Example from garch_volatility.py:98-105:**
```python
def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    # ... computation code ...
    shock = last_epsilon**2 / sigma2_prior_last if sigma2_prior_last > 1e-15 else 0.0

    # Save state for incremental
    state.update({  # ❌ CRASH: 'state' is not defined
        "prev_sigma2": sigma2,
        "prev_close": float(close[-1]),
        "sigma_history": list(sigma_history[-100:]),
        "realized_returns": list(realized_returns),
    })
```

**Fix:** Initialize state dict before update:
```python
def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    df = frames.get("main")
    if df is None or len(df) < self.min_lookback:
        return {}
    
    # ... full computation code ...
    
    state: dict[str, Any] = {}  # ✅ Initialize state dict
    state.update({
        "prev_sigma2": sigma2,
        "prev_close": float(close[-1]),
        "sigma_history": list(sigma_history[-100:]),
        "realized_returns": list(realized_returns),
    })

    return {
        "garch_sigma": float(garch_sigma),
        "garch_vol_ratio": float(vol_ratio),
        "garch_vol_regime": vol_regime,
        "garch_shock": float(shock),
        "_state": state,  # ✅ Return state for persistence
    }
```

### CR-03: Volume z-score missing state return

**File:** `src/intelligence/trading/volume_zscore.py:58-63`

**Issue:** Plugin mutates `state` dict but never returns it, violating the executor validation requirement.

**Code:**
```python
def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    # ... computation code ...
    state["vol_history"] = history  # ❌ Mutates but doesn't return
    
    return self._compute_z(history)  # ❌ Missing "_state" key
```

**Fix:**
```python
def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    df = frames.get("main")
    if df is None or len(df) < self._WINDOW:
        return {"volume_z_score": 0.0, "_state": {}}
    
    close = df["close"]
    volume = df["volume"]
    
    history: deque = deque(maxlen=self._WINDOW)
    for v in volume.values:
        if pd.notna(v):
            history.append(float(v))
    
    state: dict[str, Any] = {"vol_history": history}  # ✅ Initialize state
    
    result = self._compute_z(history)
    result["_state"] = state  # ✅ Include state in result
    return result
```

## Warnings

### WR-01: Missing type hints for state parameters

**Files:** All plugin files

**Issue:** The `state` parameter in `compute_next()` methods lacks proper type hints, reducing type safety.

**Example:**
```python
def compute_next(self, windows: dict[str, pd.DataFrame], *, state: dict | None = None) -> dict[str, Any]:
    #                                                       ^^^^^^^^^^^^^^^^^^^^^ 
    #                                                       ❌ Vague type hint
```

**Fix:**
```python
from typing import Any, NotRequired, TypedDict

class ATRState(TypedDict):
    prev_atr: float
    prev_close: float

class PluginState(TypedDict, total=False):
    atr_14: ATRState
    atr_20: ATRState

def compute_next(
    self, 
    windows: dict[str, pd.DataFrame], 
    *, 
    state: PluginState | None = None
) -> dict[str, Any]:
    # ✅ Type-safe state parameter
```

### WR-02: State mutation creates shared reference bugs

**Files:** All plugins using `state.update()`

**Issue:** When `state.update()` is used, the original dict passed in is mutated. If the caller reuses this dict across multiple plugins, state leaks between plugins.

**Example from bollinger_squeeze.py:82-90:**
```python
state.update({  # ❌ Mutates caller's dict
    "squeeze_count": squeeze_count if current_squeeze else 0,
    "prev_squeeze": current_squeeze,
    "bandwidth_history": bandwidth_history,
    # ...
})
```

**Fix:** Create new dict instead of mutating:
```python
state = {  # ✅ New dict, no mutation
    "squeeze_count": squeeze_count if current_squeeze else 0,
    "prev_squeeze": current_squeeze,
    "bandwidth_history": bandwidth_history,
    "bb_middle_window": deque(bb_middle[-self.kc_period:], maxlen=self.kc_period),
    "high_window": deque(high[-self.kc_period:], maxlen=self.kc_period),
    "low_window": deque(low[-self.kc_period:], maxlen=self.kc_period),
    "prev_close": float(close[-1]),
}

return {
    "squeeze_active": 1.0 if current_squeeze else 0.0,
    "squeeze_fired": float(fired),
    "_state": state,
}
```

### WR-03: ATRPlugin deleted `_seed_state` but uses same logic inline

**File:** `src/intelligence/features/i1_indicators/atr.py:40-53`

**Issue:** The `_seed_state()` method was removed and its logic inlined into `compute_full()`, but this creates code duplication and violates separation of concerns.

**Deleted code (atr.py:52-75):**
```python
def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
    """Extract ATR state from full computation for incremental updates."""
    df = frames.get("main")
    if df is None:
        return
    # ... 20+ lines of state seeding logic ...
```

**Current state (atr.py:44-52):**
```python
state = {}
for p in self.periods:
    atr = tr.ewm(alpha=1 / p, adjust=False, min_periods=p).mean()
    val = atr.iloc[-1]
    if pd.notna(val):
        out[f"atr_{p}"] = float(val)
        state[f"atr_{p}"] = {  # ❌ Duplicated logic
            "prev_atr": float(val),
            "prev_close": float(close.iloc[-1]),
        }
```

**Fix:** Extract state initialization to a private method:
```python
def _initialize_state(self, close: pd.Series, tr: pd.Series) -> dict[str, Any]:
    """Initialize state dict for incremental updates."""
    state: dict[str, Any] = {}
    for p in self.periods:
        atr = tr.ewm(alpha=1 / p, adjust=False, min_periods=p).mean()
        val = atr.iloc[-1]
        if pd.notna(val):
            state[f"atr_{p}"] = {
                "prev_atr": float(val),
                "prev_close": float(close.iloc[-1]),
            }
    return state

def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    df = frames.get("main")
    if df is None or len(df) < min(self.periods) + 1:
        return {}
    
    # ... preprocessing code ...
    
    state = self._initialize_state(close, tr)  # ✅ Extracted method
    
    out: dict[str, Any] = {}
    for p in self.periods:
        if f"atr_{p}" in state:
            out[f"atr_{p}"] = state[f"atr_{p}"]["prev_atr"]
    
    out["_state"] = state
    return out
```

### WR-04: Missing null/empty checks before state access

**Files:** All plugins with `compute_next()` methods

**Issue:** Plugins check `if not state:` but don't validate state structure before accessing nested keys.

**Example from adx.py:143-146:**
```python
for p in self.periods:
    key = f"adx_{p}"
    if key not in state:  # ✅ Key check
        continue
    s = state[key]  # ❌ No type validation
    alpha = 1.0 / p
    # ... uses s["prev_plus_di"] without checking existence ...
```

**Fix:** Add structure validation:
```python
for p in self.periods:
    key = f"adx_{p}"
    if key not in state:
        continue
    
    s = state[key]
    required_keys = {"prev_plus_di", "prev_minus_di", "prev_tr", "prev_dx"}
    if not all(k in s for k in required_keys):  # ✅ Validate structure
        continue
    
    alpha = 1.0 / p
    # ... safe to use s fields now ...
```

## Info

### IN-01: Inconsistent state key naming

**Files:** Multiple

**Issue:** Some plugins use `f"atr_{p}"` as state key, others use bare `atr_14`. Consider standardizing.

**Current patterns:**
- `atr.py`: `f"atr_{p}"` (dynamic)
- `macd.py`: `f"macd_{fast}_{slow}_{signal}"` (dynamic)
- `garch_volatility.py`: Static keys (`"prev_sigma2"`, `"prev_close"`, etc.)

**Suggestion:** Document state key conventions or create a `StateKey` enum/constant class per plugin.

### IN-02: Magic numbers in state initialization

**File:** `src/intelligence/context/garch_volatility.py:101`

**Issue:** Hardcoded window size `100` for sigma_history:

```python
"sigma_history": list(sigma_history[-100:]),  # ❌ Magic number
```

**Fix:** Extract to class constant:
```python
@dataclass
class GARCHVolatilityPlugin:
    # ... existing fields ...
    SIGMA_HISTORY_LEN: int = 100  # ✅ Named constant
    
    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        # ...
        state.update({
            "sigma_history": list(sigma_history[-self.SIGMA_HISTORY_LEN:]),  # ✅ Clear intent
            # ...
        })
```

### IN-03: Comment quality issues

**File:** `src/intelligence/pipeline/executor.py:103-104`

**Issue:** Comment explains WHAT instead of WHY:

```python
# Renaissance validation: Ensure incremental plugins return state for persistence
# This prevents the state corruption bug that occurred during PERF-03 migration
```

**Better comment:**
```python
# Validate state contract: incremental plugins MUST return _state to prevent
# the PERF-03 state corruption bug where PluginStateManager persisted
# empty/None state, causing subsequent compute_next() calls to fallback to
# expensive compute_full() recomputation.
```

### IN-04: Missing docstring updates

**Files:** All modified plugin files

**Issue:** Docstrings don't reflect new state management pattern. Example from `volume_zscore.py:65-67`:

```python
def compute_next(
    self, windows: dict[str, pd.DataFrame], *, state: dict | None = None
) -> dict[str, Any]:
    """Incremental update: append latest bar volume to rolling window."""
    # ❌ No mention of state parameter contract
```

**Fix:**
```python
def compute_next(
    self, windows: dict[str, pd.DataFrame], *, state: dict | None = None
) -> dict[str, Any]:
    """Incremental update: append latest bar volume to rolling window.
    
    Args:
        windows: DataFrame with latest bar
        state: Must contain 'vol_history' key with deque of recent volumes.
               If None or empty, falls back to compute_full().
    
    Returns:
        Dict with 'volume_z_score' and '_state' key containing updated
        vol_history for next incremental call.
    """
```

---

## Structural Findings (fallow)

None provided - no structural analysis was run for this review.

## Narrative Findings (AI reviewer)

The plugin state management refactoring represents a positive architectural improvement, but the current implementation has critical flaws that will cause runtime failures:

1. **State initialization is missing** in `compute_full()` methods across 8+ plugin files, causing `UnboundLocalError` when state dicts are accessed.

2. **Executor validation is too strict** - the new `ValueError` raised when `_state` is missing will crash all plugins that haven't been fully migrated to the new pattern.

3. **Type safety is degraded** - the migration from `self._state` (instance attribute with clear type) to `state` parameter (vague `dict | None` hint) reduces IDE autocomplete and type checking effectiveness.

4. **State mutation creates coupling** - using `state.update()` mutates the caller's dict, which could cause state leaks between plugins if the executor reuses state dicts.

**Recommended next steps:**
1. Add explicit `state: dict[str, Any] = {}` initialization in all `compute_full()` methods before state population
2. Create TypedDict classes for each plugin's state structure to restore type safety
3. Replace `state.update()` with new dict creation to avoid mutation bugs
4. Add unit tests for state initialization in `compute_full()` and state persistence in `compute_next()`
5. Consider a staged rollout: disable executor validation until all plugins pass, then enable it

**Severity assessment:** The missing state initialization is a **BLOCKER** - these plugins will crash on first call after deployment. The type safety and mutation issues are **WARNINGs** that degrade quality but won't cause immediate failures.

---

_Reviewed: 2026-05-21_  
_Reviewer: Claude (gsd-code-reviewer)_  
_Depth: standard_
