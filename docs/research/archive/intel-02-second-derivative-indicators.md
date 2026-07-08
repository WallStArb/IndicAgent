# Second Derivative Indicators — Current State & Future Additions

**Version:** 1.0.0
**Status:** draft
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-03-11
**Tags:** second-derivative, momentum, indicators, acceleration, oscillator, regime, exhaustion

---

## Historical Context

**Original concept document:** `momentum-acceleration-second-derivative.md` (shipped v1.6)

That doc introduced the big idea of using second derivatives (rate of momentum change) rather than just first derivatives (momentum direction). It led to the design and implementation of 4 I2 composite plugins that are now operational:

- `MomentumAcceleration` (`evt_MomentumAcceleration`)
- `DerivativeOscillator` (`cmp_DerivativeOscillator`)
- `AccelerationRegime` (`cmp_AccelerationRegime`)
- `ExhaustionScore` (`cmp_ExhaustionScore`)

This document is preserved as **historical reference** to understand the original design philosophy and evolution. For the complete current inventory of all shipped second derivative indicators plus expansion ideas, see the remainder of this document.

---

## Overview

Second derivative indicators measure **how momentum changes** — the rate of acceleration or deceleration of trends. They provide earlier reversal signals than first-derivative indicators (RSI, MACD, ROC) because they detect **inflection points** where momentum itself is reversing.

### Why Second Derivative?

| Concept | First Derivative | Second Derivative |
|----------|----------------|-------------------|
| **Interpretation** | "Are we going up or down?" | "Are we speeding up or slowing down?" |
| **Signal timing** | After price crosses threshold | Before price crosses threshold |
| **Noise sensitivity** | Moderate | High — requires smoothing |
| **Value proposition** | Trend direction + momentum strength | **Inflection detection**, exhaustion, trend acceleration |

**Inflection point (`f''(x) = 0`)** — the earliest reversal signal. Occurs when acceleration flips from positive to negative (peak) or negative to positive (trough).

---

## Shipped Indicators (Tier I2 — 4 plugins)

### 1. MomentumAcceleration (`evt_MomentumAcceleration`)

**What it does:** Tracks rate-of-change across RSI, MACD, ROC, HMA, plus raw price acceleration. Detects zero-crossing inflection points.

**Outputs:**
- `rsi_accel` — ΔRSI (first derivative)
- `rsi_curvature` — Δ²RSI (second derivative) — sign change = inflection
- `macd_accel` — ΔMACD (first derivative)
- `macd_hist_slope` — Δhistogram (first derivative)
- `roc_accel` — ΔROC (second derivative of price)
- `price_accel` — (velocity_t - velocity_{t-1}) / ATR — normalized second derivative of price
- `hma_slope` — ΔHMA (first derivative)
- `hma_accel` — Δ²HMA (second derivative)
- `inflection_flag` — binary: 1 when any accel crosses zero

**Key insight:** Raw price acceleration is noisy, so it's normalized by ATR. RSI curvature is cleanest signal.

**Inflection detection:**
```python
if prev_accel * current_accel < 0:
    inflection = 1  # sign flip
```

---

### 2. DerivativeOscillator (`cmp_DerivativeOscillator`)

**What it does:** Constance Brown's triple-smoothed RSI derivative. EMA(5) → EMA(3) → SMA(9). Leads MACD by ~1-2 bars.

**Formula:**
```
ema5   = EMA(5, RSI-14)      alpha = 2/6
ema3   = EMA(3, ema5)         alpha = 2/4
signal = SMA(9, ema3)
deriv  = ema3 - signal
```

**Outputs:**
- `deriv_osc` — oscillator value
- `deriv_osc_signal` — 9-period SMA signal line
- `deriv_osc_cross_bullish` — crossover event
- `deriv_osc_cross_bearish` — crossover event

**Key insight:** Triple-smoothing reduces noise while preserving early-detection benefit. Output gate (empty dict) until SMA9 buffer fills.

---

### 3. AccelerationRegime (`cmp_AccelerationRegime`)

**What it does:** Sign-votes across 4 acceleration measures into regime classification. "Peak" and "trough" are single-bar inflection events, not multi-bar states.

**Inputs (voting pool):**
- `rsi_curvature` — from MomentumAcceleration
- `macd_hist_slope` — from MomentumAcceleration
- `price_accel` — from MomentumAcceleration
- `hma_accel` — from MomentumAcceleration

**Voting logic:**
```python
def _vote(x):
    if x > 0:  return 1
    if x < 0:  return -1
    return 0  # abstain

votes = [_vote(rsi_curvature), _vote(macd_hist_slope),
          _vote(price_accel), _vote(hma_accel)]
```

**Outputs:**
- `accel_regime` — `"building" | "peak" | "trough" | "waning" | "neutral"`
- `accel_score` — float in [-1.0, 1.0] — signed agreement strength
- `accel_agreement` — float in [0.0, 1.0] — directional consensus (max votes / total)

**Regime determination:**
```python
prev_score > 0.3 and score <= 0.3  → "peak"      # inflection event
prev_score < -0.3 and score >= -0.3 → "trough"    # inflection event
score > 0.5                         → "building"   # strong positive accel
score < -0.3                        → "waning"     # strong negative accel
otherwise                          → "neutral"
```

**Key insight:** Inflection events (`peak`/`trough`) take priority over directional states (`building`/`waning`) because they mark the turning bar.

---

### 4. ExhaustionScore (`cmp_ExhaustionScore`)

**What it does:** Tiered exhaustion signal based on RSI extreme + curvature + MACD histogram slope alignment. Used by I7 setups as guard/boost score.

**Logic:**
1. Determine active side from RSI extreme (`rsi > 70` or `rsi < 30`)
2. Count how many of 3 conditions hold:
   - RSI extreme (already confirmed by side check)
   - Curvature aligning with exhaustion (bull: curvature < 0, bear: curvature > 0)
   - MACD hist slope aligning (bull: slope < 0, bear: slope > 0)

**Outputs:**
- `exhaustion_score` — float in `{0.0, 0.2, 0.6, 1.0}` based on condition count
- `exhaustion_side` — `"bull" | "bear" | "none"`
- `exhaustion_bars` — consecutive bars where any exhaustion holds (state-tracked)

**Score mapping:**
```
3/3 conditions → 1.0
2/3 conditions → 0.6
1/3 conditions → 0.2
0/3 conditions → 0.0
```

**Key insight:** Exhaustion is multi-factor convergence — RSI alone gives false positives, but requiring curvature + MACD agreement filters noise.

---

## First Derivative Indicators (Related — Tier I1)

| Plugin | Description | Notes |
|---------|-------------|---------|
| **ROC** (`roc_14`) | Rate of change: `((close - close_n) / close_n) * 100` | First derivative of price |
| **PPO** (`ppo_12_26`) | Percentage Price Oscillator: normalized MACD for cross-instrument comparison | `(EMA_fast - EMA_slow) / EMA_slow * 100` |

---

## Future Additions — Research Ideas

### High Priority

#### 1. ATR Acceleration

**Concept:** Volatility rate-of-change — detects expansion/contraction regimes in real-time. Complements GARCH (model-based) with simple, responsive volatility acceleration.

**Use case:**
- Dynamic position sizing: reduce exposure when volatility spikes
- Stop-loss adjustment: widen stops during expansion, tighten during contraction
- Regime detection: volatility expansion often precedes directional moves

**Implementation:**
```python
atr_t   = atr[-1]
atr_t-1 = atr[-2]
atr_accel = atr_t - atr_t-1
```

**Outputs:** `atr_accel`, `atr_curvature`

**Trade-off:** ATR is already smoothed, so acceleration is clean. May want to use shorter-period ATR (7) for responsiveness.

---

#### 2. Cross-Term Acceleration Confluence

**Concept:** Compare acceleration signatures across timeframes. Leads price when short-term accel aligns with longer-term accel.

**Use case:**
- Early confirmation: 5m accel turning while 15m accel still positive = developing inflection
- False positive filter: 1m accel flip without TF agreement = noise
- MTF trading: entry on TF alignment, exit on 1m divergence

**Implementation:**
```python
accel_1m  = price_accel_1m
accel_5m  = price_accel_5m
accel_15m = price_accel_15m

mtf_agreement = (
    (sign(accel_1m) == sign(accel_5m)) +
    (sign(accel_5m) == sign(accel_15m))
) / 2  # 0.0, 0.5, or 1.0
```

**Outputs:**
- `mtf_accel_agreement` — float [0, 1]
- `accel_tf_dominance` — which TF has strongest accel
- `accel_tf_divergence` — 1 when short-term opposes long-term

**Challenge:** Requires acceleration metrics on multiple TFs — currently only have per-TF plugin state. Would need cross-TF state sharing or compute on aggregated features.

---

#### 3. Jerk (Third Derivative of Price)

**Concept:** In physics, jerk is rate of change of acceleration. Could detect abrupt momentum changes before they manifest in price.

**Use case:**
- Early detection of order flow shifts
- Liquidity exhaustion: price accelerates, then jerk spikes as it runs out of steam
- Event-driven moves: sharp acceleration followed by rapid deceleration

**Implementation:**
```python
# Requires 4 closes, ATR for normalization
v_t    = close[-1] - close[-2]      # current velocity
v_t-1  = close[-3] - close[-4]      # previous velocity
accel_t = v_t - v_t-1             # current acceleration
accel_t-1 = self.state.get('prev_accel')  # previous acceleration

jerk = (accel_t - accel_t-1) / atr
```

**Smoothing required:** Third derivative is extremely noisy. Options:
- Low-pass filter on jerk (EMA with small alpha)
- Only fire signals when |jerk| > threshold
- Require consecutive bars of jerk same direction
- Buttermann/Batterworth filter option for noise reduction

**Outputs:** `price_jerk`, `jerk_inflection` (sign flip)

**Trade-off:** High false positive rate. Best as confirmation filter, not primary signal.

---

#### 4. VWAP Acceleration

**Concept:** VWAP is volume-weighted — its acceleration measures buying/selling pressure momentum changes. Detects institutional order flow shifts before price reacts.

**Use case:**
- Institutional entry/exit detection
- Hidden divergence: price rising but VWAP accel turning negative
- Stop hunt detection: sharp VWAP accel through known levels

**Implementation:**
```python
vwap_t   = vwap[-1]
vwap_t-1 = vwap[-2]

vwap_slope_t   = vwap_t - vwap_t-1
vwap_slope_t-1 = state.get('prev_vwap_slope')

vwap_accel = vwap_slope_t - vwap_slope_t-1
```

**Outputs:** `vwap_accel`, `vwap_curvature`

**Challenge:** VWAP resets intraday (session-based). Acceleration only meaningful within session. Could use AnchoredVWAP for longer-term accel.

---

### Medium Priority

#### 5. Volume-Weighted Momentum Acceleration

**Concept:** Weight price acceleration by volume to identify meaningful moves vs noise. Low-volume acceleration = noise, high-volume acceleration = genuine.

**Implementation:**
```python
avg_vol = sma(volume, 20)
vol_ratio = volume / avg_vol
accel_weighted = price_accel * vol_ratio
```

**Use case:**
- False positive filter: ignore accel on low volume
- Liquidity events: high-vol accel = institutional move
- Stop management: widen stops on high-vol acceleration

**Outputs:** `vol_weighted_accel`, `accel_volume_confidence`

---

#### 6. Divergence-Adjusted Exhaustion

**Concept:** Current ExhaustionScore uses raw RSI extremes. Add divergence component — exhaustion + bearish divergence = higher reversal probability.

**Logic:**
```python
base_exhaustion = 0.6  # from existing plugin
rsi_divergence = rsi_div_plugin.rsi_divergence  # from I5

if exhaustion_side == "bear" and rsi_divergence == "bearish":
    adjusted_score = min(base_exhaustion + 0.2, 1.0)
elif exhaustion_side == "bull" and rsi_divergence == "bullish":
    adjusted_score = min(base_exhaustion + 0.2, 1.0)
else:
    adjusted_score = base_exhaustion
```

**Outputs:**
- `exhaustion_score_adjusted` — original score + divergence coupling
- `divergence_coupling` — boolean: divergence aligned with exhaustion

**Use case:** I7 setups use `exhaustion_score_adjusted` as stronger guard when divergence confirms.

---

#### 7. Realized Variance Acceleration

**Concept:** Rolling window variance/volatility second derivative. More responsive than HV for detecting volatility regime shifts.

**Implementation:**
```python
rv_t = realized_variance(close[-window:])
rv_t-1 = state.get('prev_rv')
rv_accel = rv_t - rv_t-1
```

**Use case:**
- Earlier volatility regime detection than GARCH
- Gap detection: RV acceleration spikes on gaps
- VIX-future: for equity indices, RV accel leads VIX

**Outputs:** `rv_accel`, `rv_curvature`

**Challenge:** Requires window parameter selection. Shorter windows = noisier, longer = slower.

---

### Low Priority

#### 8. Intraday Acceleration Cycles

**Concept:** Track acceleration patterns relative to session phases (London/NY overlap, killzones). Some pairs exhibit cyclic acceleration behavior tied to session liquidity.

**Implementation:**
```python
session_phase = get_session_phase(timestamp)  # "asian", "london", "ny", "overlap"
accel_by_phase[session_phase].append(price_accel)
cycle_strength = accel_by_phase[session_phase].std()
```

**Use case:**
- Session-specific expectations: expect accel spikes at NY open for ES
- False positive filter: accel outside typical phase range = noise
- Killzone trading: entries on expected accel direction

**Outputs:** `accel_session_phase`, `accel_cycle_strength`, `accel_phase_zscore`

**Challenge:** Requires sufficient session-specific historical data to establish baseline.

---

#### 9. Order Flow-Implied Acceleration

**Concept:** If IBKR provides depth data, derive acceleration from bid/ask pressure. Liquidity exhaustion as price accelerates into thin book.

**Implementation:**
```python
bid_depth_t   = sum(bid_volumes)
ask_depth_t   = sum(ask_volumes)
order_pressure_t = (ask_depth_t - bid_depth_t) / (ask_depth_t + bid_depth_t)

pressure_accel = order_pressure_t - order_pressure_t-1
```

**Use case:**
- Absorption detection: price moves, accel stalls → large limit order absorbing
- Stop hunt: sharp accel into thin book → stop run
- Hidden divergence: price flat but order pressure accelerates

**Outputs:** `book_pressure_accel`, `liquidity_accel`

**Blocker:** Requires IBKR Level II data (currently using aggregated bars only). See `orderflow-based-setups.md`.

---

#### 10. Triple Smoothed MACD Acceleration

**Concept:** Apply DerivativeOscillator approach to MACD itself: EMA(3, EMA(5, MACD)) - SMA(9, ...). Could lead DerivativeOscillator.

**Implementation:**
```python
ema5   = ema(macd, 5)
ema3   = ema(ema5, 3)
signal = sma(ema3, 9)
deriv  = ema3 - signal
```

**Outputs:** `macd_deriv_osc`, `macd_deriv_signal`, `macd_deriv_cross_bullish`, `macd_deriv_cross_bearish`

**Use case:**
- Earlier MACD inflection detection
- Confirmation filter: compare DerivativeOsc(RSI) vs DerivativeOsc(MACD)

**Trade-off:** Adds complexity to already well-served MACD acceleration. Unclear if adds material edge.

---

## Prioritized Implementation Roadmap

### Phase 1: High Impact, Low Complexity
1. **ATR Acceleration** — Simple, directly useful for risk management
2. **Volume-Weighted Momentum Acceleration** — Easy extension, adds volume dimension

### Phase 2: Cross-TF Synergy
3. **Cross-Term Acceleration Confluence** — Leverages existing multi-TF infrastructure, requires state sharing design

### Phase 3: Novel Signals
4. **Jerk (Third Derivative)** — Research candidate, requires smoothing optimization
5. **VWAP Acceleration** — Volume-weighted, captures institutional flow

### Phase 4: Advanced (Blocked on data or complexity)
6. **Divergence-Adjusted Exhaustion** — Integration work, needs divergence plugin refactoring
7. **Realized Variance Acceleration** — Volatility alternative to GARCH
8. **Intraday Acceleration Cycles** — Requires session classification infrastructure
9. **Order Flow-Implied Acceleration** — Blocked on IBKR Level II data
10. **Triple Smoothed MACD Acceleration** — Lowest priority, unclear edge

---

## Related Files

- Original concept: `momentum-acceleration-second-derivative.md` (shipped v1.6)
- Implementation plan: `docs/plans/2026-02-25-momentum-acceleration-analysis.md`
- Plugin code: `src/intelligence/composites/` (4 plugins)
- Plugin registry: `src/intelligence/register_plugins.py` — `TIER_I2`

---

## Open Questions

1. **Cross-TF state sharing:** How to share acceleration metrics across timeframes without breaking current per-TF isolation?
   - Option A: Compute on aggregated `features` dict (current pattern)
   - Option B: Redis-backed shared state (like PluginStateManager but cross-TF)
   - Option C: Post-processing in I6 confluence layer

2. **Jerk smoothing:** What's the optimal low-pass filter for third derivative?
   - EMA with alpha = 0.1?
   - Buttermann filter?
   - Test and validate against false positive rate

3. **ATR acceleration window:** Use same 14-period ATR as price accel, or shorter 7-period for responsiveness?
   - Trade-off: shorter = more noise, longer = slower detection
   - Consider dual-window approach: both 7 and 14, confluence signal

4. **Volume baseline:** Volume-weighted acceleration needs dynamic baseline (session-dependent, trend-dependent)
   - Current session's typical volume?
   - Rolling 20-bar average?
   - Z-score normalization?

---

## Next Steps

1. Design **ATR Acceleration** plugin → create implementation plan in `docs/plans/`
2. Add **Volume-Weighted Momentum Acceleration** to I2 composite backlog
3. Research **Cross-TF acceleration confluence** architecture — decide on state-sharing approach
4. Prototype **Jerk** indicator with smoothing tests — validate false positive rate
