# Phase 24: Second-Derivative Acceleration — Context

**Gathered:** 2026-03-10
**Status:** Ready for planning — design and implementation plan already complete

## Source Documents

- **Design doc:** `docs/plans/2026-03-10-second-derivative-indicators-design.md`
- **Implementation plan:** `docs/plans/2026-03-10-second-derivative-indicators-plan.md`

## Scope Summary

**I1 changes (1):**
0. New `HMA` indicator — Hull Moving Average (n=20): WMA(2×WMA(n/2) − WMA(n), sqrt(n)); output `hma_20`. Add to `moving_averages.py` or new `hma.py`. ~30 lines. Prerequisite for HMA slope/accel below.

**I2 changes (4):**
1. Extend `MomentumAcceleration` — add `rsi_curvature`, `macd_hist_slope`, `price_accel`, `hma_slope`, `hma_accel` outputs (`hma_slope = hma_20[t] - hma_20[t-1]`, `hma_accel = hma_slope[t] - hma_slope[t-1]`)
2. New `ExhaustionScore` plugin (`cmp_ExhaustionScore`) — detects extreme + decelerating conditions; outputs `exhaustion_score`, `exhaustion_side`, `exhaustion_bars`
3. New `AccelerationRegime` plugin (`cmp_AccelerationRegime`) — synthesizes acceleration signals into `accel_regime` (building/peak/waning/trough/neutral), `accel_score`, `accel_agreement`

**I3 changes (1):**
4. New `SwingMomentum` plugin (`struct_SwingMomentum`) — structural momentum from swing amplitude/velocity; outputs `swing_amplitude_ratio`, `swing_amplitude_expanding`, `swing_velocity_bars`, `swing_velocity_trend`, `struct_energy`, `struct_accel_bias`

**I7 wiring (4 setups, score adjustments only):**
- `LiquiditySweepReclaim` + `LiquidityHunt` — exhaustion_score boost (confirms stop-run entry)
- `MomentumBreakout` + `TrendFollowing` — exhaustion guard penalty (suppresses chasing exhausted moves)

**ML impact:** 17 new features per bar per symbol per TF land in `intelligence_features` automatically.

**Closes todos:** `2026-03-04-add-hma-i1-plugin.md`, `2026-03-06-expand-second-derivative-indicators.md`

## Key Files

- `src/intelligence/indicators/moving_averages.py` — add HMA
- `src/intelligence/register_plugins.py` — register HMA + 3 new plugins
- `src/intelligence/composites/momentum_accel.py` — extend (+5 outputs total)
- `src/intelligence/composites/exhaustion_score.py` — new
- `src/intelligence/composites/acceleration_regime.py` — new
- `src/intelligence/structure/swing_momentum.py` — new
- `src/intelligence/trading/liquidity_sweep_reclaim.py` — wire
- `src/intelligence/trading/liquidity_hunt.py` — wire
- `src/intelligence/trading/momentum_breakout.py` — wire
- `src/intelligence/trading/trend_following.py` — wire
