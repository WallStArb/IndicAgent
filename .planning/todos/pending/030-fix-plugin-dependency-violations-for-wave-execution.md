---
created: 2026-04-08T16:36:20.952Z
title: Fix plugin dependency violations for wave execution
area: intelligence
files:
  - src/intelligence/i2/momentum_accel.py
  - src/intelligence/i2/acceleration_regime.py
  - src/intelligence/i2/exhaustion_score.py
  - src/intelligence/i2/macd_events.py
  - src/intelligence/i3/support_resistance.py
  - src/intelligence/i4/trend_regime.py
  - src/intelligence/i4/anchored_vwap.py
  - src/intelligence/i3/trend_structure.py
  - src/intelligence/i3/swing_detector.py
  - services/intelligence_pipeline_agent.py
---

## Problem

Plugin dependency audit found 5 violations of the tier execution model. The pipeline runs tiers sequentially (I1→I2→I3→I4→I5→I6→I7) but several plugins read outputs from later tiers, meaning they get stale/missing data.

**Violations:**

1. **I2 internal ordering**: `momentum_accel` produces `rsi_curvature` and `macd_hist_slope` — both `acceleration_regime` and `exhaustion_score` (I2) read these. If run in parallel within I2, they get None.

2. **I2→I3 backward**: `macd_events` (I2) reads `nearest_support` from `support_resistance` (I3). I2 runs before I3, so always gets stale data.

3. **I4→I3 backward**: `trend_regime` (I4) reads `trend_direction`, `trend_strength` from `trend_structure` (I3).

4. **I4→I3 backward**: `anchored_vwap` (I4) reads `swing_high_idx`, `swing_low_idx` from `swing_detector` (I3).

I1 is clean — all 27 I1 plugins are independent (raw OHLCV only). I3 has no internal deps.

## Solution

Options per violation:

**I2 internal (momentum_accel → acceleration_regime, exhaustion_score):**
- Split I2 into sub-waves: Wave A (momentum_accel + independent plugins), Wave B (acceleration_regime, exhaustion_score)
- Or: inline the rsi_curvature/macd_hist_slope calculation into the dependent plugins

**I2→I3 (macd_events ← support_resistance):**
- Move macd_events to I3 (it's using structural data anyway)
- Or: inline the nearest_support calc into macd_events
- Or: remove the support check from macd_events entirely (question whether it adds value)

**I4→I3 (trend_regime ← trend_structure, anchored_vwap ← swing_detector):**
- Move these 2 I4 plugins into Wave 2 alongside I5 (they depend on I3 from Wave 1)

**Proposed wave structure:**
```
Wave 1: I1 + I2-independent + I3 + I4-independent(11) + SMC
Wave 2: I2-dependent(acceleration_regime, exhaustion_score) + I4-dependent(trend_regime, anchored_vwap) + I5
Wave 3: I6 + I7
```

Context: Part of pipeline parallelization work. The current `intelligence_pipeline_agent.py` runs I2-I6 sequentially which is the throughput bottleneck.
