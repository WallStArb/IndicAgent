# Plugin State Migration Fix Implementation Plan

**Version:** 1.0
**Last Updated:** 2026-05-27
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix incomplete Renaissance refactoring that broke 12+ plugins by migrating them from removed `self._state` pattern to parameter-based `state` pattern

**Architecture:** The executor passes `state` dict as parameter to `compute_next()`, plugins mutate it in-place, and return it via `_state` key for extraction. Single source of truth, no dual-state corruption.

**Tech Stack:** Python 3.13, dataclasses, pytest, systemd service management

---

## Root Cause Analysis

The Renaissance fix removed `self._state` from plugin dataclasses and updated `compute_next()` signature to accept `state` as a parameter, but only completed migration for SOME plugins (e.g., RSI works correctly).

**Three incompatible patterns created:**

1. **Pattern 1 (WORKING):** Fully migrated to parameter-state
   - Examples: RSI, BollingerBands, Stochastic, CCI, WilliamsR, MFI, ATR
   - ✅ Uses `state` parameter
   - ✅ Returns `{"_state": state}`

2. **Pattern 2 (BROKEN - 10 plugins):** Half-migrated, still references `self._state`
   - Examples: ParabolicSAR, ACOscillator, Keltner, Aroon, CMF, Donchian, Chandelier, HistoricalVolatility, ROC_PPO, StochasticRSI
   - ❌ Line `s = self._state` fails with "name 'state' is not defined"
   - ❌ self._state no longer exists in compute_next context

3. **Pattern 3a (BROKEN - 2 plugins):** False incremental claims
   - Examples: OFI, CVD
   - ❌ Marked `supports_incremental: True` but `compute_next` just calls `compute_full`
   - ❌ Don't return `{"_state": state}`

**Evidence:** Pipeline logs show `"name 'state' is not defined"` and `"incremental plugins MUST return _state in result dict"` errors during bar processing.

## Strategy

**Renaissance Principles:**
- **Modularity:** Each plugin owns its state management
- **Simplicity:** Don't implement complex incremental logic until needed (mark non-incremental for now)
- **Correctness:** Eliminate dual-state pattern completely
- **Efficiency:** Fix broken plugins, defer optimization

**Approach:**
1. Fix Pattern 2 plugins: Replace `s = self._state` with proper `state` parameter usage (follow RSI pattern)
2. Fix Pattern 3a plugins: Mark as `supports_incremental: False` until proper implementation
3. Verify Pattern 1 plugins still work correctly

---

## Task 1: Verify Working Pattern (RSI) as Reference

**Files:**
- Read: `src/intelligence/features/i1_indicators/rsi.py:64-92`

- [ ] **Step 1: Document RSI working pattern**

Read lines 64-92 of `rsi.py` to confirm the working pattern:

```python
def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
    if not state:
        return self.compute_full(windows)

    # Use state PARAMETER, not self._state
    s = state[key]              # ✅ CORRECT

    # Mutate state dict in-place
    s["avg_gain"] = new_value   # ✅ CORRECT

    # CRITICAL: Return state for executor to extract
    out["_state"] = state       # ✅ CRITICAL
    return out
```

Expected: RSI shows correct parameter-state usage with `_state` return

---

## Task 2: Fix Pattern 2 Plugins - Replace self._state References

**Strategy:** Replace `s = self._state` with `s = state[key]` following RSI pattern

### Task 2.1: Fix ParabolicSAR Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/parabolic_sar.py:113-146`

- [ ] **Step 1: Read current broken implementation**

Read lines 104-146 to understand current state reference pattern

Expected: Line 113 shows `s = self._state` (broken)

- [ ] **Step 2: Replace self._state with state parameter access**

Change line 113 from:
```python
s = self._state
```

To:
```python
# state parameter keyed by plugin name
s = state.get("psar")
if s is None:
    # First run, seed from compute_full
    return self.compute_full(windows)
```

Expected: Uses `state` parameter instead of removed `self._state`

- [ ] **Step 3: Add _state return to output**

Before the `return` statement (line 146), add:
```python
return {"psar_value": new_sar, "psar_direction": s["direction"], "_state": state}
```

Expected: Returns state dict for executor extraction

- [ ] **Step 4: Verify syntax**

Run: `python3 -m py_compile src/intelligence/features/i1_indicators/parabolic_sar.py`

Expected: No syntax errors

---

### Task 2.2: Fix ACOscillator Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/ac_oscillator.py:92-103`

- [ ] **Step 1: Replace self._state reference**

Change line 92 from:
```python
s = self._state
```

To:
```python
s = state.get("ac_osc")
if s is None:
    return {}
```

Expected: Uses state parameter with fallback

- [ ] **Step 2: Add _state return**

Add to output dict before return:
```python
return {
    "ao_value": round(ao, 4),
    "ac_value": round(ac, 4),
    "_state": state
}
```

Expected: Returns state for extraction

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile src/intelligence/features/i1_indicators/ac_oscillator.py`

Expected: No syntax errors

---

### Task 2.3: Fix KeltnerChannels Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/keltner.py:109-130`

- [ ] **Step 1: Replace self._state reference**

Change line 109 from:
```python
s = self._state
```

To:
```python
s = state.get("keltner")
if s is None:
    return {}
```

- [ ] **Step 2: Add _state return**

Before return statement, add:
```python
return {
    "kc_upper": round(upper, 6),
    "kc_lower": round(lower, 6),
    "kc_middle": round(middle, 6),
    "_state": state
}
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile src/intelligence/features/i1_indicators/keltner.py`

---

### Task 2.4: Fix Aroon Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/aroon.py:66-77`

- [ ] **Step 1: Replace self._state reference**

Change line 66 from:
```python
s = self._state
```

To:
```python
s = state.get("aroon")
if s is None:
    return {}
```

- [ ] **Step 2: Add _state return**

Modify return to:
```python
return {
    "aroon_up_25": round(aroon_up, 2),
    "aroon_down_25": round(aroon_down, 2),
    "aroon_osc_25": round(aroon_up - aroon_down, 2),
    "_state": state
}
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile src/intelligence/features/i1_indicators/aroon.py`

---

### Task 2.5: Fix CMF Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/cmf.py:70-82`

- [ ] **Step 1: Replace self._state reference**

Change line 70 from:
```python
s = self._state
```

To:
```python
s = state.get("cmf")
if s is None:
    return {}
```

- [ ] **Step 2: Add _state return**

Modify return to:
```python
return {"cmf_20": round(cmf, 6), "_state": state}
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile src/intelligence/features/i1_indicators/cmf.py`

---

### Task 2.6: Fix DonchianChannels Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/donchian.py:78-85`

- [ ] **Step 1: Replace self._state reference**

Change line 78 from:
```python
s = self._state
```

To:
```python
s = state.get("donchian")
if s is None:
    return {}
```

- [ ] **Step 2: Add _state return**

Modify return to:
```python
return {
    "donchian_upper": round(upper, 6),
    "donchian_lower": round(lower, 6),
    "donchian_middle": round(middle, 6),
    "_state": state
}
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile src/intelligence/features/i1_indicators/donchian.py`

---

### Task 2.7: Fix ChandelierExit Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/chandelier.py:87-103`

- [ ] **Step 1: Replace self._state reference**

Change line 87 from:
```python
s = self._state
```

To:
```python
s = state.get("chandelier")
if s is None:
    return {}
```

- [ ] **Step 2: Add _state return**

Modify return to include:
```python
return {
    "chandelier_long_22": round(highest_high - self.multiplier * atr, 6),
    "chandelier_short_22": round(lowest_low + self.multiplier * atr, 6),
    "_state": state
}
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile src/intelligence/features/i1_indicators/chandelier.py`

---

### Task 2.8: Fix HistoricalVolatility Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/historical_volatility.py:72-83`

- [ ] **Step 1: Replace self._state reference**

Change line 72 from:
```python
s = self._state
```

To:
```python
s = state.get("hv")
if s is None:
    return {}
```

- [ ] **Step 2: Add _state return**

Modify return to:
```python
return {
    "hv_20": round(hv_20, 6),
    "hv_ratio_20": round(hv_ratio, 4),
    "_state": state
}
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile src/intelligence/features/i1_indicators/historical_volatility.py`

---

### Task 2.9: Fix ROC_PPO Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/roc_ppo.py:101-115`

- [ ] **Step 1: Replace self._state reference**

Change line 101 from:
```python
s = self._state
```

To:
```python
s = state.get("roc_ppo")
if s is None:
    return {}
```

- [ ] **Step 2: Add _state return**

Modify return to:
```python
return {
    "roc_6": round(roc, 6),
    "ppo_12_26_9": round(ppo, 6),
    "ppo_signal_12_26_9": round(ppo_sig, 6),
    "_state": state
}
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile src/intelligence/features/i1_indicators/roc_ppo.py`

---

### Task 2.10: Fix StochasticRSI Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/stochastic_rsi.py:96-107`

- [ ] **Step 1: Replace self._state reference**

Change line 96 from:
```python
s = self._state
```

To:
```python
s = state.get("stoch_rsi")
if s is None:
    return {}
```

- [ ] **Step 2: Add _state return**

Modify return to:
```python
return {
    "stoch_rsi_k_14": round(k, 4),
    "stoch_rsi_d_14": round(d, 4),
    "_state": state
}
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile src/intelligence/features/i1_indicators/stochastic_rsi.py`

---

## Task 3: Fix Pattern 3a Plugins - Remove False Incremental Claims

**Strategy:** Mark as non-incremental until proper implementation (YAGNI principle)

### Task 3.1: Fix OFI Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/ofi.py:42,145`

- [ ] **Step 1: Mark as non-incremental**

Change line 42 from:
```python
supports_incremental: bool = True
```

To:
```python
supports_incremental: bool = False
```

Expected: No longer claims incremental support

- [ ] **Step 2: Simplify compute_next**

Change lines 144-145 from:
```python
def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
    return self.compute_full(windows)
```

To:
```python
def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
    # Not implemented - delegate to compute_full
    return self.compute_full(windows)
```

Expected: Clear comment about non-implementation

---

### Task 3.2: Fix CVD Plugin

**Files:**
- Modify: `src/intelligence/features/i1_indicators/cvd.py:36,88`

- [ ] **Step 1: Mark as non-incremental**

Change line 36 from:
```python
supports_incremental: bool = True
```

To:
```python
supports_incremental: bool = False
```

- [ ] **Step 2: Add comment to compute_next**

Change lines 87-88 to:
```python
def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
    # Not implemented - delegate to compute_full
    return self.compute_full(windows)
```

---

## Task 4: Verify All Indicator Files Compile

**Files:**
- Test: All `src/intelligence/features/i1_indicators/*.py`

- [ ] **Step 1: Compile all I1 indicator plugins**

Run:
```bash
python3 -m py_compile src/intelligence/features/i1_indicators/*.py
```

Expected: No output (no syntax errors)

- [ ] **Step 2: Compile all context plugins**

Run:
```bash
python3 -m py_compile src/intelligence/context/*.py
```

Expected: No output

- [ ] **Step 3: Compile all I5 pattern plugins**

Run:
```bash
python3 -m py_compile src/intelligence/features/i5_patterns/*.py
```

Expected: No output

---

## Task 5: Restart Pipeline and Verify Fix

**Files:**
- System: `indicagent-intelligence-pipeline.service`

- [ ] **Step 1: Restart intelligence pipeline**

Run:
```bash
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl restart indicagent-intelligence-pipeline
```

Expected: No output (restarts silently)

- [ ] **Step 2: Wait and check service status**

Run:
```bash
sleep 5 && echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl status indicagent-intelligence-pipeline
```

Expected: `Active: active (running)` with green indicator

- [ ] **Step 3: Check logs for plugin errors**

Run:
```bash
tail -30 logs/intelligence_pipeline_agent.log | grep -E "(plugin\.error|name 'state' is not defined|MUST return _state)"
```

Expected: No output (no plugin errors)

- [ ] **Step 4: Monitor for successful bar processing**

Run:
```bash
tail -f logs/intelligence_pipeline_agent.log | grep -E "(agent\.setup_complete|intelligence_pipeline\.bar_processed)" | head -5
```

Expected: See setup_complete and bar_processed messages without errors

- [ ] **Step 5: Verify ATR values are normalized**

Run:
```bash
sleep 10 && curl -s localhost:8000/metrics | grep "atr_" | grep ESM6 | head -3
```

Expected: ATR values between 0.1 and 10.0 (not 6000+ like before fix)

---

## Task 6: Commit Fixes

**Files:**
- Git: All modified plugin files

- [ ] **Step 1: Check modified files**

Run:
```bash
git status --short src/intelligence/features/
```

Expected: List of 12 modified .py files (10 Pattern 2 + 2 Pattern 3a)

- [ ] **Step 2: Review changes**

Run:
```bash
git diff src/intelligence/features/i1_indicators/
```

Expected: Changes show `s = self._state` → `s = state.get(...)` and `_state` returns added

- [ ] **Step 3: Stage all plugin fixes**

Run:
```bash
git add src/intelligence/features/i1_indicators/*.py
```

- [ ] **Step 4: Create comprehensive commit**

Run:
```bash
git commit -m "fix(plugins): complete Renaissance state migration for 12 broken plugins

- Pattern 2 (10 plugins): Replace self._state with state parameter
  - ParabolicSAR, ACOscillator, Keltner, Aroon, CMF
  - Donchian, Chandelier, HistoricalVolatility, ROC_PPO, StochasticRSI
- Pattern 3a (2 plugins): Mark non-incremental until proper implementation
  - OFI, CVD - were claiming incremental support but only called compute_full
- All plugins now follow RSI pattern: state parameter + _state return
- Fixes 'name state is not defined' and 'MUST return _state' errors

Root cause: Renaissance fix was incomplete - removed self._state from
dataclasses but only migrated some plugins to parameter-state pattern.

Verified: Pipeline starts without plugin errors, ATR values normalized"
```

Expected: Commit created with hash

---

## Task 7: Document Architecture Decision

**Files:**
- Create: `docs/architecture/plugin-state-management.md`

- [ ] **Step 1: Create architecture decision record**

Write `docs/architecture/plugin-state-management.md`:

```markdown
# Plugin State Management Architecture

## Decision: Parameter-Based State Pattern

**Status:** Accepted (2026-05-21)

**Context:**
The Renaissance refactoring eliminated dual-state pattern (self._state + external state)
in favor of single source of truth: state parameter passed by executor.

## Pattern

All incremental plugins MUST follow this pattern:

```python
def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
    if not state:
        return self.compute_full(windows)

    # Use state PARAMETER, never self._state
    s = state.get("plugin_key")
    if s is None:
        return {}

    # Mutate state dict in-place
    s["field"] = new_value

    # CRITICAL: Return state for executor extraction
    out["_state"] = state
    return out
```

## Requirements

1. **NO self._state in compute_next()** - references will fail
2. **Return {"_state": state}** - executor extracts and persists
3. **Check state is not None** - guard against missing state
4. **Mark supports_incremental correctly** - False if compute_next just calls compute_full

## Examples

- ✅ **Working:** RSI, BollingerBands, ATR
- ⚠️ **Non-Incremental:** OFI, CVD (marked supports_incremental=False)
- ❌ **Anti-Pattern:** `s = self._state` (removed in Renaissance)

## Migration

When adding new incremental plugins:
1. Copy pattern from RSI plugin
2. Test with pytest: ensure state persists across calls
3. Mark supports_incremental=True ONLY when compute_next has actual logic

## Rationale

- **Modularity:** Each plugin owns its state structure
- **Simplicity:** Single state dict, no dual-state corruption bugs
- **Correctness:** Executor manages persistence, plugins compute only
- **Efficiency:** In-place mutation, no copy overhead
```

Expected: File created with complete pattern documentation

- [ ] **Step 2: Add to git**

Run:
```bash
git add docs/architecture/plugin-state-management.md
```

- [ ] **Step 3: Commit documentation**

Run:
```bash
git commit -m "docs: add plugin state management ADR

Documents parameter-based state pattern requirement following
Renaissance migration completion. Includes examples, anti-patterns,
and migration guide for new plugins."
```

---

## Verification Checklist

Before considering this complete, verify:

- [ ] All 10 Pattern 2 plugins use `state` parameter, not `self._state`
- [ ] All 10 Pattern 2 plugins return `{"_state": state}`
- [ ] OFI and CVD marked `supports_incremental: False`
- [ ] All Python files compile without syntax errors
- [ ] Pipeline starts: `systemctl status indicagent-intelligence-pipeline` shows active (running)
- [ ] No plugin errors in logs: no "name 'state' is not defined"
- [ ] No state return errors: no "MUST return _state in result dict"
- [ ] ATR values normalized: ESM6 ATR between 0.1-10.0 (not 6000+)
- [ ] All changes committed with comprehensive message
- [ ] Architecture decision record created

---

## Post-Completion Tasks (Future Work)

NOT in scope for this fix - defer to future phases:

1. **Implement proper incremental logic for OFI/CVD** - currently marked non-incremental
2. **Refactor state.update() into base class method** - eliminate repetition (user suggestion)
3. **Add invariant tests** - ensure state corruption bugs don't recur
4. **Mathematical validation** - verify indicator outputs match reference implementations
5. **Performance benchmarking** - measure incremental vs full compute latency

---

**End of Plan**

Total estimated time: 45-60 minutes
Breakdown: Task 2 (30 min) + Task 3 (5 min) + Tasks 4-7 (15 min)
