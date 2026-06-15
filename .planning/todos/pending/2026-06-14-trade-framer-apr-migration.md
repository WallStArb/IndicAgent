# TODO: APR Migration — trade_framer.py Hardcoded Constants

**Created:** 2026-06-14
**Source:** Phase 126 P126-01 planning session
**Priority:** Medium (architecture violation, not data quality blocker)
**Blocks:** ML discovery cannot tune stop placement parameters until these are in APR

## Problem

Every numeric constant in `src/intelligence/trading/trade_framer.py` is a CLAUDE.md architecture violation. Hardcoded thresholds in `src/` cannot be tuned by ML discovery or changed without a code deploy.

## Constants to migrate

| Constant | Current value | APR key | ML target? |
|----------|--------------|---------|-----------|
| `ATR_STOP_DEMAND_MULTIPLIER` | 0.25 | `feature.trade_framer.stop_demand_buffer_atr` | Yes |
| `ATR_STOP_SWEEP_MULTIPLIER` | 0.30 | `feature.trade_framer.stop_sweep_buffer_atr` | Yes |
| `ATR_STOP_OB_MULTIPLIER` | 0.20 | `feature.trade_framer.stop_ob_buffer_atr` | Yes |
| `ATR_STOP_SWING_MULTIPLIER` | 0.25 | `feature.trade_framer.stop_swing_buffer_atr` | Yes |
| `ATR_STOP_SR_MULTIPLIER` | 0.50 | `feature.trade_framer.stop_sr_buffer_atr` | Yes |
| `ATR_STOP_FALLBACK_MULTIPLIER` | 2.0 | `feature.trade_framer.stop_fallback_atr` | Yes |
| `MIN_STOP_ATR_MULTIPLIER` | 1.0 | `feature.trade_framer.min_stop_atr` | Yes — bounded below by `feature.zone_engine.min_stop_distance_atr` |
| `MIN_RR_T1` | 1.5 | `threshold.trade_framer.min_rr_t1` | Yes |
| `ADAPTIVE_BUFFER_HARD_CAP` | 1.40 | `feature.trade_framer.adaptive_buffer_hard_cap` | Operator preference |
| `STRUCTURE_SNAP_PROXIMITY_ATR` | 1.5 | `feature.trade_framer.structure_snap_proximity_atr` | No — structural classification |
| `ATR_ZONE_SWEEP_MULTIPLIER` | 0.5 | `feature.trade_framer.zone_sweep_atr` | Yes |
| `ATR_ZONE_LOW_MULTIPLIER` | 1.0 | `feature.trade_framer.zone_low_atr` | Yes |
| `ATR_ZONE_HIGH_MULTIPLIER` | 0.5 | `feature.trade_framer.zone_high_atr` | Yes |
| `ATR_TARGET_MIN_MULTIPLIER` | 0.5 | `feature.trade_framer.target_min_atr` | Yes |
| `VP_PROXIMITY_THRESHOLD_ATR` | 0.5 | `feature.trade_framer.vp_proximity_atr` | Yes |
| Adaptive buffer piecewise coefficients | 0.80, 0.70, 0.20/0.30, 0.35/0.50, 0.16 | `feature.trade_framer.adaptive_buffer.*` | Yes — these define the GARCH vol response curve |

## Key dependency

`feature.zone_engine.min_stop_distance_atr` (added in Phase 126) is an independent floor on stop distance. `feature.trade_framer.min_stop_atr` (added in this task) is the primary control. ML can tune `min_stop_atr` downward, but `min_stop_distance_atr` acts as the hard floor that requires an explicit operator override to breach.

## Sequencing

- Requires: Phase 127 (Clean Replay) to produce `counterfactual_pnl_r` training data
- Requires: Phase 130 (CounterfactualTracker) to populate `trade_frames.counterfactual_pnl_r`
- ML discovery can then learn optimal values for each parameter per asset class and regime
- Do not attempt before sufficient N (>= 30 outcomes per parameter level per segment)
