# Phase 65: Gradient Audit of Existing Plugins I1-I7 — Research

**Researched:** 2026-04-08
**Domain:** Intelligence plugin scoring — binary-to-gradient refactoring
**Confidence:** HIGH (all findings from direct source inspection)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Continuous over binary: hard thresholds replaced with smooth functions (sigmoid, tanh, logistic, piecewise-linear)
- Shared gradient library: `src/intelligence/utils/gradient_utils.py` — single source of truth; all plugins import from it
- Reuse over repetition: gradient functions written once, imported everywhere
- Separation of concerns: gradient math isolated from plugin signal logic (raw indicator → gradient layer → [0,1] or [-1,1])
- DAG integrity: plugins remain DB-ignorant, publish-only — no persistence or schema changes
- Automation: automated scanner confirms zero binary patterns remain; programmatic verification required
- Compute efficiency: gradient functions must be numpy-vectorizable; no Python loops where array ops apply
- Simplicity: prefer linear ramp over neural interpolation unless data justifies complexity
- Scope: all 121 plugins (I1–I7) + 2 aggregation plugins

### Claude's Discretion
- Which gradient function shape best fits each plugin (sigmoid vs tanh vs linear ramp vs softplus)
- How to structure the shared gradient utility module
- Whether to do one PLAN.md per tier or a single unified PLAN.md

### Deferred Ideas (OUT OF SCOPE)
- Adding new plugins or new signal types
- Hyperparameter tuning of gradient function shapes using historical data (future ML phase)
- Backfilling historical intelligence_features with re-scored gradient values (separate data backfill phase)
</user_constraints>

---

## Summary

Phase 65 audits all 121 plugins across I1–I7 for binary scoring shortcuts and replaces them with continuous gradients. The research reveals the codebase already has a sophisticated gradient culture in most tiers — the majority of critical scoring paths (I1, most of I4/I7 confidence logic) are already continuous. The primary binary violations cluster in four areas: (1) boolean session/temporal flags in I4 SessionContext and SMC ICT Killzones, (2) I2 composite event flags (vol_spike, bb_touch, MA crossover), (3) I3/I5 structural detection fields (bos_detected, sweep_detected, squeeze_fired), and (4) hardcoded flat confidence bases in 10 I7 plugins that ignore available gradient signals.

**Primary recommendation:** Create `src/intelligence/utils/gradient_utils.py` with 6-8 canonical gradient functions. Apply them in waves: start with I4 session flags (highest signal density, session context consumed by almost all I7 plugins), then I2 composite events (binary outputs feed I6 confluence), then I3/SMC structural fields, then I7 flat-confidence patterns. I5 pattern detection fields are largely legitimate discrete events — scope them conservatively.

---

## Binary Pattern Inventory

### Critical Distinction: True Binary vs Legitimate Discrete

Before listing patterns, this distinction is essential for planning:

**True binary (must fix):** A continuous quantity (distance, z-score, ratio) is collapsed to {0, 1}. Examples: `vol_spike = 1 if z > 2.0 else 0` — z-score is available, gradient is destroyed.

**Legitimate discrete (do NOT "fix"):** The underlying concept is genuinely categorical or the field is used as a direction selector, not a score. Examples: `direction = 1 if sweep_type > 0 else -1` — this is direction encoding, not a score. `fvg_type = 1` means bull FVG (category), not "100% confident." Changing these would break plugin logic.

**Ambiguous (contextual):** Flags like `bos_detected = 0.0 / 1.0` — detection is boolean, but `bos_strength` (distance / ATR) is the continuous gradient that is currently missing.

---

### Tier I1 — Indicators (27 plugins)

**[VERIFIED: source inspection]**

**Binary violations found: 2 (minor)**

| Plugin | File | Line | Pattern | Gradient Replacement |
|--------|------|------|---------|---------------------|
| CVD | `cvd.py` | 102-103 | `slope_dir = 1 if slope > 0 else (-1 if < 0 else 0)` — sign-only, discards magnitude | Use `slope` normalized by ATR or rolling std |
| CVD | `cvd.py` | 102-103 | `price_dir = 1 if price_change_5 > 0 else (-1 if < 0 else 0)` | Use `price_change_5 / atr` clamped to [-1, 1] |

**Assessment:** I1 tier is mostly continuous by design — indicators output raw numeric values (RSI in [0,100], MACD histogram, ATR, etc.). The 2 CVD slope-direction fields are minor directional encoders already used correctly as sign signals. **Impact: LOW**

---

### Tier I2 — Composite Events (10 plugins)

**[VERIFIED: source inspection]**

**Binary violations found: HIGH COUNT — 12+ fields across 3 plugins**

#### `ma_composites.py` — MAComposites (I2)

| Field | Line | Pattern | Gradient Replacement |
|-------|------|---------|---------------------|
| `ema_9_gt_21` | 67 | `1 if e9 > e21 else 0` | `(e9 - e21) / e21 * 100` — relative distance pct, clamped |
| `ema_9_cross_21` | 75 | `1 if crossed_up else (-1 if crossed_down else 0)` | Acceptable: this IS a discrete event signal |
| `golden_cross_active` | 90 | `1 if s50 > s200 else 0` | `(s50 - s200) / s200 * 100` — separation percentage |
| `death_cross_active` | 91 | `1 if s50 < s200 else 0` | Same as above (negative direction) |
| `sma_20_gt_50` | 104 | `1 if s20 > s50 else 0` | `(s20 - s50) / s50 * 100` — separation pct |
| `price_above_sma200` | 117/136 | `1 if px > s200 else 0` | `(px - s200) / s200 * 100` |
| `price_touch_sma_50` | 124 | `1 if within <= 0.25 else 0` | `max(0, 1 - within / 0.25)` — proximity score decays to 0 beyond threshold |
| `price_bounce_sma_50` | 132 | `1 if prev_within <= 0.25 and moved_away else 0` | Discrete event — acceptable as-is |

#### `volume_events.py` — VolumeEvents (I2)

| Field | Line | Pattern | Gradient Replacement |
|-------|------|---------|---------------------|
| `vol_spike` | 56-58 | `1 if z > 2.0 else 0` | `max(0, (z - 1.0) / 2.0)` — normalized excess (0 at z=1, 1.0 at z=3) |
| `vol_drying` | 59 | `1 if volume < vol_sma * 0.5 else 0` | `max(0, 1 - volume / (vol_sma * 0.5))` — drying intensity |
| `bb_upper_touch` | 68 | `1 if abs(close - bb_upper) <= threshold else 0` | `max(0, 1 - abs(close - bb_upper) / (bb_width * 0.15))` |
| `bb_lower_touch` | 69 | Same pattern | Same approach |
| `bb_walking_upper` | 80 | `1 if streak >= 3 else 0` | `min(1.0, streak / 5.0)` — normalized streak length |
| `bb_walking_lower` | 81 | Same | Same |

#### `rsi_events.py` — RSIEvents (I2)

| Field | Pattern | Gradient Replacement |
|-------|---------|---------------------|
| `in_extreme` | `1 if rsi < 30 or rsi > 70 else 0` | `max(0, (rsi - 70) / 30)` for OB side, `max(0, (30 - rsi) / 30)` for OS side |

**Assessment:** I2 is the most impactful tier for this fix. These binary outputs feed into I6 CrossTimeframe Confluence scoring, which feeds all 36 I7 plugins. Fixing I2 propagates gradient signal through the entire DAG. **Impact: HIGH**

---

### Tier I3 — Structure (8 plugins)

**[VERIFIED: source inspection]**

**Binary violations found: MEDIUM — pattern-detection fields are legitimately discrete, but strength fields are missing**

| Plugin | File | Field | Pattern | Verdict |
|--------|------|-------|---------|---------|
| BOSCHoCH | `bos_choch.py` | `bos_detected` | `0.0 / 1.0` step | Add companion `bos_strength` = break distance / ATR |
| BOSCHoCH | `bos_choch.py` | `choch_detected` | `0.0 / 1.0` step | Add `choch_strength` = break magnitude / ATR |
| SwingDetector | `swing_detector.py` | `high_type` / `low_type` | `1.0 if HH else -1.0` | Acceptable: encodes direction, not magnitude |
| MarketProfile | `market_profile.py` | `price_in_va` | `1.0 if va_low <= close <= va_high else 0.0` | Add `va_position_pct` = distance normalized by VA range |
| MarketProfile | `market_profile.py` | `price_above_va` | `1.0 if close > va_high else 0.0` | Add `va_distance_atr` = (close - va_high) / ATR |
| MarketProfile | `market_profile.py` | `price_below_va` | `1.0 if close < va_low else 0.0` | Same |
| FibonacciZones | `fibonacci_zones.py` | `in_discount` | `1.0 if 0.5 <= close <= 0.786 else 0.0` | Add `discount_depth` = proximity to 0.618 |
| SwingMomentum | `swing_momentum.py` | return `0 / 1` | Integer output | Convert to normalized momentum score |

**Assessment:** I3 structural detection events (BOS, CHoCH, swing) are genuinely discrete. The fix here is additive — keep the binary flag (I7 plugins use them for direction gating) but ADD continuous companion fields (`_strength`, `_magnitude`, `_distance`). These companion fields are the gradient signals. **Impact: MEDIUM (additive, not replacement)**

---

### Tier I4 — Context (12 plugins)

**[VERIFIED: source inspection]**

**Binary violations found: HIGH in SessionContext and AnchoredVWAP; LOW elsewhere**

#### `session_context.py` — SessionContext (CRITICAL)

This plugin is consumed by almost all I7 session-aware plugins. All session flags are hard {0.0, 1.0}:

| Field | Pattern | Gradient Replacement |
|-------|---------|---------------------|
| `session_asia` | `1.0 if in_window else 0.0` | Time-in-session fraction (0→1 over first 30 min, 1.0 mid, 0→1 over last 15 min) |
| `session_london` | Same | Same |
| `session_ny` | Same | Same |
| `in_london_killzone` | Same | Minutes remaining in KZ / total KZ duration |
| `in_ny_killzone` | Same | Same |
| `is_opening_range` | `1.0 if elapsed < 0.077 else 0.0` | `max(0, 1 - elapsed / 0.077)` — decays to 0 as range period ends |
| `is_power_hour` | `1.0 if elapsed > 0.846 else 0.0` | `max(0, (elapsed - 0.846) / 0.154)` — ramps up over power hour |
| `is_lunch_consolidation` | Same hard-threshold | Proximity to midday peak |
| `is_monday` / `is_friday` | Hard binary | Remain binary (truly categorical) |
| Exchange session flags | `1.0 if is_open else 0.0` | Add `session_progress_frac` = elapsed / total_duration |

**Note:** `is_monday` / `is_friday` are genuinely categorical (day-of-week) — keep as binary.

#### `anchored_vwap.py` — AnchoredVWAP

| Field | Line | Pattern | Gradient Replacement |
|-------|------|---------|---------------------|
| `above_session_vwap` | 134 | `1.0 if close > session_vwap else 0.0` | `session_vwap_deviation_sigma` already computed — use that |
| `above_swing_vwap` | 135 | `1.0 if close > swing_vwap else 0.0` | `swing_vwap_deviation_sigma` — already computed |
| `above_weekly_vwap` | 136 | `1.0 if close > weekly_vwap else 0.0` | `(close - weekly_vwap) / weekly_vwap * 100` |

**Note:** `vwap_alignment_score` (sum of the three above / 3) is already continuous — but it's built from three binary inputs. Fixing the inputs fixes the score.

#### `volatility_regime.py` — VolatilityRegime

| Field | Pattern | Verdict |
|-------|---------|---------|
| `vol_expansion` | `1.0 / -1.0 / 0.0` step | Replace with `ratio - 1.0` (continuous expansion magnitude) |
| `vol_regime` | `{-1, 0, 1, 2}` discrete steps from percentile | `vol_percentile` already output continuously — regime steps are acceptable as categorical labels consumed for gating |

#### `trend_regime.py` — TrendRegime

| Field | Pattern | Verdict |
|-------|---------|---------|
| `trend_regime` | `{-1.0, -0.5, 0.0, 0.5, 1.0}` steps from blended | `blended` already computed continuously — output it directly instead of bucketing |
| `trend_confidence` | `1.0 if same_sign else 0.3` | `0.5 + 0.5 * (agreement_strength)` — full [0,1] based on sign alignment magnitude |

**Assessment:** SessionContext is consumed by ORB15, ORB30, SessionExtremesSetup, PrevDayLevelTest, GapAnalysisSetup, CandlestickPatternSetup — fixing it propagates gradient to 6+ I7 plugins. **Impact: HIGH**

---

### Tier I5 — Patterns (16 plugins)

**[VERIFIED: source inspection]**

**Binary violations found: LOW-MEDIUM — most are legitimate discrete pattern detection**

| Plugin | Field | Pattern | Verdict |
|--------|-------|---------|---------|
| CandlestickPatterns | `inside_bar` | `1.0 if (c_h < p_h and c_l > p_l) else 0.0` | Add `inside_bar_depth` = min((p_h - c_h), (c_l - p_l)) / bar_range — how deep inside |
| CandlestickPatterns | `outside_bar` | `1.0 if (c_h > p_h and c_l < p_l) else 0.0` | Add `outside_bar_expansion` = ((c_h - p_h) + (c_l - p_l)) / p_range |
| BollingerSqueeze | `squeeze_fired` | `1.0 if prev_squeeze and not current else 0.0` | Acceptable: discrete release event |
| MTFVolatility | `mtf_exp_15m` | `1.0 if float(exp_15m) > 0 else 0.0` | Use `exp_15m` directly (it's already a continuous value) |
| MTFVolatility | `mtf_exp_1h` | Same | Same |
| MTFVolatility | `squeeze_within` | `1.0 if (is_squeezing and higher_expanding) else 0.0` | Compound boolean — hard to gradient; add `squeeze_within_degree` = magnitude of squeeze depth × expansion |
| FlagPennant | `impulse_direction` | `1.0 / -1.0 / 0.0` | Direction encoding — acceptable |
| MeasuredMove | `active` | `1.0 / 0.5` | `0.5` at partial completion is already a gradient; add precise `completion_proximity` |
| HeadShoulders | `sym_score` | Already continuous (distance ratio) | GOOD — template example |

**Assessment:** Most I5 outputs are event-type detections (pattern found / not found) — the detection is genuinely binary. The fix is additive: keep detection flags, add `_quality`, `_depth`, or `_strength` companion fields. MTFVolatility has the clearest fix (use the continuous upstream value directly). **Impact: MEDIUM (additive)**

---

### Tier SMC — Smart Money Context (13 plugins)

**[VERIFIED: source inspection]**

**Binary violations found: MEDIUM**

| Plugin | Field | Pattern | Verdict |
|--------|-------|---------|---------|
| BOSCHoCH | `bos_detected` | `0.0/1.0` | Add `bos_strength` = (close - level) / ATR |
| LiquiditySweeps | `sweep_detected` | `0.0/1.0` | Add `sweep_strength` = depth_pct normalized |
| LiquiditySweeps | `sweep_reclaimed` | `0.0/1.0` | Add `reclaim_velocity` = speed of reclaim (bars taken) |
| FairValueGap | `fvg_type` | `{-1, 0, 1}` integer | Direction encoding — acceptable |
| ICTKillzones | `in_asia_killzone` | `0.0/1.0` | Add `kz_progress_frac` = minutes_in / kz_total_duration |
| ICTKillzones | `in_london_killzone` | Same | Same |
| ICTKillzones | `in_ny_am_killzone` | Same | Same |
| ICTKillzones | `in_ny_pm_killzone` | Same | Same |
| OrderBlocks | `ob_mitigated` check | Uses `== 1.0` equality | Add `ob_freshness` = 1.0 - (mitigations / max_mitigations) |
| BreakBlocks | `active` | `0.0/1.0` step | Add proximity score |
| BOSCHoCH | `hh/hl` | `1.0/-1.0` | Direction encoding — acceptable |
| AMDCycle | `manip_detected` | `0.0/1.0` | Add `manip_strength` = spike_z or impulse_magnitude |
| SupplyDemandZones | `freshness` | `1.0 → 0.5` two-step | Should be exponential decay: `freshness = exp(-k * touch_count)` |

---

### Tier I6 — Confluence (1 plugin)

**[VERIFIED: source inspection]**

The `CrossTimeframeConfluencePlugin` (`cross_timeframe.py`) is already well-designed. It uses weighted composites, z-score scaling, and proximity decay throughout. No binary violations found in the CTF scoring paths.

**Binary violations found: 0 (already gradient-native)**

---

### Tier I7 — Trading Setups (36 plugins)

**[VERIFIED: source inspection]**

Two distinct categories of binary patterns in I7:

#### Category A: Flat confidence base values (hardcoded, not data-driven)

10 plugins start with hardcoded confidence and add sparse binary checks:

| Plugin | File | Base Confidence | Pattern |
|--------|------|----------------|---------|
| LiquiditySweepReclaim | `liquidity_sweep_reclaim.py` | 0.55 flat | `if fvg_type == float(direction): += 0.15` (binary gate) |
| FailedBreakout | `failed_breakout.py` | 0.55 flat | `if hmm_regime == 0.0: += 0.15` (binary equality gate) |
| ORB15 | `orb15.py` | 0.50 flat | `if hmm_regime in (1.0, 2.0): += 0.10` |
| ORB30 | `orb30.py` | 0.50 flat | Same pattern |
| SupplyDemandSetup | `supply_demand_setup.py` | 0.35/0.46/0.58 tiered | 3-step discrete |
| OFIDivergence | `ofi_divergence.py` | 0.42 flat | Incremental adds |
| LiquidityHunt | `liquidity_hunt.py` | 0.55 flat | 12 discrete adds |
| PrevDayLevelTest | `prev_day_level_test.py` | 0.50 flat | Regime equality checks |
| MomentumBreakout | `momentum_breakout.py` | Already gradient-continuous | `regime_score = 0.5 / 1.0 / 0.1` 3-step |
| SqueezeExpansion | `squeeze_expansion.py` | Already good | `regime_score = 0.8 / 0.2` binary |

**The fix:** `hmm_regime == 0.0` (ranging) → use `hmm_prob_ranging` (already output as continuous probability). `hmm_regime in (1.0, 2.0)` → use `max(hmm_prob_up, hmm_prob_down)` as gradient weight.

#### Category B: Direction encoding (legitimate, do NOT change)

These are correctly binary — they encode direction, not score:

```python
direction = 1 if ctf_score > 0 else -1          # direction encoding
direction = 1 if trend_regime > 0 else -1        # direction encoding
direction = 1 if fvg_type == 1 else -1           # direction encoding
cvd_sign = 1 if cvd_div > 0 else -1             # direction encoding
```

These 15+ patterns appear throughout I7 and are **correct by design**. The direction `{-1, 1}` is the appropriate output for these fields.

#### Category C: HMM regime equality comparisons

| Pattern | Occurrences | Fix |
|---------|-------------|-----|
| `hmm_regime == 1.0` | 7 plugins | Replace with `hmm_prob_up` (continuous probability already available from HMMRegime output) |
| `hmm_regime == 2.0` | 5 plugins | Replace with `hmm_prob_down` |
| `hmm_regime == 0.0` | 8 plugins | Replace with `hmm_prob_ranging` |

**Note:** HMMRegime plugin already outputs `hmm_prob_0`, `hmm_prob_1`, `hmm_prob_2` as continuous probabilities. These are underused — the integer `hmm_regime` equality comparison destroys this gradient. Replacing `hmm_regime == 1.0` with `hmm_prob_up` in confidence scoring captures the probability mass.

---

## Binary Pattern Count Summary

| Tier | True Binary Violations | Direction Encoders (keep) | Priority |
|------|----------------------|--------------------------|----------|
| I1 (27 plugins) | 2 | 2 | LOW |
| I2 (10 plugins) | 13 fields, 3 plugins | 2 (crossover events) | HIGH |
| I3 (8 plugins) | 3 plugins, 6+ additive fields | 3 | MEDIUM |
| I4 (12 plugins) | 2 plugins (Session + AnchoredVWAP), ~12 fields | 2 | HIGH |
| I5 (16 plugins) | 4 plugins, ~6 fields | 3 | MEDIUM |
| SMC (13 plugins) | 4 plugins, ~10 fields | 4 | MEDIUM |
| I6 (1 plugin) | 0 | 0 | NONE |
| I7 (36 plugins) | 10 plugins (regime equality + flat base) | 15+ direction encoders | HIGH |

**Total true binary violations: ~50 fields across ~30 plugins**
**Legitimate direction encoders (do not touch): ~25 patterns**

---

## Existing Gradient Examples (Templates)

These plugins already implement gradient scoring correctly — use as reference:

**[VERIFIED: source inspection]**

### HurstExponent (I4) — BEST TEMPLATE
`src/intelligence/context/hurst_exponent.py` — `_hurst_trend_quality()` and `_hurst_mr_quality()`:
```python
# Piecewise-linear ramp between two anchor points
if h >= 0.65:
    return 1.0
if h <= 0.45:
    return 0.3
return 0.3 + 0.7 * ((h - 0.45) / 0.20)
```
Docstring explains mapping and rationale. Thresholds calibrated from live data. This is the canonical pattern.

### ShannonEntropy (I4) — BEST TEMPLATE
`src/intelligence/context/shannon_entropy.py` — `_entropy_quality()`:
```python
# Linear interpolation between anchor points
if normalised_entropy <= 0.65:
    return 1.0
if normalised_entropy >= 0.95:
    return 0.5
return 1.0 - 0.5 * ((normalised_entropy - 0.65) / 0.30)
```
Docstring explicitly states calibration date and rationale. This is the gold standard.

### MomentumBreakout (I7) — GOOD TEMPLATE
`src/intelligence/trading/momentum_breakout.py`:
```python
roc_score = min(1.0, (abs(roc) - self.roc_threshold) / self.roc_threshold)
vol_score = min(1.0, (volume_ratio - self.volume_expansion_threshold) / self.volume_expansion_threshold)
break_margin = min(1.0, max(0.0, abs(price - structure_level) / atr))
# Composite weighted sum
raw_conf = 0.35 * roc_score + 0.30 * vol_score + 0.20 * break_margin + 0.15 * regime_score
confidence = compose_confidence(raw_conf)
```
Only flaw: `regime_score = 0.5 / 1.0 / 0.1` (3-step) — should use `hmm_prob_*` instead.

### SqueezeExpansion (I7) — GOOD TEMPLATE
`src/intelligence/trading/squeeze_expansion.py`:
```python
squeeze_bars_score = min(1.0, squeeze_bars / 30.0)  # normalized duration
vol_expansion_score = min(1.0, (volume_ratio - 1.0) / 2.0)  # normalized expansion
momentum_score = min(1.0, abs(momentum_bias))  # already [0,1]
```
Same flaw: `regime_score = 0.8 / 0.2` binary.

### AccelerationRegime (I2) — GOOD TEMPLATE
`src/intelligence/composites/acceleration_regime.py`:
```python
accel_score = round(raw_sum / n_votes, 4)  # continuous [-1, 1]
accel_agreement = round(max(pos_count, neg_count) / n_votes, 4)  # [0, 1]
```
Sign-voting aggregation that preserves intensity — correct pattern for multi-signal consensus.

### TrendRegime (I4) — PARTIAL TEMPLATE
`src/intelligence/context/trend_regime.py` — blending is correct but final bucketing destroys it:
```python
blended = 0.5 * ma_norm + 0.5 * structure_signal  # GOOD: continuous blend
if blended > 0.5:
    trend_regime = 1.0  # BAD: throws away gradient
```
Output `blended` directly as `trend_regime_continuous` alongside bucketed `trend_regime`.

---

## Shared Utility Gap Analysis

### What Already Exists

**[VERIFIED: source inspection]**

`src/intelligence/utils/core.py` contains:
- `clamp(value, min_val, max_val)` — generic clamp to [min, max]
- `linreg_slope(y)` — linear regression slope
- `find_peaks/find_troughs(data, n)` — vectorized local extrema

`src/intelligence/utils/common.py` contains:
- `is_num(x)` — isinstance check (lenient version)
- `crossover_detect(prev_a, now_a, prev_b, now_b)` — returns (0/1, 0/1)
- `threshold_cross(prev, now, threshold, direction)` — returns 0/1
- `track_bars_ago(state, key, event, max_bars)` — bars since event

`src/intelligence/trading/confidence_utils.py` contains:
- `compose_confidence(raw)` — clamps to [0.10, 0.95], rounds to 4dp
- `CONF_FLOOR = 0.10`, `CONF_CEIL = 0.95`

**Gap:** No shared gradient transformation functions exist. Everything currently inline.

### What gradient_utils.py Needs

```python
# src/intelligence/utils/gradient_utils.py

def linear_ramp(x, lo, hi, out_lo=0.0, out_hi=1.0) -> float:
    """Map x from [lo, hi] to [out_lo, out_hi] with linear interpolation.
    Clamps at boundaries. The canonical "piecewise-linear with anchors" function.
    Use for: distance-based scores, duration-based scores, any monotone relationship.
    Examples: HurstExponent trend_quality, ShannonEntropy quality_gate already do this manually.
    """

def threshold_decay(x, center, width, peak=1.0, floor=0.0) -> float:
    """Score that peaks at center and decays to floor over ±width.
    Use for: proximity-to-level scores (POC, VWAP, S/R levels, session boundaries).
    Replaces: `1 if abs(x - center) < threshold else 0`.
    """

def sigmoid_score(x, center, steepness=1.0) -> float:
    """Sigmoid mapping: output in (0, 1), 0.5 at center.
    Use for: RSI extreme scoring, z-score→probability conversion.
    Replaces: `1 if rsi > 70 else 0` → `sigmoid_score(rsi, 70, steepness=0.2)`.
    """

def z_score_to_score(z, sigma_scale=2.0) -> float:
    """Map a z-score to [0, 1] where 0 = no deviation, 1 = extreme deviation.
    Use for: volume spike intensity, deviation from VWAP, ATR expansion.
    Replaces: `1 if z > 2.0 else 0`.
    Example: z_score_to_score(z=3.5, sigma_scale=2.0) → 0.75
    """

def session_progress(elapsed_frac, start_frac, end_frac) -> float:
    """Score in [0, 1] based on how far into a time window we are.
    1.0 at midpoint, decays to 0 at edges. Bell-curve shaped.
    Use for: session flags (Asia/London/NY), killzone proximity, power hour.
    Replaces: `1.0 if in_window else 0.0`.
    """

def hmm_regime_weight(features, regime_direction) -> float:
    """Extract continuous HMM probability for a regime direction.
    regime_direction: "up" | "down" | "ranging"
    Returns: hmm_prob_1 for up, hmm_prob_2 for down, hmm_prob_0 for ranging.
    Replaces all `hmm_regime == 1.0` equality comparisons.
    """

def freshness_decay(touch_count, k=0.5) -> float:
    """Exponential freshness decay. 1.0 on first touch, decays with each touch.
    Use for: SupplyDemand zone freshness, OrderBlock mitigation freshness.
    Replaces two-step 1.0→0.5 freshness in supply_demand_zones.py.
    """

def streak_score(streak_count, saturation=5) -> float:
    """Normalize consecutive bar streak to [0, 1].
    Use for: bb_walking_upper/lower, consecutive pressure bars.
    Replaces: `1 if streak >= 3 else 0`.
    """
```

**Key design rules for gradient_utils.py:**
- Every function takes scalar floats, returns scalar float (vectorizable by caller if needed)
- Every function has a docstring with: mapping description, rationale, what it replaces
- No numpy imports in gradient_utils (functions are math primitives; numpy ops live in plugins)
- Parameter defaults chosen to match calibrated values from existing HurstExponent/ShannonEntropy patterns

---

## Gradient Function Selection Guide

**[ASSUMED: mathematical rationale based on indicator semantics — verify with domain knowledge]**

| Binary Pattern Type | Continuous Replacement | Function | Rationale |
|--------------------|----------------------|----------|-----------|
| `x > threshold: 1` | Distance above threshold | `linear_ramp(x, threshold, threshold*1.5)` | Linear: simple, monotone, no curvature assumptions |
| `abs(x - level) < eps: 1` | Proximity to level | `threshold_decay(x, level, eps * 2)` | Bell-curve: signal peaks at level, decays symmetrically |
| `rsi > 70: 1` (extreme) | Extremeness score | `sigmoid_score(rsi, 70, 0.15)` | Sigmoid: smooth saturation; risk of overshoot naturally bounded |
| `z > 2.0: 1` (spike) | Spike intensity | `z_score_to_score(z, 2.0)` | Zero below 1σ, scales to 1.0 at 4σ |
| `hmm_regime == 1.0: 1` | HMM probability | `hmm_regime_weight(features, "up")` | Use upstream probability directly |
| `in_window: 1` (session) | Session progress | `session_progress(elapsed, start, end)` | Time-position relative to session midpoint |
| `streak >= N: 1` | Streak intensity | `streak_score(streak, saturation=N+2)` | Normalized: 0→1 over [0, saturation] bars |
| `is_open: 1` (exchange) | Session depth | `session_progress(elapsed, 0, 1)` | Progress through session as gradient |
| `freshness == 1.0: fresh` | Touch count decay | `freshness_decay(touch_count, k=0.5)` | Exponential: each test reduces by ~40% |
| `x > 0: 1 (direction)` | **KEEP AS-IS** | Binary direction encoding | Not a score; don't change |

**Key: linear ramp is the default.** Only use sigmoid when there's a saturation effect (RSI extremes, z-scores). Only use bell-curve when both sides of a level are meaningful (proximity). Avoid tanh as a primary function — it requires zero-centering that most indicator values don't naturally have.

---

## Test Coverage Assessment

**[VERIFIED: source inspection]**

### Existing Coverage

```
tests/unit/intelligence/
├── test_i2_plugins.py          # I2 composites — exists
├── test_i2_registration.py     # I2 registration — exists
├── test_i4_new_plugins.py      # I4 context plugins — exists
├── test_i5_new_plugins.py      # I5 pattern plugins — exists
├── test_context_plugins.py     # I4 session/trend/vol — exists
├── test_session_context_redesign.py  # SessionContext specific — exists
├── test_trading_setups.py      # I7 setups — exists
├── test_confidence_utils.py    # compose_confidence — exists
├── test_utils.py, test_utils_common.py  # utility functions — exists
```

**Total test functions: 1,574 across all intelligence tests.**

### Gaps for Phase 65

**New test file required: `tests/unit/intelligence/test_gradient_utils.py`**
- Unit tests for every function in `gradient_utils.py`
- Parameterized tests covering: zero, midpoint, saturation, boundary inputs
- Property test: `output != 0.0 and output != 1.0` for mid-range inputs (the gradient continuity assertion)

**New test: `tests/unit/intelligence/test_gradient_continuity.py`** (or inline in per-plugin tests)
- For each modified plugin: assert that mid-range inputs produce output strictly between {0.0, 1.0}
- For session flags: `0.0 < session_progress(mid_elapsed) < 1.0`
- For volume events: `0.0 < vol_spike_intensity(z=2.5) < 1.0`

**Automated scanner test: `tests/unit/test_binary_pattern_scanner.py`**
Per CONTEXT.md requirement, a programmatic scanner that:
- Walks all `src/intelligence/**/*.py` plugin files
- Finds patterns: `= 1 if condition else 0`, `= 1.0 if ... else 0.0`, `np.where(cond, 1, 0)`
- Asserts zero True binary patterns remain (direction encoders excluded via allowlist)
- Must be executable as CI test without infra

**Regression coverage for modified plugins:**
- All modified plugins need assertions that existing behavior is preserved at extreme inputs
- `modified_plugin.compute_full(extreme_high_input)` should still return near-1.0
- `modified_plugin.compute_full(extreme_low_input)` should still return near-0.0

**Existing tests that will need updating:**
`test_i2_plugins.py` — currently checks `vol_spike == 1` or `vol_spike == 0`; will need to accept continuous values
`test_session_context_redesign.py` — session flag equality checks will break
`test_context_plugins.py` — anchored_vwap `above_session_vwap` assertions

---

## Compute Impact Assessment

**[VERIFIED: source inspection + ASSUMED for numpy benchmarks]**

### Linear Ramp (default replacement)

```python
# Before: O(1) comparison
result = 1.0 if x > threshold else 0.0

# After: O(1) arithmetic
result = max(0.0, min(1.0, (x - threshold) / (saturation - threshold)))
```

**Cost: ~2-3x per operation** (2 comparisons → 3 arithmetic ops). For a plugin computing 1 field per bar, this is ~5ns → ~15ns. Negligible against I/O, dataframe access, and numpy allocations.

### sigmoid_score

```python
# Requires math.exp() call
result = 1.0 / (1.0 + math.exp(-steepness * (x - center)))
```

**Cost: 5-10x comparison cost** due to `exp()`. Still sub-microsecond per call. Limit to fields where it's semantically correct (RSI extremes, z-score→probability).

### session_progress (bell curve via Gaussian-like)

Requires 1-2 arithmetic ops, no transcendentals needed if using triangular or trapezoidal shape. Use `linear_ramp` composed to a tent function. Negligible cost.

### Vectorization opportunity

I2 plugins that compute multiple fields per bar can batch gradient transforms:

```python
# Instead of per-field calls:
out["vol_spike"] = z_score_to_score(z)
out["vol_drying"] = threshold_decay(volume, vol_sma * 0.5, vol_sma * 0.25)

# Can be numpy-batched if computing for multiple symbols:
# gradient_utils functions should accept np.ndarray inputs via numpy ufuncs
```

Recommend: implement `gradient_utils.py` functions to accept both `float` and `np.ndarray` inputs using `np.maximum`, `np.minimum`, `np.exp` where applicable. Add `# vectorizable` comment on each function.

### No-regression benchmark

Per CONTEXT.md requirement: benchmark at least one plugin per tier before/after. Recommended targets:
- I2: `VolumeEventsPlugin` (multiple fields, hot path)
- I4: `SessionContextPlugin` (many binary fields)
- I7: `FailedBreakoutPlugin` (flat base + regime check)

Use `tests/benchmarks/` (or inline timing assertions) comparing `time.perf_counter()` before/after on 1000 `compute_full()` calls.

---

## Implementation Approach Recommendation

### Wave Structure: 4 Plans, Not Per-Tier

Given the cross-cutting nature (gradient_utils used across all tiers), one unified PLAN.md with 4 waves is more coherent than 7 per-tier plans:

**Wave 0 (setup): Create gradient_utils.py + scanner script**
- `src/intelligence/utils/gradient_utils.py` — 6-8 gradient functions with docstrings
- `tests/unit/intelligence/test_gradient_utils.py` — unit tests for each function
- `scripts/audit_binary_patterns.py` — AST/regex scanner used for pre-fix audit and post-fix verification
- No plugin changes in this wave

**Wave 1 (high-impact): I4 SessionContext + AnchoredVWAP + I2 Composites**
- `session_context.py` — ~10 binary fields → gradient
- `anchored_vwap.py` — 3 binary fields → gradient
- `trend_regime.py` — output `blended` directly
- `volatility_regime.py` — `vol_expansion` → ratio gradient
- `ma_composites.py` — 6 binary fields → gradient
- `volume_events.py` — 6 binary fields → gradient
- `rsi_events.py` — `in_extreme` → extremeness score
- Update tests for all modified plugins

**Wave 2 (medium-impact): I3 + SMC + I5 structural additions**
- `bos_choch.py` — add `bos_strength`, `choch_strength`
- `liquidity_sweeps.py` — add `sweep_strength`, `reclaim_velocity`
- `ict_killzones.py` — add `kz_progress_frac`
- `supply_demand_zones.py` — replace freshness 2-step with decay
- `market_profile.py` — add `va_position_pct`, `va_distance_atr`
- `mtf_volatility.py` — use upstream continuous values directly
- `candlestick_patterns.py` — add `inside_bar_depth`, `outside_bar_expansion`

**Wave 3 (I7 confidence graduation): Replace HMM equality comparisons + flat bases**
- 8 plugins: replace `hmm_regime == X` with `hmm_prob_*` in confidence scoring
- `momentum_breakout.py`, `squeeze_expansion.py` — replace 3-step regime_score
- `supply_demand_setup.py` — replace tiered flat bases with continuous freshness/distance inputs
- Benchmarks (before/after on 3 representative plugins)

**Wave 4 (verification): Binary pattern scanner passes at zero**
- Run `scripts/audit_binary_patterns.py` — assert zero true binary patterns
- `tests/unit/test_binary_pattern_scanner.py` — CI-runnable version
- Update `test_i2_plugins.py`, `test_session_context_redesign.py`, `test_context_plugins.py`

### Single PLAN.md Recommendation

One PLAN.md with 4 wave sections is cleaner than 7 per-tier plans. The gradient_utils dependency must be established (Wave 0) before all tier plugins can be modified. The verification (Wave 4) depends on all modifications being complete. A single document captures this dependency ordering.

---

## Key Files

### Files to Create
- `src/intelligence/utils/gradient_utils.py` — new shared gradient library
- `tests/unit/intelligence/test_gradient_utils.py` — unit tests
- `scripts/audit_binary_patterns.py` — binary pattern scanner
- `tests/unit/test_binary_pattern_scanner.py` — CI-runnable scanner

### Files to Modify

**I2:**
- `src/intelligence/composites/ma_composites.py`
- `src/intelligence/composites/volume_events.py`
- `src/intelligence/composites/rsi_events.py`

**I3:**
- `src/intelligence/features/i3_structure/bos_choch.py` (via smc_context path)
- `src/intelligence/features/i3_structure/market_profile.py`

**I4:**
- `src/intelligence/context/session_context.py`
- `src/intelligence/context/anchored_vwap.py`
- `src/intelligence/context/trend_regime.py`
- `src/intelligence/context/volatility_regime.py`

**I5:**
- `src/intelligence/features/i5_patterns/mtf_volatility.py`
- `src/intelligence/features/i5_patterns/candlestick_patterns.py`

**SMC:**
- `src/intelligence/features/smc_context/bos_choch.py`
- `src/intelligence/features/smc_context/liquidity_sweeps.py`
- `src/intelligence/features/smc_context/ict_killzones.py`
- `src/intelligence/features/smc_context/supply_demand_zones.py`
- `src/intelligence/features/smc_context/amd_cycle.py`

**I7:**
- `src/intelligence/trading/failed_breakout.py`
- `src/intelligence/trading/momentum_breakout.py`
- `src/intelligence/trading/squeeze_expansion.py`
- `src/intelligence/trading/orb15.py`
- `src/intelligence/trading/orb30.py`
- `src/intelligence/trading/liquidity_sweep_reclaim.py`
- `src/intelligence/trading/supply_demand_setup.py`
- `src/intelligence/trading/ofi_divergence.py`
- `src/intelligence/trading/liquidity_hunt.py`
- `src/intelligence/trading/prev_day_level_test.py`
- `src/intelligence/trading/choch_reversal.py`
- `src/intelligence/trading/second_leg_continuation.py`
- `src/intelligence/trading/vcp.py`
- `src/intelligence/trading/cross_asset_divergence.py`

**Tests to update:**
- `tests/unit/intelligence/test_i2_plugins.py`
- `tests/unit/intelligence/test_session_context_redesign.py`
- `tests/unit/intelligence/test_context_plugins.py`
- `tests/unit/intelligence/test_i4_new_plugins.py`
- `tests/unit/intelligence/test_i5_new_plugins.py`

### Files NOT to Modify (direction encoders, correct by design)

```
# All these are directional encoders — {-1, 1} is the correct output domain
trading/trend_following.py:          direction = 1 if trend_regime > 0 else -1
trading/fvg_fill.py:                direction = 1 if fvg_type == 1 else -1
trading/ofi_continuation.py:        current_dir = 1 if ofi_ewma > 0 else -1
trading/liquidity_sweep_reclaim.py: direction = 1 if sweep_type > 0 else -1
trading/vwap_deviation.py:          direction = 1 if price < vwap else -1
trading/vwap_reclaim.py:            direction = 1 if crossed_up else -1
composites/obv_momentum.py:         sign = 1 if slope > 0 else -1
(etc. — all ~15 direction= encoders)
```

Also **do not touch** event detection flags when they are genuinely binary concepts:
```
squeeze_fired = 1.0 if prev_squeeze and not current else 0.0   # release event
ema_9_cross_21 = 1 if crossed_up else -1                        # crossover event
```

---

## Project Constraints (from CLAUDE.md)

**[VERIFIED: CLAUDE.md]**

- Plugins are DB-ignorant, publish-only — gradient refactor touches compute layer only
- Performance: numpy-vectorized operations preferred — gradient_utils functions must support array inputs
- Test pattern: `tests/unit/intelligence/test_<module>.py`
- Pytest: `.venv/bin/pytest` not bare `pytest`
- Ruff: `.venv/bin/ruff check .` from project root
- Pre-commit: `/simplify` then `/coderabbit:code-review` before commit
- Hot-path optimization: extract repeated constructs to module-level constants where applicable
- Plugin registry: any new output fields added to I3/I4/I5/SMC plugins must be added to corresponding schema in `schemas.py` AND validated in `validate_schema_coverage()`
- All plugin output field additions require schema registration — this is a HARD STARTUP CRASH if missed

**Schema registration is the most likely failure mode.** Every additive field (e.g., `bos_strength`, `kz_progress_frac`) must be added to:
1. The plugin's `outputs` frozenset
2. The corresponding Pydantic schema class in `src/intelligence/schemas.py`
3. The `validate_schema_coverage()` tier_checks list in `register_plugins.py`

---

## Open Questions (RESOLVED)

1. **Should session flags preserve backward compatibility?** ✅ RESOLVED
   - What we know: `session_asia = 1.0 / 0.0` is consumed by downstream I7 plugins as a binary gate
   - Resolution: I7 plugins use `> 0.5` threshold checks (threshold-safe), not `== 1.0` equality. Additive approach confirmed: new `session_*_progress` companion fields added alongside existing binary flags. Old flags remain untouched to avoid breaking I7 gating logic.

2. **HMM probability field names** ✅ RESOLVED
   - What we know: HMM outputs are `hmm_prob_ranging`, `hmm_prob_trending_up`, `hmm_prob_trending_down` (verified in `schemas.py` lines 633-635 — NOT hmm_prob_0/1/2 as initially assumed)
   - Resolution: Fields are consistently available in I7 `features` dict — they are schema-registered fields on `IntelligenceEvent.i2` and propagated through the pipeline. The `hmm_regime_weight` function in gradient_utils.py MUST use these exact field names. All Plan 04 tasks updated accordingly.

3. **Direction integer vs direction float in SMC fields** ✅ RESOLVED
   - Resolution: Direction encoding uses `int` throughout. `fvg_type` is `int`. All direction comparisons use `== 1` / `== -1` (int equality). Plans 03 and 04 preserve this — direction fields are in the scanner allowlist and explicitly excluded from gradient conversion.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | sigmoid_score is mathematically appropriate for RSI extreme scoring | Gradient Function Selection Guide | Could use linear ramp instead with no behavioral difference; sigmoid just provides smoother saturation |
| A2 | Benchmarks will show < 10x slowdown per field per gradient replacement | Compute Impact Assessment | Unlikely to matter at pipeline scale (sub-microsecond), but if measured as regressions the plan must revisit |
| A3 | HMM probability fields (hmm_prob_ranging/trending_up/trending_down) are schema-registered and available in I7 features dict | Open Questions (RESOLVED) | Verified in schemas.py lines 633-635 — correct field names confirmed |

---

## Sources

### PRIMARY (HIGH confidence)
- Direct source inspection: all claims about binary patterns are from reading actual plugin files
- `src/intelligence/context/hurst_exponent.py` — gradient template patterns
- `src/intelligence/context/shannon_entropy.py` — gradient template patterns
- `src/intelligence/utils/core.py`, `src/intelligence/utils/common.py` — existing utility inventory
- `src/intelligence/trading/confidence_utils.py` — confidence contract
- `src/intelligence/register_plugins.py` — canonical plugin/tier lists
- `src/intelligence/schemas.py` — schema registration requirement discovered via `validate_schema_coverage()`

### SECONDARY (MEDIUM confidence)
- Compute cost estimates derived from standard Python/numpy operation cost knowledge [ASSUMED]

---

## Metadata

**Confidence breakdown:**
- Binary pattern inventory: HIGH — direct source inspection of all plugin files
- Gradient function selection: MEDIUM — mathematically sound but not empirically validated
- Test coverage gaps: HIGH — direct inspection of `tests/unit/intelligence/`
- Compute impact: MEDIUM — theoretical estimates, not measured

**Research date:** 2026-04-08
**Audit refresh:** 2026-04-23
**Valid until:** 2026-05-23 (stable codebase; valid until next plugin addition)

---

## Audit Refresh (2026-04-23)

Full re-scan of all plugin files, schemas, and utilities after Phases 69 (writer renaissance) and 71 (base agent infrastructure) shipped.

### Plugin Count Update

| Tier | Apr 8 Count | Apr 23 Count | Delta |
|------|-------------|--------------|-------|
| I1 | 27 | 29 | +2 |
| I2 | 10 | 10 | 0 |
| I3 | 8 | 9 | +1 |
| I4 | 12 | 12 | 0 |
| I5 | 16 | 17 | +1 |
| SMC | 13 | 14 | +1 |
| I6 | 1 | 1 | 0 |
| I7 | 36 | 37 | +1 |
| **Total** | **123** | **129** | **+6** |

### Drift Assessment

**I2/I4 files: NO DRIFT.** All binary violations from original research confirmed present at same line numbers (±2 lines). No new fields added.

**I3/SMC/I5 files: MINOR DRIFT.**
- `candlestick_patterns.py`: **20 new pattern outputs** added since Apr 8. These need binary pattern auditing before Plan 03 executes.
- `fibonacci_zones.py`: Now has `fib_cluster_strength` gradient companion (already partial).
- `supply_demand_zones.py`: Now has `demand_strength` / `supply_strength` gradient companions (already partial).
- `anchored_vwap.py` (I4): **7 new gradient fields** added (sigma values, bands, velocity) — these partially address the binary `above_*` fields. The binary flags still exist alongside.

**I7 files: NO DRIFT in binary patterns.** All `hmm_regime ==` comparisons confirmed present. Some plugins already have partial gradient patterns:
- `choch_reversal.py`: magnitude-based multi-TF boosts (lines 109-132)
- `cross_asset_divergence.py`: linear gradient with spread_z magnitude (line 145)
- `ofi_divergence.py`: tanh soft cap (line 115)
- `supply_demand_setup.py`, `liquidity_sweep_reclaim.py`: magnitude-based CTF boosts

**Infrastructure: NO DRIFT.**
- HMM field names confirmed: `hmm_prob_ranging`, `hmm_prob_trending_up`, `hmm_prob_trending_down`
- Schema classes confirmed: `I3Structure`, `I4Context`, `I5Patterns`, `SMCContext`, `I6Confluence`
- `gradient_utils.py` does NOT exist yet — clean slate
- `confidence_utils.py` unchanged: `CONF_FLOOR=0.10`, `CONF_CEIL=0.95`

### Design Decisions (Renaissance Principles)

After audit, these design decisions are locked for plan execution:

1. **gradient_utils.py: 6 exports, not 8.** `z_score_to_score` and `streak_score` are thin wrappers over `linear_ramp` — keep them for readability but they're not primitives. The 6 exports: `linear_ramp`, `threshold_decay`, `sigmoid_score`, `session_progress`, `freshness_decay`, `hmm_regime_weight`.

2. **SessionContext: REPLACE in-place, not additive.** Research confirmed I7 plugins use `> 0.5` threshold checks, not `== 1.0` equality. Replacing `0.0/1.0` with `0.0-1.0` range is safe — values outside window stay 0.0, values inside become 0.0-1.0. Simpler than adding companion fields. Exception: `is_monday`/`is_friday` remain binary (categorical).

3. **I3/SMC detection flags: ADDITIVE.** BOS detected, sweep detected, squeeze fired — these are genuinely discrete events. Keep the flag, add a `_strength` companion. I7 plugins use these for direction gating, not scoring.

4. **I7 hmm_regime: REPLACE in confidence scoring only.** `hmm_regime == X` in confidence += lines → `hmm_regime_weight(features, direction)`. Eligibility gates (return None if wrong regime) stay binary — these are hard filters, not scores.

5. **Scanner: importable module + CLI.** `tools/scan_binary_patterns.py` is both importable (for CI test) and runnable as script. No subprocess in CI test.
