# Roadmap: IndicAgent

## Milestones

- ✅ **v1.0 MVP** — Phases 0-9 (shipped 2026-02-28)
- ✅ **v1.1 Code Quality Sprint** — Phase 01 (shipped 2026-03-01)
- ✅ **v1.2 Intelligence Palette Expansion** — Phases 02-07 (shipped 2026-03-02)
- ✅ **v1.3 Signal Intelligence Expansion** — Phases 08-11 (shipped 2026-03-04)
- ✅ **v1.4 Quant Foundation** — Phases 12-17 (shipped 2026-03-07)
- ✅ **v1.5 Production Hardening** — Phases 18-22 (shipped 2026-03-10)
- ✅ **v1.6 Signal Quality** — Phases 23-24 (shipped 2026-03-10)
- ✅ **v1.7 Data Integrity** — Phases 25-27 (shipped 2026-03-12)
- ✅ **v1.8 Signal Intelligence** — Phases 28-29 (shipped 2026-03-13)
- ✅ **v1.9 I7 Alpha Engine** — Phases 31-38 (shipped 2026-03-18)
- ✅ **v2.0 Signal Integrity & ML Foundation** — Phases 39-47 (shipped 2026-03-22)
- ✅ **v2.1 Data Foundation & Signal Confidence** — Phases 48-52.8 (shipped 2026-03-28)
- ✅ **v2.2 Operational Excellence** — Phases 53.1–58, 60–63 (shipped 2026-04-08)
- ⏸ **v2.3 ML Foundation** — Phases 55-56, 59, 64 (deferred until 30+ days clean signal data)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 0-9) — SHIPPED 2026-02-28</summary>

- [x] Phase 0: GARCH/Kalman Quality Gates (3/3 plans) — completed 2026-02-22
- [x] Phase 1: Typed Event Schema (3/3 plans) — completed 2026-02-23
- [x] Phase 2: Feature Store (3/3 plans) — completed 2026-02-23
- [x] Phase 3: Historical Data (3/3 plans) — completed 2026-02-24
- [x] Phase 4: Query API (3/3 plans) — completed 2026-02-24
- [x] Phase 5: Live Pipeline (3/3 plans) — completed 2026-02-25
- [x] Phase 6: Dashboard Connected (4/4 plans) — completed 2026-02-28
- [x] Phase 7: Composite Intelligence Score (4/4 plans) — completed 2026-02-28
- [x] Phase 8: Integration Fix & Cleanup (3/3 plans) — completed 2026-02-28
- [x] Phase 9: Milestone Verification (3/3 plans) — completed 2026-02-28

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v1.1 Code Quality Sprint — SHIPPED 2026-03-01</summary>

- [x] Phase 01: Code Quality Sprint (1/1 plan) — ruff 206 → 0, 803 tests, service startup 9.2s → 1-2s

</details>

<details>
<summary>✅ v1.2 Intelligence Palette Expansion (Phases 02-07) — SHIPPED 2026-03-02</summary>

- [x] Phase 02: I2 Composite Events (5 plugins) — completed 2026-02-27
- [x] Phase 03: I5 Chart Patterns (+6 new plugins) — completed 2026-02-27
- [x] Phase 04: I6 SMC Plugins (+5 new SMC plugins) — completed 2026-02-27
- [x] Phase 05: I6 Confluence Refactor (recency weighting + I2 events) — completed 2026-03-02
- [x] Phase 06: I1-I6 Correctness Audit (35 tests) — completed 2026-03-02
- [x] Phase 07: Final Verification & Documentation (965 tests) — completed 2026-03-02

</details>

<details>
<summary>✅ v1.3 Signal Intelligence Expansion (Phases 08-11) — SHIPPED 2026-03-04</summary>

- [x] Phase 08: MomentumAcceleration (I2) — RSI/MACD/ROC 2nd-derivative + inflection detection — completed 2026-03-02
- [x] Phase 09: GapAnalysisSetup (I7) — opening gap fade/continuation for ES/NQ — completed 2026-03-03
- [x] Phase 10: CandlestickPatternSetup (I7) — confluence-gated candlestick setups — completed 2026-03-03
- [x] Phase 11: SessionExtremesSetup (I7) — Asian session H/L fade during London/NY — completed 2026-03-04

Full details: `.planning/milestones/v1.3-phases/`

</details>

<details>
<summary>✅ v1.4 Quant Foundation (Phases 12-17) — SHIPPED 2026-03-07</summary>

- [x] Phase 12: Signal Integrity — regime-aware gating (hmm_regime + prob≥0.60 + duration≥5), shadow signals — completed 2026-03-04
- [x] Phase 13: Data Completeness — i7/i8 JSONB + days_to_expiry in intelligence_features — completed 2026-03-05
- [x] Phase 14: Feedback Loop — setup_performance table + adaptive aggregator perf_multiplier — completed 2026-03-07
- [x] Phase 15: Validated Alpha — validate_alpha.py gate + 4 new alpha sources live — completed 2026-03-07
- [x] Phase 16: LLM Intelligence Layer — llm_calls hypertable + outcome back-fill + adaptive model routing — completed 2026-03-06
- [x] Phase 17: LLM Wiring Fix — signal_id UUID through pipeline + regime vocabulary fix — completed 2026-03-06

Full details: `.planning/milestones/v1.4-ROADMAP.md`

</details>

<details>
<summary>✅ v1.5 Production Hardening (Phases 18-22) — SHIPPED 2026-03-10</summary>

- [x] Phase 18: Financial Math Safety (7/7 plans) — completed 2026-03-08
- [x] Phase 19: Financial Math Characterization (3/3 plans) — completed 2026-03-09
- [x] Phase 20: Circuit Breaker Integration (4/4 plans) — completed 2026-03-09
- [x] Phase 21: Efficiency Optimizations (4/4 plans) — completed 2026-03-09
- [x] Phase 22: I8 Narrative Three-Tier Redesign (7/7 plans) — completed 2026-03-10

Full details: `.planning/milestones/v1.5-ROADMAP.md`

</details>

<details>
<summary>✅ v1.6 Signal Quality (Phases 23-24) — SHIPPED 2026-03-10</summary>

- [x] Phase 23: Signal Generator Gate — condition-vs-event onset detection, flip suppression, cross-bar memory — completed 2026-03-10
- [x] Phase 24: Second-Derivative Acceleration — HMA + 4 I2/I3 plugins + exhaustion wiring — completed 2026-03-10

Full details: `.planning/milestones/v1.6-ROADMAP.md`

</details>

<details>
<summary>✅ v1.7 Data Integrity (Phases 25-27) — SHIPPED 2026-03-12</summary>

**Milestone Goal:** Eliminate the two largest gaps in ML training data quality — NULL CIS fields on backfilled signals, and the 50-min cold-start signal blindness window after service restarts. Also close the signal lifecycle loop so the dashboard reflects signal outcomes in real time.

- [x] **Phase 25: CIS Data Repair** — Fix backfill code to populate CIS fields; audit + repair NULL CIS rows in signal_ledger (completed 2026-03-11)
- [x] **Phase 26: Signal Generator Warmup** — Seed bar_history from intelligence_features on startup; eliminate 50-min warmup wait (completed 2026-03-11)
- [x] **Phase 27: Signal Lifecycle Stream Events** — Publish terminal signal events to Redis stream; SSE snapshot age filter; dashboard resolved state with outcome badge (completed 2026-03-12)

</details>

<details>
<summary>✅ v1.8 Signal Intelligence (Phases 28-29) — SHIPPED 2026-03-13</summary>

**Milestone Goal:** Complete the dashboard intelligence surface and close Renaissance signal quality gaps — constituent contributions, alpha decay, freshness decay, Hurst/entropy gates, and distribution drift detection.

- [x] **Phase 28: Dashboard Completion** — Signal Scorecard panel, drill panel signal history from DB, GARCH/Kalman I4 fields, SMC detail fields, tier tooltips (7/7 plans) — completed 2026-03-12
- [x] **Phase 29: Renaissance Signal Quality** — constituent_contributions, alpha decay, signal freshness decay, volume/killzone CIS gates, Hurst/entropy I4 plugins, KS + CUSUM drift detection (8/8 plans) — completed 2026-03-13

Full details: `.planning/milestones/v1.8-ROADMAP.md`

</details>

<details>
<summary>✅ Phase 30: Redpanda Migration — SHIPPED 2026-03-14</summary>

- [x] **Phase 30: Redpanda Migration** — Replace DragonflyDB with Redpanda across all 8 services; pure transport-layer migration (5/5 plans) — completed 2026-03-14

</details>

<details>
<summary>✅ v1.9 I7 Alpha Engine (Phases 31-38) — SHIPPED 2026-03-18</summary>

- [x] **Phase 31: CIS Learning Loop + Signal Feature Snapshots** - Self-improving CIS with DB weight loading, binary win labels, asset-cluster segmentation, and mid-bar feature snapshots for ML training (completed 2026-03-17)
- [x] **Phase 32: Stop Architecture + Extended Divergence Stack** - Structure-first stop placement centralized in trade_framer.py (all 17 plugins inherit), Chandelier trailing stop, staleness score, and 5-input divergence convergence scoring (completed 2026-03-17)
- [x] **Phase 33: Five New I7 Signal Plugins** - FailedBreakout, ORB, PrevDayLevel, SecondLeg, VCP — covering reversal, session, level-test, and contraction setups (completed 2026-03-17)
- [x] **Phase 34: I4 Infrastructure — Anchored VWAP + Volume Profile** - Two new I4 computation plugins plus two I7 setups consuming them (completed 2026-03-17)
- [x] **Phase 35: Calibration + TOD Multiplier + CIS Kalman Filter** - Isotonic regression confidence calibration, time-of-day win rate multiplier, and Kalman-smoothed CIS score (completed 2026-03-18)
- [x] **Phase 36: Microstructure Plugins** - OFI and CVD as I1 features plus seven new I7 plugins consuming order-flow signals (completed 2026-03-18)
- [x] **Phase 37: Cross-Asset Intelligence Service** - New cross_asset_service microservice, equity spread features, and CrossAssetDivergence I7 plugin (completed 2026-03-18)
- [x] **Phase 38: Automated Futures Roll Detection** - Volume-based roll detection in TWS daemon, DB-backed active contracts, plugin state migration, roll boundary markers (completed 2026-03-18)

Full phase details: `.planning/milestones/v1.9-ROADMAP.md`

</details>

<details>
<summary>✅ v2.0 Signal Integrity & ML Foundation (Phases 39-47) — SHIPPED 2026-03-22</summary>

**Milestone Goal:** Restructure the intelligence pipeline into a clean DAG, fill intelligence gaps (FVG/OB/CTF alignment, confluence, VIX/cross-asset), harden signal integrity with enums and enforcement, graduate shadow modes, and establish the _shadow dict training data infrastructure for v2.3 ML work.

- [x] **Phase 39: Data Quality + DB Health (Expanded)** — CIS null repair, ohlcv chunk compress, signal_ledger generated columns, CHECK constraints, signal_performance_segmented, IC computation, data quality monitoring (completed 2026-03-19)
- [x] **Phase 39.1: Intelligence Layer Enforcement (INSERTED)** — regime_type Protocol enforcement, SignalStatus + SignalOutcome enums, pre-commit hooks, VWAP/ShannonEntropy bug fixes, SQL hardening, topic namespace cleanup (completed 2026-03-19)
- [x] **Phase 40: DAG Refactor — Clean Foundation** — signal_generator decomposed into 6 DAG microservices, 8 Redpanda topics, systemd units, E2E pipeline integration test (completed 2026-03-19)
- [x] **Phase 41: Intelligence Gap Fill** — i6 FVG/OB alignment from real data, POC/VAH/VAL as T1/T2 targets, multi-TF S/R context; VWAP/session TF guards, aggregator active-from-all-ranked assertion (completed 2026-03-20)
- [x] **Phase 42: Candlestick Pattern Expansion** — 18 new I5 patterns + CandlestickPatternSetup confidence tier weights (completed 2026-03-20)
- [x] **Phase 43: Performance & Stability Emergency** — market_data_ohlcv rebuilt (15,740→21 chunks), feature_writer i7/i8 buffering, asyncio.to_thread plugin execution, lifecycle O(1) active-signal index, ndarray calibration pre-alloc, _run_refresh_loop helper, 328K stale signals expired (executed 2026-03-20; threading.Lock test gap closed in Phase 49)
- [x] **Phase 44: I7 DAG Refactor** — ~458 LOC duplication extracted into shared utilities, validate_tier() enforcement, cross_timeframe decomposed, make_signal() factory + validate_signal() enforcement (completed 2026-03-21)
- [x] **Phase 44.1: Feature Pipeline Renaissance Refactor** — unified FeaturePipelineService replaces 3 services; 3 Kafka hops → 1; pipeline_latency_ms < 50ms p99 (completed 2026-03-22)
- [x] **Phase 44.2: SignalGeneratorService Consolidation** — 6 pipeline stage microservices absorbed in-process; 8 Kafka hops → 2; 6 systemd units retired (completed 2026-03-22)
- [x] **Phase 44.3: Atomic Persistence + OHLCV Unification** — single atomic INSERT per bar; DB migration for 10 new columns; FeaturePipelineService sole live OHLCV writer; 18 services → 9 (completed 2026-03-22)
- [x] **Phase 45: I6 → I7 Confluence Wiring + Exhaustion Standardization** — ctf_fvg_alignment + ctf_ob_alignment exposed; capture_confluence_features() + ConfluenceWeightProfile; all 36 I7 plugins capture _shadow dict; lifecycle O(1) index + chandelier write guard (completed 2026-03-22)
- [x] **Phase 46: I6 Confluence Expansion** — 4 new raw measurement fields (ctf_vix_level, ctf_vix_z, ctf_eq_spread_z, ctf_eq_pairs_confirming); vix_context.py pure function module (completed 2026-03-22)
- [x] **Phase 46.1: VIX + Cross-Asset to I4** — VIXRegimePlugin + CrossAssetContextPlugin promoted to I4; I4Context +4 fields / I6Confluence -4 fields; VIX injection fix (completed 2026-03-22)
- [x] **Phase 47: Shadow Mode Graduation** — CROSS_ASSET_ENABLED flag removed (unconditionally active); ROLL_MONITOR_ENABLED kept false pending D-21 re-validation; trad_DualDivergence promotion deferred (completed 2026-03-22)

</details>

<details>
<summary>✅ v2.1 Data Foundation & Signal Confidence (Phases 48-52.8) — SHIPPED 2026-03-28</summary>

**Milestone Goal:** Earn the right to trust the numbers. Fix the live data foundation (tick aggregation), close DB performance gaps, validate every intelligence layer independently, graduate shadow modes with real evidence, and harden infrastructure so nothing requires manual intervention.

- [x] **Phase 48: Tick Aggregation & I7 Quality** — verify tick aggregation (5s→1m bars, eliminate bars_processed freeze); I7 refactoring: extract 3 shared utilities (550+ line savings), fix I6 confluence violations in 4 SMC/FVG plugins, optimize aggregator calibration batching (completed 2026-03-23)
- [x] **Phase 49: DB Performance & Signal Ledger Hardening** — composite index `idx_ledger_feature_join` done; threading.Lock characterization test done; CIS backfill deferred to v2.3 (todo: `2026-03-26-backfill-cis-null-scores-in-signal-ledger.md`) — COMPLETE 2026-03-26
- [x] **Phase 49.1: Regime Gate Fix** — signal_ledger writes decoupled from winner selection; ALL signals written unconditionally; regime_type_at_fire + hmm_regime_at_fire populated — COMPLETE 2026-03-23
- [x] **Phase 49.2: HMM Operational Fixes** — structlog 2D fallback observability; hmm_n_dims + hmm_warmed_up persisted to intelligence_features; warm-up prob suppression — COMPLETE 2026-03-23
- [x] **Phase 51: Signal & Indicator Validation Framework** — per-layer sanity checks (I1→I7 output values statistically sensible); signal outcome completeness audit; automated validation on each deploy — COMPLETE
- [x] **Phase 52: Infrastructure Hardening** — Docker restart policies, log rotation, deploy scripts delivered incrementally via 52.x subphases; gap-fill automation → Phase 53.1 (v2.2) — ABSORBED
- [x] **Phase 52.1: Wiring Fixes + Doc Naming** — fixed `topic_feature_processed` ImportError; fixed naive `datetime.now()` calls; wired `persistence_batch_latency`/`persistence_consumer_lag` metrics — COMPLETE
- [x] **Phase 52.2: BaseAgent Infrastructure + IndicatorComputeAgent Rename** — TDD BaseAgent + AgentRegistry; renamed IndicatorService → IndicatorComputeAgent; fixed 4 broken tests; systemd unit — COMPLETE
- [x] **Phase 52.3: Dual-Write Shadow Writer** — migration `051_feature_snapshots_shadow.sql`; `FeatureSnapshotWriterAgent` consuming `intelligence.journal` into shadow table; independent consumer group — COMPLETE 2026-03-27
- [x] **Phase 52.4: SignalTrackerAgent Refactor** — renamed `SignalLifecycleService` → `SignalTrackerAgent`; extracted `SignalLedgerRepository`; inherited `BaseAgent`; retired `indicagent-signal-lifecycle.service` — COMPLETE
- [x] **Phase 52.5: Parity Auditor Agent** — `ParityAuditorAgent` 5-min timer; `FieldViolation` schema; `SHADOW_PARITY_CERTIFIED` gate (60 consecutive clean cycles); autonomous cutover evidence — COMPLETE 2026-03-28
- [x] **Phase 52.6: BaseAgent + ProcessManifest Enhancement** — BaseAgent enhanced lifecycle contract (_setup/_teardown, tracer, topics, running); ProcessManifest replaces singleton AgentRegistry; all 4 pipeline agents migrated; `init_tracing()` wired — COMPLETE 2026-03-28
- [x] **Phase 52.7: Grafana Tempo Infrastructure** — Tempo Docker service; OTLP HTTP :4318; Grafana datasource provisioned; `OTEL_EXPORTER_OTLP_ENDPOINT` in 5 agent systemd units; `PYTHONUNBUFFERED=1` completed across all 10 units — COMPLETE 2026-03-28
- [x] **Phase 52.8: Kafka Trace Propagation** — W3C `traceparent` inject/extract in `KafkaProducerClient`/`KafkaConsumerClient`; `_KafkaHeadersCarrier` OTel adapter; end-to-end bar journey traces visible in Grafana Tempo — COMPLETE 2026-03-28

Full details: `.planning/milestones/v2.1-ROADMAP.md`

</details>

<details>
<summary>✅ v2.2 Operational Excellence (Phases 53.1–58, 60–63) — SHIPPED 2026-04-08</summary>

**Milestone Goal:** Complete the data layer DAG decomposition, automate gap healing, graduate shadow modes with empirical evidence, and expose a clean and stable system externally. Every agent has exactly one job. Zero manual operational steps.

**Execution order** (dependency-driven, reverse numeric — DAG built dependency-first):

- [x] **Phase 53.3: RollComputeAgent + DataProviderAgent Rename** ✅ Complete 2026-03-28 — `RollComputeAgent` standalone on `topic_roll_events()`; `tws_daemon` → `DataProviderAgent`; port :9122
  - [x] 053.3-01-PLAN.md — RollEvent schema + topic_roll_events stream key
  - [x] 053.3-02-PLAN.md — DataProviderAgent rename + roll removal
  - [x] 053.3-03-PLAN.md — RollComputeAgent implementation + test redirect
  - [x] 053.3-04-PLAN.md — signal_generator_agent consumer migration + cleanup
- [x] **Phase 53.2: BarAggregatorComputeAgent** ✅ Complete 2026-03-28 — `BarAccumulator` extracted into standalone `BarAggregatorComputeAgent`; `FeatureComputeAgent` now pure intelligence consumer; port :9120
  - [x] 053.2-01-PLAN.md — is_flat_bar schema + BarAccumulator propagation + DataProviderAgent emission
  - [x] 053.2-02-PLAN.md — BarAggregatorComputeAgent implementation + systemd unit
  - [x] 053.2-03-PLAN.md — FCA simplification (remove BarAccumulator, add HTF subscription) + CLAUDE.md update
- [x] **Phase 53.1: BarWriterAgent + BarAuditorAgent** ✅ Complete 2026-03-28 — `BarWriterAgent` decouples OHLCV persistence from compute path; `BarAuditorAgent` self-healing gap-fill loop; retires `gap_fill_service`; ports :9121/:9123
  - [x] 053.1-01-PLAN.md — Shared schemas (topic_gap_requests, BarGapRequest) + BarWriterAgent implementation + tests
  - [x] 053.1-02-PLAN.md — BarAuditorAgent + DataProviderAgent gap-requests loop + tests
  - [x] 053.1-03-PLAN.md — FCA cleanup (remove _ohlcv_buffer) + systemd units + gap_fill_service retirement + CLAUDE.md
- [x] **Phase 50: Roll Monitor + DualDivergence Graduation** ✅ Infrastructure Complete 2026-04-08 — market_data_5m view, FeatureWriterAgent→topic_roll_events, trad_DualDivergence shadow verified; graduation deferred to Phase 63
  - [x] 50-PLAN.md — Infrastructure built (8/8 tasks executed 2026-04-02)
  - [x] market_data_5m view created
  - [x] FeatureWriterAgent wired to topic_roll_events
  - [x] Roll premium computation verified (0.0 = gap unknown)
  - [x] trad_DualDivergence shadow confirmed (IS_SHADOW=True)
  - ⏸ D-21 validation blocked by schema mismatch → fix in Phase 63
  - ⏸ RollComputeAgent graduation → handled by Phase 63
  - ⏸ trad_DualDivergence promotion → handled in Phase 63-06 (IS_SHADOW=False, no stat gate needed — no real prod)
- [x] **Phase 54: Provider Abstraction Layer — Broker-Agnostic Data Foundation** ✅ Complete 2026-03-28 — `BaseProviderAgent` + adapter pattern; `IBKRAdapter` wraps `IBKRProvider`; `ProviderMergerAgent` canonical author of `market.bars`; ports :9129/:9130
- [x] **Phase 57: IntelligencePipelineComputeAgent — Unified I1-I7 Pipeline** ✅ Complete 2026-03-29 — `IntelligencePipelineComputeAgent` merges I1-I7 into single in-process pipeline; Kafka/DB are output sinks only; state checkpointing to compacted topic; `pre_quality_confidence`/`pre_calibration_confidence` on `signal_ledger`; port :9125
  Design doc: `docs/plans/archive/2026-03-29-intelligence-agent-unified-pipeline-design.md`
  - [x] 57-01-PLAN.md — Kafka infrastructure, signal_ledger migration, systemd unit scaffolding
  - [x] 57-02-PLAN.md — I1-I6 in-process pipeline, state checkpointing, BarHistorySeeder warmup
  - [x] 57-03-PLAN.md — I7 integration, confidence attribution, output queue, async drain
- [x] **Phase 57.1: SignalWriterAgent — signal_generator_agent Retirement** — New `intelligence.i7.signals` topic; thin `SignalWriterAgent` (WriterAgent) consumes all ranked I7 signals → `signal_ledger`; fix winner publish to `topic_signals_aggregated`; retire `signal_generator_agent`
  Design doc: `docs/superpowers/plans/2026-03-30-signal-writer-agent.md`
  - [x] 057.1-01-PLAN.md — stream key, pipeline publish fix, SignalWriterAgent, tests, systemd, retirement

</details>

<details>
<summary>⏸ v2.3 ML Foundation (Phases 55-56, 66) — DEFERRED, requires 30+ days clean signal data from v2.1</summary>

**Milestone Goal:** A statistically validated ML scoring layer trained on clean signal_ledger outcomes, with Renaissance-grade observability (attribution, A/B testing, causal inference) proving each pipeline stage earns its compute cost.

- [ ] **Phase 55: ML Scoring Model** — LightGBM feature builder with stationarity gates, global + regime-specific models, walk-forward retraining, shadow ml_score, blend promotion (α=0.20 after 8-week shadow gate), SHAP attribution
- [ ] **Phase 56: Swarm Foundation** — Shared LLM layer (`src/core/llm/`), corrected DAG protocols (`IAlphaContributor`, `SwarmContext`), narrative module extraction (1,327→200 lines), `SwarmOrchestratorAgent` + `SwarmWriterAgent`, `alpha_multiplier_shadow` hypertable — 7 plans, shadow-only, 49 TDD tests
  Design doc: `docs/plans/2026-04-09-phase-56-swarm-foundation-design.md`
- [ ] **Phase 66: SkepticAgent** — First swarm agent on Phase 56 infrastructure. `IAlphaContributor`: "what's wrong with this signal?" Tracks predictions to `alpha_multiplier_shadow`, validates p < 0.05 n ≥ 30 before next agent.

</details>

## Phase Details

<details>
<summary>✅ v2.0 Phase Details (Phases 39-47) — ARCHIVED 2026-03-22</summary>

**Full phase details for v2.0 have been archived to:** `.planning/milestones/v2.0-PHASE-DETAILS.md`

This includes complete documentation for:
- Phase 39: Data Quality + DB Health
- Phase 39.1: Intelligence Layer Enforcement
- Phase 40: DAG Refactor — Clean Foundation
- Phase 41: Intelligence Gap Fill
- Phase 42: Candlestick Pattern Expansion
- Phase 43: Performance & Stability Emergency
- Phase 44: I7 DAG Refactor
- Phase 44.1: Feature Pipeline Renaissance Refactor
- Phase 44.2: SignalGeneratorService Consolidation
- Phase 44.3: Atomic Persistence + OHLCV Unification
- Phase 45: I6 → I7 Confluence Wiring + Exhaustion Standardization
- Phase 46: I6 Confluence Expansion
- Phase 46.1: VIX + Cross-Asset to I4
- Phase 47: Shadow Mode Graduation

Refer to the archived file for detailed success criteria, requirements, and plan breakdowns.

</details>

<details open>
<summary>🚧 v2.1 Phase Details (Phases 48-52) — IN PROGRESS</summary>

### Phase 48: Tick Aggregation & I7 Quality ✅ COMPLETE

**Goal**: Verify and complete tick aggregation feature (5s real-time bars → 1m OHLCV), then refactor I7 trading layer for code reuse and efficiency.

**Status**: ✅ Complete (2026-03-23) — Tick aggregation operational, I7 refactoring delivered (550+ lines saved, 3 shared utilities, 4 I6 violations fixed, aggregator optimized)

**Depends on**: v2.0 completion (FeaturePipelineService unification, BarMessage schema)

**Requirements**: TICK-01 ✅, I7-REF-01 ✅, I7-REF-02 ✅, I7-REF-03 ✅

**Success Criteria** (all met):
  1. ✅ TWS daemon publishes 5s real-time bars from IBKR; bars aggregate to 1m OHLCV; no `bars_processed` freeze bug
  2. ✅ After-hours data flows correctly; 1m bars match IBKR official bars (within drift tolerance)
  3. ✅ Dashboard live pricing updates via `market.ticks` topic
  4. ✅ Microstructure spike detector extracted to shared utility (`microstructure_utils.py`) — 153 LOC saved
  5. ✅ I6 confluence violations fixed in 4 SMC/FVG plugins — all capture `ctf_fvg_alignment` / `ctf_ob_alignment`
  6. ✅ Aggregator calibration batching optimized — 83% reduction in np.interp() calls (36 → 6 per bar)

**Plans**: 2 plans completed (48.1: warmup seed, 48.2: I7 refactoring)

### Phase 49: DB Performance & Signal Ledger Hardening

**Goal**: Optimize database performance, complete CIS null repair, close test gaps, and fix requirements traceability.

**Status**: ✅ Complete (ad-hoc, 2026-03-26)

**Depends on**: Phase 48 completion

**Outcome**:
  1. ✅ `idx_ledger_feature_join` composite index exists on `signal_ledger`
  2. ⏸ CIS null repair deferred to v2.3 — todo `2026-03-26-backfill-cis-null-scores-in-signal-ledger.md`
  3. ✅ `tests/unit/service_tests/test_concurrent_lock_behavior.py` exists and passes
  4. 🗑 Requirements traceability dropped — housekeeping, no downstream impact

### Phase 49.2: HMM Operational Fixes — observability, fallback logging, warm-up noise (INSERTED)

**Goal:** Make HMM regime gating observable and self-correcting — log 2D fallback, persist hmm_n_dims and hmm_warmed_up to intelligence_features JSONB, suppress warm-up noise via prob zeroing.
**Requirements**: [HMM-01, HMM-02, HMM-03, HMM-04]
**Depends on:** Phase 49
**Plans:** 1 plan

Plans:
- [x] 49.2-01-PLAN.md — TDD: HMM observability + warm-up suppression (schema, plugin, tests)










### Phase 49.1: Regime Gate Fix — Write All Signals to Signal Ledger (INSERTED)

**Goal:** Decouple signal_ledger writes from winner selection — write ALL ranked signals unconditionally. Populate regime_type_at_fire and hmm_regime_at_fire for ML training segmentation.
**Requirements**: [SHADOW-01, DATA-11]
**Depends on:** Phase 49
**Plans:** 1 plan

Plans:
- [x] 49.1-01-PLAN.md — TDD: regime gate fix + regime label population (2 tasks)

### Phase 50: Roll Monitor & DualDivergence Graduation

**Goal**: Graduate roll monitor and trad_DualDivergence from shadow mode after empirical validation.

**Status**: 🚧 Ready to Execute

**Depends on**: Phase 49 ✅ (market_data_5m exists), Phase 53.3 ✅ (RollComputeAgent validated)

**Requirements**: SHADOW-03, INTEL-04, SHADOW-04

**Success Criteria** (what must be TRUE):
  1. D-21 validation confirms roll detection works correctly with 5m backfilled data (≥90% detection, ≤10% FP)
  2. Migration `049_roll_premium_pct.sql` applied; `roll_premium_pct` populated in intelligence_features
  3. `ROLL_MONITOR_ENABLED=true` set in production environment
  4. trad_DualDivergence promoted (IS_SHADOW=False) after D-07 gate passes (N≥100, 95% CI E[PnL_R] > 0)

**Plans**: 4 plans (50.1: D-21 validation, 50.2: migration, 50.3: enable flag, 50.4: DualDivergence gate)

### Phase 51: Signal & Indicator Validation Framework

**Goal**: Establish automated validation to ensure data quality across all intelligence layers.

**Status**: ✅ Complete (absorbed into v2.1) — per-layer sanity scaffolding delivered via Phase 52.x subphases. Remaining items (VAL-01 full sweep, automated pre-deploy gate) deferred to Phase 51 standalone if prioritized in v2.3.

**Depends on**: None (can run in parallel with Phases 49-50)

### Phase 52: Infrastructure Hardening

**Goal**: Eliminate manual intervention — Docker restart policies, log rotation, deploy scripts, health checks.

**Status**: ✅ Complete (absorbed into v2.1 via 52.1–52.8 subphases) — Docker restart policies, log rotation, systemd hardening, OTEL, trace propagation all shipped.

**Note**: Automated gap-fill moved to Phase 53.1 (BarAuditorAgent). Remaining undelivered items (deploy_dashboard.sh, /health endpoints) carry to v2.2 if needed.

</details>
## Backlog

Items decided but not yet scheduled. Pull into a milestone when ready.
Re-prioritized 2026-03-19 after v2.0 roadmap defined.

### Tier 1 — v2.3 candidates (ML Foundation)

| Item | Notes | Analysis |
|------|-------|---------|
| **Intelligence Swarm** | 9 autonomous agents (Regime Sentinel, Volatility Arbiter, SMC Validator, Liquidity Decay, Correlation Contagion, Macro Event Observer, Execution Quality, SkepticAgent) providing alpha multipliers; shadow-first validation; `AlphaMultiplier` schema; hook into signal_lifecycle_service. Requires PydanticAI safety wrapper + 14-day correlation analysis infra. | `docs/ideas/intelligence-swarm-manifest.md` |
| **Phase 55: ML Scoring Model** | Deferred from v2.0 — requires 30+ days of clean signal_ledger outcomes from v2.1 + roll monitor graduated + market_data_5m populated. Feature builder, stationarity gates, global + regime-specific LightGBM, walk-forward retraining, shadow ml_score, blend promotion, SHAP attribution. `_shadow` dict already captured in all I7 plugins (Phase 45). | Phase Detail: see `### Phase 55` in Phase Details section |
| **Phase 66: SkepticAgent** | First swarm agent built on Phase 56 infrastructure. `IAlphaContributor` that asks "what's wrong with this signal?" — predicts failure probability via LLM. Tracks predictions to `alpha_multiplier_shadow`. Gate: p < 0.05, n ≥ 30 before building next agent. | `docs/ideas/intelligence-swarm-manifest.md` |
| **Renaissance Observability** | Deferred from v2.0 — depends on Phase 55 (ML provides causal analysis features). Performance attribution per DAG stage, A/B test framework, causal inference, counterfactual analysis, LLM gate optimizer; intelligence tier audit surface, staleness as first-class quality signal. | `docs/ideas/renaissance-gap-analysis.md` |
| VWAP/Session plugin TF guards | Research: VWAP and session plugins may fire on TFs where they're not meaningful (e.g. 1d). Add guards. | `.planning/todos/pending/2026-03-10-research-vwap-and-session-plugin-timeframe-guards.md` |
| LLM Call Tracking | Real token counts (Ollama eval counts), error details, cis_score/zone fields, retry chain visibility. | `.planning/todos/pending/2026-03-07-improve-llm-call-tracking.md` |
| BSL/SSL level clusters | Schema change: list of levels vs single nearest level. More useful for signal proximity scoring. | `.planning/todos/pending/2026-02-27-support-bsl-ssl-level-clusters-not-just-single-levels.md` |

### Tier 2 — Longer horizon

| Item | Notes | Analysis |
|------|-------|---------|
| Intelligence Confluence Patterns | Unsupervised discovery: enumerate concurrent I5/I6/I7 signals, track confluence signatures, surface statistically significant patterns for human labeling, feed back to I7 setups. Needs 30 days baseline data. Schema: `confluence_patterns` table + ConfluenceExplorationPlugin + writer service. | `docs/ideas/intelligence-confluence-patterns.md` |
| Latency & Persistence Audit | Hot/cold path decoupling: Fire-and-Forget Kafka in hot path, PersistenceCoordinator async batch in cold path, zero-copy headers for provenance. Blocked on Phase 52 completion. | `docs/ideas/latency-and-persistence-audit-design.md` |
| Intelligence Stack Latency | Parallel plugin workers within tiers (2-7× speedup potential). Thread-safety audit required. | `docs/ideas/intelligence-stack-latency-reduction.md` |
| API keyset pagination | Large features export endpoint has no pagination — blocks on full table scan. | `.planning/todos/pending/2026-02-24-add-keyset-pagination-to-features-export-and-rest-endpoint.md` |
| Regime-adaptive plugin parameters | I1/I4 parameter values adapt to hmm_regime (e.g. shorter RSI period in trending regime). | — |
| Plugin pipeline thread pool | CPU-bound plugin work starves event loop under load. Thread-safety audit required first. | `.planning/todos/pending/2026-02-28-offload-plugin-pipeline-to-thread-pool.md` |
| Expand 2nd-derivative indicators | Volume accel, vol accel, structural accel (beyond v1.6 ExhaustionScore/AccelerationRegime). Research-first gate. | `docs/ideas/2nd-derivative-indicator-research.md` |
| ML Mixture-of-Experts | Soft blending across regime-specific models (once hard routing proves stable). | — |
| Online learning | Incremental model updates between weekly retraining cycles. | — |

### Tier 3 — Separate products / long horizon

| Item | Notes | Analysis |
|------|-------|---------|
| Granular Stream Topology | Publish each intelligence tier (I2, I4, I5, I6) to separate topics. Build only when a real consumer materializes (MLAgent feature pipeline, AegisAgent risk service, QualAgent). | `docs/ideas/granular-stream-topology.md` |
| Orderflow Integration | reqTickByTickData; buy/sell delta metrics; delta divergence / absorption / imbalance continuation plugins. | — |
| Portfolio Management | Correlation matrix; sector exposure limits; symbol rotation. | — |
| Trade Journal Auto-Documentation | LLM daily summaries from signal_ledger — learning opportunities from losing trades, performance by setup/regime/TF. | — |
| Robinhood-Style Scaling | Consumer Proxy pattern; Changelog Streams for state recovery. | `analysis/2026-02-12-robinhood-scaling-patterns.md` |
| Broker-agnostic instrument provider | Defer until second broker integration is needed. | — |

## Progress

**Execution Order:**
Phases execute in numeric order. v1.0–v1.9 complete (Phases 0-38 shipped). v2.0 complete (Phases 39-47 shipped 2026-03-22). v2.1 complete (Phases 48-52.8 shipped 2026-03-28). v2.2 complete (Phases 53.1–63 shipped 2026-04-08). v2.3 deferred (Phases 55-56, awaiting 30+ days clean signal data).

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 0. GARCH/Kalman Quality Gates | v1.0 | 3/3 | Complete | 2026-02-22 |
| 1. Typed Event Schema | v1.0 | 3/3 | Complete | 2026-02-23 |
| 2. Feature Store | v1.0 | 3/3 | Complete | 2026-02-23 |
| 3. Historical Data | v1.0 | 3/3 | Complete | 2026-02-24 |
| 4. Query API | v1.0 | 3/3 | Complete | 2026-02-24 |
| 5. Live Pipeline | v1.0 | 3/3 | Complete | 2026-02-25 |
| 6. Dashboard Connected | v1.0 | 4/4 | Complete | 2026-02-28 |
| 7. Composite Intelligence Score | v1.0 | 4/4 | Complete | 2026-02-28 |
| 8. Integration Fix & Cleanup | v1.0 | 3/3 | Complete | 2026-02-28 |
| 9. Milestone Verification | v1.0 | 3/3 | Complete | 2026-02-28 |
| 01. Code Quality Sprint | v1.1 | 1/1 | Complete | 2026-03-01 |
| 02. I2 Composite Events | v1.2 | — | Complete | 2026-02-27 |
| 03. I5 Chart Patterns | v1.2 | — | Complete | 2026-02-27 |
| 04. I6 SMC Plugins | v1.2 | — | Complete | 2026-02-27 |
| 05. I6 Confluence Refactor | v1.2 | — | Complete | 2026-03-02 |
| 06. I1-I6 Correctness Audit | v1.2 | — | Complete | 2026-03-02 |
| 07. Final Verification | v1.2 | — | Complete | 2026-03-02 |
| 08. MomentumAcceleration | v1.3 | — | Complete | 2026-03-02 |
| 09. GapAnalysisSetup | v1.3 | 2/2 | Complete | 2026-03-03 |
| 10. CandlestickPatternSetup | v1.3 | 2/2 | Complete | 2026-03-03 |
| 11. SessionExtremesSetup | v1.3 | — | Complete | 2026-03-04 |
| 12. Signal Integrity | v1.4 | 4/4 | Complete | 2026-03-04 |
| 13. Data Completeness | v1.4 | 4/4 | Complete | 2026-03-05 |
| 14. Feedback Loop | v1.4 | 5/5 | Complete | 2026-03-07 |
| 15. Validated Alpha | v1.4 | 7/7 | Complete | 2026-03-07 |
| 16. LLM Intelligence Layer | v1.4 | 7/7 | Complete | 2026-03-06 |
| 17. LLM Wiring Fix | v1.4 | 2/2 | Complete | 2026-03-06 |
| 18. Financial Math Safety | v1.5 | 7/7 | Complete | 2026-03-08 |
| 19. Financial Math Characterization | v1.5 | 3/3 | Complete | 2026-03-09 |
| 20. Circuit Breaker Integration | v1.5 | 4/4 | Complete | 2026-03-09 |
| 21. Efficiency Optimizations | v1.5 | 4/4 | Complete | 2026-03-09 |
| 22. I8 Narrative Three-Tier Redesign | v1.5 | 7/7 | Complete | 2026-03-10 |
| 23. Signal Generator Gate | v1.6 | 3/3 | Complete | 2026-03-10 |
| 24. Second-Derivative Acceleration | v1.6 | 7/7 | Complete | 2026-03-10 |
| 25. CIS Data Repair | v1.7 | 2/2 | Complete | 2026-03-11 |
| 26. Signal Generator Warmup | v1.7 | 1/1 | Complete | 2026-03-11 |
| 27. Signal Lifecycle Stream Events | v1.7 | 10/10 | Complete | 2026-03-12 |
| 28. Dashboard Completion | v1.8 | 7/7 | Complete | 2026-03-12 |
| 29. Renaissance Signal Quality | v1.8 | 8/8 | Complete | 2026-03-13 |
| 30. Redpanda Migration | v1.8 | 5/5 | Complete | 2026-03-14 |
| 31. CIS Learning Loop + Signal Feature Snapshots | v1.9 | 3/3 | Complete | 2026-03-17 |
| 32. Stop Architecture + Extended Divergence Stack | v1.9 | 3/3 | Complete | 2026-03-17 |
| 33. Five New I7 Signal Plugins | v1.9 | 3/3 | Complete | 2026-03-17 |
| 34. I4 Infrastructure — Anchored VWAP + Volume Profile | v1.9 | 3/3 | Complete | 2026-03-17 |
| 35. Calibration + TOD Multiplier + CIS Kalman Filter | v1.9 | 3/3 | Complete | 2026-03-18 |
| 36. Microstructure Plugins | v1.9 | 2/2 | Complete | 2026-03-18 |
| 37. Cross-Asset Intelligence Service | v1.9 | 3/3 | Complete | 2026-03-18 |
| 38. Automated Futures Roll Detection | v1.9 | 3/3 | Complete | 2026-03-18 |
| 39. Data Quality + DB Health | v2.0 | 6/6 | Complete | 2026-03-19 |
| 39.1. Intelligence Layer Enforcement | v2.0 | 6/6 | Complete | 2026-03-19 |
| 40. DAG Refactor — Clean Foundation | v2.0 | 4/4 | Complete | 2026-03-19 |
| 41. Intelligence Gap Fill | v2.0 | 3/3 | Complete | 2026-03-20 |
| 42. Candlestick Pattern Expansion | v2.0 | 5/5 | Complete | 2026-03-20 |
| 43. Performance & Stability Emergency | v2.0 | 2/3 | In Progress | — |
| 44. I7 DAG Refactor | v2.0 | 5/5 | Complete   | 2026-03-22 |
| 45. I6 → I7 Confluence Wiring | v2.0 | 4/4 | Complete    | 2026-03-22 |
| 46. I6 Confluence Expansion | v2.0 | 4/4 | Complete   | 2026-03-22 |
| 47. Shadow Mode Graduation | v2.0 | 4/4 | Complete   | 2026-03-22 |
| 48. Tick Aggregation & I7 Quality | v2.1 | 2/2 | Complete   | 2026-03-23 |
| 49. DB Performance | v2.1 | 0/TBD | Complete    | 2026-03-28 |
| 49.1. Regime Gate Fix — write all signals to signal_ledger | v2.1 | 1/1 | Complete | 2026-03-23 |
| 49.2. HMM Operational Fixes — observability, fallback logging, warm-up noise | v2.1 | 1/1 | Complete    | 2026-03-23 |
| 50. Roll Monitor Graduation | v2.2 | 1/1 | Complete | 2026-04-08 |
| 51. Signal Validation Framework | v2.1 | 0/TBD | Complete (absorbed) | 2026-03-28 |
| 52. Infrastructure Hardening | v2.1 | 8/8 | Complete (absorbed) | 2026-03-28 |
| 53.3. RollComputeAgent + DataProviderAgent Rename | v2.2 | 4/4 | Complete | 2026-03-28 |
| 53.2. BarAggregatorComputeAgent | v2.2 | 3/3 | Complete | 2026-03-28 |
| 53.1. BarWriterAgent + BarAuditorAgent | v2.2 | 3/3 | Complete | 2026-03-28 |
| 54. Provider Abstraction Layer | v2.2 | 4/4 | Complete | 2026-03-28 |
| 57. IntelligencePipelineComputeAgent | v2.2 | 3/3 | Complete    | 2026-03-29 |
| 57.1. SignalWriterAgent — signal_generator_agent Retirement | v2.2 | 1/1 | Complete | 2026-03-30 |
| 58. Pipeline Parallelization Renaissance | v2.2 | 3/3 | Complete | 2026-03-28 |
| 59. OFI Divergence Redesign | v2.3 | 0/1 | Planned | — |
| 60. Signal Metrics Redesign | v2.2 | 3/3 | Complete | 2026-04-05 |
| 61. Signal Auditor & CIS Contract Enforcement | v2.2 | 1/1 | Complete | 2026-04-06 |
| 62. Service Watchdog + SSE Cleanup | v2.2 | 1/1 | Complete | 2026-04-07 |
| 63. Contract Lifecycle Automation | v2.2 | 5/5 | Complete | 2026-04-08 |

### Phase 52.5: Parity Auditor Agent

**Goal:** Build `ParityAuditorAgent` — a timer-based (5 min) comparison engine that validates `feature_snapshots_shadow` against `intelligence_features` per (symbol, tf), stores field-level violations in `feature_parity_violations`, emits `parity_match_rate` Prometheus metrics, and self-certifies parity after `CERTIFICATION_THRESHOLD` consecutive clean cycles by publishing `SHADOW_PARITY_CERTIFIED` to the system events topic.
**Requirements**: [PARITY-01, PARITY-02, PARITY-03, PARITY-04, PARITY-05]
**Depends on:** Phase 52.3 (shadow table + FeatureSnapshotWriterAgent running)
**Plans:** 1/2 plans complete

Plans:
- [x] 52.5-01-PLAN.md — ParityRepository, FieldViolation, _compare_rows, ParityAuditorAgent(BaseAgent), systemd unit

### Phase 52.6: BaseAgent + ProcessManifest Enhancement (INSERTED)

**Goal:** Enhance BaseAgent with the full Renaissance lifecycle contract (metrics auto-start, OTel tracer, setup/teardown hooks, topic declarations, DLQ stub). Replace AgentRegistry with ProcessManifest. Migrate all four concrete agents (IndicatorComputeAgent, SignalGeneratorAgent, IntelligenceComputeAgent, FeatureWriterAgent) to the new contract. Close OTel tracing todo 009.
**Requirements**: AGENT-01, AGENT-02, AGENT-03, AGENT-04, AGENT-05
**Depends on:** Phase 52.2 (BaseAgent foundation), Phase 52.4 (SignalTrackerAgent)
**Plans:** 5/5 plans complete

Plans:
- [x] 52.6-01-PLAN.md — Pre-condition: rename FeatureWriterService → FeatureWriterAgent (class-name only commit)
- [x] 52.6-02-PLAN.md — TDD: enhance BaseAgent with full lifecycle contract (metrics_port, tracer, _setup/_teardown, running, topics, DLQ)
- [x] 52.6-03-PLAN.md — ProcessManifest (src/core/agent/manifest.py), delete AgentRegistry, update package exports
- [x] 52.6-04-PLAN.md — Migrate IndicatorComputeAgent + SignalGeneratorAgent to new BaseAgent contract
- [x] 52.6-05-PLAN.md — Migrate IntelligenceComputeAgent + FeatureWriterAgent; add init_tracing() to all four entrypoints

### Phase 52.7: Grafana Tempo infrastructure

**Goal:** Stand up Grafana Tempo as the OTel trace backend. No application code changes — agents already call `init_tracing()` after Phase 52.6. This phase wires the receiving end.
**Requirements**: [TEMPO-01, TEMPO-02, TEMPO-03, TEMPO-04, TEMPO-05]
**Depends on:** Phase 52.6
**Plans:** 2/2 plans complete

**Scope:**
- Tempo Docker container (alongside timescaledb/redpanda)
- Grafana datasource pointing at Tempo
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` added to all systemd unit files
- No changes to Python application code — `init_tracing()` in each `__main__` was done in 52.6

Design doc: `docs/ideas/base-agent-enhancement.md` — see "Infrastructure Follow-On" (Docker container, datasource, env var pattern) and Section 1 Tempo rationale (Tempo vs Jaeger, Exemplars, object storage)

Plans:
- [x] 52.7-01-PLAN.md — Tempo Docker Compose service + config YAML + Grafana datasource
- [x] 52.7-02-PLAN.md — Systemd unit files: add OTEL_EXPORTER_OTLP_ENDPOINT + recover intelligence-compute unit

### Phase 52.8: Kafka Trace Propagation

**Goal:** Wire W3C `traceparent` header inject/extract into `KafkaConsumerClient` and `KafkaProducerClient` so spans link across service boundaries end-to-end through the DAG.
**Requirements**: [PARITY-01, PARITY-02, PARITY-03, PARITY-04, PARITY-05]
**Depends on:** Phase 52.6, Phase 52.7
**Plans:** 1/1 plans complete

**Scope and responsibility split:**
- `self.tracer` on every agent — **already delivered by Phase 52.6 (plan 05)**. BaseAgent's contribution is done.
- `init_tracing()` in every `__main__` block — **already delivered by Phase 52.6 (plan 05)**
- Tempo receiving spans — **delivered by Phase 52.7**
- This phase's only job: `opentelemetry.propagators.propagate.inject/extract` in `kafka_utils.py` so context crosses Kafka message boundaries. This is a transport-layer concern, not a BaseAgent concern — agents don't need to know about header propagation.

**Scoping decision for planner — context propagation only, not per-message spans:**
Inject/extract W3C `traceparent` header so parent context links across service boundaries. Do NOT create a span per Kafka message — at production throughput (1m bars × N symbols × N TFs) that is prohibitively expensive. Agents create their own spans internally using `self.tracer`; this phase only ensures the parent context is carried in the message header so those spans stitch into a single trace in Tempo.

Design doc: `docs/ideas/base-agent-enhancement.md` — see "Kafka trace propagation" in Section 1 (propagate.inject/extract in KafkaConsumerClient/KafkaProducerClient, W3C traceparent headers, why this is a kafka_utils.py concern not a BaseAgent concern)

Plans:
- [x] 52.8-01-PLAN.md — Wire traceparent inject/extract into KafkaProducerClient + KafkaConsumerClient

### Phase 54: Provider Abstraction Layer — Broker-Agnostic Data Foundation

**Goal:** Abstract DataProviderAgent into BaseProviderAgent + adapter pattern. IBKRAdapter wraps IBKRProvider. ProviderMergerAgent is the single canonical author of market.bars with auto-failover.
**Requirements**: TBD
**Depends on:** Phase 53.3
**Plans:** 4/4 plans complete

Plans:
- [x] 54-01-PLAN.md — Foundation: Contracts, Schemas, Stream Keys
- [x] 54-02-PLAN.md — IBKRAdapter + provider_meta Migration
- [x] 54-03-PLAN.md — BaseProviderAgent + IBKRProviderAgent
- [x] 54-04-PLAN.md — ProviderMergerAgent + Zero-Downtime Cutover

### Phase 57: IntelligencePipelineComputeAgent — Unified I1-I7 Pipeline ✅ Complete 2026-03-29

**Goal:** Merge `feature_compute_agent` (I1-I6) and `signal_generator_agent` (I7) into a single `IntelligencePipelineComputeAgent`. Eliminate Kafka as an inter-compute bus (I6→I7 round-trip removed). Add state checkpointing to a compacted Kafka topic so restarts are zero-warmup. Add `pre_quality_confidence` and `pre_calibration_confidence` columns to `signal_ledger` for full per-stage attribution.
**Design doc:** `docs/plans/archive/2026-03-29-intelligence-agent-unified-pipeline-design.md`
**Plans:** 3/3 plans complete — shipped 2026-03-29

### Phase 58: Pipeline Parallelization Renaissance Completion

**Goal:** Close the final observability and parallelization gaps for the IntelligencePipelineComputeAgent. Add per-plugin latency/error metrics, TDD test coverage, and configurable systemd unit wiring.
**Requirements**: PIPE-01 (per-plugin latency), PIPE-02 (per-plugin errors), PIPE-03 (configurable pool), PIPE-06 (configurable metrics port)
**Plans:** 3/3 plans complete

Plans:
- [x] 58-01-PLAN.md — Observability foundation: PLUGIN_DURATION_MS Histogram, PLUGIN_ERRORS_TOTAL Counter, THREAD_POOL_WORKERS Gauge, configurable Settings fields
- [x] 58-02-PLAN.md — TDD tests for per-plugin observability metrics
- [x] 58-03-PLAN.md — Systemd unit wiring for configurable pool size and metrics port


### Phase 63: Contract Lifecycle Automation

**Goal:** Eliminate all manual futures roll tasks via a four-stage DAG: seed contract_metadata from settings, detect rolls via RollComputeAgent, promote front-month atomically via ContractMetadataWriterAgent, and audit bars with session-aligned windows.
**Requirements**: [CLA-01, CLA-02, CLA-03, CLA-04, CLA-05]
**Depends on:** Phase 58
**Plans:** 5/6 plans complete

Plans:
- [x] 63-01-PLAN.md — Foundation types: TradingSession methods, stream keys, ContractUpdateEvent schema
- [x] 63-02-PLAN.md — ContractMetadataWriterAgent: seed + roll promotion + DLQ + systemd unit
- [x] 63-03-PLAN.md — BarAuditorAgent session-aligned windows and derived completeness threshold
- [x] 63-04-PLAN.md — RollComputeAgent graduation: backtest script + systemd enable
- [x] 63-05-PLAN.md — settings.py SoT cleanup: base-symbol templates
- [ ] 63-06-PLAN.md — BarWriterAgent base symbol fix: contract_metadata lookup + backfill

### Phase 59: OFI Divergence Redesign

**Goal:** Replace discrete `{-2..+2}` `ofi_divergence` I1 field with a continuous z-score factor. Fix multi-symbol state corruption in OFIPlugin. Rewrite `OFIDivergencePlugin` (I7) with persistence, peak magnitude tracking, EWMA soft factor, and principled `tanh` confidence.
**Design doc:** `docs/plans/2026-04-05-ofi-divergence-redesign-design.md`
**Plans:** 0/1 plan complete
**Depends on:** Phase 63

Plans:
- [ ] 59-PLAN.md — Full rewrite: I1 state keyed by (symbol, tf), continuous ofi_divergence z-score, I7 OFIDivergencePlugin persistence + tanh confidence

### Phase 60: Signal Metrics Redesign — Renaissance-Aligned Performance System

**Goal:** Replace the broken signal performance system (pnl_r = ±∞ when stop ≈ entry, inline SQL aggregation, no regime conditioning, two tracks collapsed) with a DAG ComputeAgent/WriterAgent pipeline. Adds DataQualityValidator (4-gate DQ), regime-conditioned segmentation, zone vs market track separation, and IC metrics. Fixes CVDDivergence Sharpe = -496 at root.
**Design doc:** `docs/plans/2026-04-05-signal-metrics-redesign.md`
**Plans:** 3/3 plans complete ✅ Shipped 2026-04-05 · **UAT verified 2026-04-08** (9/11 pass, window filtering bug fixed, IC gradient improvement todoed)

Plans:
- [x] 60-01-PLAN.md — Foundation: DB migration (3 tables), topic_signal_metrics(), DataQualityValidator, compute_signal_metrics(), compute_ic_metrics()
- [x] 60-02-PLAN.md — Agents: SignalMetricsComputeAgent (timer 15min, :9126), SignalMetricsWriterAgent (:9127), systemd units
- [x] 60-03-PLAN.md — Integration: API attribution endpoint (two tracks), intelligence_pipeline_agent regime-conditioned perf_multiplier, setup_performance shim, dashboard two-track layout

### Phase 64: I6 Confluence Expansion — Cross-TF Plugins + Macro Context Service

**Goal:** Expand I6 from single-plugin cross-timeframe confluence to multi-dimensional intelligence across three axes: time-scale (cross-TF), cross-asset (macro context), and market-structure (yield curve, credit, sectors). Build one plugin at a time; validate with p < 0.05 before building next.

**Architecture:** Hybrid approach matching existing patterns:
- **Cross-TF plugins** — run in-process within `IntelligencePipelineComputeAgent`, reading `frames["intel_*"]` (already cached). Zero new Kafka topics, zero new services.
- **Cross-asset/macro plugins** — new `MacroContextComputeAgent` service subscribes to `market.bars` for non-signal instruments (FX, rates, ETFs), computes macro metrics, publishes to `intelligence.macro_context` Kafka topic. Pipeline injects via `frames["macro"]`. Pure DAG: separate lifecycle, separate scaling, compute-once-per-bar (not per-symbol).

**Design doc:** `docs/ideas/i6-confluence-expansion.md` (v2.0 — 21 ideas, 3-tier roadmap)
**Architecture note:** `.planning/notes/i6-confluence-architecture.md`

**Depends on:** v2.2 completion, todo 030 (wave restructuring — DONE)

**Success Criteria:**
1. CrossTFMomentumDivergence plugin implemented with continuous gradient scoring (not binary)
2. I6Confluence schema extended with new fields (all gradient [-1,+1] or [0,1])
3. MacroContextComputeAgent created — computes USD strength, yield curve, flight-to-quality, credit stress, sector rotation from bar history
4. Pipeline receives macro context via `frames["macro"]` — pure injection, no coupling
5. Each new plugin tracked to `signal_ledger` with `_shadow` dict for future ML validation
6. First plugin validated: N≥30 signals, p<0.05 before building second

**Plans:** 3 plans (Wave 1: Plan 01 + Plan 02 parallel, Wave 2: Plan 03 after validation gate)

Plans:
- [ ] 64-01-PLAN.md — IC fix (continuous pnl_r) + cross-asset instrument constants + CrossTFMomentumDivergence plugin + I6Confluence schema extension + _shadow capture
- [ ] 64-02-PLAN.md — MacroContextComputeAgent + 3 macro factors (USD strength, yield curve, flight-to-quality) + topic_macro_context + systemd unit
- [ ] 64-03-PLAN.md — 4 additional Tier 1 cross-TF plugins (S/R confluence, regime agreement, squeeze/expansion, orderflow alignment) — requires Plan 01 validation gate (N>=30, p<0.05)

### Phase 56: Swarm Foundation

**Goal**: Build shared LLM layer, fix DAG protocols, extract narrative module, wire two new shadow-only swarm services, and create `alpha_multiplier_shadow` hypertable for regime-segmented validation.

**Status**: 🚧 Ready to Execute

**Depends on**: v2.2 completion

**Wave Structure**:
- Wave 1 (parallel): 56-01 + 56-02
- Wave 2 (parallel): 56-03 + 56-04
- Wave 3: 56-05 (needs Wave 1)
- Wave 4: 56-06 (needs Wave 2)
- Wave 5: 56-07 (needs Wave 4)

**Success Criteria** (what must be TRUE):
1. `LLMProviderChain` in `src/core/llm/` — all imports updated
2. `ai_narrative_service.py` archived → `ai_narrative_agent.py` ≤ 210 lines
3. `IAlphaContributor.compute(SwarmContext)` is the only contract — no `get_multiplier` callers
4. `SafeSwarmWrapper` wraps instances, reports violations to Prometheus
5. `SwarmOrchestratorAgent` publishes Path A within 10ms of signal
6. `alpha_multiplier_shadow` hypertable exists and receives writes
7. All agents `shadow_only=True` — no production promotion without segment-level ρ ≥ 0.4
8. DLQ topics wired for both services
9. 49 TDD tests pass

**Plans**: 7 plans across 5 waves

Plans:
- [ ] 56-01-PLAN.md — Move `llm_providers.py` → `src/core/llm/providers.py`, add `call_type` + Kafka audit
- [ ] 56-02-PLAN.md — Create `src/intelligence/narrative/` (orchestrator, synthesizer, prompts, parsers)
- [ ] 56-03-PLAN.md — Fix `IAlphaContributor` protocol, add `SwarmContext`/`SwarmContextCache`, extend schemas
- [ ] 56-04-PLAN.md — Rewrite `SafeSwarmWrapper`, create `SwarmAggregator`, `SwarmMetrics`, `PromptRegistry`
- [ ] 56-05-PLAN.md — Write thin `ai_narrative_agent.py` (~200 lines), archive monolith, update systemd
- [ ] 56-06-PLAN.md — Add 5 swarm stream key functions, write `058_alpha_multiplier_shadow.sql` migration
- [ ] 56-07-PLAN.md — Create `SwarmOrchestratorAgent` + `SwarmWriterAgent`, systemd units, regime-segmented promotion



### Phase 65: Gradient audit of existing plugins I1-I7 broader sweep

**Goal:** Scan all 121 plugins (I1-I7) for binary scoring shortcuts and replace with continuous gradients. Create shared gradient utility module. Add automated verification.
**Requirements**: [GRAD-UTILS, GRAD-SCANNER, GRAD-I4-SESSION, GRAD-I4-VWAP, GRAD-I4-TREND, GRAD-I4-VOL, GRAD-I2-MA, GRAD-I2-VOL, GRAD-I2-RSI, GRAD-I3-STRUCT, GRAD-SMC, GRAD-I5-PATTERNS, GRAD-I7-HMM, GRAD-I7-CONFIDENCE, GRAD-VERIFY, GRAD-CI]
**Depends on:** Phase 64
**Plans:** 5 plans

Plans:
- [ ] 65-01-PLAN.md — Shared gradient_utils.py library + binary pattern scanner
- [ ] 65-02-PLAN.md — I4 SessionContext/AnchoredVWAP/TrendRegime/VolRegime + I2 composites to gradients
- [ ] 65-03-PLAN.md — I3/SMC/I5 additive gradient companion fields + schema registration
- [ ] 65-04-PLAN.md — I7 HMM regime equality graduation + flat confidence base replacement
- [ ] 65-05-PLAN.md — Verification: scanner zero violations + CI test gate + full suite
