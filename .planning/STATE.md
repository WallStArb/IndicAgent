---
gsd_state_version: 1.0
milestone: v1.9
milestone_name: I7 Alpha Engine
status: defining_requirements
stopped_at: Requirements defined — roadmap being created
last_updated: "2026-03-16T00:00:00.000Z"
last_activity: 2026-03-16 — Milestone v1.9 started; requirements written (46 reqs, 10 new I7 plugins)
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-16)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.
**Current focus:** v1.9 I7 Alpha Engine — defining roadmap

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-03-16 — Milestone v1.9 started

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity (cumulative):**
- Total plans completed: 100 (v1.0–v1.8)
- Average duration: ~30 min/plan
- Total execution time: ~50 hours

## Accumulated Context

### Architecture Constraints (SoC / DAG / Microservices)
- **Plugin tier purity**: I5 divergence plugins → `src/intelligence/patterns/`; I7 setups → `src/intelligence/trading/`; I4 context → `src/intelligence/context/`
- **DAG ordering**: I1 → I2 → I3 → I4 → I5 → SMC → I6 → I7; new I4/I5 plugins computed before I7
- **`indicator_service` is per-symbol isolated**: cross-asset features require `cross_asset_service.py` (new service)
- **`lifecycle_tracker.py` is pure-function**: staleness state injected from service; no DB/Kafka in tracker
- **`trade_framer.py` is single source of truth for stop sizing**: all 17 plugins inherit changes; no per-plugin stop logic
- **`CISScorer` stays stateless**: Kalman filter wraps it in service layer
- **Plugin registry is source of truth**: all new plugins registered in `TIER_I4`, `TIER_I5`, or `TIER_I7`; `registry.validate_tier()` hard-crashes on missing names

### Key Verified Facts
- `weight_updater.py` EXISTS at `src/intelligence/weight_updater.py` — trains LogisticRegression on `signal_quality` (needs upgrade to binary win labels)
- `cis_weights` table EXISTS — needs `asset_cluster` + `timeframe` schema extension
- `cis_attribution` column EXISTS in `signal_ledger` — `signal_features` table adds raw feature values (not a duplicate)
- CMF (`cmf_20`), OBV (`obv`), MACD histogram (`macd_histogram_12_26_9`) already exist as I1 indicators
- `garch_vol_regime` field already exists in `IntelligenceEvent` (output of VolatilityRegimePlugin)
- Correct outcome taxonomy: `target_1`, `target_1_2`, `target_full` (wins); `stopped_at_entry`, `stopped_in_trade`, `never_activated`, `ttl_expired_ahead`, `ttl_expired_behind`, `condition_expired` (losses)
- `KalmanTrendPlugin` at `src/intelligence/context/kalman_trend.py` — reuse this implementation for CIS Kalman

### Design Anchor
Full spec: `docs/ideas/i7-quant-audit-2026-03-16.md` (reviewed + corrected 2026-03-16)

## Session Continuity

Last session: 2026-03-16
Stopped at: Requirements defined — awaiting roadmap creation
Resume file: None
