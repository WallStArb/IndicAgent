# Phase 24: Second-Derivative Acceleration — Context

**Gathered:** 2026-03-10
**Status:** Ready for planning — design and implementation plan already complete

## Source Documents

- **Design doc:** `docs/plans/2026-03-10-second-derivative-indicators-design.md`
- **Implementation plan:** `docs/plans/2026-03-10-second-derivative-indicators-plan.md`

## Scope Summary

**I2 changes (3):**
1. Extend `MomentumAcceleration` — add `rsi_curvature`, `macd_hist_slope`, `price_accel` outputs
2. New `ExhaustionScore` plugin (`cmp_ExhaustionScore`) — detects extreme + decelerating conditions; outputs `exhaustion_score`, `exhaustion_side`, `exhaustion_bars`
3. New `AccelerationRegime` plugin (`cmp_AccelerationRegime`) — synthesizes acceleration signals into `accel_regime` (building/peak/waning/trough/neutral), `accel_score`, `accel_agreement`

**I3 changes (1):**
4. New `SwingMomentum` plugin (`struct_SwingMomentum`) — structural momentum from swing amplitude/velocity; outputs `swing_amplitude_ratio`, `swing_amplitude_expanding`, `swing_velocity_bars`, `swing_velocity_trend`, `struct_energy`, `struct_accel_bias`

**I7 wiring (4 setups, score adjustments only):**
- `LiquiditySweepReclaim` + `LiquidityHunt` — exhaustion_score boost (confirms stop-run entry)
- `MomentumBreakout` + `TrendFollowing` — exhaustion guard penalty (suppresses chasing exhausted moves)

**ML impact:** 15 new features per bar per symbol per TF land in `intelligence_features` automatically.

## Key Files

- `src/intelligence/composites/momentum_accel.py` — extend
- `src/intelligence/composites/exhaustion_score.py` — new
- `src/intelligence/composites/acceleration_regime.py` — new
- `src/intelligence/structure/swing_momentum.py` — new
- `src/intelligence/trading/liquidity_sweep_reclaim.py` — wire
- `src/intelligence/trading/liquidity_hunt.py` — wire
- `src/intelligence/trading/momentum_breakout.py` — wire
- `src/intelligence/trading/trend_following.py` — wire
- `src/intelligence/register_plugins.py` — register 3 new plugins
