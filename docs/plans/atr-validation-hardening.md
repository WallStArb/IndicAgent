# ATR Validation Hardening — Single-Point Gate

## Problem

`atr_14` is consumed with inconsistent null handling across all tiers. Three distinct root
causes, each with different blast radius:

### Root Cause 1 — I7 tick-floor bypass (HIGH severity)

All 30 I7 plugins call:
```python
atr = get_atr_with_floor(features, str(features.get("symbol", "")))
```

`features` is a merged dict of I1–I6 tier sub-dicts. It contains no `"symbol"` key.
`features.get("symbol", "")` → `""`. `get_tick_size("")` → falls through to `0.01` default.

For ES (tick=0.25) and NQ (tick=0.25), the effective floor being applied is `0.01`, not `0.25`.
Sub-tick ATR signals are being emitted when they should be suppressed. This is a live signal
integrity defect.

The correct key is `frames["__symbol__"]` (the raw `plugin_input` dict passed to `compute_full`).
No plugin currently reads from it.

### Root Cause 2 — `get_atr()` exists but is unused outside I7

`atr_utils.py` already exports two functions:
- `get_atr(features)` — returns raw positive ATR or None (null/zero guard)
- `get_atr_with_floor(features, symbol)` — adds the tick-size floor on top

I2-I6 consumers invent their own null strategies instead of calling `get_atr()`:

| Location | Pattern | Risk |
|---|---|---|
| `confluence/confluence_smc.py` (×2) | `features.get("atr_14") or 0.0` | div-by-zero if ATR=0 AND no guard |
| `confluence/cross_tf_sr_confluence.py` | `intel.get("atr_14", 1)` | silent wrong default (1 point) |
| `confluence/squeeze_expansion_divergence.py` | `intel.get("atr_14")` | no null guard before division |
| `context/anchored_vwap.py` | `i1_tier.get("atr_14")` | no null guard |
| `context/volume_profile.py` | inline `isinstance` + `atr_14 > 0` (×4) | correct but 4× duplicated |
| `features/i3_structure/fibonacci_zones.py` | inline `isinstance` + `> 0` (×3) | correct but duplicated |
| `features/i3_structure/macd_events.py` | `i1.get("atr_14")` | no null guard |
| `features/i3_structure/market_profile.py` | inline `isinstance` + `> 0` (×4) | correct but duplicated |
| `features/i3_structure/session_levels.py` | inline `isinstance` + `> 0` (×3) | correct but duplicated |
| `features/i3_structure/swing_momentum.py` | `(frames.get("i1") or {}).get("atr_14") or 0.0` | div-by-zero if used as divisor |
| `features/i3_structure/trend_structure.py` | `i1["atr_14"]` with isinstance check | correct but verbose |
| `features/i5_patterns/candlestick_patterns.py` | `features.get("atr_14") or 0.0` | div-by-zero |
| `features/i5_patterns/key_level_reaction.py` | inline isinstance check | correct but verbose |
| `features/smc_context/bos_choch.py` | inline isinstance check | correct but verbose |
| `features/smc_context/breaker_blocks.py` | `features.get("atr_14")` | no null guard |
| `trading/zone_engine.py` | `_fval(features, "atr_14") or 0.5` | arbitrary fallback (0.5 points) |
| `trading/cross_asset_divergence.py` | `float(features.get("atr_14", 0.0) or 0.0)` | guarded by `if atr <= 0` but fragile |
| `trading/momentum_accel.py` (I5 composite) | `features.get("atr_14")` | no null guard |
| `ai/narrative/prompts.py` (×2) | `getattr(intel.i1, "atr_14", None) or 1.0` | typed access, 1.0 default acceptable for prompts |

### Root Cause 3 — `atr_14_valid` injection is the wrong abstraction

The previous plan proposed injecting `atr_14_valid` into `frames["i1"]` or the pipeline.
This is incorrect for two reasons:

1. **Wrong semantics**: The tick-size floor is meaningful only for I7 (stop distance must be
   ≥ instrument minimum tick). For I2-I6 scale-factor uses (distance normalization), a sub-tick
   ATR is still a valid normalization value. Injecting a tick-floored field as the canonical
   ATR for all tiers conflates two different contracts.

2. **Wrong propagation path**: `build_flat_features()` assembles I7's flat features from the
   already-constructed `IntelligenceEvent` (after I1-I6 have run). Injecting into `frames["i1"]`
   during the pipeline does NOT propagate to I7's flat feature dict.

## Fix

### 1. `executor.py` — expose `symbol` in plugin_input

In `run_i7_complete`, add a plain `"symbol"` key to `plugin_input` alongside `"__symbol__"`:

```python
plugin_input = {
    "main": main_df,
    "features": features,
    "__symbol__": symbol,
    "symbol": symbol,          # NEW: plain key for plugin compatibility
    "__timeframe__": tf,
    "timeframe": tf,
    "__instrument__": self._instrument_map.get(symbol),
    "intel_event": intel_event,
    "cache_snapshot": cache_snapshot,
}
```

This is the single source of truth fix. All current and future I7 plugins can now reliably
get the symbol via `frames.get("symbol", "")`.

### 2. `atr_utils.py` — add `get_atr_with_floor_from_frames()`

```python
def get_atr_with_floor_from_frames(frames: dict[str, Any]) -> float | None:
    """Get tick-floored ATR from the plugin_input frames dict.

    Reads symbol from frames["symbol"] (set by executor) and ATR from
    frames["i1"]. Call this in compute_full() — it correctly applies the
    instrument tick-size floor that get_atr_with_floor() was always intended to apply.
    """
    symbol = frames.get("symbol") or frames.get("__symbol__", "")
    i1 = frames.get("i1") or {}
    return get_atr_with_floor(i1, symbol)
```

### 3. Update all 30 I7 plugins — fix tick-floor bypass

Replace:
```python
from .atr_utils import get_atr_with_floor
# ...
atr = get_atr_with_floor(features, str(features.get("symbol", "")))
```
With:
```python
from .atr_utils import get_atr_with_floor_from_frames
# ...
atr = get_atr_with_floor_from_frames(frames)
```

`frames` is the argument to `compute_full(self, frames: dict[str, Any])` — already in scope
in every I7 plugin. No other changes to plugin logic.

**Plugins to update** (all in `src/intelligence/trading/`):
`anchored_vwap_reversion`, `candlestick_pattern_setup`, `choch_reversal`, `cross_asset_divergence`,
`cvd_divergence`, `delta_exhaustion`, `divergence_stack`, `dual_divergence`, `failed_breakout`,
`fvg_fill`, `gap_analysis_setup`, `hvn_rejection`, `liquidity_hunt`, `liquidity_sweep_reclaim`,
`lvn_breakout`, `mean_reversion`, `microstructure_utils`, `momentum_breakout`, `mtf_alignment`,
`ofi_continuation`, `ofi_divergence`, `orb15`, `orb30`, `pattern_completion`, `poc_rejection`,
`regime_transition`, `second_leg_continuation`, `session_extremes_setup`, `squeeze_expansion`,
`supply_demand_setup`, `trend_following`, `vcp`, `vwap_deviation`, `vwap_reclaim`

Note: `microstructure_utils.py` is a shared utility called by I7 plugins — fix it so callers
don't need to pass symbol separately.

### 4. Standardize I2-I6 consumers — use existing `get_atr()`

Replace all inline ATR null patterns with the existing `get_atr(i1_dict)` from `atr_utils`:

| File | Change |
|---|---|
| `confluence/confluence_smc.py` | `features.get("atr_14") or 0.0` → `get_atr(features) or 0.0` |
| `confluence/cross_tf_sr_confluence.py` | `intel.get("atr_14", 1)` → `get_atr(intel) or 1.0` |
| `confluence/squeeze_expansion_divergence.py` | `intel.get("atr_14")` → `get_atr(intel)` + None guard |
| `context/anchored_vwap.py` | `i1_tier.get("atr_14")` → `get_atr(i1_tier)` + None guard |
| `context/volume_profile.py` | 4× inline isinstance → `get_atr(i1)` with None guard |
| `features/i3_structure/fibonacci_zones.py` | 3× inline isinstance → `get_atr(i1)` with None guard |
| `features/i3_structure/macd_events.py` | `i1.get("atr_14")` → `get_atr(i1)` + None guard |
| `features/i3_structure/market_profile.py` | 4× inline isinstance → `get_atr(i1_result)` |
| `features/i3_structure/session_levels.py` | 3× inline isinstance → `get_atr(i1)` |
| `features/i3_structure/swing_momentum.py` | `... or 0.0` → `get_atr(frames.get("i1") or {}) or 0.0` |
| `features/i3_structure/trend_structure.py` | inline isinstance → `get_atr(i1)` |
| `features/i5_patterns/candlestick_patterns.py` | `features.get("atr_14") or 0.0` → `get_atr(features) or 0.0` |
| `features/i5_patterns/key_level_reaction.py` | inline isinstance → `get_atr(features)` |
| `features/smc_context/bos_choch.py` | inline isinstance → `get_atr(features)` |
| `features/smc_context/breaker_blocks.py` | `features.get("atr_14")` → `get_atr(features)` + None guard |
| `trading/zone_engine.py` | `_fval(features, "atr_14") or 0.5` → `get_atr(features) or 0.5` |
| `trading/cross_asset_divergence.py` | `float(features.get("atr_14", 0.0) or 0.0)` → `get_atr(features) or 0.0` |
| `trading/momentum_accel.py` | `features.get("atr_14")` → `get_atr(features)` + None guard |

**Do NOT change:**
- `features/smc_context/hmm_regime.py` — reads raw `atr_14` as HMM training observation. Correct.
- `services/signal_tracker.py` — reads from stored signal payload, not live features. Out of scope.
- `ai/narrative/prompts.py` — reads typed `intel.i1.atr_14` (not raw dict), `or 1.0` is acceptable
  as normalization default for prose generation.
- `src/core/ml/training_data.py`, `validation/` — SQL queries against DB. Out of scope.

### 5. Leave `atr_14` (raw) untouched

Raw `atr_14` stays in all feature dicts and `I1Indicators` schema for HMM trainer, ML features,
and any consumer that legitimately wants the unfiltered value. No new fields are added to
`IntelligenceEvent` or `I1Indicators`.

## Files to change

```
src/intelligence/pipeline/executor.py                   — add "symbol" to plugin_input (1 line)
src/intelligence/trading/atr_utils.py                   — add get_atr_with_floor_from_frames()
src/intelligence/trading/*.py (30 files)                — swap import + call
src/intelligence/confluence/confluence_smc.py
src/intelligence/confluence/cross_tf_sr_confluence.py
src/intelligence/confluence/squeeze_expansion_divergence.py
src/intelligence/context/anchored_vwap.py
src/intelligence/context/volume_profile.py
src/intelligence/features/i3_structure/fibonacci_zones.py
src/intelligence/features/i3_structure/macd_events.py
src/intelligence/features/i3_structure/market_profile.py
src/intelligence/features/i3_structure/session_levels.py
src/intelligence/features/i3_structure/swing_momentum.py
src/intelligence/features/i3_structure/trend_structure.py
src/intelligence/features/i5_patterns/candlestick_patterns.py
src/intelligence/features/i5_patterns/key_level_reaction.py
src/intelligence/features/smc_context/bos_choch.py
src/intelligence/features/smc_context/breaker_blocks.py
src/intelligence/trading/zone_engine.py
src/intelligence/trading/cross_asset_divergence.py
src/intelligence/trading/momentum_accel.py
```

## Verification

```bash
# 1. No I7 plugin still calls get_atr_with_floor with features (should be zero)
grep -rn "get_atr_with_floor(features" src/intelligence/trading/ --include="*.py"

# 2. No plugin extracts symbol from features dict (should be zero)
grep -rn 'features.get("symbol"' src/intelligence/ --include="*.py"
grep -rn "features.get('symbol'" src/intelligence/ --include="*.py"

# 3. No remaining bare atr_14 dict access outside atr_utils and permitted exceptions
grep -rn '\.get("atr_14"' src/intelligence/ --include="*.py" | \
  grep -v "atr_utils\|hmm_regime\|narrative\|test"

# 4. Confirm symbol key is in plugin_input
grep -n '"symbol": symbol' src/intelligence/pipeline/executor.py

# 5. Unit tests green
.venv/bin/pytest tests/unit/ -q
```

## What this is NOT

- Not a schema change. No new fields on `I1Indicators` or `IntelligenceEvent`.
- Not a pipeline injection. No `atr_14_valid` field. Validation lives in accessor functions,
  not in the data contract.
- Not a semantic change for I2-I6. `get_atr()` returns the same value as the existing inline
  checks — it just removes the duplication.
- Not a behavioural change for I7. `get_atr_with_floor_from_frames(frames)` produces the same
  result as the old call would have if symbol had been passed correctly. The fix restores
  intended behavior that was silently broken.
