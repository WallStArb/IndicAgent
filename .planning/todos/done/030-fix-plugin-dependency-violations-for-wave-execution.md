---
created: 2026-04-08T16:36:20.952Z
updated: 2026-04-08
title: Fix plugin dependency violations for wave execution
area: intelligence
files:
  - src/intelligence/i2/momentum_accel.py
  - src/intelligence/i2/acceleration_regime.py
  - src/intelligence/i2/exhaustion_score.py
  - src/intelligence/i2/macd_events.py
  - src/intelligence/i4/trend_regime.py
  - src/intelligence/i4/anchored_vwap.py
  - src/intelligence/i4/mtf_volatility.py
  - src/intelligence/features/smc_context/supply_demand_zones.py
  - src/intelligence/features/smc_context/breaker_blocks.py
  - src/intelligence/features/smc_context/mitigation_blocks.py
  - services/intelligence_pipeline_agent.py
---

## Problem

Plugin dependency audit found **8 cross-tier violations + 6 internal deps** of the tier execution model. The pipeline runs tiers sequentially (I1→I2→I3→I4→I5/SMC→I6→I7) but several plugins read outputs from later tiers, meaning they get stale/missing data under parallel execution.

### Cross-Tier Violations (stale/None data):

1. **I2→I3**: `macd_events` (I2) reads `nearest_support` from `support_resistance` (I3)
2. **I4→I3**: `trend_regime` reads `trend_direction`, `trend_strength` from `trend_structure` (I3)
3. **I4→I3**: `anchored_vwap` reads `swing_high_idx`, `swing_low_idx` from `swing_detector` (I3)
4. **I4→I5**: `mtf_volatility` reads `squeeze_active` from `bollinger_squeeze` (I5) — backward!

### Internal Tier Dependencies (ordering within parallel wave):

5. **I2**: `momentum_accel` → `acceleration_regime` + `exhaustion_score` (rsi_curvature, macd_hist_slope)
6. **I4**: `garch_volatility` → `kalman_trend` (garch_sigma)
7. **I4**: `volatility_regime` → `mtf_volatility` (vol_expansion)
8. **SMC**: `order_blocks` → `breaker_blocks` + `mitigation_blocks` (ob_type, ob_top, ob_bottom, ob_mitigated)
9. **SMC**: `fair_value_gap` + `liquidity_pools` → `supply_demand_zones` (fvg_midpoint, price_in_premium)

### Clean Tiers:
- I1 (27): all independent, raw OHLCV only
- I3 (7): no internal or cross-tier deps
- I5 (15): all read I1-I3 only
- I6 (1): reads cross-TF intel by design
- I7 (36): all read I1-I6 only, zero I7-to-I7 deps

## Solution

Restructure into sub-waves within each tier to respect dependencies:

**I2 → split into Wave A/B:**
- Wave A: momentum_accel + 8 independent plugins
- Wave B: acceleration_regime, exhaustion_score (after momentum_accel)
- Move macd_events to I3 (uses structural data) or remove support check

**I4 → split into Wave A/B + fix mtf_volatility:**
- Wave A: volatility_regime, garch_volatility + 7 independent (anchored_vwap, trend_regime can stay — they read I3 which is done)
- Wave B: kalman_trend (after garch), mtf_volatility (after vol_regime)
- mtf_volatility: remove `squeeze_active` dependency (I4→I5 circular) or move to I5

**SMC → split into Wave A/B:**
- Wave A: bos_choch, fvg, order_blocks, liq_sweeps, bocpd, hmm, liquidity_pools, ict_killzones, amd_cycle, premium_discount (10 independent)
- Wave B: supply_demand_zones, breaker_blocks, mitigation_blocks (after order_blocks, fvg, liquidity_pools)

**Proposed wave structure:**
```
Wave 0: I1 (27 independent)
Wave 1: I2-WaveA(9) + I3(7) + SMC-WaveA(10)
Wave 2: I2-WaveB(2) + SMC-WaveB(3) + I4-WaveA(11)
Wave 3: I4-WaveB(2) + I5(15)
Wave 4: I6(1)
Wave 5: I7(36)
```

Context: Part of pipeline parallelization work. The current `intelligence_pipeline_agent.py` runs I2-I6 sequentially which is the throughput bottleneck.
