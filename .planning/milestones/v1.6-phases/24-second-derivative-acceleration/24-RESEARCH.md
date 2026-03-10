# Phase 24: Second-Derivative Acceleration — Research

**Researched:** 2026-03-10
**Domain:** Python dataclasses, numpy, pandas, pytest — plugin-native intelligence pipeline (I1/I2/I3/I7)
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **I1 change (1):** New `HMA` indicator — Hull Moving Average (n=20): WMA(2×WMA(n/2) − WMA(n), sqrt(n)); output `hma_20`. Add to `moving_averages.py` or new `hma.py`. ~30 lines. Prerequisite for HMA slope/accel below.
- **I2 changes (4):**
  1. Extend `MomentumAcceleration` — add `rsi_curvature`, `macd_hist_slope`, `price_accel`, `hma_slope`, `hma_accel` outputs (`hma_slope = hma_20[t] - hma_20[t-1]`, `hma_accel = hma_slope[t] - hma_slope[t-1]`)
  2. New `ExhaustionScore` plugin (`cmp_ExhaustionScore`) — outputs `exhaustion_score`, `exhaustion_side`, `exhaustion_bars`
  3. New `AccelerationRegime` plugin (`cmp_AccelerationRegime`) — outputs `accel_regime`, `accel_score`, `accel_agreement`
- **I3 change (1):** New `SwingMomentum` plugin (`struct_SwingMomentum`) — outputs `swing_amplitude_ratio`, `swing_amplitude_expanding`, `swing_velocity_bars`, `swing_velocity_trend`, `struct_energy`, `struct_accel_bias`
- **I7 wiring (4 setups, score adjustments only):**
  - `LiquiditySweepReclaim` + `LiquidityHunt` — exhaustion_score boost (confirms stop-run entry)
  - `MomentumBreakout` + `TrendFollowing` — exhaustion guard penalty (suppresses chasing exhausted moves)
- Plugin convention: `tuple[InputSpec, ...]` for inputs, `frozenset[str]` for outputs, `_state: dict` for inter-bar state
- New ExhaustionScore + AccelerationRegime → `TIER_I2`; SwingMomentum → `TIER_I3` in `register_plugins.py`
- All new features land in `intelligence_features` via `feature_writer_service` automatically — no wiring needed
- Closes todos: `2026-03-04-add-hma-i1-plugin.md`, `2026-03-06-expand-second-derivative-indicators.md`

### Claude's Discretion
- HMA can be added to `moving_averages.py` or a new `hma.py` — planner decides based on file size
- SwingMomentum internal peak/valley detection algorithm implementation details (±N bar window, N=3)
- Test helper function design for new plugins

### Deferred Ideas (OUT OF SCOPE)
- CIS adaptive weight learning
- HMA usage beyond slope/accel outputs (e.g., HMA crossover signals)
- ML scoring model (consumes features — separate future phase)
- Dashboard wiring for new acceleration fields
</user_constraints>

---

## Summary

Phase 24 adds second-derivative (acceleration) intelligence to the I1/I2/I3 tiers. The work is purely plugin-native: one new I1 indicator (HMA), three I2 composite expansions/additions, one I3 structural plugin, and four I7 score-adjustment wires. No new services, no DB migrations, no stream schema changes — all new outputs flow into `intelligence_features` JSONB automatically.

The design is fully specified in `docs/plans/2026-03-10-second-derivative-indicators-design.md` and the implementation plan in `docs/plans/2026-03-10-second-derivative-indicators-plan.md`. Both documents are the primary reference for the planner. This research documents the codebase patterns, gotchas, and test structure needed to execute the plan correctly.

The central insight this phase encodes: a setup entering with decelerating momentum at an extreme has poor odds; the same setup entering with accelerating momentum at a fresh level has excellent odds. Once encoded, this judgment applies to every bar across all 23 symbols and all timeframes — the Medallion principle in action.

**Primary recommendation:** Follow the implementation plan directly. The plugin patterns are well-established in this codebase. The main execution risk is `_state` management correctness in MomentumAcceleration (three new state keys must be added without breaking the four existing ones) and the SwingMomentum warmup gate (must return `{}` until 3 complete swings confirmed, not partial data).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python dataclasses | stdlib | Plugin class definition | All 91 existing plugins use `@dataclass` |
| numpy | project dep | Array math, OHLCV slicing | Used in all I3+ plugins for `df.to_numpy()` |
| pandas | project dep | DataFrame for OHLCV frames | `frames["main"]` is always a pandas DataFrame |
| pytest | project dep | Unit tests | `.venv/bin/pytest` — project standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `composites/common.py::is_num` | internal | Type-safe numeric check | All I2 plugins use `is_num(x)` instead of `if x` |
| `tests/unit/intelligence/helpers.py::make_ohlcv` | internal | Build OHLCV DataFrame from close array | Use for I3 SwingMomentum tests needing OHLCV |

**Installation:** No new dependencies required — everything uses existing project libraries.

---

## Architecture Patterns

### Plugin Protocol
All plugins are `@dataclass` classes implementing the `PatternPlugin` protocol from `src/intelligence/plugins.py`:
- `name: str` — must be unique string, prefix convention: `cmp_` (composite/I2), `struct_` (structure/I3)
- `outputs: frozenset[str]` — NOT `set[str]` or `list[str]` — must be `frozenset`
- `inputs: tuple[InputSpec, ...]` — NOT `list[InputSpec]` — must be `tuple`
- `_state: dict = field(default_factory=dict)` — inter-bar state, managed entirely by the plugin
- `compute_full(frames)` — called every bar; `compute_next` delegates to `compute_full` for stateful plugins
- `plugin = PluginClassName()` — module-level singleton at bottom of file
- Register in `register_all_plugins()` + add to `TIER_*` constant in `register_plugins.py`

### I2 Composite Plugin Structure
```python
# src/intelligence/composites/new_plugin.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from ..plugins import InputSpec
from .common import is_num

@dataclass
class NewPlugin:
    name: str = "cmp_NewPlugin"
    outputs: frozenset = field(
        default_factory=lambda: frozenset({"output_a", "output_b"})
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset = field(
        default_factory=lambda: frozenset({"momentum"})
    )
    inputs: tuple[InputSpec, ...] = ()   # reads from frames["features"] only
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        # ... logic ...
        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

plugin = NewPlugin()
```

### I3 Structure Plugin Structure
I3 plugins read OHLCV directly (`frames["main"]`) and also read accumulated features (`frames["features"]`). They have an `InputSpec` with lookback to declare their bar requirement:
```python
inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=60),)
```
When `frames["main"]` is `None` or `len(df) < self.min_lookback`, return `{}` immediately.

### `_state` Management in MomentumAcceleration
The existing plugin already has `prev_rsi_accel`, `prev_macd_accel`, `prev_roc_accel` in `_state`. Three new keys must be added:
- `prev_macd_histogram` — stores current `macd_histogram_12_26_9` for next bar's slope computation
- The `rsi_curvature` computation reuses the existing `prev_rsi_accel` state key — no new key needed
- `hma_slope` and `hma_accel` require reading `hma_20` from `features` and computing differences; need `prev_hma` in state

**CRITICAL gotcha:** The existing `prev_rsi_accel` state write (`self._state["prev_rsi_accel"] = rsi_accel`) already exists and must NOT be removed. The new `rsi_curvature` is computed from that same key before the write.

### I7 Score Adjustment Pattern
Existing pattern from `MomentumBreakout` and `TrendFollowing` (zone friction penalty):
```python
# After main confidence scoring but before return:
in_supply = float(features.get("in_supply_zone", 0.0))
if direction == 1 and in_supply == 1.0:
    confidence -= 0.12 * supply_str
    supporting.append("penalty_supply_zone_friction")
confidence = round(min(0.95, max(0.10, confidence)), 4)
```
The exhaustion guard follows the same pattern: adjust `confidence`, append audit tag to `supporting`, clamp. For suppression (`return {}`): check if `confidence` drops below the setup's fire threshold after penalty, then `return self._no_signal()`.

For boost setups (`LiquiditySweepReclaim`, `LiquidityHunt`): same pattern as existing `fvg_type` / `ob_type` boosts with `min(confidence, 0.95)` cap.

### HMA Formula
Hull Moving Average (n=20): `WMA(2×WMA(n/2, close) − WMA(n, close), sqrt(n))`
- WMA(k, series) = weighted average with weights [1, 2, ..., k]
- Requires min_lookback of n bars (20)
- Output: `hma_20` (float)
- Slope/accel: consumed by `MomentumAcceleration` via `frames["features"]["hma_20"]`

### SwingMomentum Internal Algorithm
Self-contained peak/valley detection (does NOT depend on `SwingDetector`):
- Confirm swing high: bar's high is highest in ±N bar window (N=3 default)
- Track last 5 confirmed extremes in `_state["extremes"]` (list of price/bar_index tuples)
- Warmup gate: return `{}` until 3 complete swings (6 extremes) confirmed
- ATR normalization: read `atr_14` from `frames["features"]`; if absent/zero, compute amplitude in raw price units

### Registration Pattern
```python
# In register_plugins.py — import section:
from .composites.exhaustion_score import plugin as exhaustion_score_plugin
from .composites.acceleration_regime import plugin as accel_regime_plugin
from .structure.swing_momentum import plugin as swing_momentum_plugin

# In register_all_plugins():
registry.register_pattern(exhaustion_score_plugin)
registry.register_pattern(accel_regime_plugin)
registry.register_pattern(swing_momentum_plugin)

# In TIER_I2 list:
TIER_I2: list[str] = [
    ...existing...,
    exhaustion_score_plugin.name,
    accel_regime_plugin.name,
]

# In TIER_I3 list:
TIER_I3: list[str] = [
    ...existing...,
    swing_momentum_plugin.name,
]
```

### Anti-Patterns to Avoid
- **`list[InputSpec]` instead of `tuple[InputSpec, ...]`:** Phase 23-03 cleanup explicitly fixed all 11 I7 plugins that had this wrong. New plugins MUST use `tuple[InputSpec, ...]`.
- **`set[str]` for outputs instead of `frozenset`:** Causes mutation hazards and inconsistency.
- **Reading `macd_12_26_9` for histogram slope:** The design specifies `macd_histogram_12_26_9` (the histogram, not the MACD line). Using the wrong key is a silent bug — the histogram leads zero-line crossovers by 1-2 bars, the line does not.
- **Not guarding ATR=0 in price_accel:** Division by zero if `atr` is 0 or None. Guard: `if is_num(atr) and atr > 0`.
- **Returning partial data before warmup:** SwingMomentum must return `{}` until 3 complete swings, not partial outputs. The existing `struct_SwingDetector` pattern: `if df is None or len(df) < self.min_lookback: return {}`.
- **Deriving `active` from raw signals not `all_ranked`:** Not directly relevant here but recorded for awareness. New plugins don't touch the aggregator.
- **`validate_tier()` hard-crash:** If any plugin name in `TIER_I2`/`TIER_I3` is not registered in the registry, the service crashes at startup. Import + register + add to TIER must all happen together.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Numeric type safety | Custom `isinstance(x, (int, float))` | `composites/common.py::is_num` | Already handles the `isinstance(val, int | float)` gotcha for MagicMock |
| OHLCV test data | Custom DataFrame builder | `tests/unit/intelligence/helpers.py::make_ohlcv` | Consistent synthetic data with correct high/low/open derivation |
| Feature store wiring | Manual `feature_writer_service` changes | Nothing — automatic | All outputs in `frames` dict land in JSONB automatically |
| Confidence clamping | Raw `min/max` calls | `round(min(0.95, max(0.10, confidence)), 4)` | Matches established pattern in all 4 target I7 plugins |

---

## Common Pitfalls

### Pitfall 1: State Key Collision in MomentumAcceleration
**What goes wrong:** Adding `rsi_curvature` to the existing plugin requires reading `prev_rsi_accel` from state BEFORE writing the new value. If the write happens first, curvature is always zero.
**Why it happens:** The existing code writes `self._state["prev_rsi_accel"] = rsi_accel` after computing inflection. The new curvature must read this key in the same block, before the write.
**How to avoid:** Compute `rsi_curvature = rsi_accel - prev_rsi_accel` (using the OLD state value) then write `self._state["prev_rsi_accel"] = rsi_accel`.
**Warning signs:** Test `test_rsi_curvature_computed_on_second_bar` always returns 0.0.

### Pitfall 2: macd_hist_slope State vs. prev_features
**What goes wrong:** `macd_hist_slope = current_hist - prev_hist` where `prev_hist` comes from `_state["prev_macd_histogram"]` (written by prior call), NOT from `frames["prev_features"]["macd_histogram_12_26_9"]`.
**Why it happens:** The design specifies state-based tracking for histogram (so the plugin owns its own history). Using `prev_features` would require the feature accumulator to have the histogram key, which is not guaranteed.
**How to avoid:** Always read `prev_macd_hist = self._state.get("prev_macd_histogram")` and write `self._state["prev_macd_histogram"] = macd_hist` each bar.
**Warning signs:** Slope is 0.0 on every bar, or jumps erratically.

### Pitfall 3: SwingMomentum Premature Output
**What goes wrong:** Plugin emits partial outputs (e.g., `swing_velocity_bars` but not `struct_energy`) before 3 complete swings are confirmed.
**Why it happens:** Incomplete warmup guard — checking extremes count against 3 instead of 6 (6 extremes = 3 complete high/low pairs = 3 swings).
**How to avoid:** Gate on `len(self._state.get("extremes", [])) >= 6` before any output. If not met, return `{}`.
**Warning signs:** `struct_energy` appears in early bars, or tests fail with KeyError on partial dicts.

### Pitfall 4: AccelerationRegime Peak/Trough Are Single-Bar Events
**What goes wrong:** Emitting `"peak"` on multiple consecutive bars when `accel_score` stays flat.
**Why it happens:** Not persisting `prev_accel_score` in state — each call re-evaluates against a default of 0.0.
**How to avoid:** Write `self._state["prev_accel_score"] = accel_score` each bar. Peak fires only when `prev_accel_score > 0.3` AND `accel_score <= 0.3`, then the following bar's prev_accel_score IS the current score (≤0.3), so it won't re-fire peak.
**Warning signs:** Test `test_peak_fires_once_then_reverts` shows peak on 2+ consecutive bars.

### Pitfall 5: I7 Suppression Return Value
**What goes wrong:** Returning `{}` instead of `self._no_signal()` when exhaustion guard suppresses.
**Why it happens:** Confusion between "no data" (`{}`) and "explicit no-signal" (`{"signal_type": "none", "direction": 0, "confidence": 0.0}`).
**How to avoid:** For I7 plugins, suppression must return `self._no_signal()`. Returning bare `{}` bypasses the aggregator's signal filtering.
**Warning signs:** Suppressed signals appearing in signal_ledger with direction=0.

### Pitfall 6: HMA min_lookback Insufficient
**What goes wrong:** HMA returns `None` or `{}` on bars 1-19 because WMA(n/2=10) needs 10 bars, WMA(n=20) needs 20 bars.
**Why it happens:** Not setting `min_lookback = 20` on the HMA plugin.
**How to avoid:** HMA(n=20) requires `min_lookback: int = 20`. Downstream consumers (MomentumAcceleration via features dict) must guard `is_num(hma_20)` before using it.

---

## Code Examples

### Existing `is_num` guard pattern (from composites/common.py)
```python
# Source: src/intelligence/composites/common.py
def is_num(x: Any) -> bool:
    return isinstance(x, int | float)
```

### Existing MomentumAcceleration state pattern (from momentum_accel.py)
```python
# Source: src/intelligence/composites/momentum_accel.py
if is_num(rsi) and is_num(prev_rsi):
    rsi_accel = rsi - prev_rsi
    prev_rsi_accel = self._state.get("prev_rsi_accel")
    if is_num(prev_rsi_accel) and prev_rsi_accel * rsi_accel < 0:
        inflection = 1
    self._state["prev_rsi_accel"] = rsi_accel
    out["rsi_accel"] = rsi_accel
else:
    out["rsi_accel"] = 0.0
```

### Existing I7 confidence adjustment pattern (from momentum_breakout.py)
```python
# Source: src/intelligence/trading/momentum_breakout.py
# Zone friction penalty — exhaustion guard follows same pattern
in_supply = float(features.get("in_supply_zone", 0.0))
if direction == 1 and in_supply == 1.0:
    confidence -= 0.12 * supply_str
    supporting.append("penalty_supply_zone_friction")
confidence = round(min(0.95, max(0.10, confidence)), 4)
```

### I7 sweep boost pattern (from liquidity_sweep_reclaim.py)
```python
# Source: src/intelligence/trading/liquidity_sweep_reclaim.py
fvg_type = features.get("fvg_type", 0.0)
if fvg_type == float(direction):
    confidence += 0.15
    supporting.append("fvg_confirmed")
confidence = round(min(1.0, confidence), 4)
```

### ExhaustionScore exhaustion_bars counter pattern
```python
# exhaustion_bars tracked in _state — not from features
if condition_holds:
    self._state["exhaustion_bars"] = self._state.get("exhaustion_bars", 0) + 1
else:
    self._state["exhaustion_bars"] = 0
out["exhaustion_bars"] = float(self._state["exhaustion_bars"])
```

### make_ohlcv helper (tests/unit/intelligence/helpers.py)
```python
# Source: tests/unit/intelligence/helpers.py
def make_ohlcv(close: np.ndarray, volume: np.ndarray | None = None) -> pd.DataFrame:
    n = len(close)
    spread = np.abs(close) * 0.002
    high = close + spread
    low = close - spread
    # ... returns pd.DataFrame with open/high/low/close/volume
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `list[InputSpec]` for inputs | `tuple[InputSpec, ...]` | Phase 23-03 | All new plugins must use tuple — the fix is now codebase standard |
| Per-bar RSI only (first derivative) | rsi_accel + rsi_curvature | This phase | Second derivative available for exhaustion detection |
| Manual chart reading for exhaustion | ExhaustionScore plugin | This phase | Systematic detection across 23 symbols, all TFs |

---

## Open Questions

1. **HMA in `moving_averages.py` vs. new `hma.py`**
   - What we know: `moving_averages.py` is 130 lines, handles SMA + EMA with incremental state
   - What's unclear: Whether adding HMA to the same file makes it unwieldy or cleaner
   - Recommendation: Add to `moving_averages.py` if < 50 lines added; create `hma.py` if HMA needs its own incremental state management. The CONTEXT.md says "add to `moving_averages.py` or new `hma.py`" — planner decides.

2. **MomentumAcceleration inputs field**
   - What we know: Current plugin has `inputs: list[InputSpec] = field(default_factory=list)` (empty)
   - What's unclear: Whether `price_accel` requiring OHLCV bars means the `inputs` tuple should declare a lookback
   - Recommendation: Add `inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=5),)` since `price_accel` reads `frames["main"]` for 3 bars. The implementation plan already shows this — use it.

3. **HMA output naming in MomentumAcceleration**
   - What we know: CONTEXT.md lists `hma_slope` and `hma_accel` as outputs to add to MomentumAcceleration
   - What's unclear: Whether the implementation plan covers these (the plan's implementation code shown in research stops at `price_accel`) — need to check plan chunks beyond the first
   - Recommendation: Include `hma_slope` and `hma_accel` in the `outputs` frozenset and compute from `features.get("hma_20")` with state key `prev_hma_20`.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.x |
| Config file | `pytest.ini` (project root) |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/ -v -k "momentum_accel or exhaustion or accel_regime or swing_momentum or hma"` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements to Test Map

| Component | Behavior | Test Type | Automated Command | File Exists? |
|-----------|----------|-----------|-------------------|-------------|
| HMA (I1) | `hma_20` computed correctly from WMA formula | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "hma"` | ❌ Wave 0 |
| MomentumAcceleration | `rsi_curvature` = second derivative of RSI; 0.0 on first bar | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v -k "curvature"` | ✅ (in plan) |
| MomentumAcceleration | `macd_hist_slope` reads `macd_histogram_12_26_9` not `macd_12_26_9` | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v -k "hist_slope"` | ✅ (in plan) |
| MomentumAcceleration | `price_accel` = ATR-normalized 2nd derivative; 0.0 when ATR missing | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v -k "price_accel"` | ✅ (in plan) |
| MomentumAcceleration | `hma_slope` and `hma_accel` computed from `hma_20` feature | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v -k "hma_slope or hma_accel"` | ❌ Wave 0 |
| ExhaustionScore | Score = 1.0 when all 3 conditions hold; 0.6 for 2/3; 0.2 for 1/3 | unit | `.venv/bin/pytest tests/unit/intelligence/composites/ -v -k "exhaustion"` | ❌ Wave 0 |
| ExhaustionScore | `exhaustion_bars` counter increments each bar condition holds, resets to 0 | unit | `.venv/bin/pytest tests/unit/intelligence/composites/ -v -k "exhaustion_bars"` | ❌ Wave 0 |
| ExhaustionScore | `exhaustion_side` = "bull" / "bear" / "none" correct for each case | unit | `.venv/bin/pytest tests/unit/intelligence/composites/ -v -k "exhaustion_side"` | ❌ Wave 0 |
| AccelerationRegime | `accel_regime == "peak"` fires exactly on the bar where crossing occurs, reverts next bar | unit | `.venv/bin/pytest tests/unit/intelligence/composites/ -v -k "accel_regime or peak"` | ❌ Wave 0 |
| AccelerationRegime | `accel_agreement` = fraction of measures in agreement (0.0–1.0) | unit | `.venv/bin/pytest tests/unit/intelligence/composites/ -v -k "accel_agreement"` | ❌ Wave 0 |
| SwingMomentum | Returns `{}` when fewer than 3 complete swings confirmed | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "swing_momentum"` | ❌ Wave 0 |
| SwingMomentum | `struct_energy` formula: amplitude_ratio × speed_factor / 3.0, clamped 0.0–1.0 | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "struct_energy"` | ❌ Wave 0 |
| SwingMomentum | `swing_amplitude_expanding = 1` only when last 3 amplitudes monotonically increasing | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "amplitude_expanding"` | ❌ Wave 0 |
| LiquiditySweepReclaim | `exhaustion_score > 0.6` in sweep direction → confidence += 0.1 + "exhaustion_sweep_boost" in supporting | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "sweep_reclaim and exhaustion"` | ❌ Wave 0 |
| LiquidityHunt | Same boost pattern as LiquiditySweepReclaim | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "liquidity_hunt and exhaustion"` | ❌ Wave 0 |
| MomentumBreakout | `exhaustion_score > 0.7` AND `exhaustion_bars >= 3` → confidence -= 0.15 + "exhaustion_guard_penalty" | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "momentum_breakout and exhaustion"` | ❌ Wave 0 |
| TrendFollowing | Same guard pattern; if confidence < threshold after penalty → `_no_signal()` | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "trend_follow and exhaustion"` | ❌ Wave 0 |
| Registration | `cmp_ExhaustionScore` in TIER_I2; `cmp_AccelerationRegime` in TIER_I2; `struct_SwingMomentum` in TIER_I3 | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "tier_i2 or tier_i3 or registration"` | ✅ (test_i2_registration.py, test_i7_registration.py) |

### Key Edge Cases to Validate

1. **rsi_curvature reads OLD prev_rsi_accel before write:** Call plugin twice, verify bar 2 curvature = accel[bar2] - accel[bar1]
2. **macd_hist_slope uses state, not prev_features:** Mock frames with `prev_features["macd_histogram_12_26_9"]` set to a different value than `_state["prev_macd_histogram"]` — plugin must use state value
3. **price_accel with exactly 3 close values:** `len(df) == 3` is the minimum; verify it works
4. **ExhaustionScore partial exhaustion:** RSI > 70 + rsi_curvature < 0 but macd_hist_slope >= 0 → score = 0.6, side = "bull"
5. **AccelerationRegime trough:** `prev_accel_score < -0.3` AND `accel_score >= -0.3` → regime = "trough"; following bar re-classifies
6. **SwingMomentum with exactly 5 extremes:** Must return `{}` (needs 6 for 3 complete swings)
7. **SwingMomentum ATR=0 fallback:** Use raw price amplitude for ratio without ATR normalization
8. **I7 boost cap:** Total confidence cannot exceed 0.95 after all boosts applied to LiquiditySweepReclaim/LiquidityHunt
9. **I7 suppression threshold:** MomentumBreakout/TrendFollowing must check actual fire threshold after penalty — not hardcoded 0.0

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/intelligence/ -v -k "momentum_accel or exhaustion or accel_regime or swing_momentum or hma"` (quick targeted)
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v` (full suite)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps (test files that don't exist yet)
- [ ] `tests/unit/intelligence/composites/test_exhaustion_score.py` — covers ExhaustionScore all conditions
- [ ] `tests/unit/intelligence/composites/test_acceleration_regime.py` — covers AccelerationRegime regime transitions
- [ ] `tests/unit/intelligence/test_swing_momentum.py` — covers SwingMomentum warmup gate + struct_energy formula
- [ ] `tests/unit/intelligence/test_hma.py` — covers HMA WMA formula correctness (or add to existing moving averages test)
- [ ] `tests/unit/intelligence/test_i7_exhaustion_wiring.py` — covers all 4 I7 exhaustion boost/guard wires

*(Existing `tests/unit/intelligence/composites/test_momentum_accel.py` needs extension for new outputs — file exists, new test functions needed)*

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection — `src/intelligence/composites/momentum_accel.py` — verified current state/output structure
- Direct codebase inspection — `src/intelligence/register_plugins.py` — verified TIER_I2/TIER_I3 lists and registration pattern
- Direct codebase inspection — `src/intelligence/trading/liquidity_sweep_reclaim.py`, `momentum_breakout.py`, `trend_following.py`, `liquidity_hunt.py` — verified confidence adjustment pattern
- Direct codebase inspection — `src/intelligence/indicators/moving_averages.py` — verified I1 plugin structure
- Direct codebase inspection — `src/intelligence/composites/common.py` — verified `is_num` utility
- Direct codebase inspection — `tests/unit/intelligence/helpers.py` — verified `make_ohlcv` test helper
- Direct codebase inspection — `tests/unit/intelligence/composites/test_momentum_accel.py` — verified test patterns
- `docs/plans/2026-03-10-second-derivative-indicators-design.md` — authoritative design spec
- `docs/plans/2026-03-10-second-derivative-indicators-plan.md` — authoritative implementation plan with full code

### Secondary (MEDIUM confidence)
- `src/intelligence/structure/swing_detector.py` — SwingMomentum algorithm reference (self-contained, but same ±N peak detection approach)
- `src/intelligence/CLAUDE.md` — plugin tier reference and gotchas

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all patterns verified directly in codebase
- Architecture patterns: HIGH — copied from verified source files
- Pitfalls: HIGH — derived from actual code reading, design doc, and prior-phase decisions in STATE.md
- Test strategy: HIGH — follows exact patterns from existing composites test suite

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable codebase, plugin patterns don't change frequently)
