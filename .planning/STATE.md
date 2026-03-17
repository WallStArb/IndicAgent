---
gsd_state_version: 1.0
milestone: v1.9
milestone_name: I7 Alpha Engine
status: roadmap_defined
stopped_at: Roadmap created — ready for plan-phase 31
last_updated: "2026-03-16T00:00:00.000Z"
last_activity: 2026-03-16 — Roadmap created for v1.9 (7 phases, 41 requirements, Phases 31-37)
progress:
  total_phases: 7
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-16)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.
**Current focus:** v1.9 I7 Alpha Engine — Phase 31 ready to plan

## Current Position

Phase: 31 (not started)
Plan: —
Status: Roadmap defined — awaiting `/gsd:plan-phase 31`
Last activity: 2026-03-16 — Roadmap written for v1.9

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
- **`indicator_service` is per-symbol isolated**: cross-asset features require `cross_asset_service.py` (new service in Phase 37)
- **`lifecycle_tracker.py` is pure-function**: staleness state injected from service; no DB/Kafka in tracker
- **`trade_framer.py` is single source of truth for stop sizing**: all 17 plugins inherit changes; no per-plugin stop logic
- **`CISScorer` stays stateless**: Kalman filter wraps it in service layer (Phase 35)
- **Plugin registry is source of truth**: all new plugins registered in `TIER_I4`, `TIER_I5`, or `TIER_I7`; `registry.validate_tier()` hard-crashes on missing names

### Key Verified Facts
- `weight_updater.py` EXISTS at `src/intelligence/weight_updater.py` — trains LogisticRegression on `signal_quality` (Phase 31 upgrades to binary win labels)
- `cis_weights` table EXISTS — needs `asset_cluster` + `timeframe` schema extension (Phase 31)
- `cis_attribution` column EXISTS in `signal_ledger` — `signal_features` table (Phase 31) adds raw feature values (not a duplicate)
- CMF (`cmf_20`), OBV (`obv`), MACD histogram (`macd_histogram_12_26_9`) already exist as I1 indicators
- `garch_vol_regime` field already exists in `IntelligenceEvent` (output of VolatilityRegimePlugin)
- Correct outcome taxonomy: `target_1`, `target_1_2`, `target_full` (wins); `stopped_at_entry`, `stopped_in_trade`, `never_activated`, `ttl_expired_ahead`, `ttl_expired_behind`, `condition_expired` (losses)
- `KalmanTrendPlugin` at `src/intelligence/context/kalman_trend.py` — reuse this implementation for CIS Kalman (Phase 35)

### v1.9 Phase Ordering Rationale
- **Phase 31 first**: Learning loop + signal_features schema + shadow infrastructure must be in place before any new plugins fire — all downstream phases accumulate labeled training data from day one
- **Phase 32 second**: Stop architecture centralized in trade_framer.py before adding new plugins — all 17 existing + 10 new plugins inherit correct stops automatically
- **Phase 33 third**: Five new I7 plugins added after stop architecture is stable; no per-plugin stop logic needed
- **Phase 34 fourth**: New I4 infrastructure (AVWAP, Volume Profile) before the two I7 plugins that consume them
- **Phase 35 fifth**: Calibration, TOD, Kalman filter applied after full plugin set is stable — no moving target
- **Phase 36 sixth**: Microstructure (OFI/CVD) placed last among plugin phases — tick data dependency requires audit before implementation variant is chosen
- **Phase 37 last**: New microservice with highest SoC complexity; all I7 plugins stable before adding cross-asset dependency

### Design Anchor
Full spec: `docs/ideas/i7-quant-audit-2026-03-16.md` (reviewed + corrected 2026-03-16)

## Session Continuity

Last session: 2026-03-16
Stopped at: Roadmap defined — ready to plan Phase 31
Resume file: None
Next action: `/gsd:plan-phase 31`
