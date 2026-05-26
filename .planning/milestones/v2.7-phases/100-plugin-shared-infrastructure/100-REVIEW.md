---
phase: 100-plugin-shared-infrastructure
reviewed: 2026-05-21T00:00:00Z
depth: standard
files_reviewed: 27
files_reviewed_list:
  - src/intelligence/composites/ma_composites.py
  - src/intelligence/features/i1_indicators/ac_oscillator.py
  - src/intelligence/features/i1_indicators/adx.py
  - src/intelligence/features/i1_indicators/atr.py
  - src/intelligence/features/i1_indicators/bollinger.py
  - src/intelligence/features/i1_indicators/cci.py
  - src/intelligence/features/i1_indicators/cmf.py
  - src/intelligence/features/i1_indicators/cvd.py
  - src/intelligence/features/i1_indicators/keltner.py
  - src/intelligence/features/i1_indicators/macd.py
  - src/intelligence/features/i1_indicators/mfi.py
  - src/intelligence/features/i1_indicators/moving_averages.py
  - src/intelligence/features/i1_indicators/ofi.py
  - src/intelligence/features/i1_indicators/roc_ppo.py
  - src/intelligence/features/i1_indicators/rsi.py
  - src/intelligence/features/i1_indicators/stochastic.py
  - src/intelligence/features/i1_indicators/williams_r.py
  - src/intelligence/features/i3_structure/market_profile.py
  - src/intelligence/features/i3_structure/session_levels.py
  - src/intelligence/features/smc_context/bocpd_changepoint.py
  - src/intelligence/plugins/base.py
  - src/intelligence/plugins/__init__.py
  - src/intelligence/plugins/mixins.py
  - src/intelligence/trading/volume_zscore.py
  - tests/unit/intelligence/indicators/test_rsi_characterization.py
  - tests/unit/intelligence/test_incremental_mixin.py
  - tests/unit/intelligence/test_plugin_mixins.py
findings:
  critical: 3
  warning: 6
  info: 3
  total: 12
status: issues_found
---

# Phase 100: Code Review Report

**Reviewed:** 2026-05-21
**Depth:** standard
**Files Reviewed:** 27
**Status:** issues_found

## Summary

This phase delivers plugin shared infrastructure: `IncrementalMixin`, shared utility functions (`wilders_update`, `update_ema`, `get_main_df`), migration of 6 indicator plugins to the mixin, and a new `PluginRegistry.validate_tier()` guard. The core infrastructure (`mixins.py`, `base.py`, ATR/ADX/Stochastic/WilliamsR/MFI/Keltner/VolumeZscore via IncrementalMixin) is sound. Three critical defects were found: a wrong output key in `ma_composites.py` (declared vs. written key mismatch), incorrect `prior_session_close` value in `session_levels.py`'s incremental session rollover, and CVD state commingling across symbols in multi-symbol deployments. Six warnings cover protocol violations (missing `_state` in compute_next returns, `if not state` vs. `if state is None`, misleading BOCPD comment) and a per-instance state footgun in non-mixin plugins.

## Critical Issues

### CR-01: MACompositePlugin writes undeclared output key and never writes declared key

**File:** `src/intelligence/composites/ma_composites.py:30,142`
**Issue:** The `outputs` frozenset on line 30 declares `"price_above_sma_50"`. The `compute_full` method at line 142 writes `out["price_above_sma200"]` instead. The declared key is never written; the written key is never declared. Any downstream consumer reading `price_above_sma_50` from features gets `None`/`KeyError`. Any schema validation or tier validation against the `outputs` declaration will miss `price_above_sma200`.

**Fix:**
```python
# In outputs frozenset (line 30) change:
"price_above_sma_50",
# to:
"price_above_sma200",

# OR in compute_full (line 142) change:
out["price_above_sma200"] = linear_ramp(px_s200_sep_pct, -2.0, 2.0)
# to:
out["price_above_sma_50"] = linear_ramp(px_s200_sep_pct, -2.0, 2.0)
# (and align the guard condition to use s50, not s200, for "price above sma_50")
```
Note: the intent is ambiguous. The guard on line 122 checks `is_num(s200)` before writing, suggesting this block computes distance from SMA200, not SMA50. The `outputs` declaration is likely what needs correcting -- change it to `"price_above_sma200"`.

---

### CR-02: SessionLevelsPlugin.compute_next sets prior_session_close to the WRONG bar

**File:** `src/intelligence/features/i3_structure/session_levels.py:269`
**Issue:** When `new_session` fires (line 265), the code sets:
```python
state["prior_session_close"] = bar_close  # last bar of old session
```
But `bar_close` is `float(bar["close"])` where `bar = df.iloc[-1]` -- the CURRENT bar that triggered the session rollover. This is the **first** bar of the new session (conceptually), not the last close of the old session. The `compute_full` reference path correctly sets `prior_session_close = float(prior["close"].iloc[-1])` which is the last close of the prior session block. The incremental path sets it to the wrong bar, producing incorrect `opening_gap_pct` for every subsequent bar in the new session.

**Fix:**
```python
if new_session:
    # Roll: current session becomes prior session
    state["prior_session_high"] = state.get("session_high")
    state["prior_session_low"] = state.get("session_low")
    # Use the last bar of the PREVIOUS session (last known session close), not the current bar
    state["prior_session_close"] = state.get("session_close_last")  # must be tracked
    # ... or derive from the running session state before reset:
    # The old session_high/low are already in state; also track the last session close:
    state["prior_session_close"] = state.get("session_close_running")
```
The fix requires adding a `session_close_running` (or equivalent) field that tracks the most recent close within the current session. Seed it in `compute_full` as the last close of the current session slice, and update it on every non-rollover bar in `compute_next`.

---

### CR-03: CVDPlugin._state is not keyed per symbol -- cross-symbol contamination

**File:** `src/intelligence/features/i1_indicators/cvd.py:68-113`
**Issue:** CVD stores all session state (`cum_cvd`, `cvd_history`, `delta_history`) directly in `self._state` with no per-symbol key. The module-level singleton `plugin = CVDPlugin()` is shared across all symbols. In a multi-symbol deployment (e.g., ES and NQ both flowing through the pipeline), every bar for any symbol accumulates into the same `cum_cvd` and history deques, producing nonsense output. The docstring on line 36 says "per-symbol self._state architecture" but the implementation does not implement it.

Compare OFI (the sibling plugin), which correctly keys state as `state_key = f"{symbol}_{tf}"` and uses `self._state.setdefault(state_key, {})`.

**Fix:**
```python
def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    df = frames.get("main")
    tick_buf = frames.get("tick_buffer") or []
    symbol = frames.get("__symbol__", "_")
    tf = frames.get("__timeframe__", "_")
    state_key = f"{symbol}_{tf}"

    if df is None or len(df) < self.min_lookback:
        return {}

    # Per-(symbol, tf) state
    state = self._state.setdefault(state_key, {})

    # Use `state` instead of `self._state` for all subsequent reads/writes
    ts = self._extract_ts(df)
    if ts is not None:
        et_dt = ts.astimezone(_ET_TZ)
        ...
        last_session_date = state.get("last_session_date")
        if et_hour == 9 and et_minute >= 30 and et_date != last_session_date:
            state["cum_cvd"] = 0.0
            state["last_session_date"] = et_date

    state["cum_cvd"] = state.get("cum_cvd", 0.0) + bar_delta
    # ... continue with `state` instead of `self._state`
    return {
        "cvd": ...,
        "_state": self._state,  # still return entire per-symbol dict for executor
    }
```

---

## Warnings

### WR-01: ROCPPOPlugin.compute_next and ACOscillatorPlugin.compute_next do not return `_state`

**File:** `src/intelligence/features/i1_indicators/roc_ppo.py:126`, `src/intelligence/features/i1_indicators/ac_oscillator.py:129`
**Issue:** Both plugins declare `supports_incremental: bool = True` but their `compute_next` methods return output dicts without `"_state"`. The executor threads state by reading `result["_state"]` and passing it as `state=` on the next call. Without `_state` in the return, the executor passes `state=None` on every subsequent call. These plugins recover because they fall back to `if not self._state:` (instance-level check) rather than the `state` parameter, but this is fragile: the `state` parameter is completely ignored and executor state threading is broken.

The test suite (`test_plugin_mixins.py:test_incremental_plugins_return_state`) is supposed to catch this but does not, because both plugins reference `self._state` in their `compute_next` bodies, satisfying the string-match check `"_state" not in source`.

**Fix (roc_ppo.py):**
```python
def compute_next(...) -> dict[str, Any]:
    if not self._state:
        return self.compute_full(windows)
    ...
    out[f"ppo_signal_{self.ppo_fast}_{self.ppo_slow}"] = s["ppo_signal_ema"]
    out["_state"] = self._state  # ADD THIS LINE
    return out
```

**Fix (ac_oscillator.py):**
```python
    return {"ao": float(ao), "ac": float(ac), "_state": self._state}  # add _state
```

---

### WR-02: RSI, MACD, Bollinger, CCI, CMF, MovingAverages use `if not state` instead of `if state is None`

**File:** `src/intelligence/features/i1_indicators/rsi.py:70`, `macd.py:85`, `bollinger.py:72`, `cci.py:67`, `cmf.py:60`, `moving_averages.py:99`
**Issue:** The `IncrementalMixin` documents the critical contract: `compute_next` must use `state is None` (identity check), not `if not state` (truthiness). An empty dict `{}` is a valid seeded state (e.g., when `_seed_state` found no data to seed). Using `if not state` silently falls back to `compute_full` when passed `{}`, which violates the expected behavior documented in the mixin and tested in `test_empty_dict_state_does_NOT_trigger_fallback`. These six plugins are not yet using `IncrementalMixin`, so they don't benefit from the mixin's correct `None` check.

**Fix:** For each plugin's `compute_next`:
```python
# Change:
if not state:
    return self.compute_full(windows)
# To:
if state is None:
    return self.compute_full(windows)
```

---

### WR-03: BOCPD shallow copy comment is misleading -- numpy arrays in returned `_state` are still shared

**File:** `src/intelligence/features/smc_context/bocpd_changepoint.py:106`
**Issue:** `compute_full` returns `"_state": dict(self._state)` with comment "Shallow copy to prevent caller mutation." The `dict()` constructor creates a new dict object, but the values (`run_length_probs`, `mu`, `kappa`, `alpha`, `beta` numpy arrays) are still the same array objects. A caller that mutates `result["_state"]["run_length_probs"]` will corrupt `self._state["run_length_probs"]`. This was confirmed: after `compute_full`, mutating the returned state's array directly mutates `p._state`.

This is particularly dangerous because `_reset_state()` is called on every `compute_full`, overwriting `self._state` entirely with fresh arrays. The shared arrays from the previous `compute_full` call persist in any held reference. The comment gives false confidence.

**Fix:**
```python
import copy
return {
    ...
    "_state": copy.deepcopy(self._state),  # True deep copy -- numpy arrays are independent
}
```
Or document explicitly that the returned state is a view and callers must not mutate it.

---

### WR-04: MovingAveragesPlugin uses `self._state` in `compute_full` and `_seed_state` instead of local state

**File:** `src/intelligence/features/i1_indicators/moving_averages.py:67-68,83,94`
**Issue:** `compute_full` calls `self._seed_state(frames)` which mutates `self._state` in place, then does `out["_state"] = self._state`. This means:
1. Two concurrent calls to `compute_full` on the same singleton instance will race on `self._state`.
2. The returned `_state` reference IS `self._state` -- any executor mutation of the returned dict mutates the plugin's own instance state.

Other non-mixin plugins (RSI, MACD, Bollinger, CCI) build local `state = {}` and populate it separately, avoiding shared reference. MovingAverages is the only one that aliases the instance dict into the output.

**Fix:**
```python
def compute_full(self, frames, *, state=None):
    ...
    new_state = {}
    self._populate_state(frames, new_state)  # fills new_state, not self._state
    out["_state"] = new_state
    self._state = new_state  # optional: keep instance var in sync for legacy callers
    return out
```

---

### WR-05: Multiple dataclass fields typed `list[int] = None` instead of `field(default=None)`

**File:** `rsi.py:21`, `atr.py:44`, `adx.py:45`, `macd.py:22`, `bollinger.py:21`, `stochastic.py:40`, `williams_r.py:39`, `mfi.py:44`
**Issue:** Assigning `None` as the default for a field typed `list[int]` or `list[tuple]` in a dataclass is technically a type lie and will trigger mypy/pyright strict errors. The correct pattern is `field(default=None)` or use `Optional[list[int]] = None`. While Python does not enforce this at runtime (None is the sentinel that `__post_init__` replaces), static type checkers will flag all call sites.

**Fix:**
```python
from dataclasses import dataclass, field
from typing import Optional

periods: Optional[list[int]] = field(default=None)
# or simply:
periods: list[int] | None = field(default=None)
```

---

### WR-06: CVDPlugin comment on line 36 claims per-symbol architecture that does not exist

**File:** `src/intelligence/features/i1_indicators/cvd.py:36`
**Issue:** The comment reads `"Delegation pattern: compute_next delegates to compute_full (per-symbol self._state architecture)"`. There is no per-symbol architecture -- state is flat in `self._state` (see CR-03). This misleading comment may cause future developers to believe the architecture is safe for multi-symbol use when it is not.

**Fix:** Remove "per-symbol" from the comment and add a note that per-symbol keying is needed. Cross-reference the OFI plugin as the correct pattern.

---

## Info

### IN-01: `valid_asset_classes` Protocol attribute not implemented on any plugin

**File:** `src/intelligence/plugins/base.py:25,48`
**Issue:** Both `IndicatorPlugin` and `PatternPlugin` Protocol definitions require `valid_asset_classes: ClassVar[frozenset[AssetClass]]`, but none of the reviewed plugins implement this attribute. This means no plugin fully conforms to either Protocol. Runtime structural typing checks against the Protocol would fail silently; explicit `isinstance` checks would fail loudly.

**Fix:** Either add `valid_asset_classes: ClassVar[frozenset[AssetClass]] = frozenset()` as a default on a base class all plugins inherit, or remove the attribute from the Protocol if it is not enforced anywhere.

---

### IN-02: RSI `compute_full` signature doesn't accept `*, state=None` unlike Protocol

**File:** `src/intelligence/features/i1_indicators/rsi.py:29`
**Issue:** The `IndicatorPlugin` Protocol defines `compute_full(self, frames, *, state=None)`. `RSIPlugin.compute_full` is defined as `compute_full(self, frames)` without the `state` keyword argument. Callers passing `state=` to RSI's `compute_full` will get a `TypeError`. The other non-mixin plugins (MACD, Bollinger, CCI, CMF) correctly include `*, state=None`.

**Fix:**
```python
def compute_full(self, frames: dict[str, pd.DataFrame], *, state: dict | None = None) -> dict[str, Any]:
```

---

### IN-03: Session boundary detection in `compute_next` is off-by-one (heuristic only)

**File:** `src/intelligence/features/i3_structure/session_levels.py:263`
**Issue:** `new_session = current_session_length > _SESSION_BARS` where `_SESSION_BARS = 390`. A session fires as "new" after 391 bars since `session_start_idx`, not 390. For 1m bars this means sessions are detected 1 minute late. Given that session boundaries are already approximated by bar-count rather than clock time (documented intent), this is a minor precision issue rather than a correctness failure.

**Fix:** Change to `>= _SESSION_BARS` if exact alignment to 390 bars is desired:
```python
new_session = current_session_length >= _SESSION_BARS
```

---

_Reviewed: 2026-05-21_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
