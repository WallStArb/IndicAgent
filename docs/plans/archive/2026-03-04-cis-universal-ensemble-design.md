# CIS Universal Ensemble — Design Document

**Date:** 2026-03-04
**Status:** Approved
**Author:** brainstorming session
**Inspiration:** Renaissance Capital / Jim Simons ensemble approach

---

## Problem

10 of 23 I1 indicators and all 6 I2 composite plugins compute every bar for every symbol × timeframe but have zero downstream I2–I7 consumers. Their outputs are stored in `intelligence_features` but never influence I7 signal generation.

**Unused I1 outputs:** `williams_r_14`, `mfi_14`, `obv`, `aroon_up/down/osc_25`, `chandelier_long/short_22`, `cmf_20`, `psar_value/direction`, `hv_20/hv_ratio_20`, `stoch_rsi_k/d_14`, `donchian_high/mid/low_20`

**Unused I2 outputs:** All event fields from MACDEvents, RSIEvents, StochasticEvents, ADXEvents, VolumeEvents, MomentumAcceleration

These are breadcrumbs. The Simons principle: *every measurable signal carries some predictive information. Put it in the model. Let outcomes decide the weights.*

---

## Design Principle

Do not wire indicators into individual I7 setup plugins ("Williams%R confirms MeanReversion"). That is story-based, editorial, and creates human bias about which combinations matter. Instead:

**Route ALL signals into a universal CIS ensemble. Record every contribution. Let outcomes learn the weights.**

Architecture:

```
ALL I1 outputs ──┐
ALL I2 outputs ──┤──► CIS (universal ensemble, 6 buckets) ──► direction + attribution
I3/I4/I5/SMC  ──┘
                              │
I7 setups ────────► structural gate (entry/stop/target context)
                              │
             both must agree ─► signal fires
                              │
                    signal_ledger (cis_attribution JSONB)
                              │
                    signal_lifecycle → outcome label
                              │
                    cis_weights table ← logistic regression ← (contribution, outcome) pairs
```

I7 setups define WHAT the trade is (structure, zone, context). CIS decides WHETHER to fire (directional scoring). Every constituent contribution is recorded so outcomes can teach the model which signals actually predicted price.

---

## Component 1: Two New Bridge Composites (I2 tier)

Some I1 indicators are price-relative (price vs. a level) and need preprocessing before they become a directional [-1, +1] signal.

### DonchianPosition
- **Inputs:** `donchian_high_20`, `donchian_mid_20`, `donchian_low_20` + current `close` (passed via feature dict)
- **Output:** `donchian_position_20: float` in [-1, +1]
- **Formula:** `(close - donchian_mid) / (half_range)` where `half_range = (donchian_high - donchian_low) / 2`
- **Semantics:** +1 = price at top of channel (trend bullish), -1 = at bottom (trend bearish)
- **Bucket:** Regime

### OBVMomentum
- **Inputs:** raw bar `close`, `volume` (stateful, tracks rolling OBV)
- **Output:** `obv_slope_sign: int` ∈ {-1, 0, +1}
- **Formula:** linear regression slope of last 10 bars of OBV; sign of slope
- **Semantics:** rising OBV = accumulation = bullish; falling = distribution = bearish
- **Bucket:** Volume/Institutional

*Note: Chandelier exit levels are not wired in this iteration — PSAR already covers trailing-stop trend direction.*

---

## Component 2: CIS Bucket Expansion

### Momentum Bucket
Currently: `rsi_14`, `macd_histogram_12_26_9`, `roc_14`, `momentum_bias`, `DivergenceStack plugin`

**Additions:**

| Signal | Normalization | Type |
|--------|--------------|------|
| `williams_r_14` | `-(wr + 50) / 50` | indicator (current) |
| `mfi_14` | `(mfi - 50) / 50` | indicator (current) |
| `stoch_rsi_k_14` | `(k - 0.5) / 0.5` | indicator (current) |
| `cmf_20` | already [-1, +1] | indicator (current) |
| `rsi_accel` (I2) | sign | event (decays, halflife=5) |
| `macd_accel` (I2) | sign | event (decays, halflife=5) |
| `roc_accel` (I2) | sign | event (decays, halflife=5) |
| `stoch_cross_bullish` (I2) | +1 | event (decays, halflife=5) |
| `stoch_cross_bearish` (I2) | -1 | event (decays, halflife=5) |
| `stoch_oversold_reversal` (I2) | +1 | event (decays, halflife=5) |
| `stoch_overbought_reversal` (I2) | -1 | event (decays, halflife=5) |

**Correlation group:** `williams_r`, `mfi`, `stoch_rsi_k`, `stoch_cross` are in the oscillator correlation group (see Section 4).

### Trend Bucket
Currently: `trend_regime`, `kalman_slope`, `smc_trend_direction`, `ctf_trend_alignment`, `trend_confluence_score`

**Additions:**

| Signal | Normalization | Type |
|--------|--------------|------|
| `aroon_osc_25` | `aroon_osc / 100` | indicator (current) |
| `psar_direction` | already +1/-1 | indicator (current) |
| `di_spread` (I2 ADXEvents) | `di_spread / 50`, clamped | indicator (current) |
| `macd_bull_cross` (I2 MACDEvents) | +1 event | event (decays, halflife=10) |
| `macd_bear_cross` (I2 MACDEvents) | -1 event | event (decays, halflife=10) |
| `adx_trend_confirmed × di_spread_sign` (I2) | ±1 | event (decays, halflife=20) |

### Regime Bucket
Currently: `hmm_prob_trending_up/down`, `cp_probability`, `ctf_regime_agreement`, `vol_regime`, `RegimeTransition plugin`

**Additions:**

| Signal | Normalization | Type |
|--------|--------------|------|
| `hv_ratio_20` | `-(hv_ratio - 1.0)` clamped | indicator (current) — high HV = uncertainty |
| `donchian_position_20` | [-1, +1] (new composite) | indicator (current) |
| `inflection_flag` (I2 MomentumAccel) | 0 when True (suppresses direction) | event (decays, halflife=3) |

### Volume/Institutional Bucket
Currently: `ob_type/strength`, `fvg_type/count`, `in_demand/supply_zone`, `FVGFill plugin`, `SupplyDemandSetup plugin`

**Additions:**

| Signal | Normalization | Type |
|--------|--------------|------|
| `obv_slope_sign` (new composite) | +1/0/-1 | indicator (current) |
| `vol_spike × ctf_trend_sign` (I2 VolumeEvents) | ±1 | event (decays, halflife=3) |
| `bb_walking_upper` (I2 VolumeEvents) | +1 | event (decays, halflife=5) |
| `bb_walking_lower` (I2 VolumeEvents) | -1 | event (decays, halflife=5) |
| `bb_upper_touch` (I2 VolumeEvents) | -1 (overextension) | event (decays, halflife=3) |
| `bb_lower_touch` (I2 VolumeEvents) | +1 (overextension) | event (decays, halflife=3) |

---

## Component 3: Correlation Penalty

The momentum bucket contains multiple correlated oscillators: `rsi_14`, `williams_r_14`, `mfi_14`, `stoch_rsi_k_14`, `stoch_cross_bullish/bearish`. These capture the same underlying momentum state. Without a penalty, unanimous oscillator agreement inflates the momentum bucket beyond its true information content.

### Oscillator Correlation Groups

Two groups are defined with a penalty factor:

```python
CORRELATION_GROUPS: list[dict] = [
    {
        "name": "momentum_oscillators",
        "members": {"rsi_14", "williams_r_14", "mfi_14", "stoch_rsi_k_14",
                    "stoch_cross_bullish", "stoch_cross_bearish",
                    "stoch_oversold_reversal", "stoch_overbought_reversal"},
        "effective_n": 2.5,   # treat as 2.5 independent signals regardless of count firing
    },
    {
        "name": "trend_followers",
        "members": {"psar_direction", "aroon_osc_25", "di_spread",
                    "adx_trend_confirmed"},
        "effective_n": 2.0,
    },
]
```

### Application

Within each bucket, after computing the raw weighted sum of correlated group members, normalize by `actual_firing_count / effective_n`. Members outside any group are unpenalized.

This prevents 5 correlated oscillators from collectively overwhelming the bucket — they collectively count as ~2.5 independent signals.

Bootstrap weights for new signals start conservatively (`0.02–0.05`) so even without the penalty, their marginal influence is small. The learning loop will correct weights upward for signals with genuine predictive power.

---

## Component 4: Event Decay

I2 composite outputs are discrete events: they fire at a point in time and become less relevant as bars pass. Without decay, a MACD crossover from 40 bars ago contributes the same weight as one from 2 bars ago.

### Decay Formula

```python
decay = exp(-bars_since_event / halflife)
effective_contribution = raw_contribution * decay
```

### Halflives by Event Type

| Event class | Halflife (bars) | Rationale |
|-------------|----------------|-----------|
| Momentum events (stoch cross, accel) | 5 | Short-lived, fade quickly |
| Trend events (MACD cross, BB walking) | 10 | Medium persistence |
| Structural/confirmatory (ADX confirmed) | 20 | Trend regimes last longer |
| Inflection flag | 3 | Acute signal, fades fast |

### Event Tracking

Events that need decay require a `bars_since_event` feature alongside the event flag. Some already exist (`di_cross_bars_ago` from ADXEvents). Others need to be added to the I2 composite outputs, or tracked internally in the CIS scorer via state (`_event_bars: dict[str, int]`).

The CIS scorer maintains a small internal state dict `_event_ages` that tracks how many bars since each event last fired. This state is reset when the event fires again.

---

## Component 5: CISResult Attribution Schema

```python
@dataclass
class CISResult:
    cis_score: float
    direction: int
    bucket_scores: dict[str, float]
    weights_version: int
    buckets_agreeing: int
    # NEW — per-constituent contribution to final CIS score
    constituent_contributions: dict[str, dict[str, float]]
```

Each inner value is the **actual contribution to the final CIS score**:

```
contribution = normalized_signal_value × weight_within_bucket × bucket_weight
```

Example:
```json
{
  "momentum": {
    "rsi_14": 0.038,
    "macd_histogram_12_26_9": 0.022,
    "williams_r_14": 0.011,
    "mfi_14": 0.009,
    "momentum_bias": 0.018
  },
  "trend": {
    "trend_regime": 0.062,
    "kalman_slope": 0.031,
    "psar_direction": 0.008,
    "aroon_osc_25": 0.012
  },
  ...
}
```

Small values are noise. Large values are the real drivers. This is a lightweight SHAP equivalent — no ML model required.

---

## Component 6: signal_ledger Schema

```sql
ALTER TABLE signal_ledger
    ADD COLUMN cis_attribution JSONB;
```

- Written at signal fire time alongside `cis_score`, `cis_direction`, `cis_buckets_agreeing`
- Stores the full `constituent_contributions` dict
- Immutable after write (outcome data is appended to separate columns)
- Enables post-hoc queries:

```sql
-- Which signals fired where williams_r contributed meaningfully?
SELECT signal_type, outcome, (cis_attribution->'momentum'->>'williams_r_14')::float AS wr_contrib
FROM signal_ledger
WHERE (cis_attribution->'momentum'->>'williams_r_14')::float > 0.01
ORDER BY determined_at DESC;
```

---

## Component 7: I8 Narrative Integration

The AI narrative prompt receives a pre-digested attribution summary alongside the raw intelligence event. Format:

```
CIS: +0.71 (bullish) — 5/6 buckets agreeing

Top contributors:
  institutional: ob_type[+0.18]  in_demand_zone[+0.14]  fvg_type[+0.09]  obv_slope[+0.03]
  trend:         trend_regime[+0.22]  psar_direction[+0.05]  aroon_osc[+0.04]
  regime:        hmm_trending_up[+0.12]  ctf_regime[+0.08]
  momentum:      rsi_14[+0.04]  williams_r[+0.02]  mfi[+0.01]
  structure:     bos_detected[+0.09]  choch_direction[+0.08]
```

I8 can produce qualitatively richer narratives: *"Price entered a demand zone backed by institutional order block alignment, PSAR and Aroon confirming bullish trend, HMM 78% trending-up. Momentum oscillators mildly supportive."*

---

## Bootstrap Weight Strategy

New signals start with conservative weights (0.02–0.05) so they have minimal influence until the learning loop validates them. The rule: new signals should not be capable of tipping CIS direction on their own at bootstrap — they only stack with existing confirmed signals.

```python
# Example momentum bucket weight updates
MOMENTUM_WEIGHTS = {
    "rsi_14":              0.25,  # existing, validated
    "macd_histogram":      0.20,  # existing, validated
    "roc_14":              0.15,  # existing, validated
    "momentum_bias":       0.15,  # existing, validated
    "DivergenceStack":     0.10,  # existing, validated
    # NEW — conservative bootstrap
    "williams_r_14":       0.04,
    "mfi_14":              0.04,
    "stoch_rsi_k_14":      0.03,
    "cmf_20":              0.03,
    "rsi_accel":           0.02,  # decayed event
    "macd_accel":          0.02,  # decayed event
    ...
}
```

Weights must sum to 1.0 within each bucket. Existing signals are proportionally reduced to accommodate new ones.

---

## Phasing

**Phase A — Infrastructure:**
1. `DonchianPosition` and `OBVMomentum` bridge composites
2. `CISResult.constituent_contributions` field + scoring logic
3. Event decay framework in CIS scorer (internal `_event_ages` state)
4. `signal_ledger.cis_attribution` column + migration

**Phase B — Bucket Wiring:**
5. Expand momentum bucket (williams_r, mfi, stoch_rsi, cmf, accel events, stoch events)
6. Expand trend bucket (aroon, psar, di_spread, macd events, adx events)
7. Expand regime bucket (hv_ratio, donchian_position, inflection_flag)
8. Expand institutional bucket (obv_slope, volume events, BB events)

**Phase C — Attribution Propagation:**
9. signal_generator_service writes `cis_attribution` to signal_ledger
10. I8 narrative prompt updated with attribution summary

**Phase D — Tests:**
11. Unit tests for correlation penalty, event decay, attribution math
12. Full test suite green, ruff 0 errors

---

## Success Criteria

- All 10 previously unused I1 outputs contribute to CIS
- All 6 I2 composite output sets contribute to CIS
- `CISResult.constituent_contributions` populated on every score call
- `signal_ledger.cis_attribution` written for every new signal
- Correlated oscillators penalized — no single correlation group can produce bucket score > 0.7 alone
- Stale events decay to <10% contribution after 2× halflife
- I8 narrative references top-3 contributors by name
- 1083 tests passing + 0 ruff errors (regression-free)
