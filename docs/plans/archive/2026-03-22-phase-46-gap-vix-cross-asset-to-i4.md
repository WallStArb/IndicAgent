# Phase 46 Gap Closure: VIX and Cross-Asset Context → I4

**Date:** 2026-03-22
**Status:** Approved — ready for planning
**Type:** Gap closure against Phase 46 (46.1)
**Trigger:** Renaissance design review identified architectural misplacement and data quality defect

---

## Problem Statement

Phase 46 placed VIX and EQ cross-asset spread data as pass-through fields in `I6Confluence` (cross-timeframe alignment layer). This violates two Renaissance principles:

1. **Wrong layer.** I6 answers "are signals across timeframes aligned?" VIX answers "what is the macro fear regime?" EQ spread answers "is the equity sector rotating?" Both are regime context signals — they belong in I4 alongside GARCH, HMM, Hurst, and Shannon entropy.

2. **Per-TF VIX z-score is a data quality defect.** The current implementation computes VIX z-score using the trading symbol's current timeframe:
   ```python
   vix_deque = self._bar_history.get(self._vix_symbol, tf)  # tf varies
   frames["vix"] = compute_vix_context(vix_deque)           # z_window=20 always
   ```
   - 1m TF: z_window=20 → 20 minutes of VIX history (noise)
   - 5m TF: z_window=20 → 100 minutes
   - 1h TF: z_window=20 → 20 hours (meaningful)

   The same market moment produces different `ctf_vix_z` values depending on which TF triggered the computation. Phase 49's training matrix will contain contradictory regime readings for the same signal fired on different TFs — training data poisoning.

3. **I6 plugin acts as data relay, not computation.** Lines 127–144 of `CrossTimeframeConfluencePlugin.compute_full()` copy injected frame values to output without computing anything. Plugins are analytical units, not data conduits.

4. **Signal identity violation.** VIX and EQ spread are informationally distinct with different symbol scopes. Combining them into a single plugin (`MacroContextPlugin`) would collapse two separable ML feature groups. Phase 49 must be able to attribute alpha to VIX regime independently of EQ sector rotation.

5. **`capture_confluence_features()` is misnamed.** After Phase 46 it captures I4 macro context + I6 confluence + exhaustion state. The name implies I6-only scope.

---

## Design

### Two new I4 plugins

**`VIXRegimePlugin`** (`ctx_VIXRegime`)
- File: `src/intelligence/context/vix_regime.py`
- Reads: `frames["vix"]` — injected by `feature_pipeline_service` from fixed `VIX_REGIME_TF="1h"` bars
- Outputs: `vix_level`, `vix_z`
- Symbol scope: all symbols (VIX is a global fear gauge relevant to gold, bonds, crypto, not just equities)
- Window: `z_window=20` on 1h bars = 20 trading hours
- Rationale for 20h window: captures session-scale fear elevation. Complementary to GARCH, which captures multi-week structural vol regime. GARCH answers "what regime is this week?"; VIX z-score at 20h answers "is today's session fear-elevated vs recent baseline?"
- Returns `{}` (empty dict) when VIX bars unavailable — not an error condition; plugin silently degrades

**`CrossAssetContextPlugin`** (`ctx_CrossAssetContext`)
- File: `src/intelligence/context/cross_asset_context.py`
- Reads: `frames["cross_asset"]` — already injected by `feature_pipeline_service` for EQ_INDEX symbols
- Outputs: `eq_spread_z`, `eq_pairs_confirming`
- Symbol scope: EQ_INDEX symbols only → `None` for all others (non-EQ symbols see `{}` return — fields absent from features dict → I4Context defaults to `None`)
- Phase 49 segmentation requirement: ML training matrix MUST segment on symbol group before using `eq_*` features. Training on non-EQ symbols with `None` eq_* values without segmentation will produce uninformative coefficients.

### Schema changes

**Add to `I4Context`** (alongside GARCH, Hurst, HMM):
```python
# VIXRegimePlugin outputs — all symbols
vix_level: float | None = None        # VIX close price (raw level); all symbols
vix_z: float | None = None            # VIX z-score, 20-bar rolling mean, fixed 1h TF

# CrossAssetContextPlugin outputs — EQ_INDEX symbols only
eq_spread_z: float | None = None      # dominant EQ pair spread z-score (ES/NQ or ES/RTY)
eq_pairs_confirming: float | None = None  # 0.0–2.0 confirming pairs; EQ_INDEX only
```

**Remove from `I6Confluence`**: `ctf_vix_level`, `ctf_vix_z`, `ctf_eq_spread_z`, `ctf_eq_pairs_confirming` — and from `CrossTimeframeConfluencePlugin.outputs` frozenset.

### VIX frame injection fix

`feature_pipeline_service.py` — one constant, one line change:
```python
# Module-level constant — fixed TF for VIX regime context
VIX_REGIME_TF: str = "1h"  # 20 × 1h ≈ 20 trading hours; intraday fear complement to GARCH

# In _run_bar() — replaces the current tf-dependent lookup
if self._vix_symbol:
    vix_deque = self._bar_history.get(self._vix_symbol, VIX_REGIME_TF)
    frames["vix"] = compute_vix_context(vix_deque)
else:
    frames["vix"] = {"ready": False}
```

All TF bars for all symbols now see an identical VIX regime reading for the same market moment.

### I6 cleanup

Remove ~20 lines from `CrossTimeframeConfluencePlugin.compute_full()` (lines 126–144 in current code) — the VIX and cross_asset pass-through blocks. Remove the 4 field names from `outputs` frozenset. I6 returns to pure cross-TF alignment computation.

### `capture_signal_features()` rename

`confidence_utils.py`: rename `capture_confluence_features()` → `capture_signal_features()` across all callers. Function signature and body unchanged except:
- Rename 4 shadow dict keys: `ctf_vix_level` → `vix_level`, `ctf_vix_z` → `vix_z`, `ctf_eq_spread_z` → `eq_spread_z`, `ctf_eq_pairs_confirming` → `eq_pairs_confirming`
- These now read from I4 fields in the features dict (correct layer)

Callers (all 36 I7 plugins + confidence_utils.py itself): mechanical rename only.

### Constants consolidation

`_CROSS_ASSET_VALID_TFS` is defined identically in `feature_pipeline_service.py` (line 106) and `signal_generator_service.py` (line 217). Move to `src/core/service_utils.py`. Both services import from there.

### What does NOT change

- `vix_context.py` — pure function module is correct and reused as-is
- `CrossAssetDivergencePlugin` (I7) — continues to read `frames["cross_asset"]` directly from signal_generator_service injection. The I7 plugin needs the full payload (~10 fields including `low_vol_flag`, `eq_vol_imbalance`, `eq_corr_break`, `data_quality_score`). The `eq_spread_z` / `eq_pairs_confirming` in I4 are regime context for all I7 plugins; the full payload in `frames["cross_asset"]` is the signal source specifically for `CrossAssetDivergencePlugin`.
- `signal_generator_service` cross-asset subscription — retained; it serves `CrossAssetDivergencePlugin` with a different payload scope than what I4 captures
- `ctf_score` formula — untouched
- `ConfluenceWeightProfile` / `FAMILY_PROFILES` — unchanged

---

## Files changed

| File | Change |
|------|--------|
| `src/intelligence/context/vix_regime.py` | **New** — `VIXRegimePlugin` |
| `src/intelligence/context/cross_asset_context.py` | **New** — `CrossAssetContextPlugin` |
| `src/intelligence/schemas.py` | `I4Context` +4 fields; `I6Confluence` −4 fields |
| `src/intelligence/register_plugins.py` | Add both plugins to `TIER_I4` and `register_all_plugins()` |
| `src/intelligence/confluence/cross_timeframe.py` | Remove ~20 lines VIX/cross-asset pass-through; update `outputs` frozenset |
| `src/intelligence/trading/confidence_utils.py` | Rename function + 4 shadow dict keys; update module docstring and function docstring (currently references `ctf_*` prefixed keys and old function name) |
| `services/feature_pipeline_service.py` | Add `VIX_REGIME_TF="1h"` constant; fix VIX injection TF; import `CROSS_ASSET_VALID_TFS` |
| `services/signal_generator_service.py` | Import `CROSS_ASSET_VALID_TFS` from service_utils; remove local definition |
| `src/core/service_utils.py` | Add `CROSS_ASSET_VALID_TFS: frozenset[str]` |
| `tests/unit/intelligence/test_vix_regime.py` | **New** — VIXRegimePlugin tests |
| `tests/unit/intelligence/test_cross_asset_context.py` | **New** — CrossAssetContextPlugin tests |
| `tests/unit/intelligence/pipeline/test_*` | Update: rename `capture_confluence_features` → `capture_signal_features` |
| `tests/unit/test_cross_timeframe_confluence.py` | Remove 4 field assertions; verify I6 has no VIX/EQ fields |
| `tests/unit/test_capture_confluence_features.py` | Rename + update field names |

---

## Non-goals

- No change to `ctf_score` formula
- No change to Phase 49 ML design (this gap closure makes the training data correct; Phase 49 still designs the model)
- No elimination of signal_generator_service cross-asset subscription (needed for `CrossAssetDivergencePlugin`)
- No changes to any I7 plugin bodies (they consume from `features` dict — field names in shadow dict change but that's in `capture_signal_features()` only)

---

## Verification criteria

1. `VIXRegimePlugin` registered in TIER_I4; `validate_tier()` passes at startup
2. `CrossAssetContextPlugin` registered in TIER_I4; `validate_tier()` passes at startup
3. `I4Context` has `vix_level`, `vix_z`, `eq_spread_z`, `eq_pairs_confirming` — all `float | None`
4. `I6Confluence` does NOT have `ctf_vix_level`, `ctf_vix_z`, `ctf_eq_spread_z`, `ctf_eq_pairs_confirming`
5. `feature_pipeline_service` uses `VIX_REGIME_TF="1h"` for all VIX bar lookups (no `tf`-dependent lookup)
6. `CROSS_ASSET_VALID_TFS` appears once (in `service_utils.py`), not in either service file
7. `capture_signal_features()` is the function name in `confidence_utils.py` — `capture_confluence_features` does not exist
8. All 36 I7 plugin callers updated to `capture_signal_features` (excluding the definition site in `confidence_utils.py` itself)
9. 2716 existing unit tests pass (no regressions)
