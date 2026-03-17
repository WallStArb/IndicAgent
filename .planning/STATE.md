---
gsd_state_version: 1.0
milestone: v1.9
milestone_name: I7 Alpha Engine — In Progress
status: "Phase 31 in progress — Plan 02 complete"
stopped_at: Completed 031-02-PLAN.md
last_updated: "2026-03-17T01:35:00Z"
last_activity: 2026-03-17 — 031-02 executed (binary WIN_OUTCOMES labels, ASSET_CLUSTER_MAP, per-cluster training in weight_updater)
progress:
  total_phases: 13
  completed_phases: 0
  total_plans: 6
  completed_plans: 2
  percent: 33
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-16)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.
**Current focus:** v1.9 I7 Alpha Engine — Phase 31 ready to plan

## Current Position

Phase: 31 (in progress)
Plan: 02 complete → 03 next
Status: Phase 31 in progress — Plan 02 complete
Last activity: 2026-03-17 — 031-02 executed (binary WIN_OUTCOMES labels, ASSET_CLUSTER_MAP, per-cluster training in weight_updater)

Progress: [███░░░░░░░] 33%

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
- `weight_updater.py` UPGRADED in 031-02 — trains LogisticRegression on binary WIN_OUTCOMES labels (target_1/target_1_2/target_full=win, rest=loss); ASSET_CLUSTER_MAP (21 symbols, 5 clusters); per-cluster training when N >= 100; is_shadow=FALSE filter; WeightUpdateResult has win_rate (not signal_quality_mean)
- `cis_weights` table has `asset_cluster` column + unique index on (asset_cluster, timeframe, version) — DONE in 031-01
- `signal_features` hypertable EXISTS — 7-day chunks, PK (signal_id, feature_name, computed_at) — DONE in 031-01
- `signal_ledger.is_shadow` column EXISTS — partial index WHERE is_shadow = TRUE — DONE in 031-01
- `CISScorer.update_weights()` EXISTS — GIL-protected hot-swap; service has `_cis_scorer` instance refreshed every 30min from DB
- **TimescaleDB hypertable unique constraint caveat**: PK must include partitioning column (computed_at). `PRIMARY KEY (signal_id, feature_name)` fails on hypertables.
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

Last session: 2026-03-17T01:35:00Z
Stopped at: Completed 031-02-PLAN.md
Resume file: .planning/phases/31-cis-learning-loop-signal-feature-snapshots/031-02-SUMMARY.md
Next action: `/gsd:execute-phase 31 03` (031-03: signal_features writer)
