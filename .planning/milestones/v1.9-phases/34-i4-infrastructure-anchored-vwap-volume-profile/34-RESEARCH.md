# Phase 34: I4 Infrastructure — Anchored VWAP + Volume Profile - Research

**Researched:** 2026-03-17
**Domain:** Plugin tier migration (I3/I5 → I4), VWAP computation, volume profile, I7 setup plugins
**Confidence:** HIGH — all findings verified against live source code

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Plugin Architecture — Upgrade + Migrate (no duplication)**
- Do NOT create new parallel plugins — two overlapping plugins already exist; duplicate feature names would introduce multicollinearity that silently degrades logistic regression in `weight_updater.py`
- Migrate `structure/anchored_vwap.py` → `context/anchored_vwap.py`: keep all existing output names (`session_vwap`, `swing_vwap`, `weekly_vwap`, `above_session_vwap`, `vwap_alignment_score`, etc.), add new I4 fields (bands, deviation sigma, velocity). Update TIER_I3 → TIER_I4. One canonical VWAP computation.
- Migrate `patterns/volume_profile.py` → `context/volume_profile.py`: keep existing output names (`nearest_hvn_level`, `nearest_hvn_dist_atr`, `nearest_lvn_level`, `in_lvn`), add new fields (poc, vah, val, session/rolling dual track, VA context). Update TIER_I5 → TIER_I4. One canonical volume profile computation.
- DAG ordering: both now in I4 — run after I3 (swings available for swing VWAP anchor) and before I7 (features available for setups). No ordering issue.

**AnchoredVWAP — New I4 Fields**
- `avwap_upper_band`, `avwap_lower_band`: computed for session VWAP anchor
- `swing_vwap_upper_band`, `swing_vwap_lower_band`: std band calculation anchored to swing VWAP
- `session_vwap_deviation_sigma`: `(close - session_vwap) / std(typical - session_vwap)`
- `swing_vwap_deviation_sigma`: same for swing VWAP anchor
- `session_vwap_deviation_velocity`: rate of change of `session_vwap_deviation_sigma` over last 3 bars

**Volume Profile — Dual Track**
- Session-reset track (primary): resets at session open (09:30 ET). Outputs: `poc_price`, `vah`, `val`, `nearest_hvn_above`, `nearest_hvn_below`, `nearest_lvn_above`, `nearest_lvn_below`
- Rolling fixed-window track (parallel): last 480 bars. Outputs: `poc_price_rolling`, `vah_rolling`, `val_rolling`
- Keep existing outputs (`nearest_hvn_level`, `nearest_hvn_dist_atr`, `nearest_lvn_level`, `in_lvn`)

**Value Area Context Fields**
- `price_in_value_area`, `va_width_atr`, `distance_to_vah_atr`, `distance_to_val_atr` — all logged every bar

**I7 VWAP Setups**
- `trad_AnchoredVWAPReversion`: gate `abs(session_vwap_deviation_sigma) > 1.5 AND hmm_regime == 0 AND hurst_exponent < 0.55`, `regime_type = "mean_reversion"`, `entry_type = "at_limit"`
- `trad_VWAPReclaim`: prior bar closes wrong side of session VWAP, current bar reclaims with `rel_volume > 1.2`, `regime_type = "any"`, `entry_type = "at_pullback"`

**I7 Volume Profile Setups — Three Separate Plugins**
- `trad_POCRejection`: `abs(close - poc_price) / atr_14 < 0.3` + momentum reversal, `regime_type = "mean_reversion"`
- `trad_HVNRejection`: price within 0.3×ATR of `nearest_hvn_above`/`nearest_hvn_below` + momentum reversal, `regime_type = "mean_reversion"`
- `trad_LVNBreakout`: `in_lvn == 1.0 AND rel_volume > 1.5 AND hmm trending`, `regime_type = "trend"`

**Cross-Plugin Architecture**
- All 5 new I7 plugins call `trade_framer.py`
- All fire as production signals immediately (no shadow gate)
- All log continuous values every bar

### Claude's Discretion
- Exact std band computation (rolling std window length within session — start of session vs trailing N bars)
- `poc_migration_rate` implementation
- HVN `volume_rank` computation methodology
- Momentum reversal indicator used in POC/HVN rejection gate (RSI divergence vs oscillator cross vs candle pattern)
- Exact `bars_below_vwap` maximum cap for VWAPReclaim

### Deferred Ideas (OUT OF SCOPE)
- MTF volume profile convergence (1m/5m/15m POC agreement at same price)
- VWAP anchor selection by highest-volume day
- `poc_migration_rate` field (unless Claude adds it)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VWAP-01 | Migrate AnchoredVWAP to I4 context with new I4 fields (bands, sigma, velocity) | Existing plugin at `src/intelligence/structure/anchored_vwap.py` is fully functional — migrate and extend. New fields added to I4Context schema. TIER_I3 remove, TIER_I4 add. |
| VWAP-02 | New I7 plugin `trad_AnchoredVWAPReversion` — extended by context decision to also include `trad_VWAPReclaim` | `mean_reversion.py` is the closest reference pattern. `hurst_exponent` confirmed in I4Context schema. `hmm_regime` confirmed in SMCContext. `rel_volume` confirmed available via `features.get()` (computed from bar data or `volume_ratio` in I1). |
| VOL-01 | Migrate VolumeProfile to I4 context with session-reset + rolling dual-track and POC/VAH/VAL | Existing plugin at `src/intelligence/patterns/volume_profile.py` has working histogram. Session reset logic in `src/intelligence/context/session_context.py` (`_ET_TZ`, `_in_window()`). |
| VOL-02 | Three I7 plugins: `trad_POCRejection`, `trad_HVNRejection`, `trad_LVNBreakout` | `in_lvn`, `nearest_hvn_level` already exist in plugin — extend to directional `nearest_hvn_above`/`nearest_hvn_below`. `rel_volume` gate available via bar volume ratio. |
</phase_requirements>

---

## Summary

Phase 34 migrates two existing computation plugins up the DAG to I4/context/ and extends each with richer feature fields, then implements five I7 setup plugins that consume the new I4 infrastructure. All implementation work is in Python — no new services, no Redpanda topics, and no schema outside the existing intelligence bus.

The migration pattern is well-established in this codebase: change file location, update TIER lists in `register_plugins.py`, add new fields to the relevant schema model (I4Context or I5Patterns removal), update `validate_schema_coverage()` tier check lists, and add all new field names to the plugin's `outputs` frozenset. The strict `extra="forbid"` on `I4Context` means every new output field must be declared in the schema before any plugin outputs it.

The five new I7 plugins follow the exact same minimal pattern as `choch_reversal.py` and `mean_reversion.py`: `@dataclass`, `name`, `outputs`, `regime_type`, `_state`, `compute_full()`, `_no_signal()`, and a module-level `plugin = PluginClass()`. All delegate stop/target resolution to `frame_trade()` from `trade_framer.py` — no per-plugin stop logic.

**Primary recommendation:** Implement in three work units — (1) migrate + extend AnchoredVWAP plugin + schema + tests, (2) migrate + extend VolumeProfile plugin + schema + tests, (3) implement all five I7 plugins + update TIER_I7 + DB migration.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | installed | Array math for VWAP/histogram computation | Already used in both existing plugins |
| pydantic | installed | Schema validation (IntelligenceEvent) | Canonical typed bus requires it |
| dataclasses | stdlib | Plugin class definition | Project-wide plugin pattern |
| zoneinfo | stdlib | ET timezone for session reset | Used by `session_context.py` (`ZoneInfo("America/New_York")`) |

### No new dependencies required
All libraries needed are already installed and in use.

---

## Architecture Patterns

### Recommended File Structure After Migration
```
src/intelligence/
├── context/
│   ├── anchored_vwap.py       # MOVED from structure/; extended with I4 fields
│   └── volume_profile.py      # MOVED from patterns/; extended with dual-track
├── structure/
│   └── anchored_vwap.py       # DELETE after migration
├── patterns/
│   └── volume_profile.py      # DELETE after migration
└── trading/
    ├── anchored_vwap_reversion.py   # NEW trad_AnchoredVWAPReversion
    ├── vwap_reclaim.py              # NEW trad_VWAPReclaim
    ├── poc_rejection.py             # NEW trad_POCRejection
    ├── hvn_rejection.py             # NEW trad_HVNRejection
    └── lvn_breakout.py              # NEW trad_LVNBreakout
```

### Pattern 1: Plugin Tier Migration
**What:** Move plugin file, update name prefix, update TIER lists and schema coverage check, update imports in `register_plugins.py`.
**When to use:** When a plugin is promoted to an earlier/later DAG tier.

Critical steps in order:
1. Copy file to new location (e.g., `context/anchored_vwap.py`)
2. Rename plugin class and `name` attribute (e.g., `"ctx_AnchoredVWAP"`)
3. Add new output fields to `outputs` frozenset
4. Add new field declarations to `I4Context` schema (not `I3Structure`)
5. Remove old field declarations from `I3Structure` (the 8 existing VWAP fields)
6. Update `validate_schema_coverage()` tier check: remove from `I3` check list, add to `I4` check list
7. Update `TIER_I3` / `TIER_I5` to remove old plugin names; update `TIER_I4` to add both
8. Update imports in `register_plugins.py`
9. Delete old files

**Critical:** The `validate_schema_coverage()` function in `register_plugins.py` checks each plugin's `outputs` against the schema class for its tier. Both migrated plugins must be moved into the `I4` tier check and removed from their old tier checks. Missing this causes a `RuntimeError` at startup.

### Pattern 2: I4Context Schema Extension
**What:** Add new `float | None = None` fields to `I4Context` in `schemas.py` under a clearly labeled comment block.

Existing I4 VWAP fields live in `I3Structure`. After migration all VWAP fields move to `I4Context`. Volume Profile fields currently in `I5Patterns` move to `I4Context`.

Fields to add to `I4Context`:
```python
# AnchoredVWAPPlugin outputs (migrated from I3Structure)
session_vwap: float | None = None
session_vwap_dist_pct: float | None = None
swing_vwap: float | None = None
weekly_vwap: float | None = None
above_session_vwap: float | None = None
above_swing_vwap: float | None = None
above_weekly_vwap: float | None = None
vwap_alignment_score: float | None = None
# New I4 VWAP fields
avwap_upper_band: float | None = None
avwap_lower_band: float | None = None
swing_vwap_upper_band: float | None = None
swing_vwap_lower_band: float | None = None
session_vwap_deviation_sigma: float | None = None
swing_vwap_deviation_sigma: float | None = None
session_vwap_deviation_velocity: float | None = None
# VolumeProfilePlugin outputs (migrated from I5Patterns)
nearest_hvn_level: float | None = None
nearest_hvn_dist_atr: float | None = None
nearest_lvn_level: float | None = None
in_lvn: float | None = None
# New I4 volume profile fields
poc_price: float | None = None
vah: float | None = None
val: float | None = None
nearest_hvn_above: float | None = None
nearest_hvn_below: float | None = None
nearest_lvn_above: float | None = None
nearest_lvn_below: float | None = None
poc_price_rolling: float | None = None
vah_rolling: float | None = None
val_rolling: float | None = None
price_in_value_area: float | None = None
va_width_atr: float | None = None
distance_to_vah_atr: float | None = None
distance_to_val_atr: float | None = None
```

Fields to REMOVE from `I3Structure` (the 8 existing VWAP fields):
`session_vwap`, `session_vwap_dist_pct`, `swing_vwap`, `weekly_vwap`, `above_session_vwap`, `above_swing_vwap`, `above_weekly_vwap`, `vwap_alignment_score`

Fields to REMOVE from `I5Patterns` (the 4 existing VP fields):
`nearest_hvn_level`, `nearest_hvn_dist_atr`, `nearest_lvn_level`, `in_lvn`

**Warning:** `IntelligenceEvent` is serialized/deserialized across the bus. Removing fields from `I3Structure` and `I5Patterns` is safe because `extra="forbid"` — any old messages with those fields will fail validation. Since this is a migration (not removal), old messages from before the migration are not a concern for a live system restart.

### Pattern 3: Std Band Computation for VWAP (Claude's Discretion)
**What:** Compute rolling std of `(typical - session_vwap)` over the current session window.
**Recommendation:** Use cumulative std over the full session window (start of session to current bar), not a trailing N-bar window. Rationale: VWAP itself is session-cumulative — anchoring the std to the same window is consistent. The full-session std widens through the day, which naturally tightens the deviation sigma as the day matures (more data = more stable mean), producing fewer false-extension signals in the afternoon.

```python
# Source: existing anchored_vwap.py pattern + VWAP std methodology
# Compute over session slice (bar 0 to current)
deviations = typical - session_vwap  # element-wise deviation
session_std = float(np.std(deviations)) if len(deviations) > 1 else 0.0
avwap_upper_band = session_vwap + 2.0 * session_std
avwap_lower_band = session_vwap - 2.0 * session_std
session_vwap_deviation_sigma = (current_close - session_vwap) / session_std if session_std > 0 else 0.0
```

**Velocity over last 3 bars requires `_state`:**
```python
key = (symbol, tf)
prev_sigmas = self._state.get(key, {}).get("prev_sigmas", [])
prev_sigmas = (prev_sigmas + [session_vwap_deviation_sigma])[-3:]
velocity = (prev_sigmas[-1] - prev_sigmas[0]) / len(prev_sigmas) if len(prev_sigmas) > 1 else 0.0
self._state[key] = {"prev_sigmas": prev_sigmas}
```

### Pattern 4: Session-Reset Volume Profile
**What:** Track intraday session volume separately from rolling window.
**Reference:** `session_context.py` `_ET_TZ` and `_in_window()` for session detection.

Session reset approach — use `_state` keyed by `(symbol, tf)`:
```python
# Detect session date from df timestamp column
if "timestamp" in df.columns:
    ts = df["timestamp"].iloc[-1]
    et_ts = ts.astimezone(_ET_TZ)
    session_date = et_ts.date()
    # Filter bars to current session (09:30 ET onward same day)
    ...
```

The plugin currently uses `lookback=120` (120 bars). For full session on 1m this needs `lookback=390` (6.5h × 60). **Critical:** Update `lookback` to 390 in VolumeProfilePlugin to capture a full session window. Alternatively, use the existing timestamp-based session slicing pattern already in `vwap.py` (I1).

### Pattern 5: Value Area Computation (70% Volume Rule)
**What:** Standard Market Profile value area — include price buckets in descending volume order until cumulative volume >= 70% of total session volume.

```python
# Sort bucket volumes descending, accumulate until 70% threshold
total_vol = vol_hist.sum()
target_vol = total_vol * 0.70
sorted_idx = np.argsort(vol_hist)[::-1]
cumvol = 0.0
va_buckets = []
for idx in sorted_idx:
    cumvol += vol_hist[idx]
    va_buckets.append(idx)
    if cumvol >= target_vol:
        break
if va_buckets:
    vah = float(bucket_prices[max(va_buckets)])
    val = float(bucket_prices[min(va_buckets)])
    poc_idx = int(np.argmax(vol_hist))
    poc_price = float(bucket_prices[poc_idx])
```

### Pattern 6: I7 Plugin Structure (Verified Against Codebase)
**What:** Every I7 plugin follows the same dataclass pattern.

```python
@dataclass
class AnchoredVWAPReversionPlugin:
    name: str = "trad_AnchoredVWAPReversion"
    outputs: frozenset[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=120),)
    regime_type: str = "mean_reversion"  # MANDATORY — aggregator regime gate uses this
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        ...

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}

plugin = AnchoredVWAPReversionPlugin()
```

### Pattern 7: Momentum Reversal Gate for POC/HVN (Claude's Discretion)
**Recommendation:** Use RSI divergence from existing `rsi_div_bullish`/`rsi_div_bearish` fields in features, supplemented by stochastic K<20 (long) or K>80 (short). Rationale: RSI divergence is already computed every bar (rsi_divergence.py), available in features dict, and uses the same rolling window as the POC/HVN distance check. This avoids implementing a new momentum indicator just for the rejection gate.

```python
# POC/HVN rejection — momentum reversal gate
direction == 1:  # long (price below, rejecting upward)
    rsi_div_ok = features.get("rsi_div_bullish", 0.0) > 0.3
    stoch_ok = float(features.get("stoch_k_14_3", 50.0)) < 30.0
    reversal_ok = rsi_div_ok or stoch_ok

direction == -1:  # short
    rsi_div_ok = features.get("rsi_div_bearish", 0.0) > 0.3
    stoch_ok = float(features.get("stoch_k_14_3", 50.0)) > 70.0
    reversal_ok = rsi_div_ok or stoch_ok
```

### Anti-Patterns to Avoid

- **Creating parallel plugins**: `avwap_session` alongside `session_vwap` — multicollinearity in logistic regression. The decision is locked: keep existing field names, add new fields alongside.
- **Using `set` instead of `frozenset`**: plugin `outputs` and `capability_tags` must be `frozenset`, not `set` — `registry.validate_tier()` iterates them and the pattern is consistent throughout.
- **Adding new output fields without schema declaration**: `extra="forbid"` on `I4Context` will raise a `ValidationError` at publish time. Every field in `outputs` must be in the schema.
- **Not updating `validate_schema_coverage()` tier lists**: the function checks each plugin against a hardcoded list of plugins per tier. After migration, `anchored_vwap_plugin` must be in the I4 check list, not the I3 check list.
- **Not removing old schema fields**: leaving VWAP fields in `I3Structure` after migration means they'll appear twice in the serialized event. The `extra="forbid"` model won't complain (the field just won't be populated), but it wastes space and misleads the training pipeline with always-null columns.
- **I7 plugins accessing `i3.session_vwap` directly**: I7 plugins receive a flat `features` dict from `signal_generator_service._build_features_from_event()`. They access fields by string key (`features.get("session_vwap")`), not by tier sub-model. The migration doesn't break I7 plugin access patterns — the flat features dict will still contain `session_vwap` after the VWAP plugin moves to I4.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Stop placement | Per-plugin stop logic | `frame_trade()` from `trade_framer.py` | GARCH-adaptive scaling, structural stops, RR gate all free |
| Session timezone | Manual offset math | `_ET_TZ = ZoneInfo("America/New_York")` from `session_context.py` | DST-correct; already in use |
| VWAP std bands | Custom band formula | Extend existing `AnchoredVWAPPlugin` computation | Session slice already computed |
| Volume histogram | Custom bin loop | Extend existing `VolumeProfilePlugin._N_BUCKETS=50` | NumPy histogram already working |
| Feature access | Direct `IntelligenceEvent` model | `features.get("field_name")` flat dict | Signal generator flattens all tier sub-models into one dict |

**Key insight:** `frame_trade()` handles GARCH-adaptive ATR scaling automatically. Passing `session_vwap` as the structural stop level (for VWAPReclaim) or `poc_price` (for POCRejection) doesn't require changes to `trade_framer.py` — the framer's structural stop hierarchy already has swing_low/high and S/R levels. For VWAP-specific structural stops, the I7 plugin must override the stop after `frame_trade()` returns, or pass the VWAP level as a synthetic S/R level in the features dict. The simplest approach: compute structural stop manually using VWAP as invalidation, then use `frame_trade()` for target resolution only.

---

## Common Pitfalls

### Pitfall 1: `validate_schema_coverage()` Hard-Crash at Startup
**What goes wrong:** Service crashes with `RuntimeError: Schema coverage gaps detected` on first run after migration.
**Why it happens:** `validate_schema_coverage()` in `register_plugins.py` has hardcoded lists of plugins per tier. Adding the migrated plugin to `TIER_I4` without updating the coverage check list leaves it in the I3 or I5 check where the schema fields are wrong.
**How to avoid:** After updating `TIER_I3`/`TIER_I5`/`TIER_I4`, update the `tier_checks` list in `validate_schema_coverage()` to match. Run `pytest tests/unit/intelligence/test_plugin_registry.py` locally before committing.
**Warning signs:** Any `RuntimeError` at import time from `register_plugins.py`.

### Pitfall 2: `registry.validate_tier()` Missing Plugin Name
**What goes wrong:** Service hard-crashes on startup with missing plugin name in tier list.
**Why it happens:** `TIER_I7` is a list of plugin `name` strings. If the new plugin's `name` attribute (e.g., `"trad_AnchoredVWAPReversion"`) doesn't match the string in `TIER_I7`, the validator will crash.
**How to avoid:** Copy the exact `name` string from the plugin class into `TIER_I7`. Build `TIER_I4` and `TIER_I7` additions from `plugin.name` attribute references (not string literals), following the pattern in the existing tier lists.

### Pitfall 3: Plugin Count Tests Need Updating
**What goes wrong:** `test_total_plugin_count` and `test_i7_plugins_registered` fail after adding 5 new I7 plugins.
**Why it happens:** These tests have hardcoded counts (`total == 104`) and hardcoded sets of expected plugin names.
**How to avoid:** Update `test_i7_registration.py` when adding the 5 new I7 plugins. New total: 104 + 5 = 109. New expected set: add all 5 new names.

### Pitfall 4: rel_volume Availability in I7 Gate
**What goes wrong:** `trad_VWAPReclaim` and `trad_LVNBreakout` gate on `rel_volume` but it returns None.
**Why it happens:** `rel_volume` is NOT produced by any I1 or I2 plugin as a named output. It is used by existing I7 plugins (ORB15, ORB30) as a fallback — they compute it from the bar dataframe if `features.get("rel_volume")` returns None. `volume_ratio` (in `I1Indicators`) is a different field produced by the legacy `_volume.py` calc module, not the current plugin system.
**How to avoid:** In all new I7 plugins that gate on volume, use the ORB15/ORB30 pattern:
```python
rel_volume = features.get("rel_volume")
if rel_volume is not None and isinstance(rel_volume, (int, float)):
    vol_ok = float(rel_volume) >= threshold
else:
    # Fallback: compute from bar dataframe
    bar_vol = float(df["volume"].iloc[-1])
    avg_vol = float(df["volume"].mean())
    vol_ok = avg_vol > 0 and bar_vol >= threshold * avg_vol
```

### Pitfall 5: Removing Fields from I3Structure Breaks Downstream Schema Consumers
**What goes wrong:** Any downstream consumer that accesses `event.i3.session_vwap` gets an `AttributeError`.
**Why it happens:** After removing the 8 VWAP fields from `I3Structure`, code that accesses `i3.session_vwap` will break. The `extra="forbid"` schema won't guard against this at runtime.
**How to avoid:** `grep -rn "i3\.session_vwap\|i3\.swing_vwap\|i3\.weekly_vwap\|i3\.above_session_vwap\|i3\.vwap_alignment"` across all services and tests before removing the fields. Verify no code directly accesses `i3.` sub-model attributes for these fields.

### Pitfall 6: Session-Reset Logic in VolumeProfile Needs Timestamp Data
**What goes wrong:** Session reset never fires because `df["timestamp"]` column is absent.
**Why it happens:** VolumeProfilePlugin currently uses `lookback=120` and doesn't inspect timestamps. The session-reset track requires timestamp-aware slicing.
**How to avoid:** Follow the pattern in `vwap.py` (I1) which already does session detection via `pd.to_datetime(df["timestamp"])`. Increase `lookback` to 390 in VolumeProfilePlugin's `InputSpec` for session coverage on 1m. Add a guard: if timestamp column absent, fall back to full window (rolling track only).

### Pitfall 7: poc_price Collision with I3Structure.poc_level
**What goes wrong:** Schema validation confusion between `poc_level` (already in I3Structure from MarketProfilePlugin) and new `poc_price` (in I4Context from VolumeProfilePlugin).
**Why it happens:** `struct_MarketProfile` outputs `poc_level`, `va_high`, `va_low`. The new VolumeProfilePlugin uses different names: `poc_price`, `vah`, `val`.
**How to avoid:** The names are different — no collision. But planners/implementers must not confuse them. `poc_level` is the I3 Market Profile POC (tick-histogram based, rolling). `poc_price` is the I4 Volume Profile POC (session-cumulative, volume-based). Both are legitimate independent features.

---

## Code Examples

### Computing VWAP Std Deviation (Session-Anchored)
```python
# Source: extension of src/intelligence/structure/anchored_vwap.py computation
# Compute over same session slice as session_vwap
deviations = typical - session_vwap  # already computed: typical = (H+L+C)/3, session_vwap cumulative
session_std = float(np.std(deviations)) if len(deviations) > 1 else 0.0
if session_std > 0:
    avwap_upper_band = session_vwap + 2.0 * session_std
    avwap_lower_band = session_vwap - 2.0 * session_std
    session_vwap_deviation_sigma = (current_close - session_vwap) / session_std
else:
    avwap_upper_band = session_vwap
    avwap_lower_band = session_vwap
    session_vwap_deviation_sigma = 0.0
```

### Value Area 70% Rule
```python
# Standard Market Profile value area algorithm
# Source: market profile methodology; extends existing VolumeProfilePlugin histogram
total_vol = vol_hist.sum()
target_vol = total_vol * 0.70
sorted_idx = np.argsort(vol_hist)[::-1]
cumvol = 0.0
va_buckets = set()
for idx in sorted_idx:
    cumvol += vol_hist[idx]
    va_buckets.add(int(idx))
    if cumvol >= target_vol:
        break
poc_idx = int(np.argmax(vol_hist))
poc_price = float(bucket_prices[poc_idx])
if va_buckets:
    vah = float(bucket_prices[max(va_buckets)])
    val = float(bucket_prices[min(va_buckets)])
```

### Directional HVN/LVN Detection
```python
# Extend existing HVN/LVN detection with directional fields
# Source: extends src/intelligence/patterns/volume_profile.py
if len(hvn_prices) > 0:
    hvn_above = hvn_prices[hvn_prices > close]
    hvn_below = hvn_prices[hvn_prices <= close]
    nearest_hvn_above = float(hvn_above.min()) if len(hvn_above) > 0 else None
    nearest_hvn_below = float(hvn_below.max()) if len(hvn_below) > 0 else None
if len(lvn_prices) > 0:
    lvn_above = lvn_prices[lvn_prices > close]
    lvn_below = lvn_prices[lvn_prices <= close]
    nearest_lvn_above = float(lvn_above.min()) if len(lvn_above) > 0 else None
    nearest_lvn_below = float(lvn_below.max()) if len(lvn_below) > 0 else None
```

### VWAPReclaim bars_below_vwap State Tracking (Claude's Discretion: cap at 20 bars)
```python
# Track consecutive bars below/above session VWAP using _state
key = (symbol, tf)
state = self._state.get(key, {})
above_vwap_prev = state.get("above_vwap_prev", None)
bars_below_counter = state.get("bars_below_counter", 0)
above_now = 1.0 if current_close > session_vwap else 0.0
if above_now == 0.0:
    bars_below_counter = min(bars_below_counter + 1, 20)  # cap at 20 bars
else:
    bars_below_counter = 0
state.update({"above_vwap_prev": above_now, "bars_below_counter": bars_below_counter})
self._state[key] = state
# Gate: reclaim from below = prior bar was below, current bar is above
reclaim_long = above_vwap_prev == 0.0 and above_now == 1.0 and bars_below_counter > 0
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| VWAP in I3/structure/ | VWAP in I4/context/ | Phase 34 | DAG correct — runs after I3 swing detection |
| VolumeProfile in I5/patterns/ | VolumeProfile in I4/context/ | Phase 34 | Correct tier — context-level feature, not a pattern |
| Single VP nearest-HVN field | Directional HVN above/below + POC/VAH/VAL | Phase 34 | I7 setups can gate on direction-aware proximity |
| No VWAP extension setups | `trad_AnchoredVWAPReversion` + `trad_VWAPReclaim` | Phase 34 | Two independent VWAP alpha tests |
| No volume node setups | Three VP plugins (POC, HVN, LVN) | Phase 34 | Mean-reversion and trend separately tracked |

**Deprecated/outdated:**
- `struct_AnchoredVWAP` plugin name — replaced by `ctx_AnchoredVWAP` in phase 34
- `patt_VolumeProfile` plugin name — replaced by `ctx_VolumeProfile` in phase 34

---

## Open Questions

1. **Should VWAPReclaim also track bars above VWAP for short setup?**
   - What we know: CONTEXT.md specifies both directions (above/below)
   - What's unclear: whether the state tracking uses a single counter for "wrong side" bars regardless of direction
   - Recommendation: implement a single `bars_wrong_side` counter that increments when below (long) or above (short), reset when reclaimed. Symmetric logic.

2. **Does `poc_price` need to be added to `trade_framer.py`'s structural stop candidates?**
   - What we know: `trade_framer.py` uses swing_low, OB, demand zone, S/R as structural stops. POC is not in the hierarchy.
   - What's unclear: whether POCRejection should rely on the framer's existing hierarchy or explicitly pass POC as a custom stop
   - Recommendation: For `trad_POCRejection`, compute stop as `poc_price ± ATR×0.20` in the plugin directly (before calling `frame_trade()`), then pass it as the `entry` to frame_trade with the POC level as the invalidation boundary. The framer's structural stop will land near `swing_low` which may be appropriate. Alternatively, use the framer for targets only, override `stop` from the returned frame. Document the decision.

3. **VWAP plugin name collision — `VWAP` (I1) vs `ctx_AnchoredVWAP` (I4)**
   - What we know: I1 `VWAP` plugin outputs `vwap`, `vwap_upper_1`, `vwap_lower_1`, `vwap_upper_2`, `vwap_lower_2`, `vwap_std`. These are different fields from the new I4 AVWAP outputs.
   - What's unclear: whether `vwap` (I1) and `session_vwap` (I4) will be numerically identical or diverge
   - Recommendation: They will differ slightly — I1 VWAP uses session detection based on date boundary; I4 AnchoredVWAP currently uses all 120 lookback bars without session slicing (review: the existing `anchored_vwap.py` computes session VWAP as `tpv.sum() / total_vol` over ALL lookback bars, not just the current session). **Fix as part of migration**: add session-aware slicing to the I4 plugin to use only current-session bars, matching what I1 VWAP does. This makes `session_vwap` truly session-anchored.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pytest.ini` or inferred |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/ -x -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VWAP-01 | AnchoredVWAP migrated to I4, new fields computed | unit | `.venv/bin/pytest tests/unit/intelligence/context/test_anchored_vwap.py -x` | ❌ Wave 0 |
| VWAP-01 | Schema coverage: all AVWAP outputs declared in I4Context | unit | `.venv/bin/pytest tests/unit/intelligence/test_plugin_registry.py -x` | ✅ (existing) |
| VWAP-01 | TIER_I3 no longer contains ctx_AnchoredVWAP | unit | `.venv/bin/pytest tests/unit/intelligence/test_i4_new_plugins.py -x` | ✅ (extend) |
| VWAP-02 | trad_AnchoredVWAPReversion fires on correct gate conditions | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_anchored_vwap_reversion.py -x` | ❌ Wave 0 |
| VWAP-02 | trad_VWAPReclaim fires on reclaim bar with volume confirmation | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_vwap_reclaim.py -x` | ❌ Wave 0 |
| VOL-01 | VolumeProfile migrated to I4, session-reset + rolling computed | unit | `.venv/bin/pytest tests/unit/intelligence/context/test_volume_profile.py -x` | ❌ Wave 0 |
| VOL-01 | POC/VAH/VAL computed correctly (70% value area) | unit | `.venv/bin/pytest tests/unit/intelligence/context/test_volume_profile.py::test_poc_value_area -x` | ❌ Wave 0 |
| VOL-02 | trad_POCRejection fires near POC with momentum reversal | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_poc_rejection.py -x` | ❌ Wave 0 |
| VOL-02 | trad_HVNRejection fires near nearest_hvn_above/below | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_hvn_rejection.py -x` | ❌ Wave 0 |
| VOL-02 | trad_LVNBreakout fires on in_lvn + rel_volume + trending | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_lvn_breakout.py -x` | ❌ Wave 0 |
| ALL | All 5 new I7 plugins in TIER_I7, total count = 109 | unit | `.venv/bin/pytest tests/unit/intelligence/test_i7_registration.py -x` | ✅ (update counts) |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/intelligence/ -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/intelligence/context/test_anchored_vwap.py` — covers VWAP-01
- [ ] `tests/unit/intelligence/context/test_volume_profile.py` — covers VOL-01
- [ ] `tests/unit/intelligence/trading/test_anchored_vwap_reversion.py` — covers VWAP-02
- [ ] `tests/unit/intelligence/trading/test_vwap_reclaim.py` — covers VWAP-02
- [ ] `tests/unit/intelligence/trading/test_poc_rejection.py` — covers VOL-02
- [ ] `tests/unit/intelligence/trading/test_hvn_rejection.py` — covers VOL-02
- [ ] `tests/unit/intelligence/trading/test_lvn_breakout.py` — covers VOL-02

Existing tests to UPDATE (not create):
- `tests/unit/intelligence/test_i7_registration.py` — update count from 23 to 28, add 5 new plugin names to `expected_i7` set, update `total == 104` to `total == 109`
- `tests/unit/intelligence/test_i4_new_plugins.py` — add AVWAP/VP migration coverage
- `tests/unit/intelligence/test_structure_plugins.py` — remove VWAP fields from I3 coverage
- `tests/unit/intelligence/test_pattern_plugins.py` — remove VP fields from I5 coverage

---

## DB Migration Required

Migration file: `036_vwap_volume_profile_fields.sql` (next sequential number after `035_stop_basis_and_divergence_stack.sql`)

New columns to add to `intelligence_features` i4 JSONB (stored in the `i4` column as JSONB — no ALTER TABLE needed for JSONB fields). However, verify the schema: if `intelligence_features` stores these as top-level columns rather than JSONB, ALTER TABLE is required.

**Verification needed:** Check `intelligence_features` table DDL to confirm column storage.

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "\d intelligence_features"
```

The CONTEXT.md states: "DB migration required: new schema columns for `session_vwap_deviation_sigma`, `avwap_upper_band`..." — this implies top-level columns, not JSONB fields. The migration is likely `ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS ...` for each new field.

---

## Sources

### Primary (HIGH confidence)
- `src/intelligence/structure/anchored_vwap.py` — existing plugin code, verified
- `src/intelligence/patterns/volume_profile.py` — existing plugin code, verified
- `src/intelligence/schemas.py` — canonical schema fields, verified
- `src/intelligence/register_plugins.py` — TIER lists + `validate_schema_coverage()` logic, verified
- `src/intelligence/trading/trade_framer.py` — full stop/target resolution logic, verified
- `src/intelligence/trading/mean_reversion.py` — I7 plugin reference pattern, verified
- `src/intelligence/trading/choch_reversal.py` — minimal I7 plugin pattern, verified
- `src/intelligence/context/session_context.py` — `_ET_TZ`, `_in_window()`, session patterns, verified
- `src/intelligence/trading/orb15.py` — `rel_volume` fallback pattern, verified
- `src/intelligence/trading/aggregator.py` — `TREND_SETUPS` frozenset, verified
- `tests/unit/intelligence/test_i7_registration.py` — current plugin count = 23, total = 104, verified

### Secondary (MEDIUM confidence)
- Market Profile 80% value area rule — standard methodology documented across trading literature; implementation follows standard 70% cumulative volume definition

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in use, no new dependencies
- Architecture patterns: HIGH — verified against live plugin code
- Migration procedure: HIGH — exact steps derived from `validate_schema_coverage()` source
- Pitfalls: HIGH — based on actual code behavior observed in register_plugins.py and test files
- DB migration details: MEDIUM — CONTEXT.md implies top-level columns but table DDL not checked

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable codebase; only changes if Phase 34 is delayed past a major refactor)
