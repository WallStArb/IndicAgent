---
phase: 65-gradient-audit-of-existing-plugins-i1-i7-broader-sweep
reviewed: 2026-04-24T09:15:00Z
depth: quick
files_reviewed: 28
files_reviewed_list:
  - src/intelligence/composites/ma_composites.py
  - src/intelligence/composites/rsi_events.py
  - src/intelligence/composites/volume_events.py
  - src/intelligence/context/anchored_vwap.py
  - src/intelligence/context/session_context.py
  - src/intelligence/context/trend_regime.py
  - src/intelligence/context/volatility_regime.py
  - src/intelligence/features/i3_structure/market_profile.py
  - src/intelligence/features/i5_patterns/candlestick_patterns.py
  - src/intelligence/features/i5_patterns/mtf_volatility.py
  - src/intelligence/features/smc_context/amd_cycle.py
  - src/intelligence/features/smc_context/bos_choch.py
  - src/intelligence/features/smc_context/ict_killzones.py
  - src/intelligence/features/smc_context/liquidity_sweeps.py
  - src/intelligence/features/smc_context/supply_demand_zones.py
  - src/intelligence/schemas.py
  - src/intelligence/trading/choch_reversal.py
  - src/intelligence/trading/failed_breakout.py
  - src/intelligence/trading/liquidity_hunt.py
  - src/intelligence/trading/liquidity_sweep_reclaim.py
  - src/intelligence/trading/momentum_breakout.py
  - src/intelligence/trading/ofi_divergence.py
  - src/intelligence/trading/orb15.py
  - src/intelligence/trading/orb30.py
  - src/intelligence/trading/prev_day_level_test.py
  - src/intelligence/trading/squeeze_expansion.py
  - src/intelligence/trading/supply_demand_setup.py
  - src/intelligence/utils/gradient_utils.py
  - tools/scan_binary_patterns.py
findings:
  critical: 1
  warning: 2
  info: 3
  total: 6
status: issues_found
---

# Phase 65: Code Review Report

**Reviewed:** 2026-04-24T09:15:00Z
**Depth:** quick
**Files Reviewed:** 28
**Status:** issues_found

## Summary

Quick-depth pattern scan of 28 source files across composites (I2), context (I4), structure (I3), patterns (I5), SMC context, trading plugins (I7), gradient utilities, schemas, and a binary-pattern scanner tool. All automated pattern scans returned clean: no hardcoded secrets, no dangerous functions (eval/exec/system), no debug artifacts (console.log/debugger), no TODO/FIXME markers, no empty catch blocks.

Manual read of all files identified one critical bug (missing `_state` field on a dataclass that writes to it), two warnings (duplicate computation and a subtle shadowing issue), and three info items.

## Critical Issues

### CR-01: MACompositePlugin uses `_state` without declaring it as a dataclass field

**File:** `src/intelligence/composites/ma_composites.py:103`
**Issue:** The `compute_full` method reads and writes `self._state` (lines 103, 107) to track `golden_cross_bars_ago` across invocations. However, `MACompositePlugin` does not declare `_state: dict = field(default_factory=dict)` as a dataclass field. This means `self._state` is never initialized by the dataclass constructor, causing an `AttributeError` at runtime when `self._state.get("golden_cross_bars_ago", 999)` is called on line 103.

Every other stateful plugin in this review (`RSIEventsPlugin`, `VolumeEventsPlugin`, `AnchoredVWAPPlugin`, etc.) correctly declares `_state` as a dataclass field. This appears to be an omission specific to `MACompositePlugin`.

**Fix:**
```python
@dataclass
class MACompositePlugin:
    name: str = "MAComposite"
    outputs: frozenset[str] = field(
        default_factory=lambda: frozenset({...})
    )
    min_lookback: int = 200
    supports_incremental: bool = True
    capability_tags: frozenset[str] = field(default_factory=lambda: frozenset({"trend"}))
    inputs: list[InputSpec] = ()
    _state: dict = field(default_factory=dict)   # <-- ADD THIS

    atr_key: str = "atr_14"
    bb_mid_key: str = "bb_mid"
```

## Warnings

### WR-01: Duplicate `price_above_sma200` computation in MACompositePlugin

**File:** `src/intelligence/composites/ma_composites.py:120-148`
**Issue:** `price_above_sma200` is computed and assigned on line 126 inside the `if px is not None and is_num(s200):` block (lines 120-142), then computed again and reassigned on lines 145-148 in a separate `if px is not None and is_num(s200):` block. The second block unconditionally overwrites the first. This is dead code -- the first computation (lines 120-128) is wasted. Additionally, the second block re-fetches `s200` from `ma.get("sma_200")` on line 122, which is redundant since it was already fetched on line 91.

**Fix:** Remove the second `if px is not None and is_num(s200):` block (lines 145-148) since the first block already computes and assigns `price_above_sma200`.

### WR-02: `s200` variable shadowing in MACompositePlugin dynamic S/R block

**File:** `src/intelligence/composites/ma_composites.py:120-122`
**Issue:** On line 91, `s200 = ma.get("sma_200")`. Then on line 120, the guard `if px is not None and is_num(s200):` uses the value from line 91. But on line 122, `s200 = ma.get("sma_200")` re-fetches and reassigns `s200`, shadowing the outer variable. The subsequent `isinstance(s200, (int, float))` check on line 123 uses this re-fetched value. While the re-fetch returns the same value in practice, the shadowing is confusing and indicates a copy-paste artifact. The guard on line 120 already confirmed `s200` is numeric via `is_num(s200)`.

**Fix:** Remove the redundant `s200 = ma.get("sma_200")` on line 122 and the isinstance guard on line 123. The outer guard on line 120 already validated the value.

## Info

### IN-01: ORB15 and ORB30 are near-identical implementations

**File:** `src/intelligence/trading/orb15.py` and `src/intelligence/trading/orb30.py`
**Issue:** These two files are line-for-line duplicates except for `_RANGE_END = (9, 45)` vs `_RANGE_END = (10, 0)`, the class name, and the `name` attribute. The docstrings in both files acknowledge this: "Identical logic to ORB15 except the accumulation window is 09:30-10:00 ET. Implemented as a separate class (not a shared base) for independent statistical tracking." This is an intentional design decision per Renaissance principles ("segment relentlessly"), but worth noting for future maintenance -- any bug fix must be applied to both files.

**Fix:** No action required. Document the coupling with a shared comment if desired.

### IN-02: `hammer_detected` and `shooting_star_detected` fall through to `1.0` when no support/resistance data available

**File:** `src/intelligence/features/i5_patterns/candlestick_patterns.py:136-150`
**Issue:** When `nearest_support` or `nearest_resistance` are not provided in features, the code treats any pin bar as a valid hammer/shooting star. The comments acknowledge this ("No support info -> treat any pin bar bull as potential hammer"), but it means these patterns fire more liberally when upstream S/R data is missing, potentially creating inconsistent signal behavior depending on whether the S/R plugin ran before this one.

**Fix:** Consider gating on S/R data availability explicitly, or reducing confidence in the fallback case.

### IN-03: `amd_cycle.py` state accumulation is per-plugin-instance, not per-symbol

**File:** `src/intelligence/features/smc_context/amd_cycle.py:82-88`
**Issue:** The AMDCycle plugin stores overnight range in `self._state["overnight"]` without a symbol/timeframe key. If the same plugin instance serves multiple symbols, the overnight ranges from different instruments would be merged. All other SMC context plugins and I7 trading plugins key state by `(symbol, tf)`. This appears safe in the current architecture (one instance per symbol/timeframe pipeline), but would break if the plugin were reused across instruments.

**Fix:** Consider keying state by symbol like `AnchoredVWAPPlugin` does (line 162 of `anchored_vwap.py`).

---

_Reviewed: 2026-04-24T09:15:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
