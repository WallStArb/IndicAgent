# TODO: APR Migration — trade_framer.py Hardcoded Constants (PARTIAL — Phase 132 Plans 01-04 complete)

**Created:** 2026-06-14
**Updated:** 2026-06-18 (Phase 132 Plans 01-04 done; Plan 05 pending)
**Source:** Phase 126 P126-01 planning session
**Priority:** Medium (architecture violation, not data quality blocker)
**Blocks:** ML discovery cannot tune stop placement parameters until these are in APR

## Status

Phase 132 migrated the bulk of trade_framer constants (Plans 02/03/04). Plan 05 is still pending.

## Constants migrated (Phase 132 Plans 02-04)

| Constant | APR key | Done |
|----------|---------|------|
| `ATR_STOP_DEMAND_MULTIPLIER` | `feature.trade_framer.stop_demand_buffer_atr` | Plan 02 |
| `ATR_STOP_SWEEP_MULTIPLIER` | `feature.trade_framer.stop_sweep_buffer_atr` | Plan 02 |
| `ATR_STOP_OB_MULTIPLIER` | `feature.trade_framer.stop_ob_buffer_atr` | Plan 02 |
| `ATR_STOP_SWING_MULTIPLIER` | `feature.trade_framer.stop_swing_buffer_atr` | Plan 02 |
| `ATR_STOP_SR_MULTIPLIER` | `feature.trade_framer.stop_sr_buffer_atr` | Plan 02 |
| `ATR_STOP_FALLBACK_MULTIPLIER` | `feature.trade_framer.stop_fallback_atr` | Plan 02 |
| `MIN_STOP_ATR_MULTIPLIER` | `feature.trade_framer.min_stop_atr` | Plan 02 |
| `MIN_RR_T1` | `threshold.trade_framer.min_rr_t1` | Plan 02 |
| `ADAPTIVE_BUFFER_HARD_CAP` | `feature.trade_framer.adaptive_buffer_hard_cap` | Plan 03 |
| Adaptive buffer piecewise coefficients | `feature.trade_framer.adaptive_buffer.*` | Plan 03 |
| Per-asset-class stop floor | `threshold.trade_framer.min_stop_floor_<class>` | Plan 04 |

## Constants still hardcoded (Phase 132 Plan 05 — PENDING)

| Constant | Current value | APR key | ML target? |
|----------|--------------|---------|-----------|
| `STRUCTURE_SNAP_PROXIMITY_ATR` | 1.5 | `feature.trade_framer.structure_snap_proximity_atr` | No — structural classification |
| `ATR_ZONE_SWEEP_MULTIPLIER` | 0.5 | `feature.trade_framer.zone_sweep_atr` | Yes |
| `ATR_ZONE_LOW_MULTIPLIER` | 1.0 | `feature.trade_framer.zone_low_atr` | Yes |
| `ATR_ZONE_HIGH_MULTIPLIER` | 0.5 | `feature.trade_framer.zone_high_atr` | Yes |
| `ATR_TARGET_MIN_MULTIPLIER` | 0.5 | `feature.trade_framer.target_min_atr` | Yes |
| `ATR_TARGET_MAX_MULTIPLIER` | 8.0 | `feature.trade_framer.target_max_atr` | Yes |
| `ATR_TARGET_MAX_MULTIPLIER_BY_TF` | per-TF dict | `feature.trade_framer.target_max_atr_<tf>` | Yes |
| `VP_PROXIMITY_THRESHOLD_ATR` | 0.5 | `feature.trade_framer.vp_proximity_atr` | Yes |

## Key dependency

`feature.zone_engine.min_stop_distance_atr` (added in Phase 126) is an independent floor on stop distance. `feature.trade_framer.min_stop_atr` (added in this task) is the primary control. ML can tune `min_stop_atr` downward, but `min_stop_distance_atr` acts as the hard floor that requires an explicit operator override to breach.

## Sequencing

- Requires: Phase 127 (Clean Replay) to produce `counterfactual_pnl_r` training data
- Requires: Phase 130 (CounterfactualTracker) to populate `trade_frames.counterfactual_pnl_r`
- ML discovery can then learn optimal values for each parameter per asset class and regime
- Do not attempt before sufficient N (>= 30 outcomes per parameter level per segment)
