# Phase 132: Stop-Zone Geometry + APR Migration — Research

**Researched:** 2026-06-17
**Domain:** trade_framer.py stop geometry, zone_engine.py zone validation, APR constant migration
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Phase 126 (commit 6fe15543) already added zone width rejection gate (lines 1052-1077) and stop distance floor at `feature.zone_engine.min_stop_distance_atr` = 0.5 ATR (lines 1099-1110). Measure current stopped_at_entry rate first. If <5%, A2 is closed.
- **D-02:** Per-asset-class APR keys for minimum stop floor (`feature.trade_framer.stop_multiplier_floor.{fx,commodity_small_tick,equity_etf,futures_large_tick}`). Seed values from empirical `intelligence_features.technical_indicators->>'atr_14'` median per asset class, divided by tick_size.
- **D-03:** Count actual APR keys from the adaptive buffer function before writing SQL — each distinct configurable value gets its own key. The todo table last row covers multiple distinct values.
- **D-04:** Seed value computation is a first-task prerequisite — query DB first, then write migration SQL.

### Claude's Discretion
- Whether to combine A2 + A3 in one plan or separate (recommend separate — cleaner regression boundary)
- Migration file numbering (next available after Phase 131 migrations)
- Regression test design (1-month sample replay + lifecycle_replay, compare stopped_at_entry rate)

### Deferred Ideas (OUT OF SCOPE)
- FX-specific plugin parameter tuning (min_agreeing, session context) — EURUSD excluded from corpus until future phase
- ML learning on stop ATR multiplier — v2.11 after corpus is populated with `counterfactual_pnl_r`
</user_constraints>

---

## Summary

Phase 132 has three work streams. A2 (stop geometry) is partially complete from Phase 126 — the zone width gate and stop distance floor both exist in trade_framer.py lines 1052-1110. The current corpus has zero `stopped_at_entry` rows in trade_executions, which is consistent with those gates working, but lifecycle_replay has not been run on post-Phase-126 data with the current corpus, so the rate cannot be confirmed without a 2-week sample replay. A5 (APR migration) is entirely pending: all 15+ hardcoded constants in trade_framer.py remain as module-level Python variables. A3 (per-asset-class stop floors) is pending, with empirical seed values now computed from intelligence_features.

The config service wiring for trade_framer already exists: `intelligence_pipeline.py` calls `trade_framer.set_config_service()` at line 520, and the module-level `_config_service` + `_cfg()` + `set_config_service()` pattern is already implemented at lines 65-74. The only work is inserting migration SQL records and replacing Python constants with `_cfg()` calls.

**Primary recommendation:** Run 2-week sample replay + lifecycle_replay first to confirm stopped_at_entry rate. Then execute A5 APR migration (the bulk of the work). A3 per-asset-class floors can be in the same migration using the empirical seed values documented below.

---

## 1. Current State Assessment

### 1.1 Stop geometry in trade_framer.py

**File:** `src/intelligence/trading/trade_framer.py`

**Config wiring (lines 65-74) — already complete:**
```python
_config_service: Any | None = None

def set_config_service(cfg: Any) -> None:
    global _config_service
    _config_service = cfg

def _cfg(key: str, default: float) -> float:
    return _config_service.get_sync(key, default) if _config_service is not None else default
```

**Zone width gate (lines 1052-1077) — Phase 126, exists:**
- Computes `zone_width = zone_high - zone_low`
- Reads `_min_zone_width_atr(asset_class)` which calls `_cfg("feature.zone_engine.min_zone_width_atr", MIN_ZONE_WIDTH_ATR)`
- Rejects with `_reject_frame("zone_too_narrow:...")` if `zone_width < atr * _min_width`
- Already APR-backed via `feature.zone_engine.min_zone_width_atr`

**Stop distance floor gate (lines 1095-1110) — Phase 126, exists:**
```python
_stop_distance = abs(resolved_entry - stop)
_min_stop_dist = atr * _cfg("feature.zone_engine.min_stop_distance_atr", 0.5)
if _stop_distance < _min_stop_dist:
    return _reject_frame(f"stop_too_close:{stop_type}", ...)
```
Current APR values: default=0.5, equity=0.5, futures=0.4, fx=0.3 (confirmed in config_state).

**Stop placement geometry (lines 537-675):**
- Stop is computed from structural levels (demand_zone, sweep_level, ob_bottom, swing_low, sr_support) or ATR fallback
- **All structural stops are measured from the structural LEVEL, not the entry price** — e.g., `stop = nearest_demand_low - atr * adaptive_buffer(ATR_STOP_DEMAND_MULTIPLIER)` (line 558)
- The `min_stop` floor at line 544 (`min_stop = entry - atr * _adaptive_buffer(features, MIN_STOP_ATR_MULTIPLIER)`) enforces stop distance FROM ENTRY — this is the primary fix mechanism
- `validate_stop_against_zone()` at line 1084 corrects stops inside the zone — this handles the stopped_at_entry root cause directly

**Stop validation chain order (critical):**
1. Zone width gate — rejects narrow zones outright (line 1059)
2. `validate_stop_against_zone()` — pushes stop outside zone if it lands inside (line 1084)
3. Stop distance floor gate — rejects if stop still too close after zone correction (line 1101)

### 1.2 zone_engine.py — fast-path bypass check

**File:** `src/intelligence/trading/zone_engine.py`

zone_engine does NOT generate zones independently — it is called from trade_framer via `resolve_structural_zone()` (zone_engine.py line 485-499). zone_engine returns a `ZoneResult` with `tier="atr"` when no structural level is found; trade_framer then applies its own ATR-based bounds.

**`_expand_to_min_width()` at line 398:**
```python
def _expand_to_min_width(low: float, high: float, atr: float) -> tuple[float, float]:
    min_width = atr * _min_width_atr()
    if high - low < min_width:
        mid = (low + high) / 2
        low = mid - min_width / 2
        high = mid + min_width / 2
    return low, high
```
This is called inside zone_engine for confluence/single-level zones. However `_min_width_atr()` reads `feature.zone_engine.min_width_atr` (current value: 0.25 ATR), not `feature.zone_engine.min_zone_width_atr` (1.5 ATR). These are two different parameters with different purposes: `min_width_atr` is the zone_engine internal structural width minimum; `min_zone_width_atr` is the trade_framer rejection threshold.

**A2(a) finding:** A zone returned from zone_engine CAN have width < `feature.zone_engine.min_zone_width_atr` (1.5 ATR). zone_engine's `_expand_to_min_width()` uses a much smaller threshold (0.25 ATR). The trade_framer zone width gate at line 1059 is the first and only rejection point for narrow zones. This is by design — zone_engine doesn't know trade_framer's threshold. The defensive assertion would add a belt-and-suspenders check but is not closing a logical gap.

**Conclusion on A2(a):** No bypass in zone_engine. zone_engine correctly returns whatever structural zone it finds; trade_framer's gate rejects if too narrow. The defensive assertion in zone_engine output would be redundant but harmless.

### 1.3 ATR source used at runtime

`get_atr()` in `atr_utils.py` reads `features["atr_14"]` from the I1 indicator dict (the smoothed 14-bar ATR). The `intelligence_features.technical_indicators->>'atr_14'` field matches this exactly. The CONTEXT.md instruction to use `atr_14` for seed value computation is correct — confirmed by code trace.

---

## 2. Stop Geometry Bug Evidence

### 2.1 Current stopped_at_entry rate

Query run 2026-06-17 against current corpus (749,982 signal_events, 752,098 trade_frames, 775,204 trade_executions):

```
exit_reason          | count  |  pct
---------------------+--------+-------
stop_loss            | 289287 | 37.32
ttl_expired          | 242063 | 31.23
ttl_expired_ahead    | 129221 | 16.67
ttl_expired_behind   |  62504 |  8.06
target_1             |  52129 |  6.72
stopped_at_entry     |      0 |  0.00
```

**`stopped_at_entry` count = 0.** This corpus was rebuilt post-Phase-126 with the zone width gate and stop distance floor active. The 25% rate in the todo file predates Phase 126 (commit 6fe15543).

**Interpretation:** The Phase 126 fixes are working. A2 may already be closed, but this corpus does NOT reflect a lifecycle_replay with the full current trade_framer code — the corpus was populated before some trade_framer changes. A 2-week sample replay + lifecycle_replay is still required to confirm the rate on freshly-framed signals. The verification is fast and should be the first task.

### 2.2 Pre-Phase-126 sample data (for reference only)
From `.planning/todos/pending/2026-06-14-review-stop-zone-logic.md`:
- QQQ zone [723.14, 723.16], entry 723.09 — stop was ABOVE entry (negative stop_distance), caused stopped_at_entry
- XLE zone [57.46, 57.47], entry 57.49, stop 57.46 — 3 cents, well inside zone

These examples are now rejected by the zone width gate (QQQ zone width = 0.02, far below 1.5 ATR) and `validate_stop_against_zone()` respectively.

---

## 3. APR Constant Inventory

### 3.1 Complete constant listing

Every hardcoded numeric value in `trade_framer.py` as of the code read above:

**Module-level constants (all still hardcoded, need migration):**

| Constant | Line | Value | APR key | ML target? |
|----------|------|-------|---------|-----------|
| `MIN_ZONE_WIDTH_ATR` | 86 | 1.5 | `feature.zone_engine.min_zone_width_atr` | Operator preference — already in APR (fallback only, D-18 comment) |
| `ATR_STOP_DEMAND_MULTIPLIER` | 93 | 0.25 | `feature.trade_framer.stop_demand_buffer_atr` | Yes |
| `ATR_STOP_SWEEP_MULTIPLIER` | 94 | 0.30 | `feature.trade_framer.stop_sweep_buffer_atr` | Yes |
| `ATR_STOP_OB_MULTIPLIER` | 95 | 0.20 | `feature.trade_framer.stop_ob_buffer_atr` | Yes |
| `ATR_STOP_SWING_MULTIPLIER` | 96 | 0.25 | `feature.trade_framer.stop_swing_buffer_atr` | Yes |
| `ATR_STOP_SR_MULTIPLIER` | 97 | 0.50 | `feature.trade_framer.stop_sr_buffer_atr` | Yes |
| `ATR_STOP_FALLBACK_MULTIPLIER` | 98 | 2.0 | `feature.trade_framer.stop_fallback_atr` | Yes |
| `ATR_ZONE_SWEEP_MULTIPLIER` | 101-103 | 0.76 | `feature.trade_framer.zone_sweep_atr` | Yes |
| `ATR_ZONE_LOW_MULTIPLIER` | 104 | 1.0 | `feature.trade_framer.zone_low_atr` | Yes |
| `ATR_ZONE_HIGH_MULTIPLIER` | 105 | 0.5 | `feature.trade_framer.zone_high_atr` | Yes |
| `ATR_TARGET_MIN_MULTIPLIER` | 106 | 0.5 | `feature.trade_framer.target_min_atr` | Yes |
| `ATR_ZONE_PLUGIN_FALLBACK_MULTIPLIER` | 108-110 | 0.2 | `feature.trade_framer.zone_plugin_fallback_atr` | No — structural fallback |
| `VP_PROXIMITY_THRESHOLD_ATR` | 119 | 0.5 | `feature.trade_framer.vp_proximity_atr` | Yes |
| `ATR_FALLBACK_T1_MULTIPLIER` | 122 | 2.0 | `feature.trade_framer.fallback_t1_atr` | Yes |
| `ATR_FALLBACK_T2_MULTIPLIER` | 123 | 3.5 | `feature.trade_framer.fallback_t2_atr` | Yes |
| `ATR_FALLBACK_T3_MULTIPLIER` | 124 | 5.5 | `feature.trade_framer.fallback_t3_atr` | Yes |
| `MIN_STOP_ATR_MULTIPLIER` | 130 | 1.0 | `feature.trade_framer.min_stop_atr` | Yes — primary ML stop control, bounded below by `feature.zone_engine.min_stop_distance_atr` |
| `MIN_RR_T1` | 131 | 1.5 | `threshold.trade_framer.min_rr_t1` | Yes |
| `ADAPTIVE_BUFFER_HARD_CAP` | 133 | 1.40 | `feature.trade_framer.adaptive_buffer_hard_cap` | Operator preference |
| `STRUCTURE_SNAP_PROXIMITY_ATR` | 165 | 1.5 | `feature.trade_framer.structure_snap_proximity_atr` | No — structural classification |

**NOT migrated (intentionally):**
- `EPSILON_TOLERANCE` (1e-9) — numerical stability constant, not a behavioral parameter
- `ATR_EMERGENCY_FALLBACK_PCT` (0.001) — defensive fallback, not tunable
- `ATR_TARGET_MAX_MULTIPLIER` (8.0) — per-TF dict overrides this; constant is the final fallback
- `ATR_TARGET_MAX_MULTIPLIER_BY_TF` dict — per-TF max target distance; these SHOULD be migrated but are a dict, not simple scalars; defer to avoid over-engineering
- `OUTCOME_THRESHOLD_QUICK_STOP_BARS` in lifecycle_tracker.py — not in trade_framer

### 3.2 Adaptive buffer function (lines 136-159) — breakdown

```python
def _adaptive_buffer(features, base_mult, regime_type=None):
    vol_ratio = float(features.get("garch_vol_ratio") or 1.0)
    vol_ratio = max(0.70, min(1.50, vol_ratio))   # clamp range: [0.70, 1.50]

    if vol_ratio <= 1.0:
        garch_mult = 0.80 + (vol_ratio - 0.70) * (0.20 / 0.30)
    else:
        garch_mult = 1.00 + (vol_ratio - 1.00) * (0.35 / 0.50)

    result = base_mult * garch_mult

    hurst = features.get("hurst_exponent")
    if hurst is not None and regime_type in ("trend", "mean_reversion"):
        h = float(hurst)
        if regime_type == "trend" and h >= 0.55:
            result *= 1.0 - (h - 0.55) * 0.16   # trend: tighten when Hurst > 0.55
        elif regime_type == "mean_reversion" and h <= 0.45:
            result *= 1.0 - (0.45 - h) * 0.16   # MR: tighten when Hurst < 0.45

    if float(features.get("garch_shock") or 0.0) > 3.0:
        result = max(result, base_mult * 1.35)

    return min(result, base_mult * ADAPTIVE_BUFFER_HARD_CAP)
```

**Distinct configurable values in adaptive buffer:**

| Parameter | Current value | APR key |
|-----------|--------------|---------|
| vol_ratio clamp min | 0.70 | `feature.trade_framer.adaptive_buffer_vol_ratio_min` |
| vol_ratio clamp max | 1.50 | `feature.trade_framer.adaptive_buffer_vol_ratio_max` |
| low-vol regime base | 0.80 | `feature.trade_framer.adaptive_buffer_low_vol_base` |
| low-vol slope numerator | 0.20 | `feature.trade_framer.adaptive_buffer_low_vol_slope_num` |
| low-vol slope denominator | 0.30 | `feature.trade_framer.adaptive_buffer_low_vol_slope_den` |
| high-vol slope numerator | 0.35 | `feature.trade_framer.adaptive_buffer_high_vol_slope_num` |
| high-vol slope denominator | 0.50 | `feature.trade_framer.adaptive_buffer_high_vol_slope_den` |
| Hurst trend threshold | 0.55 | `feature.trade_framer.adaptive_buffer_hurst_trend_threshold` |
| Hurst MR threshold | 0.45 | `feature.trade_framer.adaptive_buffer_hurst_mr_threshold` |
| Hurst tightening rate | 0.16 | `feature.trade_framer.adaptive_buffer_hurst_tighten_rate` |
| GARCH shock threshold | 3.0 | `feature.trade_framer.adaptive_buffer_garch_shock_threshold` |
| GARCH shock multiplier | 1.35 | `feature.trade_framer.adaptive_buffer_garch_shock_mult` |

**Total: 12 adaptive buffer keys.** The todo table said "0.80, 0.70, 0.20/0.30, 0.35/0.50, 0.16" = 5 apparent values, but these are actually 12 distinct configurable values when the piecewise function is decomposed. Each slope has a numerator and denominator; the clamp range has min/max; the Hurst function has threshold, MR threshold, and rate.

**Total APR keys to create:** 19 module-level constants + 12 adaptive buffer constants + 4 per-asset-class stop floor keys (A3) = 35 keys. However, `MIN_ZONE_WIDTH_ATR` already exists in APR (it's a fallback constant). The adaptive buffer coefficients are ML-learning targets for the GARCH vol-response curve.

**Practical note:** The 12 adaptive buffer coefficients define a piecewise function that should be treated as a unit — changing one in isolation can break the function shape. Flag all 12 as ML-learning targets but note they should be tuned as a group or the piecewise structure preserved. Alternative: define the full piecewise as a single JSON structure in one APR key. Decision is left to the planner (Claude's Discretion).

---

## 4. Empirical Seed Values

### 4.1 Data source

All values computed from `intelligence_features.technical_indicators->>'atr_14'` (1m bars), median per symbol, then median per asset class. This matches the `get_atr()` call at runtime via `atr_utils.get_atr()` which reads `atr_14`.

### 4.2 Raw per-symbol ATR14 medians (1m bars)

**FX:**
| Symbol | median_atr_14 | tick_size | ATR/tick |
|--------|--------------|-----------|---------|
| EURUSD | 8.63e-05 | 0.00001 | 8.6 |
| GBPUSD | 1.18e-04 | 0.00001 | 11.8 |
| USDCHF | 7.05e-05 | 0.00001 | 7.0 |
| USDJPY | 9.17e-03 | 0.001 | 9.2 |
| **Class median** | | | **8.9** |

**commodity_small_tick (SI/NG/HG/CL):**
| Symbol | median_atr_14 | tick_size | ATR/tick |
|--------|--------------|-----------|---------|
| SI (K6/M6/N6) | 0.02792 | 0.005 | 5.6 |
| NG (K6/M6/N6) | 0.001535 | 0.001 | 1.5 |
| HG (K6/M6/N6) | 0.001053 | 0.0005 | 2.1 |
| CL (K6/M6/N6) | 0.06364 | 0.01 | 6.4 |
| **Class median** | | | **3.8** |

**equity_etf (QQQ/SPY/IWM/XLE/SMH):**
| Symbol | median_atr_14 | tick_size | ATR/tick |
|--------|--------------|-----------|---------|
| QQQ | 0.2233 | 0.01 | 22.3 |
| SPY | 0.1518 | 0.01 | 15.2 |
| IWM | 0.09145 | 0.01 | 9.1 |
| XLE | 0.02269 | 0.01 | 2.3 |
| SMH | 0.3646 | 0.01 | 36.5 |
| **Class median** | | | **15.2** |

**futures_large_tick (ES/NQ/YM/RTY):**
| Symbol | median_atr_14 | tick_size | ATR/tick |
|--------|--------------|-----------|---------|
| ES (M6/U6/Z6) | 1.3826 | 0.25 | 5.5 |
| NQ (M6/U6/Z6) | 8.655 | 0.25 | 34.6 |
| YM (M6/U6/Z6) | 7.938 | 1.0 | 7.9 |
| RTY (M6/U6/Z6) | 0.7528 | 0.1 | 7.5 |
| **Class median** | | | **7.7** |

### 4.3 Derived seed values for A3 APR keys

The per-asset-class floor is a minimum stop size expressed as an ATR multiplier. Purpose: ensure the stop is at least N ATR units from entry for this class. The floor should exceed 1 ATR (the existing universal `MIN_STOP_ATR_MULTIPLIER=1.0`).

These ATR/tick ratios confirm that ATR-relative stops are already reasonable (well above 1 tick). The per-asset-class floor should be a conservative floor on the ATR multiplier — not derived from tick ratios but from what makes sense as a minimum stop in ATR terms for each class.

Recommendation: set all four keys initially at 1.0 ATR (same as current universal floor). This is a clean starting point for ML to tune per-class. The empirical data confirms no class has pathologically small ATR values relative to tick size that would require a different floor seed.

If the planner wants class-differentiated seeds: commodities (NG median_atr/tick = 1.5x) suggest a 1.0 ATR floor may still result in very small absolute stops. Consider 1.5 ATR for commodity_small_tick as the seed. For futures_large_tick (NQ at 34.6x ATR/tick), 1.0 ATR is already generous.

**Recommended seed values:**
| APR key | Seed value | Rationale |
|---------|-----------|-----------|
| `feature.trade_framer.stop_multiplier_floor.fx` | 1.0 | Starting point; FX has small ticks but adequate ATR/tick ratio |
| `feature.trade_framer.stop_multiplier_floor.commodity_small_tick` | 1.5 | NG has only 1.5x ATR/tick headroom; floor slightly higher for safety |
| `feature.trade_framer.stop_multiplier_floor.equity_etf` | 1.0 | Strong ATR/tick ratio; universal floor is sufficient |
| `feature.trade_framer.stop_multiplier_floor.futures_large_tick` | 1.0 | Strong ATR/tick ratio for all major contracts |

These are `[initial_estimate]` provenance — first real values come after Phase 133 corpus rebuild.

---

## 5. Migration Numbering

**Latest migration files (from `ls production/migrations/ | sort | tail -5`):**
```
141_trade_frames_labeled_data_index.sql
142_phase130_apr_seeds.sql
143_drop_signal_ledger.sql
```

**Next migration number: 144**

One migration file covers all Phase 132 APR inserts (A5 constants + A3 per-class floors). The migration number is 144.

---

## 6. Integration Patterns

### 6.1 Config service wiring — already complete

`trade_framer.set_config_service()` is already called at line 520 of `services/intelligence_pipeline.py`. The module-level `_config_service` field and `_cfg()` wrapper are already implemented at lines 65-74 of trade_framer.py.

**No new wiring required for A5.** The pattern is:
1. Replace hardcoded constant usage: `ATR_STOP_DEMAND_MULTIPLIER` → `_cfg("feature.trade_framer.stop_demand_buffer_atr", 0.25)`
2. The `_cfg()` function handles the None-guard and fallback automatically

### 6.2 Prewarm tuple registration

`_THRESHOLD_KEYS` in `services/intelligence_pipeline.py` must include each new key with its default value. This is the pre-warm mechanism that loads all keys at startup. Look at lines 430-495 for the existing format: `("feature.zone_engine.cluster_radius_atr", 0.50)`.

Each new APR key must be added to `_THRESHOLD_KEYS`. This is the ONLY change needed in intelligence_pipeline.py — the `trade_framer.set_config_service()` call at line 520 already handles injection.

### 6.3 run_historical_pipeline.py config injection

The historical replay pipeline also uses trade_framer. Confirm `set_config_service()` is called there:

```bash
grep -n "set_config_service\|trade_framer" production/scripts/run_historical_pipeline.py
```

If not present, this is a gap — the replay would use hardcoded fallbacks rather than APR values. The planner should verify this.

### 6.4 Migration SQL format (from existing migrations)

Each APR key requires two INSERT statements in the migration file:
```sql
INSERT INTO config_schema (config_key, value_type, description, min_value, max_value)
VALUES (
    'feature.trade_framer.stop_demand_buffer_atr',
    'float',
    'ATR multiplier for demand zone stop buffer. Demand zone stop = nearest_demand_low - ATR×value. [initial_estimate] ML learning target: correlate with counterfactual_pnl_r per asset class after 30+ outcomes.',
    0.05, 2.0
) ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('feature.trade_framer.stop_demand_buffer_atr', '0.25', 1)
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = now();
```

---

## 7. Silent Failure Risks

### 7.1 `_cfg()` returns hardcoded default when config_service is None

**Risk:** If `set_config_service()` is not called (e.g., replay script path), `_config_service is None` → `_cfg()` returns the Python default argument.
**Severity:** MEDIUM. After A5, the Python default is preserved in the `_cfg()` call signature. Behavior is identical to pre-migration — no regression.
**Detection:** Run `grep -n "set_config_service" production/scripts/run_historical_pipeline.py`. If missing, add it.

### 7.2 Migration not run: key doesn't exist in config_state

**Risk:** If migration 144 is not applied but code is deployed, `_config_service.get_sync("feature.trade_framer.stop_demand_buffer_atr", 0.25)` returns 0.25 (the default). No error, no signal.
**Severity:** LOW. The default IS the current hardcoded value — no behavior change.
**Detection:** `SELECT COUNT(*) FROM config_state WHERE config_key LIKE 'feature.trade_framer.%'` should return the expected key count after migration.

### 7.3 Adaptive buffer coefficient typo produces wrong stop geometry

**Risk:** Piecewise function coefficients (12 values) define a specific vol-response curve. Mistyping a value (e.g., 0.20/0.30 → 0.20/0.03) changes buffer behavior for all stops, silently corrupting stop placement for high-vol bars.
**Severity:** HIGH — affects all signals in high-vol regimes.
**Detection:** Unit test: after APR migration, call `_adaptive_buffer({"garch_vol_ratio": 0.70}, 1.0)` should return 0.80; call with `vol_ratio=1.50` should return `1.0 + 0.50 * (0.35/0.50) = 1.35`; both constrained by `ADAPTIVE_BUFFER_HARD_CAP=1.40`. Write these as regression tests before removing the constants.

### 7.4 `validate_stop_against_zone()` silent correction hides geometry problems

**Risk:** `validate_stop_against_zone()` corrects stops that land inside the zone. If the per-asset-class floor from A3 is set too low, stops could still be very close to entry after correction, but the zone gate would pass because the stop is technically outside the zone.
**Severity:** MEDIUM. This is not introduced by Phase 132 — it exists today. The fix is setting appropriate A3 seed values (done in section 4.3 above).
**Detection:** After lifecycle_replay, check `WHERE exit_reason = 'stopped_at_entry'` — should be 0.

### 7.5 Module-level constant still used after `_cfg()` replacement

**Risk:** If a constant is used in multiple places but only some references are updated, the remaining hardcoded references silently ignore APR.
**Severity:** MEDIUM.
**Detection:** After APR migration, run `grep -n "ATR_STOP_DEMAND_MULTIPLIER\|ATR_STOP_SWEEP_MULTIPLIER\|MIN_STOP_ATR_MULTIPLIER\|MIN_RR_T1\|ADAPTIVE_BUFFER_HARD_CAP" src/intelligence/trading/trade_framer.py` — should return only the constant definition comment or zero results if constants are removed.

### 7.6 DAG invariant check: does trade_framer touch the database?

**Confirmed: NO.** trade_framer.py imports only from `src.observability.metrics`, `src.intelligence.trading.plugin_utils`, and `src.intelligence.trading.zone_engine`. No DB imports, no asyncpg. The config service is injected and uses a pre-warmed cache — the `get_sync()` call reads the in-memory cache, not the DB. DAG invariant 3 is satisfied.

---

## 8. Implementation Approach

### Recommended plan structure (Claude's Discretion: separate A2 check, then A5+A3 together)

**Plan 132-01: Measure current stopped_at_entry rate**
- Run 2-week sample replay (`run_historical_pipeline.py --replay-only --start 2026-06-01 --end 2026-06-14`)
- Run lifecycle_replay on same date range
- Query `SELECT exit_reason, COUNT(*) FROM trade_executions GROUP BY 1`
- If stopped_at_entry = 0 or <5%: document and close A2
- If stopped_at_entry ≥ 5%: investigate which zone_source paths produce them, apply targeted fix

**Plan 132-02: APR migration (A5 + A3)**
1. Write migration `144_phase132_trade_framer_apr.sql` with all 35 APR keys (19 module constants + 12 adaptive buffer + 4 per-class floors)
2. Add all 35 keys to `_THRESHOLD_KEYS` in `services/intelligence_pipeline.py`
3. Replace all module-level constant references in trade_framer.py with `_cfg()` calls (preserving existing constant values as defaults)
4. Write regression unit tests: verify `_adaptive_buffer()` produces identical output with APR-backed values at seeds vs hardcoded values
5. Confirm `stopped_at_entry = 0` in test replay after APR migration (signals at seed values should be geometrically identical)

**Plan 132-03: Verification**
- Run 1-month sample replay + lifecycle_replay
- Confirm `stopped_at_entry < 5%` of stop exits
- Confirm all APR keys visible in `/config/parameters` dashboard
- Confirm regression test (APR at seed values = hardcoded values) passes

### Simplest correct solution

The Phase 126 gates already fix the geometry. Phase 132 is primarily a constant migration with a measurement step. The critical correctness property is: APR values at seed equal the current hardcoded values, so no behavioral change at deployment. ML tuning only begins after Phase 133 corpus rebuild.

Do not re-architect the adaptive buffer as a JSON structure — keep 12 distinct scalar keys. The planner can group them logically in the migration description but they must be individually queryable from the `/config/parameters` dashboard for ML tuning.

---

## 9. Validation Architecture

### 9.1 Pre-fix baseline (Plan 132-01 output)

```sql
SELECT exit_reason, COUNT(*) as count,
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as pct
FROM trade_executions
GROUP BY 1 ORDER BY 2 DESC;
```

Baseline (current): stopped_at_entry = 0 (Phase 126 gates working).

### 9.2 Post-APR migration regression test

Goal: APR-backed code at seed values produces identical TradeFrame outputs to hardcoded constants.

```python
# Unit test pseudocode
# Before APR: result_before = frame_trade(...)  [with hardcoded constants]
# After APR: inject mock ConfigService returning seed values; result_after = frame_trade(...)
# Assert: result_before.stop == result_after.stop (within EPSILON_TOLERANCE)
#         result_before.entry == result_after.entry
#         result_before.viable == result_after.viable
```

Specifically test `_adaptive_buffer()`:
- `vol_ratio=0.70` → `garch_mult=0.80`, result should be `0.80 * base_mult`
- `vol_ratio=1.00` → `garch_mult=1.00`, result should be `1.00 * base_mult`
- `vol_ratio=1.50` → `garch_mult=1.35`, capped by `hard_cap=1.40`, result should be `min(1.35, 1.40) * base_mult`

### 9.3 stopped_at_entry < 5% gate

**Important:** `stopped_at_entry` is written by `lifecycle_replay.py` (not the backfill script). The query is only valid AFTER lifecycle_replay completes on the same date range.

```sql
SELECT exit_reason, COUNT(*), 
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as pct
FROM trade_executions
GROUP BY 1 ORDER BY 2 DESC;
-- Pass criterion: stopped_at_entry row is absent OR pct < 5.00
```

### 9.4 APR keys visible check

```sql
SELECT COUNT(*) FROM config_state WHERE config_key LIKE 'feature.trade_framer.%';
-- Expected: 35 (or actual count from implementation)
```

---

## Sources

### Primary (HIGH confidence)
- Direct code read: `src/intelligence/trading/trade_framer.py` lines 1-1231
- Direct code read: `src/intelligence/trading/zone_engine.py` lines 1-499
- Direct code read: `services/intelligence_pipeline.py` lines 430-536
- Direct code read: `src/config/config_service.py` lines 1-80
- DB queries: `config_state`, `trade_executions`, `intelligence_features` (live DB 2026-06-17)

### Secondary (MEDIUM confidence)
- `.planning/todos/pending/2026-06-14-trade-framer-apr-migration.md` — constant table (verified against actual code)
- `.planning/phases/132-stop-zone-geometry-apr-migration/132-CONTEXT.md` — locked decisions

---

## Metadata

**Confidence breakdown:**
- Stop geometry current state: HIGH — read actual code + queried live DB
- APR constant inventory: HIGH — read every line of trade_framer.py; 35 keys vs 16 in todo (adaptive buffer decomposition is the difference)
- Empirical seed values: HIGH — computed from 5M intelligence_features rows with exact field used at runtime
- Migration numbering: HIGH — read actual files
- Integration patterns: HIGH — read actual pipeline code, confirmed wiring exists

**Research date:** 2026-06-17
**Valid until:** 30 days (stable codebase; constants don't change without commits)

---

## RESEARCH COMPLETE
