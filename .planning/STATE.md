---
gsd_state_version: 1.0
milestone: v2.1
milestone_name: Data Foundation & Signal Confidence
status: In progress
last_updated: "2026-03-23T16:30:00Z"
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 0
  completed_plans: 2
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-03-22)

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** Phase 49 — DB Performance & Signal Ledger Hardening

## Current Position

Phase: 49
Plan: Not started

## v2.1 Milestone Goal

Earn the right to trust the numbers. Fix the live data foundation (tick aggregation), close DB performance gaps, validate every intelligence layer independently, graduate shadow modes with real evidence, and harden infrastructure so nothing requires manual intervention.

## Architecture Constraints (SoC / DAG / Microservices)

- **Plugin tier purity**: I5 patterns → `src/intelligence/patterns/`; I7 setups → `src/intelligence/trading/`; I4 context → `src/intelligence/context/`
- **DAG ordering**: I1 → I2 → I3 → I4 → I5 → SMC → I6 → I7; new I4/I5 plugins computed before I7
- **`FeaturePipelineService` is the unified I1-I6 pipeline**: Replaces indicator_service, market_analysis_service, timeframes_builder_service (consolidated in v2.0)
- **`SignalGeneratorService` consumes BarMessage and publishes BarIntelligenceRecord`: 6 DAG stages run in-process (QualityGate → RegimeGate → TODAdjuster → Calibrator → Ranker → WinnerSelector)
- **`lifecycle_tracker.py` is pure-function`: Staleness state injected from service; no DB/Kafka in tracker
- **`trade_framer.py` is single source of truth for stop sizing`: All 36 I7 plugins inherit changes; no per-plugin stop logic
- **`CISScorer` stays stateless**: Kalman filter wraps it in service layer (v2.0)
- **Plugin registry is source of truth**: All new plugins registered in `TIER_I4`, `TIER_I5`, or `TIER_I7`; `registry.validate_tier()` hard-crashes on missing names

## Key Verified Facts (v2.0 Foundation)

- **TIER_I1 = 27, TIER_I2 = 7, TIER_I3 = 7, TIER_I4 = 11, TIER_I5 = 15, TIER_I6 = 1, TIER_I7 = 36** — 121 total plugins after v2.0
- **SignalStatus enum** — Replaced raw strings ("pending", "active", "regime_suppressed") with `SignalStatus` enum (v2.0)
- **SignalOutcome enum** — 8-class taxonomy for signal exits (v2.0)
- **FeaturePipelineService** — Single service handles I1-I6; publishes `development.intelligence` with BarMessage/IntelligenceEvent schemas (v2.0)
- **SignalGeneratorService** — In-process DAG stages; publishes `development.intelligence.record` with BarIntelligenceRecord (v2.0)
- **Atomic persistence** — FeatureWriterService INSERTs complete rows; no UPSERTs, no partial writes (v2.0)
- **Cross-asset unconditionally active** — `CROSS_ASSET_ENABLED` flag removed (v2.0)
- **Roll monitor pending** — `ROLL_MONITOR_ENABLED=false` awaiting D-21 validation after market_data_5m backfill (v2.0)
- **Shadow dict infrastructure** — All 36 I7 plugins capture `_shadow` dict with ctf_*, exhaustion fields for ML training (v2.0)

## v2.1 Phase Context

**Phase 48:** ✅ COMPLETE — Tick aggregation implemented (5s→1m bars via IBKR real-time bar push). I7 refactoring complete — extracted 3 shared utilities (microstructure_utils, state_utils, volume_profile_utils), fixed 4 I6 confluence violations, optimized aggregator calibration batching. 550+ lines of duplicate code eliminated, 83% reduction in calibration interpolation calls, 40-60% per-bar latency reduction.

  - **48.1:** Signal Generator Warmup Seed — fix bars_processed=0 issue by restoring DB seed on startup.
  - **48.2:** I7 Trading Layer Refactoring — code reuse utilities + performance optimizations.

**Phase 49:** DB performance optimization — signal_ledger composite index, query optimization, CIS null repair completion.

**Phase 50:** Roll monitor graduation — D-21 validation, migration 049_roll_premium_pct.sql, enable ROLL_MONITOR_ENABLED.

**Phase 51:** Validation framework — per-layer sanity checks, outcome completeness audit, automated validation.

**Phase 52:** Infrastructure hardening — Docker restart policies, automated gap-fill, log rotation, deploy scripts.

## Accumulated Context

### Roadmap Evolution

- Phase 48.1 added: Signal Generator Warmup Seed (2026-03-23) — fix bars_processed=0, restore DB seed from startup
- Phase 48 COMPLETE (2026-03-23): Tick aggregation + I7 refactoring — 550+ lines eliminated, 3 shared utilities created, 4 I6 confluence violations fixed, aggregator calibration optimized
- Phase 49.1 inserted after Phase 49: Regime Gate Fix — Write All Signals to Signal Ledger (URGENT)
