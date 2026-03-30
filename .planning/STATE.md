---
gsd_state_version: 1.0
milestone: v2.2
milestone_name: Operational Excellence
status: In progress
last_updated: "2026-03-30T13:30:00.000Z"
progress:
  total_phases: 13
  completed_phases: 2
  total_plans: 7
  completed_plans: 7
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-03-22)

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** Phase 57.1 — signal-writer-agent-retirement

## Current Position

Phase: 57.1
Plan: 01 Complete (2026-03-30)
Next: Phase 57.1 complete — signal_generator_agent retired, SignalWriterAgent live

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

- Phase 54 added: Provider Abstraction Layer — Broker-Agnostic Data Foundation (2026-03-28)
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

### Decisions (Phase 52.4 Plan 01)

- Kept signal_lifecycle_service.py as compatibility shim (one release cycle) — 20+ test imports still resolve without touching external test files
- All SQL centralized in SignalLedgerRepository — added update_chandelier_state, update_chandelier_vol_source, update_shadow_outcome, set_shadow_tracking_start methods
- Repository constructor kept as db_manager: Any (not asyncpg.Pool) — plan's pool interface was aspirational; changing would break signal_generator_agent and other callers
- update_lifecycle_state wraps update_signal_status — canonical agent name while preserving backward-compat internal calls
- indicagent-signal-lifecycle disabled; indicagent-signal-tracker installed on live system (pending main repo merge for ExecStart to resolve)

### Pending Todos

**31 pending todos** (see `.planning/todos/pending/`)

Recent additions:

- 2026-03-24: Signal quality and pipeline integrity audit (comprehensive — confluence, regime suppression, ML data gaps, performance metrics)

### Decisions (Phase 57.1 Plan 01)

- agent.start() not agent.run() — BaseAgent only exposes start(); design doc had run() which does not exist
- PERSISTENCE_BATCH_LATENCY label is agent_id (not agent) — matched actual metrics.py definition
- setup_service_logging requires full log path 'logs/signal_writer_agent.log' (not bare name)
- BaseAgent.running is read-only property — removed agent.running = True from __new__ test bypass pattern
- 3 test files updated to import from _archived_signal_generator_agent (file preserved for test documentation)
- Signal flow verified: signal_writer_group consumer stable, topic created, pipeline processing backlog

### Decisions (Phase 57 Plan 03)

- WIP skeleton was 90% complete; only ruff UP041/E501 fixes and pre-commit dead import removals needed
- Pre-existing test collection errors (test_signal_ledger.py ImportError, test_gap_fill_service.py ModuleNotFoundError) out of scope per deviation boundary rule
- consumer.subscribe() RuntimeWarning in state restore tests is test-only artifact; harmless in production

### Decisions (Phase 053.2 Plan 02)

- BarAggregatorComputeAgent uses prometheus_client.Counter/Histogram directly (not metrics.py helper) — helper lacks label support needed for `tf` label on htf_bars_produced_total
- Dual-format bar parsing: BarMessage.model_validate() first, flat-dict fallback for DataProviderAgent format
- After=indicagent-data-provider.service in systemd unit — D-18 startup ordering enforced at OS level
- Service enabled but not started — FCA must be simplified in Plan 03 before cutover

### Decisions (Phase 053.2 Plan 03)

- feature_pipeline_service.py shim re-exports FeatureComputeAgent as FeaturePipelineService — 12 existing tests reference old class name; shim avoids touching test files
- Pre-existing ruff E501 at line 705 deferred — out of scope per deviation scope boundary rule; was present in HEAD before these changes

### Decisions (Phase 053.1 Plan 01)

- topic_gap_requests() follows topic_roll_events() pattern — market.events.gap_requests
- BarGapRequest.request_id auto-generates UUID via default_factory — no manual caller overhead
- source field on BarGapRequest defaults to 'bar_auditor' for DLQ traceability
- BarWriterAgent uses asyncpg.create_pool directly — not DatabaseManager — WriterAgent owns its own pool
- source='live_1m' for 1m bars, 'live_htf' for HTF bars — matches D-04 spec
- ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING — idempotent replay-safe writes
- Golden Signals use direct prometheus_client (not metrics.py helper) — label support needed for tf dimension

### Decisions (Phase 54 Plan 01)

- DataProviderAdapter placed alongside (not replacing) DataProvider Protocol — existing IBKRProvider callers unaffected; new adapter is the MergerAgent contract
- ProviderQualityEvent uses field_validator mode=before on all three datetime fields to uniformly reject naive datetimes
- SOURCE_IBKR_GENERIC added to BarMessage.source Literal — IBKRAdapter (Plan 54-02) produces bars with source=SOURCE_IBKR_GENERIC
- topic_market_data_quality distinct from topic_data_quality — former is provider telemetry, latter is pipeline signal quality gating

### Decisions (Phase 54 Plan 02)

- IBKRAdapter._provider wraps IBKRProvider directly — no DI container needed at this scale; swapping broker = new adapter file
- _SESSION_ID_TO_TYPE dict maps Instrument.session_id to SessionType enum at adapter level (futures_24_5→RTH, fx_24_5→FX, crypto_24_7→CRYPTO, nyse→RTH)
- Legacy flat provider_meta fallback in IBKRProvider.qualify_instrument — callers not yet migrated still resolve trading_class correctly
- asyncio.ensure_future for background tasks inside stream_bars generator; cancelled in finally block on generator close
- VXJ6 provider_meta canonical format is now {"ibkr": {"trading_class": "VX"}} — all new instruments must use nested format

### Decisions (Phase 54 Plan 03)

- gap-fill bars publish to topic_market_bars_raw(env, provider) not market.bars — MergerAgent owns routing
- IBKRProviderAgent client_id = ib_client_id + 1 (36) during transition; DataProviderAgent uses base 35
- gap_requests_loop consumer group: {provider_name}_provider_gap_consumer — distinct from DataProviderAgent's data_provider_consumer
- PluginCircuitBreaker not used in reconnect — designed for plugin/workflow protection, not connection backoff; exponential cap at 60s provides equivalent safety

### Decisions (Phase 54 Plan 04)

- provider_merger_consumer group name — idempotent on restart, matches project convention
- _extract_provider_from_topic() uses rsplit('.', 1)[-1] — handles any env prefix depth without hardcoding
- Test helper _make_agent() sets module-level Prometheus label children — avoids duplicate registration on repeated test runs
- Recovery publishes event first, then falls through to route bar normally — primary is authoritative immediately on resume
- latency_ms clamped to 0 with max(0.0, latency_s * 1000) — prevents negative values from clock skew
- Removed After=indicagent-data-provider.service stale dependency from ibkr-provider unit — post-cutover cleanup; service no longer exists
