---
gsd_state_version: 1.0
milestone: v2.1
milestone_name: Data Foundation & Signal Confidence
status: Milestone complete
last_updated: "2026-03-26T23:00:00.000Z"
progress:
  total_phases: 8
  completed_phases: 3
  total_plans: 2
  completed_plans: 4
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-03-22)

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** Phase 52.2 plan 02 in progress (IndicatorComputeAgent rename + BaseAgent inheritance). Next: 52.3 → 52.4 → 52.5 → Phase 53.

## Current Position

Phase: 52.3
Plan: 01

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

## Key Verified Facts (v2.1 Phase 52.2)

- **BaseAgent(abc.ABC)** — `src/core/agent/base.py`; lifecycle: `start/stop/_run/_report_consumer_lag/_register_signal_handlers`; `self.logger` (not `self.log`); `asyncio.get_running_loop()` for SIGTERM/SIGINT
- **AgentRegistry singleton** — `src/core/agent/registry.py`; `register/list_names/get`; singleton via `__new__`; test isolation via `_instance = None` reset
- **IndicatorComputeAgent(BaseAgent)** — first concrete BaseAgent subclass; `_run()` raises `NotImplementedError` (start() manages loop directly); `PERSISTENCE_CONSUMER_LAG` set to 0 (no partition end-offset API)
- **systemd unit** — `services/indicagent-indicator-compute.service`; requires manual `sudo cp` to `/etc/systemd/system/` before activation

## v2.1 Phase Context

**Phase 48:** COMPLETE — Tick aggregation implemented (5s→1m bars via IBKR real-time bar push). I7 refactoring complete — extracted 3 shared utilities (microstructure_utils, state_utils, volume_profile_utils), fixed 4 I6 confluence violations, optimized aggregator calibration batching. 550+ lines of duplicate code eliminated, 83% reduction in calibration interpolation calls, 40-60% per-bar latency reduction.

  - **48.1:** Signal Generator Warmup Seed — fix bars_processed=0 issue by restoring DB seed on startup.
  - **48.2:** I7 Trading Layer Refactoring — code reuse utilities + performance optimizations.

**Phase 49:** CLOSED 2026-03-26 — composite index + threading test done ad-hoc. CIS null repair deferred to v2.3 (todo: 2026-03-26-backfill-cis-null-scores-in-signal-ledger.md). Requirements traceability dropped.

**Phase 50:** Reframed 2026-03-26 — D-21 blocker was imaginary (market_data_5m not needed; 5m data exists in intelligence_features). Phase 50 now DEPENDS ON Phase 53.3 (RollDetectionAgent must be running before graduating flag). Execute after 53.3.

**Phase 51:** CLOSED 2026-03-26 retroactively — all 4 goals delivered in Phase 39 (data_quality_check.py, systemd timer, lifecycle_replay validate(), IC health checks).

**Phase 52:** Infrastructure hardening — Docker restart policies, automated gap-fill, log rotation, deploy scripts.

  - **52.1:** COMPLETE — Wiring fixes; PERSISTENCE_CONSUMER_LAG wired in llm_writer_service; buffer-size proxy pattern established.
  - **52.2:** COMPLETE — BaseAgent abstract class + AgentRegistry singleton; IndicatorService → IndicatorComputeAgent(BaseAgent); 4 broken test imports fixed; systemd unit file created. 15/15 TDD tests pass.

## Accumulated Context

### Roadmap Evolution

- Phase 49.2 inserted after Phase 49: HMM Operational Fixes — observability, fallback logging, warm-up noise (URGENT)
- Phase 48.1 added: Signal Generator Warmup Seed (2026-03-23) — fix bars_processed=0, restore DB seed from startup
- Phase 48 COMPLETE (2026-03-23): Tick aggregation + I7 refactoring — 550+ lines eliminated, 3 shared utilities created, 4 I6 confluence violations fixed, aggregator calibration optimized
- Phase 49.1 inserted after Phase 49: Regime Gate Fix — Write All Signals to Signal Ledger (URGENT)
- Phase 49.1 COMPLETE (2026-03-23): signal_ledger writes decoupled from winner selection; regime_type_at_fire + hmm_regime_at_fire populated on every LedgerEntry; 6 new TDD tests, 57 total passing
- Phase 49.2 COMPLETE (2026-03-23): HMM observability — structlog 2D fallback warning, hmm_n_dims + hmm_warmed_up fields, warm-up prob suppression; 11 new TDD tests, 19 total HMM tests passing
- Phase 52.2 COMPLETE (2026-03-26): BaseAgent + AgentRegistry + IndicatorComputeAgent rename; 15 TDD tests, all passing

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

### Phase 53 — Data Layer DAG (NEW — designed 2026-03-26)

Design doc: `docs/plans/2026-03-26-data-layer-dag-design.md`

5-agent data layer refactor. Sub-phases:
- **53.1:** BarWriterAgent + BarCompletenessAgent (unblocks Phase 52 DB-ignorant refactor; retires gap_fill_service)
- **53.2:** BarAggregatorAgent (extracts BarAccumulator from feature_compute_agent; makes it pure intelligence)
- **53.3:** RollDetectionAgent + DataProviderAgent rename (extracts RollMonitor; typed RollEvent schema; cleans tws_daemon)
- **Phase 50:** Enable ROLL_MONITOR_ENABLED after 53.3 validated

Key invariant: DataProviderAgent owns canonical 1440 1m bar grid (flat bars for empty minutes). BarAggregatorAgent produces canonical HTF from guaranteed 1m. BarCompletenessAgent audits historical gaps only.

Ports: BarAggregatorAgent=:9120, BarWriterAgent=:9121, RollDetectionAgent=:9122, BarCompletenessAgent=:9123

### Pending Todos

**32 pending todos** (see `.planning/todos/pending/`)

Recent additions:
- 2026-03-26: Backfill CIS null scores in signal_ledger (deferred to v2.3)
- 2026-03-24: Signal quality and pipeline integrity audit (comprehensive — confluence, regime suppression, ML data gaps, performance metrics)
