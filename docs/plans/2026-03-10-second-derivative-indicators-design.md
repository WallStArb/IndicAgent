# Second-Derivative Indicator Coverage Expansion (I2/I3)

**Date:** 2026-03-10
**Status:** Approved — ready for implementation planning
**Estimated scope:** ~4d
**Milestone target:** v1.5

---

## Problem Statement

IndicAgent can measure *where* momentum is but not *whether* it is building or dying. This distinction is worth real alpha:

- A setup entering with decelerating momentum at an extreme has poor odds.
- The same setup entering with accelerating momentum at a fresh level has excellent odds.

MACD histogram slope + higher highs is a well-known exhaustion tell (user-validated in live trading), especially at swing S/R with an upcoming liquidity pool. Once encoded in the feature store, the system can apply this judgment to every bar on every symbol — the core Medallion principle: discretionary insight encoded once, applied forever.

---

## Design Goals

1. **Early inflection detection** — catch momentum turns before they're obvious (leads price)
2. **Exhaustion guard** — prevent I7 setups from firing into overextended moves
3. **ML feature richness** — 15 new normalized features per bar land in `intelligence_features` automatically

---

## Architecture

### I2 — Mathematical Second Derivatives (3 changes)

#### 1. Extend `MomentumAcceleration` (existing plugin)

Add three outputs to the existing `evt_MomentumAcceleration` plugin:

| Output | Formula | Notes |
|--------|---------|-------|
| `rsi_curvature` | `rsi_accel - prev_rsi_accel` | True 2nd derivative of RSI |
| `macd_hist_slope` | `macd_histogram_12_26_9 - prev_macd_histogram` | 2nd derivative of MACD; reads `macd_histogram_12_26_9` from I1 features (not the MACD line `macd_12_26_9`); leads zero-line crossovers 1-2 bars |
| `price_accel` | `((close - prev_close) - (prev_close - prev2_close)) / atr_14` | ATR-normalized; cross-instrument comparable |

All three require one additional bar of state stored in `_state`: `prev_rsi_accel`, `prev_macd_histogram`, `prev_price_velocity`.

`price_accel` normalization by ATR is essential — raw price acceleration differs by 100× between ES and NVDA; ATR-normalized values are directly comparable and usable as ML features without further scaling.

#### 2. New `ExhaustionScore` I2 plugin (`cmp_ExhaustionScore`)

**Purpose:** Detect when indicators are extreme AND decelerating — the classic institutional trap setup before a stop run.

**Inputs (from accumulated features):** `rsi_14`, `rsi_curvature`, `macd_hist_slope`

**Internal state:** `exhaustion_bars` is a running counter tracked entirely in `_state` — incremented each bar the condition holds, reset to 0 when it does not. It is not read from the feature accumulator.

**Logic:**
- Bullish exhaustion: `rsi_14 > 70` AND `rsi_curvature < 0` AND `macd_hist_slope < 0` (price extended, RSI decelerating, histogram contracting)
- Bearish exhaustion: `rsi_14 < 30` AND `rsi_curvature > 0` AND `macd_hist_slope > 0`
- Partial exhaustion: 2 of 3 conditions → fractional score

**Outputs:**

| Output | Type | Description |
|--------|------|-------------|
| `exhaustion_score` | float 0.0–1.0 | Weighted danger score (3/3 conditions = 1.0, 2/3 = 0.6, 1/3 = 0.2) |
| `exhaustion_side` | str | `"bull"` \| `"bear"` \| `"none"` |
| `exhaustion_bars` | float | Consecutive bars the exhaustion condition has held |

**I7 use:** `exhaustion_score > 0.7` for 3+ bars → apply score penalty in CISScorer or suppress setup entirely.

#### 3. New `AccelerationRegime` I2 plugin (`cmp_AccelerationRegime`)

**Purpose:** Synthesize rsi_curvature, macd_hist_slope, price_accel into a single regime label. Provides the "building vs waning" context that I7 setups can consume directly.

**Inputs:** `rsi_curvature`, `macd_hist_slope`, `price_accel` (all from extended MomentumAcceleration)

**Logic:** Each input is sign-voted (+1 / 0 / -1), weighted and summed. Regime thresholds on the composite score.

**Outputs:**

| Output | Type | Description |
|--------|------|-------------|
| `accel_regime` | str | `"building"` \| `"peak"` \| `"waning"` \| `"trough"` \| `"neutral"` |
| `accel_score` | float −1.0 to +1.0 | Direction × magnitude |
| `accel_agreement` | float 0.0–1.0 | Fraction of measures in agreement |

**Regime definitions (evaluated in order):**
- `building`: `accel_score > 0.5` (majority positive, momentum growing)
- `peak`: `prev_accel_score > 0.3` AND `accel_score ≤ 0.3` (was building, now falling back — inflection top)
- `trough`: `prev_accel_score < -0.3` AND `accel_score ≥ -0.3` (was waning, now rising back — inflection bottom)
- `waning`: `accel_score < -0.3` (decelerating with negative conviction)
- `neutral`: all other cases (|accel_score| ≤ 0.3 without an inflection crossing)

`_state` must persist `prev_accel_score` between bars. Peak/trough are transient (single-bar inflection events); the following bar re-classifies as `neutral` or `building`/`waning` based on the new score.

---

### I3 — Structural Momentum: `SwingMomentum` plugin (`struct_SwingMomentum`)

**Purpose:** Complement indicator math with structural momentum — is the market's own swing structure building energy or exhausting? Orthogonal to oscillator signals.

**Self-contained** (reads raw OHLCV bars directly, lightweight internal peak/valley detection, no dependency on `SwingDetector` — keeps it independent and testable).

**Inputs:** `InputSpec(symbol=".*", timeframe=".*", lookback=60)` for OHLCV bars. Also reads `atr_14` from `frames["features"]` (I1 accumulated features) for ATR normalization. If `atr_14` is absent or zero, amplitude is stored in raw price units and `swing_amplitude_ratio` is computed relative to the 3-swing average in those same units (no cross-instrument normalization until ATR is available).

**Internal algorithm:** Confirm a swing high when a bar's high is the highest in a ±N bar window (default N=3). Same for swing lows. Track last 5 confirmed extremes in `_state`. Require at least 3 complete swings (6 extremes) before emitting.

**Outputs:**

| Output | Type | Description |
|--------|------|-------------|
| `swing_amplitude_ratio` | float | Current swing amplitude / 3-swing ATR-normalized average. >1.0 = expanding, <1.0 = contracting |
| `swing_amplitude_expanding` | int | 1 if last 3 amplitudes are monotonically increasing, else 0 |
| `swing_velocity_bars` | float | Bars since last confirmed swing extreme |
| `swing_velocity_trend` | str | `"accelerating"` \| `"decelerating"` \| `"stable"` — based on bars-between-swings trajectory |
| `struct_energy` | float 0.0–1.0 | `amplitude_ratio × speed_factor`, normalized. High = structure alive and building |
| `struct_accel_bias` | int | +1 / 0 / -1 matching current trend direction |

**`struct_energy` formula:**
```
amplitude_ratio = current_amp / avg_of_last_3_amps  (ATR-normalized)
speed_factor    = reference_bars / swing_velocity_bars  (faster = higher factor, clamped 0.1–3.0)
struct_energy   = clamp(amplitude_ratio * speed_factor / 3.0, 0.0, 1.0)
```

The `/3.0` denominator normalizes the product so that `struct_energy = 1.0` represents a clearly strong, accelerating structure (amplitude_ratio=1.5 × speed_factor=2.0 = 3.0 → 1.0). Typical values in a healthy trend will be 0.4–0.7. Values above 0.8 indicate a parabolic, high-energy move. Values below 0.2 indicate contracting, exhausting structure.

---

### I7 Integration — Consuming New Outputs (no new plugins)

Two existing setups gain awareness of the new fields. These are **score adjustments only** — no new setup logic, no new signal types.

**`LiquiditySweepReclaim` and `LiquidityHunt`:**
- `exhaustion_score > 0.6` in sweep direction → `confidence += 0.1` (these setups enter after a stop run; exhaustion into the sweep is confirmation, not danger)
- `accel_regime == "building"` post-sweep → `confidence += 0.05` secondary confirmation
- `struct_energy > 0.6` → `confidence += 0.05` structural momentum behind the reclaim
- Cap total boost: `confidence = min(confidence, 0.95)`

**`MomentumBreakout` and `TrendFollowing`:**
- `exhaustion_score > 0.7` AND `exhaustion_bars >= 3` in breakout direction → `confidence -= 0.15`
- If `confidence` falls below the setup's fire threshold after penalty → return `{}` (suppression)
- Guards against chasing exhausted moves

Implementation follows the existing zone friction penalty pattern (inline `confidence +=/-=` in `compute_full()` before returning the signal dict). Audit reason appended to `supporting_factors` list (e.g. `"exhaustion_guard_penalty"` or `"exhaustion_sweep_boost"`) — not a separate `penalty_reason` field.

---

## ML Feature Store Impact

All new outputs land in `intelligence_features` JSONB automatically via `feature_writer_service`. No additional wiring needed.

New features per bar, per symbol, per timeframe:

```
# From extended MomentumAcceleration:
rsi_curvature, macd_hist_slope, price_accel

# From ExhaustionScore:
exhaustion_score, exhaustion_side, exhaustion_bars

# From AccelerationRegime:
accel_regime, accel_score, accel_agreement

# From SwingMomentum:
swing_amplitude_ratio, swing_amplitude_expanding,
swing_velocity_bars, swing_velocity_trend,
struct_energy, struct_accel_bias
```

Every `signal_ledger` row with an `outcome` is now a labeled sample with these 15 acceleration features attached. The scoring model can directly test: does `exhaustion_score` at signal fire predict `stopped_at_entry`? Does `struct_energy` predict `target_full`?

---

## Alpha Connection

The high-conviction confluence this design enables — which currently requires manual chart reading:

```
exhaustion_score > 0.7           # indicator math: 3 measures decelerating
struct_energy < 0.3              # structure: amplitude contracting, swings slowing
near liquidity_pool OR swing_sr  # institutional zone: stops clustered here
accel_regime == "peak"           # inflection: about to turn
```

→ `LiquiditySweepReclaim` or `LiquidityHunt` setup with elevated CISScorer confidence.

This is the institutional stop-run setup the user identifies manually — now systematically detected and scored across all 23 symbols and all timeframes, every bar.

---

## File Changes

| File | Change |
|------|--------|
| `src/intelligence/composites/momentum_accel.py` | Extend: +3 outputs (`rsi_curvature`, `macd_hist_slope`, `price_accel`) |
| `src/intelligence/composites/exhaustion_score.py` | New plugin: `cmp_ExhaustionScore` |
| `src/intelligence/composites/acceleration_regime.py` | New plugin: `cmp_AccelerationRegime` |
| `src/intelligence/structure/swing_momentum.py` | New plugin: `struct_SwingMomentum` |
| `src/intelligence/trading/liquidity_sweep_reclaim.py` | Wire `exhaustion_score`, `accel_regime`, `struct_energy` |
| `src/intelligence/trading/liquidity_hunt.py` | Wire `exhaustion_score`, `accel_regime`, `struct_energy` |
| `src/intelligence/trading/momentum_breakout.py` | Wire exhaustion guard |
| `src/intelligence/trading/trend_following.py` | Wire exhaustion guard |
| `src/intelligence/register_plugins.py` | Register 3 new plugins: `cmp_ExhaustionScore` → `TIER_I2`, `cmp_AccelerationRegime` → `TIER_I2`, `struct_SwingMomentum` → `TIER_I3` |

---

## Testing Approach (TDD)

- Unit tests for each new plugin with synthetic bar sequences: ascending exhaustion, declining structure, inflection detection
- Verify `rsi_curvature` sign change leads `rsi_accel` direction change by 1 bar
- Verify `exhaustion_score` reaches 1.0 only when all 3 conditions hold simultaneously
- Verify `struct_energy` returns `{}` when fewer than 3 complete swings confirmed (warmup gate); also verify `swing_velocity_bars` is not emitted in this state
- Verify I7 suppression: mock setup with `exhaustion_score=0.8`, `exhaustion_bars=3` → assert return `{}`
- Verify I7 boost: mock sweep setup with `exhaustion_score=0.65` → assert `confidence` increases and `"exhaustion_sweep_boost"` in `supporting_factors`
- Verify `AccelerationRegime` `peak` fires exactly on the bar where `prev_accel_score > 0.3` AND `accel_score ≤ 0.3`, and reverts next bar
- `cmp_ExhaustionScore` → `TIER_I2`, `cmp_AccelerationRegime` → `TIER_I2`, `struct_SwingMomentum` → `TIER_I3` — `validate_tier()` coverage
