---
gsd_state_version: 1.0
milestone: v2.2
milestone_name: Operational Excellence
status: Phase complete — ready for verification
last_updated: "2026-03-28T12:31:39.694Z"
progress:
  total_phases: 11
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-03-28)

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** v2.2 — Phase 53.3 executing (Plan 03 complete: RollComputeAgent + test redirect done)

## Current Position

Phase: 053.3 (roll-detection-agent-data-provider-rename) — EXECUTING
Plan: 4 of 4 complete

### Decisions (Phase 053.3 Plan 04)

- parse_roll_event uses RollEvent.model_validate for typed pydantic validation; old dict-key parsing (event_type/old_symbol/new_symbol) retired per D-02
- feature_writer_agent reads detection_ts (not detected_at) from RollEvent schema payloads — field name changed with typed schema
- signal_generator_agent subscribes to topic_roll_events (market.events.roll); topic_system_events removed per D-01

### Decisions (Phase 053.3 Plan 03)

- is_enabled property removed from RollMonitor — pre-existing test asserts SHADOW-03 graduated (always active)
- Module-level prometheus counters in test fixture prevent duplicate registration across test runs
- TestOnRollConfirmedChain, TestCallSiteBugFix, TestBarLoopWiring skipped (not deleted) to preserve test history traceability
- roll_gap_price/roll_gap_pct = 0.0 intentional — previous contract price unavailable at detection time (Phase 50 refinement)

### Decisions (Phase 053.3 Plan 02)

- DataProviderAgent in services/data_provider_agent.py (ExecStart points directly, not through production/daemons/ wrapper which doesn't exist)
- RollMonitor class deleted entirely from DataProviderAgent — moves to Plan 03 as standalone RollDetectionAgent
- _UNSET sentinel added to __new__ test fixture (CLAUDE.md Service test pattern compliance)

## v2.2 Milestone Goal

Complete the data layer DAG decomposition, automate gap healing, graduate shadow modes with empirical evidence, and expose a clean and stable system externally. Every agent has exactly one job. Zero manual operational steps.

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

- Phase 49.2 inserted after Phase 49: HMM Operational Fixes — observability, fallback logging, warm-up noise (URGENT)
- Phase 48.1 added: Signal Generator Warmup Seed (2026-03-23) — fix bars_processed=0, restore DB seed from startup
- Phase 48 COMPLETE (2026-03-23): Tick aggregation + I7 refactoring — 550+ lines eliminated, 3 shared utilities created, 4 I6 confluence violations fixed, aggregator calibration optimized
- Phase 49.1 inserted after Phase 49: Regime Gate Fix — Write All Signals to Signal Ledger (URGENT)
- Phase 49.1 COMPLETE (2026-03-23): signal_ledger writes decoupled from winner selection; regime_type_at_fire + hmm_regime_at_fire populated on every LedgerEntry; 6 new TDD tests, 57 total passing
- Phase 49.2 COMPLETE (2026-03-23): HMM observability — structlog 2D fallback warning, hmm_n_dims + hmm_warmed_up fields, warm-up prob suppression; 11 new TDD tests, 19 total HMM tests passing

### Decisions (Phase 49.2)

- Warm-up suppression zeroes all 4 hmm_prob_* fields for audit trail consistency when bars_processed < min_lookback
- structlog module-level logger = structlog.get_logger(__name__) in hmm_regime.py for 2D fallback observability
- n_dims stored in _state after _reset_state() so it persists into _build_output() without argument threading

### Decisions (Phase 52.1)

- Used buffer size as PERSISTENCE_CONSUMER_LAG proxy — KafkaConsumerClient has no partition end-offset API
- Tasks for feature_compute_agent.py and parity-auditor-agent.md skipped — files absent in worktree-agent-adfad16f branch (pre-date those file creations on main)

### Decisions (Phase 52.2 Plan 01)

- Named BaseAgent attribute self.logger (not self.log) to match 20+ existing call sites in IndicatorComputeAgent — avoids 700+ line diff in Plan 02
- asyncio.get_running_loop() over deprecated get_event_loop() — Python 3.13 requirement; always valid inside start() which runs in asyncio.run()
- @pytest.mark.asyncio explicit — pytest-asyncio 1.3.0 runs STRICT mode despite asyncio_mode=auto in pytest.ini; matches all other async tests in project
- BaseAgent.start() auto-calls _run() — Plan 02 decides whether IndicatorComputeAgent restructures to super().start() or calls _register_signal_handlers() directly

### Decisions (Phase 52.2 Plan 02)

- IndicatorComputeAgent.start() keeps own implementation (NOT routed through super().start()/_run()) — 60+ line initialization; _register_signal_handlers() called directly; lag_task created/cancelled in finally
- _run() raises NotImplementedError — satisfies @abc.abstractmethod while documenting that start() manages the loop
- MarketAnalysisService tests preserved with @pytest.mark.skip — file consolidated into feature_compute_agent (v2.0); tests document threading.Lock contract
- PERSISTENCE_CONSUMER_LAG set to 0 — consistent with Phase 52.1 llm_writer pattern; no partition end-offset API available

### Decisions (Phase 52.5 Plan 01)

- Certification derived from fetch_clean_cycles query over feature_parity_violations — no state table (D-01/D-09)
- Shadow-only rows: SHADOW_AHEAD_ROWS_TOTAL counter only, never FieldViolation (D-03/D-07)
- 10-minute comparison window (2x COMPARISON_INTERVAL_SECS) — self-adjusting across TFs (D-02)
- SHADOW_PARITY_CERTIFIED published to topic_system_events when all pairs reach CERTIFICATION_THRESHOLD=12 (D-06)
- Metrics port :9120 — 9119 reserved for FeatureSnapshotWriterAgent (D-04/D-08)

### Decisions (Phase 52.4 Plan 01)

- Kept signal_lifecycle_service.py as compatibility shim (one release cycle) — 20+ test imports still resolve without touching external test files
- All SQL centralized in SignalLedgerRepository — added update_chandelier_state, update_chandelier_vol_source, update_shadow_outcome, set_shadow_tracking_start methods
- Repository constructor kept as db_manager: Any (not asyncpg.Pool) — plan's pool interface was aspirational; changing would break signal_generator_agent and other callers
- update_lifecycle_state wraps update_signal_status — canonical agent name while preserving backward-compat internal calls
- indicagent-signal-lifecycle disabled; indicagent-signal-tracker installed on live system (pending main repo merge for ExecStart to resolve)

### Decisions (Phase 52.6 Plan 05)

- Source inspection (AST/text) for IntelligenceComputeAgent tests — avoids services.indicator_service ModuleNotFoundError at import time
- init_tracing in all four __main__ blocks — no-op until Phase 52.7 wires OTEL_EXPORTER_OTLP_ENDPOINT in systemd unit files
- config-before-super pattern applied consistently — metrics_port extracted before super().__init__()
- FeatureWriterAgent._env_name (underscore prefix) differs from other agents' env_name — noted in test setup

### Pending Todos

**31 pending todos** (see `.planning/todos/pending/`)

Recent additions:

- 2026-03-24: Signal quality and pipeline integrity audit (comprehensive — confluence, regime suppression, ML data gaps, performance metrics)
