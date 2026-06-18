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
- ✅ **v2.3 ML Foundation** — Phases 64, 65, 66 (shipped 2026-05-14; Phase 64 03C USD strength deferred)
- ✅ **v2.4 Observability Hardening** — Phases 67–68 (shipped 2026-04-23)
- ✅ **v2.5 Data Quality & Intelligence Completion** — Phases 69–83 (shipped 2026-05-16; all 15 phases complete including 70, 80, 81, 82, 83)
- ✅ **v2.6 Foundation Hardening & Signal Transform** — Phases 084–092 (shipped 2026-05-20)
- ✅ **v2.7 Mathematical Correctness, Storage & Hardening** — Phases 093, 100, 100.5, 104-109 (shipped 2026-05-29)
- ✅ **v2.8 AI Platform — Part 1** — Phases 094-095, 106-108, 110-116 (shipped 2026-06-08)
- ✅ **v2.9 Signal Quality Renaissance** — Phases 117-122 (shipped 2026-06-13; 5.18M noise signals deleted, 21 setups refactored, param store wired)
- 📋 **v2.10 Data Architecture Evolution** — Phases 123-130 (8 phases: ECL restoration + APR full migration (all 3 tiers) + signal universe hardening + clean replay + 3-table migration)
- ⏸️ **v2.8 AI Platform — Part 2** — Phases 096-099, 101-103 (unblocked — v2.9 complete; next after v2.10)

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
- [x] **Phase 52.2: BaseAgent Infrastructure + AgentRegistry** — TDD BaseAgent + AgentRegistry; renamed IndicatorService → IndicatorComputeAgent; fixed 4 broken tests; systemd unit — COMPLETE
- [x] **Phase 52.3: Dual-Write Shadow Writer** — migration `051_feature_snapshots_shadow.sql`; `FeatureSnapshotWriterAgent` consuming `intelligence.journal` into shadow table; independent consumer group — COMPLETE 2026-03-27
- [x] **Phase 52.4: SignalTrackerAgent Refactor** — renamed `SignalLifecycleService` → `SignalTrackerAgent`; extracted `SignalLedgerRepository`; inherited `BaseAgent`; retired `indicagent-signal-lifecycle.service` — COMPLETE 2026-03-27
- [x] **Phase 52.5: Parity Auditor Agent** — `ParityAuditorAgent` 5-min timer; `FieldViolation` schema; `SHADOW_PARITY_CERTIFIED` gate (60 consecutive clean cycles); autonomous cutover evidence — COMPLETE 2026-03-27
- [x] **Phase 52.6: BaseAgent + ProcessManifest Enhancement** — BaseAgent enhanced lifecycle contract (_setup/_teardown, tracer, topics, running); ProcessManifest replaces singleton AgentRegistry; all 4 pipeline agents migrated; `init_tracing()` wired — COMPLETE 2026-03-27
- [x] **Phase 52.7: Grafana Tempo Infrastructure** — Tempo Docker service; OTLP HTTP :4318; Grafana datasource provisioned; `OTEL_EXPORTER_OTLP_ENDPOINT` in 5 agent systemd units; `PYTHONUNBUFFERED=1` completed — COMPLETE 2026-03-27
- [x] **Phase 52.8: Kafka Trace Propagation** — W3C `traceparent` inject/extract in `KafkaProducerClient`/`KafkaConsumerClient`; `_KafkaHeadersCarrier` OTel adapter; end-to-end bar journey traces visible in Grafana Tempo — COMPLETE 2026-03-28

Full details: `.planning/milestones/v2.1-ROADMAP.md`

</details>

<details>
<summary>✅ v2.2 Operational Excellence (Phases 53.1–58, 60–63) — SHIPPED 2026-04-08</summary>

**Milestone Goal:** Complete the data layer DAG decomposition, automate gap healing, graduate shadow modes with empirical evidence, and expose a clean and stable system externally. Every agent has exactly one job. Zero manual operational steps.

**Execution order** (dependency-driven, reverse numeric — DAG built dependency-first):

- [x] **Phase 53.3: RollComputeAgent + DataProviderAgent Rename** ✅ Complete 2026-03-28 — `RollComputeAgent` standalone on `topic_roll_events()`; `tws_daemon` → `DataProviderAgent`; port :9122
- [x] **Phase 53.2: BarAggregatorComputeAgent** ✅ Complete 2026-03-28 — `BarAccumulator` extracted into standalone `BarAggregatorComputeAgent`; `FeatureComputeAgent` now pure intelligence consumer; port :9120
- [x] **Phase 53.1: BarWriterAgent + BarAuditorAgent** ✅ Complete 2026-03-28 — `BarWriterAgent` decouples OHLCV persistence from compute path; `BarAuditorAgent` self-healing gap-fill loop; retires `gap_fill_service`; ports :9121/:9123
- [x] **Phase 50: Roll Monitor + DualDivergence Graduation** ✅ Infrastructure Complete 2026-04-08 — market_data_5m view, FeatureWriterAgent→topic_roll_events, trad_DualDivergence shadow verified; graduation deferred to Phase 63
- [x] **Phase 54: Provider Abstraction Layer — Broker-Agnostic Data Foundation** ✅ Complete 2026-03-28 — `BaseProviderAgent` + adapter pattern; `IBKRAdapter` wraps `IBKRProvider`; `ProviderMergerAgent` is canonical author of `market.bars` with auto-failover; ports :9129/:9130
- [x] **Phase 57: IntelligencePipelineComputeAgent — Unified I1-I7 Pipeline** ✅ Complete 2026-03-29 — `IntelligencePipelineComputeAgent` merges I1-I7 into single in-process pipeline; Kafka/DB are output sinks only; state checkpointing to compacted topic; `pre_quality_confidence`/`pre_calibration_confidence` on `signal_ledger`; port :9125
Design doc: `docs/plans/archive/2026-03-29-intelligence-agent-unified-pipeline-design.md`

- [x] **Phase 57.1: SignalWriterAgent — signal_generator_agent Retirement** — New `intelligence.i7.signals` topic; thin `SignalWriterAgent` (WriterAgent) consumes all ranked I7 signals → `signal_ledger`; fix winner publish to `topic_signals_aggregated`; retire `signal_generator_agent`
Design doc: `docs/plans/archive/2026-03-30-signal-writer-agent.md` (historical — file since removed)

</details>

<details>
<summary>✅ v2.3 ML Foundation (Phases 64, 65, 66) — SHIPPED 2026-05-14</summary>

**Milestone Goal:** Intelligence pipeline expansion (cross-TF confluence, gradient scoring), and the first swarm agent (SkepticAgent) on Phase 56 infrastructure.

- [x] **Phase 56: Swarm Foundation** — Shared LLM layer (`src/core/llm/`), corrected DAG protocols (`IAlphaContributor`, `SwarmContext`), narrative module extraction (1,327→200 lines), `SwarmOrchestratorAgent` + `SwarmWriterAgent`, `alpha_multiplier_shadow` hypertable — 11 plans, shadow-only — COMPLETE 2026-04-11
Design doc: `docs/plans/2026-04-09-phase-56-swarm-foundation-design.md`

- [x] **Phase 65: Gradient Audit** — 25+ binary fields converted, 8-function gradient_utils.py, CI scanner gate, 5/5 plans — COMPLETE 2026-04-24. Note: swing_amplitude_expanding companion (swing_amplitude_intensity) not implemented — minor gap, non-blocking.
- [x] **Phase 64: I6 Confluence Expansion** — COMPLETE 2026-05-14. 5 new I6 cross-TF plugins (momentum divergence, S/R confluence, regime agreement, squeeze/expansion, orderflow alignment) + MacroComputeAgent (yield curve + FTQ) + full pipeline integration. 03C USD strength deferred (low priority; YC+FTQ providing macro context).
Design doc: `docs/ideas/i6-confluence-expansion.md`

- [x] **Phase 66: Swarm Intelligence Agents** — Single SwarmDispatchService with Skeptic, Correlation, and Volume agents. 16/16 truths verified, 43/43 tests passing — COMPLETE 2026-04-24. Operational gates pending: live service deploy + 30-day statistical validation (~May 25).

Plans:

- [x] 066-01-PLAN.md — Shared infrastructure: SwarmDispatchService + SwarmContext D-16 fix + SkepticAgent + systemd unit + tests
- [x] 066-02-PLAN.md — CorrelationAgent + VolumeAgent: pure compute classes + prompt registries + registry wiring
- [x] 066-03-PLAN.md — Validation framework: naive baseline + Pearson correlation with graduation gates
- [x] 066-04-PLAN.md — Integration tests: multi-agent dispatch, shared cache, context enrichment

</details>

<details>
<summary>✅ v2.4 Observability Hardening (Phases 67–68) — SHIPPED 2026-04-23</summary>

**Milestone Goal:** Fix critical pipeline correctness bugs first (regime filtering bypass, write-path reliability, clean slate), then instrument the corrected system with observability. Grafana alerts → Telegram/Discord within 60s of crash. Roll events auto-restart provider. Gap windows recorded for ML training exclusion. Zero manual operational steps.

**Execution order:** 63-06 → 68 → 67 (correctness before instrumentation — Renaissance principle)

- [x] **Phase 68: Pipeline Hardening & Institutional Foundation** — Complete 2026-04-23
Fix 5 critical signal pipeline bugs (regime type bypass, dead Settings wiring, numeric label, long bias, confidence boost pre-calibration), BaseWriterAgent + 5 writer migrations + write-path reliability (offset commit, DLQ, bounded buffer), end-to-end bar_id trace, full confidence attribution vector, TRUNCATE signal_ledger clean slate, symbol-keyed aggregate tables (6 tables).
Design doc: `docs/plans/2026-04-11-pipeline-hardening-design.md`

- [x] **Phase 67: Observability, Alerting & Automation** ← COMPLETE 2026-04-23 (2/2 plans)
✅ AlertingAgent (Plan 01) — centralized Kafka-to-Telegram/Discord dispatcher
✅ Webhook removal (Plan 02) — service_auditor migrated to _send_alert(), SRP restored
Grafana alert rules (Telegram/Discord), `market_data_gaps` table + `bar_auditor_agent` write path, roll automation in `service_auditor_agent`, 4 code fixes (bootstrap retry, cache seeding, webhook dispatcher, crash counter), 3 dashboard rebuilds.
Design doc: `docs/plans/2026-04-12-observability-automation-design.md`

</details>

<details>
<summary>✅ v2.5 Data Quality & Intelligence Completion (Phases 69-83) — SHIPPED 2026-05-16</summary>

**Milestone Goal:** Eliminate silent data loss, prove writer correctness, instrument persistence path, harden AI/LLM layer, complete swarm intelligence, harden signal lifecycle, and add ML scoring + qualitative foundation. All 14 phases shipped.

- [x] **Phase 69: Writer Agent Renaissance Refactor** — COMPLETE 2026-04-23
Shared consume loop in BaseWriterAgent, _create_consumer() helper, 5 Prometheus metrics, critical overflow alerts + backpressure, FeatureSnapshotWriterAgent migrated from BaseAgent to BaseWriterAgent. 3 writers removed duplicated _run(). 146 tests pass.
**Design doc:** `docs/plans/2026-04-13-basewriter-renaissance-refactor-design.md`
**Planning:** `.planning/phases/069-writer-renaissance-refactor/`

- [x] **Phase 71: BaseAgent Infrastructure Alignment** — COMPLETE 2026-04-14
Settings singleton in BaseAgent, auto init_tracing(), vestigial logging removal, default _report_consumer_lag(), LLMWriterService migrated to BaseWriterAgent.
**Design doc:** `docs/plans/2026-04-14-base-agent-infrastructure-alignment-design.md`
**Planning:** `.planning/phases/071-base-agent-infrastructure-alignment/`

- [x] **Phase 72: Signal Transform Log** — COMPLETE 2026-04-25
Phase 1 dual-write infrastructure: signal_transform_log hypertable, transform_graduation table, TransformRecorder batch writer, graduation.py validation module, GraduationComputeAgent + GraduationWriterAgent services, Kafka topics, and recorder calls wired into all 9 transforms (6 math + 3 swarm). Existing confidence-mutation behavior unchanged; log is write-only and graduation runs in shadow.
**Design spec:** `docs/plans/2026-04-24-signal-transform-log-design.md`
**Planning:** `.planning/phases/072-signal-transform-log-unified-alpha-modifier-architecture-add/`

- [x] **Phase 73: AI LLM Layer B+ Architecture Refactor** — COMPLETE 2026-04-29 (7/7 plans shipped)
Fixes 10 structural defects in AI/LLM layer, creates universal AI agent infrastructure (`src/core/ai/`), reorganizes agents into mandate-based groups (`src/intelligence/ai/`), applies 6 LLM chain fixes, adds narrative TF gate, deletes dead `swarm_orchestrator_agent`, renames `swarm_dispatch_service` -> `alpha_swarm_agent`, merges shadow+transform into unified signal_lineage, and enforces import boundary discipline.
**Planning:** `.planning/phases/73-ai-llm-layer-b-architecture-refactor/`

Plans:

- [x] 73-01-PLAN.md — Delete dead swarm_orchestrator + add Kafka topic functions (D-08, D-09, D-16, D-49) — COMPLETE 2026-04-29
- [x] 73-02-PLAN.md — Build src/core/ai/ infrastructure: 5 modules + TDD tests (D-18-22, D-30-31, D-42-45, D-51) — COMPLETE 2026-04-29
- [x] 73-03-PLAN.md — 6 LLM chain fixes: rate limiter, guardrails, auto-audit, real tokens, cache key (D-04-07, D-11-15, D-17) — COMPLETE 2026-04-29
- [x] 73-04-PLAN.md — Move agents to mandate-based groups + narrative TF gate (D-23-27, D-34, D-35) — COMPLETE 2026-04-29
- [x] 73-05-PLAN.md — Rename dispatch->alpha_swarm + refactor services to BaseGroupService (D-10, D-32, D-33, D-50) — COMPLETE 2026-04-29
- [x] 73-06-PLAN.md — Unified signal_lineage: hypertable, LineageRecorder, LineageWriterAgent (D-01-07 lineage, D-46-48) — COMPLETE 2026-04-29
- [x] 73-07-PLAN.md — Test migration, import boundary enforcement, cleanup, CLAUDE.md update (D-36-41, D-48, D-51) — COMPLETE 2026-04-29
- [x] **Phase 74: BarNormalizerAgent - State Checkpointing for BarAggregator** — COMPLETE 2026-04-26
Add state checkpointing to BarAggregatorComputeAgent following IntelligencePipelineComputeAgent pattern. Persist BarAccumulator state to compacted Kafka topic on every 1m bar, restore from checkpoint on startup. Eliminates data loss on restart (in-progress HTF bars) and prevents stale state corruption.
**Planning:** `.planning/phases/74-barnormalizeragent-canonical-grid-completeness-service-for-t/`

- [x] **Phase 76: Signal Lifecycle Labeling Fix & Activation Gate** — COMPLETE 2026-04-28
Fix 2,744 mislabeled signals (activated_at + never_activated), add temporal guard, bootstrap TTL sweep, activation probability gate, backfill SQL. 3 plans.
**Planning:** `.planning/phases/076-signal-lifecycle-labeling-activation-gate/`

- [x] **Phase 70: ML Scoring Model + AI-SEP-01 Table Decoupling** — COMPLETE 2026-05-13
LightGBM scoring layer (MLScorerMultiplierAgent, shadow_only=True), nightly MLTrainingComputeAgent (L8), AI-SEP-01 table decoupling (signal_ai_enrichment + intelligence_ai_enrichment tables), feature_builder.py with walk-forward CV, SHAP via MLflow, SIGUSR1 hot-reload. 4/4 plans shipped.
**Planning:** `.planning/phases/070-ml-scoring-model/`
- [x] **Phase 75: Shadow Governance System** — COMPLETE (absorbed into Phase 77; shadow_registry migration 077, ShadowAuditorAgent service, features_snapshot rename, auto-enrollment)
- [x] **Phase 77: OTel Observability Unification** — COMPLETE 2026-04-29 (4/4 plans)
Replace 24 per-process HTTP metrics servers + manual service registries with OTel Collector stack. One OTLP push pipeline, dynamic systemd service discovery, Alertmanager declarative rules, hot-path distributed tracing activation. Zero manual config maintenance.
Design doc: `docs/plans/2026-04-28-otel-observability-unification-design.md`
**Planning:** `.planning/phases/077-otel-observability-unified/`

- [x] **Phase 79: Signal Quality Fix — Zone Width + Entry Price** — COMPLETE 2026-05-03
Fix zero-width signal zones (entry==stop==target) caused by plugins building signal dicts manually instead of using `make_signal_from_frame()`. Add `signal_schema_version` (tracks `SIGNAL_SCHEMA_VERSION` constant, currently 'v2') and `entry_type` columns to signal_ledger. Add co-fire tracking (`co_fire_count`/`co_fire_partners`). Migrate all 36 I7 plugins to `make_signal_from_frame()`. Add signal quality metrics. Pre-v1 signals ('v0') are contaminated — ML training queries MUST filter `WHERE signal_schema_version >= 'v1'`.
Design spec: `docs/plans/2026-05-03-phase-79-signal-quality-fix-design.md`
**Planning:** `.planning/phases/079-signal-quality-fix/`

**Success Criteria (Phases 69+71+72+73+75+76+77):**

- ✅ Single consumer creation pattern across all 6 writers
- ✅ 5/6 writers use base class `_run()` loop (feature_writer exception)
- ✅ Buffer overflow triggers critical alert (pager + backpressure)
- ✅ Settings singleton in BaseAgent — zero tribal knowledge for new agents
- ✅ Auto init_tracing() — no manual __main__ calls
- ✅ Default lag reporting in base classes — 15 overrides removed
- ✅ Signal transform log dual-write infrastructure shipped
- ✅ AI/LLM B+ architecture: BaseAIAgent, BaseGroupService, mandate groups, lineage recorder, 6 chain fixes
- ✅ Shadow governance: shadow_registry, ShadowAuditorAgent, auto-enrollment, features_snapshot rename
- ✅ OTel unification: OTLP push, OTel Collector, Loki, Alertmanager, systemd discovery
- ✅ Signal quality fix: zero-width zones eliminated, make_signal_from_frame() mandatory, signal_schema_version='v1', entry_type, co-fire tracking

**Pending:**

- None — all v2.5 phases shipped.

**Completed (v2.5):**

- ✅ Phase 69: Writer Agent Renaissance Refactor (2026-04-23)
- ✅ Phase 70: ML Scoring Model + AI-SEP-01 (2026-05-13)
- ✅ Phase 71: BaseAgent Infrastructure Alignment (2026-04-14)
- ✅ Phase 72: Signal Transform Log (Phase 1 dual-write) (2026-04-25)
- ✅ Phase 73: AI LLM Layer B+ Architecture Refactor (2026-04-29)
- ✅ Phase 74: BarNormalizerAgent State Checkpointing (2026-04-26)
- ✅ Phase 75: Shadow Governance System (2026-04-29, absorbed into Phase 77)
- ✅ Phase 76: Signal Lifecycle Labeling (2026-04-28)
- ✅ Phase 77: OTel Observability Unification (2026-04-29)
- ✅ Phase 78: I8 Alpha Feedback Loop (2026-05-03)
- ✅ Phase 79: Signal Quality Fix — Zone Width + Entry Price (2026-05-03)
- ✅ Phase 80: Renaissance Swarm Intelligence Layer (2026-05-07)
- ✅ Phase 81: Signal Lifecycle Hardening (2026-05-10)
- ✅ Phase 82: ML Intelligence Quality & Qualitative Foundation (2026-05-14)
- ✅ Phase 83: Observability Hardening (2026-05-16)

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
- Phase 45: I6 → I7 Confluence Wiring
- Phase 46: I6 Confluence Expansion
- Phase 46.1: VIX + Cross-Asset to I4
- Phase 47: Shadow Mode Graduation

Refer to the archived file for detailed success criteria, requirements, and plan breakdowns.

</details>

<details>
<summary>✅ v2.1 Phase Details (Phases 48-52) — SHIPPED 2026-03-28</summary>

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

### Phase 49.2: HMM Operational Fixes — INSERTED

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

**Depends on**: Phase 093 ✅ (market_data_5m exists), Phase 093 ✅ (RollComputeAgent validated)

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

**Note**: Automated gap-fill moved to Phase 091.1 (BarAuditorAgent). Remaining undelivered items (deploy_dashboard.sh, /health endpoints) carry to v2.2 if needed.

</details>

<details>
<summary>v2.6 Foundation Hardening & Signal Transform (Phases 084-092) — SHIPPED 2026-05-20</summary>

- [x] **Phase 084: Base Agent Hardening** — Pydantic contracts on BaseWriterAgent, _setup_with_retry, OTel on BaseAIAgent._on_error, circuit breaker opt-in, dead-code cleanup (4/4 plans)
- [x] **Phase 085: Persistence Writer Migration** — all 6 writers adopt 084 contracts; lineage_writer silent data loss fixed; named params across positional-tuple writers (4/4 plans)
  - [x] 085-01-PLAN.md — Pydantic schema definitions (LineageEvent + SignalMetricsEvent)
  - [x] 085-02-PLAN.md — PERSIST-02 + PERSIST-03 (snapshot writer + llm writer fixes)
  - [x] 085-03-PLAN.md — PERSIST-05 named params fleet migration (lifecycle, ctx, bar)
  - [x] 085-04-PLAN.md — PERSIST-01 + PERSIST-04 (lineage + signal_metrics adopt payload_model)
- [x] **Phase 086: Pipeline Hardening** — PluginCircuitBreaker per-plugin; validate_signal() at I7 boundary; checkpoint fail-fast; output queue block/retry (4/4 plans)
  - [x] 086-01-PLAN.md — PIPE-01 + PIPE-03 + PIPE-04 (pipeline agent: circuit breaker, raising checkpoint, blocking enqueue)
  - [x] 086-02-PLAN.md — PIPE-02 (signal_writer_agent: validate_signal gate + DLQ buffer)
  - [x] 086-03-PLAN.md — OBS-03 (BaseAgent.last_processed_at + service_auditor stall detection)
  - [x] 086-04-PLAN.md — OBS-02 (/api/health/system Prometheus aggregation route)
- [ ] **Phase 087: Signal Transform Architecture Phases 2-4** — deferred; gated on data accumulation (0/TBD plans)
- [x] **Phase 088: God Class Decomposition** — extract PluginExecutor, PluginStateManager, SignalProcessor, CacheManager, OutputQueue from IntelligencePipelineComputeAgent; 1928→763 lines (5/5 plans)
- [x] **Phase 089: Compute Performance Optimization** — per-bar allocation waste eliminated; plugin state race fixed; per-key concurrency via PerKeyWorkerManager (6/6 plans)
- [x] **Phase 090: Signal Ledger Thread Safety** — signal_ledger_repository `_to_row` + field annotations; threading.RLock for settings.py globals (2/2 plans) — verified 2026-05-19
- [x] **Phase 091: Instrument Registry** — FX PK collision fix, pg_notify trigger, asyncpg LISTEN, soft-delete route (6/6 plans)
- [x] **Phase 091.1: Instrument Registry Hardening** — BarAuditorAgent gap-fill; additional registry hardening (5/5 plans)
- [x] **Phase 092: Signal Quality Completeness** — (3/3 plans)

*(Qualitative/fundamental horizontal lanes → v2.7 Horizontal Intelligence Foundation)*

</details>

<details>
<summary>✅ v2.7 Mathematical Correctness, Storage & Hardening (Phases 093, 100, 100.5, 104-109) — SHIPPED 2026-05-29</summary>

**Milestone Goal:** (1) Ensure mathematical correctness of all intelligence pipeline computations via Renaissance-style validation (ATR bug fix + systematic audit). (2) Build plugin shared infrastructure and incremental compute foundation. (3) Redesign storage architecture (column rename + signal ledger slim). (4) Infrastructure hardening: architecture hotfixes, foundation hardening, infrastructure hygiene, self-healing hardening, config foundation. Phases 094-099 (AI platform) deferred to v2.8.

### Phase 093: Renaissance Mathematical Correctness Audit

**Goal**: Fix ATR bug and systematically validate all mathematical computations against reference implementations. Ensure every indicator, transform, and statistical function is mathematically correct with invariant tests and edge case coverage.
**Depends on**: Phase 092
**Requirements**: MATH-01, MATH-02, MATH-03, MATH-04, MATH-05
**Success Criteria** (what must be TRUE):

  1. ATR bug is fixed and validated against pandas-ta or TA-lib reference implementation
  2. All Tier 1 financial math (ATR, Bollinger, VWAP, Volume Profile, MACD, RSI, Stochastic, GARCH, Kalman) has reference validation tests
  3. All stateful computations (Kalman filters, GARCH models, rolling windows) have invariant tests
  4. Edge case coverage for gap handling, zero volatility, numerical stability
  5. CI gate prevents merges with failing correctness tests
  6. No regression in existing functionality

**Plans**: 5 plans

Plans:

**Wave 1**

- [x] 093-01-PLAN.md — Test infrastructure (pandas-ta install, correctness/ package, conftest fixtures)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 093-02-PLAN.md — Tier 1 indicator reference validation vs pandas-ta (10 indicators) + ATR Wilder investigation
- [x] 093-03-PLAN.md — Kalman and GARCH stateful invariant tests
- [x] 093-04-PLAN.md — Hot-path efficiency fixes (np.percentile, remove .tolist()) + numeric equivalence guard

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 093-05-PLAN.md — Edge case coverage, numerical stability over 10K bars, CI gate confirmation

### Phase 094: LiteLLM Backend — COMPLETE 2026-05-29

**Goal**: Users of `LLMProviderChain.generate()` get multi-provider routing, automatic retries, and a consistent audit interface — without knowing which underlying HTTP client is in use.
**Depends on**: Phase 092
**Requirements**: LLM-INFRA-01, LLM-INFRA-02, LLM-INFRA-03, LLM-INFRA-04, LLM-INFRA-05
**Success Criteria** (what must be TRUE):

  1. `LiteLLMBackend` handles calls to Ollama (primary) and OpenRouter (fallback) via LiteLLM model strings; no custom HTTP code remains
  2. `LLMProviderChain.generate()` signature is unchanged; `BaseGroupService` and all 4 swarm agents compile without modification
  3. `last_provider_id` and `last_token_usage` populate in `llm_calls` rows; Grafana token-spend panel shows real values
  4. Kafka audit callbacks, `SemanticCache`, and `TokenBudget` produce identical behavior before and after swap (verified by existing tests)
  5. `OllamaProvider`, `OpenRouterProvider`, and `LLMChain` classes are deleted; `git grep` finds zero references

**Plans:** 7 plans in 3 waves

Plans:

- [x] 108-01-PLAN.md — OTel instruments + BaseAgent watchdog counters + requirements.txt
- [x] 108-02-PLAN.md — WatchdogSec=60 rollout to 25 daemon unit files
- [x] 108-03-PLAN.md — DLQ quarantine migration + DLQDrainAgent counting logic
- [x] 108-04-PLAN.md — ServiceAuditor stall threshold + pipeline CB open logging + bar e2e latency
- [x] 108-05-PLAN.md — FastAPI OTel instrumentation + api_health gauge
- [x] 108-06-PLAN.md — Oneshot job_completed_total counters (ml-training, shadow-auditor, roll-batch)
- [x] 108-07-PLAN.md — CLAUDE.md SOP + HYGIENE-07 audit + HEAL-02 deferral record

### Phase 095: Pydantic AI Agent Adapter — COMPLETE 2026-05-31

**Goal**: Agent authors write typed `_compute()` implementations against a `RunContext[AgentDeps]`; all session lifecycle, error handling, and dependency injection are handled by the adapter — not hand-coded per agent.
**Depends on**: Phase 093
**Requirements**: AGENT-EXEC-01, AGENT-EXEC-02, AGENT-EXEC-03, AGENT-EXEC-04, AGENT-EXEC-05
**Success Criteria** (what must be TRUE):

  1. `PydanticAIAdapter` exists; calling `adapter.run(context)` produces the same `AgentOutput` as the legacy `_compute()` path, verified by a test against the Skeptic agent
  2. `AgentDeps` carries `signal_context`, `llm_chain`, `db_pool`, and optional `memory_client`; agents access them via `RunContext[AgentDeps]` without constructor injection
  3. Skeptic agent runs on Pydantic AI adapter in shadow mode (`shadow_only=True`); all other agents run on `BaseAIAgent` unchanged
  4. After >= 100 inferences, `calibrated_confidence` delta between Skeptic (Pydantic AI) and baseline is measured and logged; promotion requires explicit operator action
  5. `BaseAIAgent` class is unchanged; unmigrated agents continue to pass all existing tests

**Plans:** 5 plans in 3 waves

- [x] 094-01-PLAN.md — AgentDeps dependency container (Wave 1)
- [x] 094-02-PLAN.md — PydanticAIAdapter bridge class (Wave 1)
- [x] 094-03-PLAN.md — SkepticResult Pydantic model (Wave 2)
- [ ] 094-04-PLAN.md — SkepticComputeAgentPydantic implementation (Wave 2)
- [ ] 094-05-PLAN.md — Service registration + pydantic-ai dependency (Wave 3)

### Phase 096: Agent Registry

**Goal**: Operators can add or reconfigure an agent by editing `agents.yaml` and restarting the service; no Python file changes, no deployment, no code review required.
**Depends on**: Phase 094
**Requirements**: AGENT-REG-01, AGENT-REG-02, AGENT-REG-03, AGENT-REG-04
**Success Criteria** (what must be TRUE):

  1. `agents.yaml` exists; adding a new entry with valid `agent_id`, `group`, `model_override`, `shadow_only`, `latency_budget_ms`, `prompt_version` and restarting the service instantiates the agent without code changes
  2. `AgentRegistry` reads `agents.yaml` at startup and constructs agent instances; the registry is the sole construction path — no agent is instantiated elsewhere
  3. Starting the service with a spec missing a required field or pointing to a non-existent agent class fails fast with a descriptive error before any bar is processed
  4. `shadow_registry` DB table is the promotion/demotion authority; `agents.yaml` can set `shadow_only=True` but cannot force production promotion — that requires the statistical gate

**Plans:** 3 plans in 3 waves

Plans:

**Wave 1**

- [x] 096-01-PLAN.md — SwarmDeps + registry core (AgentSpec, _REGISTRY, AgentRegistry) + __init_subclass__ self-registration (Wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 096-02-PLAN.md — Migrate all six agent constructors + BaseAIWorker.__init__ to deps: SwarmDeps (Wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 096-03-PLAN.md — register_agents.py + config/agents.yaml + wire BaseSwarmCoordinator._setup + slim AlphaSwarm/NarrativeSwarm (Wave 3)

### Phase 097: Zep Episodic Memory

**Goal**: Agents can recall past setups by regime, symbol, and setup type; memory is gated behind feature flag and validated for quality before production use.
**Depends on**: Phase 095
**Requirements**: MEM-01, MEM-02, MEM-03, MEM-04
**Success Criteria** (what must be TRUE):

  1. `ZepMemoryClient` provides `recall(context: AIContext) -> list[Episode]` and `store(episode: Episode)` interface; agents receive it via `AgentDeps.memory_client`
  2. Memory recall is scoped by `(regime_type, symbol, setup_type)` to surface contextually relevant past setups
  3. Memory is gated behind `AGENT_MEMORY_ENABLED` feature flag; disabled by default; enabled only after shadow-mode recall quality is validated
  4. Memory latency is measured per-call via OTel histogram; recall must complete within 50ms p95 to remain within agent `latency_budget_ms`

**Plans:** 6 plans in 3 waves

Plans:

- [x] 097-01-PLAN.md — DB migration: 6 memory tables + 3 ENUMs + indexes + hypertables + compression policies
- [x] 097-02-PLAN.md — Core types (Episode/CalibrationStats/RegimeHistory) + 4 backend Protocols + AGENT_MEMORY_ENABLED + config/memory.yaml + 6 OTel metrics
- [x] 097-03-PLAN.md — EmbeddingService + Pgvector episodic/calibration/regime read backends
- [x] 097-04-PLAN.md — Mem0 backend + MemoryClient facade + MemoryEpisodeWriter/EmbeddingWorker + WorkerContext wiring
- [x] 097-05-PLAN.md — memory_batch.py 4-step nightly orchestrator + systemd timer/service + _DAG_ORDER registration
- [x] 097-06-PLAN.md — Unit tests for MemoryClient, MemoryEpisodeWriter, EmbeddingService (CI-clean)

### Phase 098: DSPy Offline Prompt Optimizer

**Goal**: DSPy optimizer reads labeled (prompt, result, outcome) tuples from `llm_calls` table, compiles optimized prompts, and stores them for A/B testing.
**Depends on**: Phase 096
**Requirements**: OPT-01, OPT-02, OPT-03, OPT-04
**Success Criteria** (what must be TRUE):

  1. `DSPyOptimizer` reads labeled (prompt, result, outcome) tuples from `llm_calls` table where `outcome` is non-null; compiles optimized prompt variants offline
  2. Optimized prompts are stored in `prompt_versions` table with A/B test assignment; `prompt_version` field in `llm_calls` enables controlled comparison
  3. DSPy optimizer runs as a timer-triggered batch job (not a daemon); optimizer does not touch the live inference path
  4. A/B comparison report (win rate delta, parse failure delta, calibrated_confidence delta) shows measurable improvement before any optimized prompt is promoted to default

**Plans:** 5 plans in 4 waves

Plans:

**Wave 1**

- [ ] 098-01-PLAN.md — Migration 115_prompt_versions table (status CHECK candidate/active/retired) + dspy>=3.2.1 pin

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 098-02-PLAN.md — DSPyOptimizer core class: per-agent data gate, BootstrapFewShot compile, JSONB candidate write

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 098-03-PLAN.md — Oneshot entrypoint + systemd service/timer (weekly Mon 07:00 UTC) + _DAG_ORDER registration
- [ ] 098-04-PLAN.md — A/B promotion runner (D-09 criteria, '0'/'1'/'2' regime guard) + comparison report + unit tests

**Wave 4** *(blocked on Wave 3 completion)*

- [ ] 098-05-PLAN.md — [DEFERRED until Phase 096] Startup prompt injection via AgentDependencies + prompt_loader + unit tests

### Phase 099: Guardrails AI Validation

**Goal**: `GuardrailsAIValidator` implements the same interface as existing validators; drop-in replacement with zero call-site changes.
**Depends on**: Phase 097
**Requirements**: GUARD-01, GUARD-02, GUARD-03
**Success Criteria** (what must be TRUE):

  1. `GuardrailsAIValidator` implements the same interface as existing validators; drop-in replacement with zero call-site changes
  2. Guardrails AI replaces custom field-level validation in `_validate_*_fields` methods; total custom validation LOC reduced
  3. Latency overhead of Guardrails AI validation is measured and documented; must not exceed 10ms p95 vs existing validator

**Plans:** 7 plans in 3 waves

Plans:

- [x] 108-01-PLAN.md — OTel instruments + BaseAgent watchdog counters + requirements.txt
- [x] 108-02-PLAN.md — WatchdogSec=60 rollout to 25 daemon unit files
- [x] 108-03-PLAN.md — DLQ quarantine migration + DLQDrainAgent counting logic
- [x] 108-04-PLAN.md — ServiceAuditor stall threshold + pipeline CB open logging + bar e2e latency
- [x] 108-05-PLAN.md — FastAPI OTel instrumentation + api_health gauge
- [x] 108-06-PLAN.md — Oneshot job_completed_total counters (ml-training, shadow-auditor, roll-batch)
- [ ] 108-07-PLAN.md — CLAUDE.md SOP + HYGIENE-07 audit + HEAL-02 deferral record

### Phase 100: Plugin Shared Infrastructure

**Goal**: Reduce duplication across 132 plugins (I1-I7) through promoted shared utilities and a targeted IncrementalMixin for the 31 genuine incremental plugins.
**Depends on**: Phase 093
**Requirements**: PLUGIN-INFRA-01 through PLUGIN-INFRA-06
**Success Criteria** (what must be TRUE):

  1. State archetype mixins exist for the 7 identified state shapes (Wilder's Accumulator, Rolling Window+Min/Max, etc.)
  2. IncrementalMixin provides correct incremental update semantics for the 31 genuine incremental plugins
  3. All 132 plugins continue to produce identical outputs (golden-file parity tests)
  4. Shared validation utilities replace duplicated NaN/guard logic across all tiers
  5. Plugin registration uses shared metadata helpers (no more ad-hoc `supports_incremental` patterns)
  6. Zero increase in per-bar latency (shared code must not add overhead to hot path)

**Status**: ✅ COMPLETE — 6/6 plans executed and verified (2026-05-22)

**Plans**: 6 plans in 4 waves

**Wave 1**

- [x] 100-01-PLAN.md — Shared utility functions (wilders_update, update_ema, get_main_df)

**Wave 2**

- [x] 100-02-PLAN.md — IncrementalMixin class + ATR reference implementation
- [x] 100-03-PLAN.md — Fix 5 HIGH bugs (RSI, CMF, MarketProfile, SessionLevels, BOCPD)

**Wave 3**

- [x] 100-04-PLAN.md — Migrate 6 easy plugins to IncrementalMixin (ADX, Stochastic, WilliamsR, MFI, VolumeZscore, Keltner)

**Wave 4**

- [x] 100-05-PLAN.md — Migrate I1/I2 plugins to get_main_df() (Bollinger, MovingAverages, MACD, ROC/PPO, AC Oscillator, CCI, AccelerationRegime) — PLANNED
- [x] 100-06-PLAN.md — Correct supports_incremental flags on delegation plugins (CVD, OFI, MAComposite) + conformance test — PLANNED

</details>

<details>
<summary>✅ Phase 100.5: Plugin Infrastructure Hardening — COMPLETE 2026-05-22</summary>

### Phase 100.5: Plugin Infrastructure Hardening ✅

**Goal**: Eliminate silent failure in the plugin system by enforcing structural contracts, wiring production-grade observability, and migrating 24 incremental plugins from ad-hoc state management to IncrementalMixin.
**Depends on**: Phase 100 (IncrementalMixin + ATR reference), Phase 093 (mathematical correctness)
**Status**: ✅ Complete (2026-05-22) — 16 tasks, ~55 files, 24 plugins migrated to IncrementalMixin

**Architecture:** PluginObserver (single recording surface) + IncrementalMixin (state lifecycle) + emit_signal() (validate at construction).

**Wave 1** — Observability layer (independent)

- [x] 100.5-PLAN.md Task 1 — Add 5 new OTel instruments + rename plugin_fallbacks_total
- [x] 100.5-PLAN.md Task 2 — Move plugin_validator inline metrics to metrics.py
- [x] 100.5-PLAN.md Task 3 — Add PluginCallResult dataclass to executor.py
- [x] 100.5-PLAN.md Task 4 — Create PluginObserver + NoOpPluginObserver

**Wave 2** — Executor integration (requires Wave 1)

- [x] 100.5-PLAN.md Task 5 — Wire PluginObserver into PluginExecutor + frame pre-validation

**Wave 3** — Signal contract + CI gates (independent)

- [x] 100.5-PLAN.md Task 6 — Add emit_signal() to plugin_utils.py
- [x] 100.5-PLAN.md Task 7 — CI hard-block: test_incremental_mixin_adoption.py
- [x] 100.5-PLAN.md Task 8 — Equivalence test infrastructure + fixture directory

**Wave 4** — Plugin migrations (requires Task 8)

- [x] 100.5-PLAN.md Task 9  — Migrate Group 1A: RSI, MACD (reference implementations)
- [x] 100.5-PLAN.md Task 10 — Migrate Group 1B: CCI, Aroon, Chandelier, CMF
- [x] 100.5-PLAN.md Task 11 — Migrate Group 1C: HV, ROC/PPO, PSAR, StochRSI, AC Oscillator
- [x] 100.5-PLAN.md Task 12 — Migrate remaining simple plugins (Bollinger, Donchian, MAs, OBV, SuperTrend, VWAP, SessionLevels, MarketProfile, BollingerSqueeze)
- [x] 100.5-PLAN.md Task 13 — (consolidated into Task 12)
- [x] 100.5-PLAN.md Task 14 — Migrate Group 3: BOCPD, HMM, GARCH, Kalman (src/intelligence/context/)

**Wave 5** — Output consistency + cleanup (requires Wave 4)

- [x] 100.5-PLAN.md Task 15 — Output key consistency CI test
- [x] 100.5-PLAN.md Task 16 — Final verification + legacy fixture cleanup + service restart

</details>

<details>
<summary>✅ Phase 104: Storage Architecture Redesign — COMPLETE 2026-05-22</summary>

### Phase 104: Storage Architecture Redesign ✅

**Goal**: Eliminate 39 GB/week disk growth from 3 structural violations. Establish 3-store architecture: intelligence_features (canonical, renamed columns) + signal_ledger (slimmed to ~25 columns, lifecycle/outcome only) + ml_signal_training (nightly materialized typed-column store). Apply retention policies to 9 hypertables and byte caps to 6 unbounded Kafka topics.
**Depends on**: None (tactical insertion - no upstream phase blockers)
**Plans**: 4 plans in 3 waves (completed 2026-05-22)

**Wave 1** *(parallel, no schema changes)*

- [x] 104-01-PLAN.md — Storage audit doc + retention policies on 9 hypertables + Kafka byte caps on 6 topics
- [x] 104-02-PLAN.md — Drop feature_snapshots_shadow (13 GB) + retire parity_auditor + feature_snapshot_writer; replace with SQL freshness function + consumer lag verification before group deletion

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 104-03-PLAN.md — Atomic maintenance window: rename intelligence_features tier columns (i1..i8 -> concept names) + slim signal_ledger (drop ~47 fire-time duplicate columns); update all read/write callsites and dashboard API LATERAL JOIN; explicit systemctl stop/start sequence with verification; rollback procedure (pg_dump backup + reverse DDL); dashboard LATERAL JOIN performance note

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 104-04-PLAN.md — Create ml_signal_training hypertable + MLSignalTrainingMaterializeAgent + nightly systemd timer (02:00 UTC) + service_auditor registration; outcome backfill via ON CONFLICT DO UPDATE UPSERT (idempotent, handles late-resolving pnl_r/mae/mfe)

**Success Criteria** (all met):

  1. 9 hypertables have retention policies (timescaledb_information.jobs has 9+ policy_retention rows)
  2. 6 Kafka topics have retention.bytes=524288000 (no longer -1)
  3. feature_snapshots_shadow table no longer exists; 13 GB reclaimed
  4. feature_snapshot_writer_group consumer group deleted only after verifying zero lag (orphan offsets prevented)
  5. intelligence_features has 8 renamed columns (technical_indicators, market_context, pattern_detections, regime_features, confluence_scores, cross_timeframe_context, trading_signals, llm_narrative); no i1..i8 columns
  6. signal_ledger has ~38 columns (down from 97); no entry_price/stop_loss/confidence/cis_score (live in trading_signals JSONB)
  7. ml_signal_training hypertable exists, flat typed columns, nightly populated via systemd timer
  8. Dashboard /api/signals/active continues to return fire-time fields (via LATERAL jsonb_array_elements join)
  9. All affected services (feature_writer, signal_writer, signal_tracker_compute, lifecycle_writer, signal_auditor, signal_metrics_compute) restart cleanly with new schema
  10. DB backup exists at /tmp/indicagent-pre-migration-*.dump and rollback procedure documented
  11. Dashboard LATERAL JOIN latency monitored (target <500ms p95)
  12. ml_signal_training outcome backfill uses UPSERT pattern for idempotent updates

**Revision notes (2026-05-22):**

- Plan 02: Added consumer lag verification before deleting feature_snapshot_writer_group to prevent orphan offsets
- Plan 03: Added explicit systemctl stop sequence with verification; added pg_dump backup and rollback DDL procedure; added LATERAL JOIN performance note for dashboard API
- Plan 04: Clarified outcome backfill strategy using ON CONFLICT DO UPDATE UPSERT pattern; handles late-resolving pnl_r/mae/mfe idempotently

</details>

<details>
<summary>✅ Phase 105: Architecture Hotfix Sprint — COMPLETE 2026-05-24</summary>

### Phase 105: Architecture Hotfix Sprint ✅

**Goal**: Fix 11 active bugs identified in the 2026-05-23 architectural audit — shadow signal suppression, data loss in persistence writers, stall watchdog wiring, and FeatureWriter ghost-run on DB failure.
**Depends on**: Phase 104
**Status**: ✅ Complete (5/5 plans)

- [x] 105-01-PLAN.md — ctx_writer + llm_writer AttributeErrors, stall watchdog, dead topics (HF-2, HF-3, HF-6, HF-10, HF-11)
- [x] 105-02-PLAN.md — feature_writer fail-fast, bar_writer liveness, swarm_ledger auto-commit (HF-4, HF-5, HF-7)
- [x] 105-03-PLAN.md — OTel metric types: shadow gauges + pipeline latency histograms (HF-8 defs, HF-9)
- [x] 105-04-PLAN.md — Shadow signal suppression: is_shadow stamp, winner filter, auditor SQL + .set() (HF-1, HF-8 call sites)
- [x] 105-05-PLAN.md — Regression tests for shadow suppression + writer fixes; full unit suite green

</details>

<details>
<summary>✅ v2.8 AI Platform — Part 1 (Phases 094-095, 106-108, 110-116) — SHIPPED 2026-06-08</summary>

**Milestone Goal (Part 1)**: Execute foundational AI platform stack (LiteLLM, Pydantic AI), infrastructure hardening, naming alignment, SR consensus, framing audit, and Occam's razor foundation. Part 2 (genetic operators, remaining AI platform) is blocked until v2.9 Signal Quality Renaissance completes.

**Completed Phases (Part 1)**:

- Phase 094: LiteLLM + Instructor Structured Output ✅
- Phase 095: Pydantic AI Agent Execution Layer ✅
- Phase 106: Foundation Hardening ✅
- Phase 107: Infrastructure Hygiene ✅
- Phase 107.5: Signal Lifecycle Architecture Fix ✅
- Phase 108: Self-Healing Hardening ✅ (6/7 plans, 108-07 deferred)
- Phase 109: Config Foundation & Self-Healing Engine ✅
- Phase 110: Renaissance Rename ✅
- Phase 111: Full Naming Alignment ✅
- Phase 112: Intelligence Pipeline Signal Integrity ✅
- Phase 113: Architecture Hardening ✅
- Phase 114: Occam's Razor — Complexity-Aware Model Selection ✅ (4/4 plans written, 0 executed)
- Phase 115: Framing Audit Trail ✅
- Phase 116: SR Consensus — Multi-Method Support/Resistance ✅

**Blocked Phases (Part 2 — requires v2.9 first)**:

- Phase 096: Agent Registry — BLOCKED until signal quality fixed (trains on noisy signals)
- Phase 097: Zep Episodic Memory — SHIPPED but needs v2.9 for quality data
- Phase 098: DSPy Offline Prompt Optimizer — BLOCKED until signal quality fixed
- Phase 099: Guardrails AI Validation — BLOCKED until parse failure rate measured
- Phase 101: Composite Fitness Function — BLOCKED until signal quality fixed (fitness on noisy data)
- Phase 102: Genetic Infrastructure — BLOCKED until v2.9 completes
- Phase 103: Reproductive Operators — BLOCKED until v2.9 completes

**Rationale for Blocking**: Phases 096-103 depend on high-quality signal data. Current state: 21 setups fire 4.46M noise signals (99.8% noise rate). Training ML models, evolving agents, or measuring fitness on corrupted data produces garbage results. v2.9 Signal Quality Renaissance fixes this root cause.

**Design principles (Renaissance standard):**

- Every AI platform phase states the metric it must move — no phase ships without naming the measurement
- Evidence gates between phases: 099 (Guardrails) only if post-Instructor parse failure rate > 1%; 102-103 (genetics) only if FIT-06 discriminative power gate passes
- DAG discipline: no new Kafka topics without named producer-consumer pair; no new daemons without justification; compute is in-process
- Shadow mode by default: all new agent behavior runs shadow_only=True until >= 100 inferences measured

### Phase 106: Foundation Hardening

**Goal**: Zero structural weaknesses from the audit that block v2.8. DAG correctly models all deployed services and never restarts oneshots. Dead code removed. Shared infrastructure reused (retry path, JSONB pool wrapper). PluginCircuitBreaker wired (shadow-mode-first). Queue backpressure and O(1) state lookup in place. Hot path traced via observed_span.
**Depends on**: Phase 105
**Requirements**: FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05, FOUND-06
**Success Criteria** (what must be TRUE):

  1. `git grep -r "ShadowRecorder\|GuardrailsValidator"` returns zero results; dead Settings fields absent from Settings class
  2. `_DAG_ORDER` lists all deployed services; starting the service auditor with an ML batch service active does not trigger a restart attempt
  3. `bar_aggregator_agent` startup uses `BaseAgent._setup_with_retry`; all DB pool creation goes through the shared pool wrapper — no bare `asyncpg.create_pool` calls outside the wrapper
  4. Sending a burst of 500 bars to the pipeline does not grow the output queue unboundedly; `enqueue_blocking` blocks callers rather than dropping; `process_bar_inner` emits an OTel span
  5. `PluginCircuitBreaker` trips on repeated plugin failures and the OTel gauge reflects OPEN/CLOSED state; shadow-mode flag controls whether trips affect live processing
  6. `pytest tests/unit/ -q` passes with no failures after all Phase 106 plans execute

**Plans**: 6 plans

**Wave 1** *(parallel, non-overlapping files; 106-04 depends on 105-03 for shared file)*

- [x] 106-01-PLAN.md — Dead code deletion: ShadowRecorder, GuardrailsValidator (+ chain.py branch), 6+1 dead Settings fields
- [x] 106-02-PLAN.md — DAG correctness: 9 missing services, _ONESHOT_UNITS guard, lag thresholds, agent-id key, systemd unit fixes
- [x] 106-03-PLAN.md — Code reuse: bar_aggregator retry → BaseAgent._setup_with_retry, 3 JSONB create_pool bypasses
- [x] 106-04-PLAN.md — Queue backpressure (enqueue_blocking for intel/journal), PluginStateManager O(1) index, process_bar_inner span

**Wave 2** *(blocked on 106-04 + 105-03/105-04 for shared intelligence_pipeline_agent.py)*

- [x] 106-05-PLAN.md — PluginCircuitBreaker wiring: populate circuit_breakers dict, shadow-mode enabled flag, OTel state gauge

**Wave 3** *(blocked on all code changes)*

- [x] 106-06-PLAN.md — Regression tests: oneshot guard, state index parity, breaker wiring, backpressure; full suite green

### Phase 107: Infrastructure Hygiene

**Goal**: Audit and close accumulated DB and observability debt before AI platform work begins. Fix silent data loss, standardize service patterns, eliminate dead code, and ensure metrics correctness across 9 measurable criteria organized into 3 waves.
**Depends on**: Phase 106
**Requirements**: HYGIENE-01, HYGIENE-02, HYGIENE-03, HYGIENE-04 (expanded to 9 criteria via Renaissance design)
**Success Criteria** (what must be TRUE):

  1. Binary SQL verification query returns TRUE for all 9 criteria (see 107-CONTEXT.md for query)
  2. All 42+ services use BaseAgent lifecycle with SIGTERM handling and stall detection
  3. All services use DatabaseManager.create_pool() with JSONB codecs
  4. Metric label consistency: agent_id used across all services
  5. All writer services have flush span coverage (no silent data loss)
  6. Zero AttributeError bugs in persistence writers
  7. Shadow metrics use correct OTel instrument types (Gauge, not UpDownCounter)
  8. _DAG_ORDER contains all deployed services with justified priorities
  9. Shadow promotion queries exclude shadow signals (is_shadow=FALSE filter)

**Plans**: 3 plans (3 waves)

**Wave 1** — Service Consistency (30%):

- [x] 107-01-PLAN.md — BaseAgent migration (2 services) + DatabaseManager standardization (3 services) + agent_id label consistency

**Wave 2** — Silent Failure Elimination (35%):

- [x] 107-02-PLAN.md — Writer flush spans + AttributeError fixes + metric type corrections (shadow gauges, latency histograms)

**Wave 3** — Complexity Reduction (35%):

- [x] 107-03-PLAN.md — DAG completeness (11 missing services) + shadow promotion query fixes + assessment update

**Renaissance Design Notes:**

- Expanded from 4 criteria (HYGIENE-01–04) to 9 criteria (HYGIENE-01–09) based on architectural weakness assessment
- 3-wave structure: Service Consistency → Silent Failure Elimination → Complexity Reduction
- Measurement-driven: every criterion has quantified before/after metrics and binary verification
- Serial wave execution with stabilization gates (Wave 1 → verify → stabilize → Wave 2 → verify → stabilize → Wave 3)
- Root-cause focused: fixes include CI gates, pre-commit hooks, and process changes

### Phase 107.5: Signal Lifecycle Architecture Fix

**Goal**: Fix four structural defects in signal lifecycle that caused 96% of signals to be permanently pending and mask real performance data. After this phase: signal records are self-contained, TTL evaluation is deterministic and unified, the live tracker handles restarts correctly, and the replay auditor is a true canary processing near-zero signals in steady state.
**Depends on**: Phase 107
**Requirements**: LIFECYCLE-FIX-01, LIFECYCLE-FIX-02, LIFECYCLE-FIX-03, LIFECYCLE-FIX-04
**Success Criteria** (what must be TRUE):

  1. After the next restart, stale pending signals fire TTL-expired transitions immediately (no backlog accumulation) - measured by zero pending signals surviving first `_ingest_signal` cycle post-restart
  2. `signal_ledger.entry_zone_low` and `entry_zone_high` are non-NULL for all new signals; backfill reconciliation report shows zero unmatched signal_ids
  3. `signal_ledger.expires_at` is non-NULL for all signals; `lifecycle_tracker.py` and `signal_tracker_compute_agent.py` use `expires_at` exclusively; zero dual-model divergence
  4. `signal_replay_auditor` processes near-zero signals in steady state (< 5 signals/cycle after 10 minutes); LATERAL JOIN removed; `REPLAY_BATCH_SIZE`/`REPLAY_INTERVAL_SECONDS` in Settings

**Plans**: 6 plans in 6 serial waves

Plans:

- [x] 107.5-01-PLAN.md — Fix 1: Remove is_backfill guard from _ingest_signal (Wave 1)
- [x] 107.5-02-PLAN.md — Fix 2a: zone field name fix in signal_writer + migration 096 DDL (Wave 2)
- [x] 107.5-03-PLAN.md — Fix 2b: Zone field backfill script + reconciliation report (Wave 3)
- [x] 107.5-04-PLAN.md — Fix 3a: tf_to_seconds utility + migration 097 + expires_at backfill (Wave 4)
- [x] 107.5-05-PLAN.md — Fix 3b: Atomic evaluator deploy — both TTL evaluators switch to expires_at (Wave 5)
- [x] 107.5-06-PLAN.md — Fix 4: Replay auditor LATERAL JOIN removal + canary params via Settings (Wave 6)

### Phase 108: Self-Healing Hardening

**Goal**: Eliminate the remaining availability gaps left after Phase 107. systemd WatchdogSec rollout gives the init system automatic service recovery without manual intervention. A nightly pg_dump backup ensures DB recovery is possible. Three self-healing gaps in the runtime layer are closed: circuit breaker opens emit to the health event bus, DLQ poison-pill quarantine prevents infinite retry loops, and ServiceAuditor detects stuck consumers that are alive but not processing.
**Depends on**: Phase 107
**Requirements**: HEAL-01, HEAL-02, HEAL-03, HEAL-04
**Success Criteria** (what must be TRUE):

  1. All 39 daemon services have `WatchdogSec=60` in their unit files; `BaseAgent` heartbeat loop calls `sd_notify(WATCHDOG=1)` every 30s; `systemd-analyze verify` passes on all units
  2. `indicagent-db-backup.service` + `.timer` present and active; nightly `pg_dump` runs; `/var/backups/indicagent/` contains a `.sql.gz` no older than 25h; retention script deletes files older than 7 days
  3. When a `PluginCircuitBreaker` opens, an event is published to `system.health.events` with `type=circuit_breaker_open`, `plugin_id`, `failure_count`, `opened_at`; CB events visible in service auditor log
  4. DLQ messages re-delivered more than `DLQ_MAX_RETRIES` times (default 3) are quarantined to a dead-letter-final topic with metadata; ServiceAuditor emits a `consumer_stall` alert when a consumer lag stops decreasing for > `STALL_TIMEOUT_SEC` (default 120s)

**Plans:** 7/7 plans complete

Plans:

**Wave 1**

- [x] 108-01-PLAN.md — OTel instruments + BaseAgent watchdog counters + requirements.txt
- [x] 108-02-PLAN.md — WatchdogSec=60 rollout to 25 daemon unit files

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 108-03-PLAN.md — DLQ quarantine migration + DLQDrainAgent counting logic
- [x] 108-04-PLAN.md — ServiceAuditor stall threshold + pipeline CB open logging + bar e2e latency
- [x] 108-05-PLAN.md — FastAPI OTel instrumentation + api_health gauge
- [x] 108-06-PLAN.md — Oneshot job_completed_total counters (ml-training, shadow-auditor, roll-batch)

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 108-07-PLAN.md — CLAUDE.md SOP + HYGIENE-07 audit + HEAL-02 deferral record

### Phase 109: Config Foundation & Self-Healing Engine

**Goal**: Unified config system with time-series audit trail and control-theory-based self-healing engine. Config changes propagate via Kafka with hot-reload. Automated remediation for common infrastructure issues.
**Depends on**: Phase 108
**Success Criteria** (what must be TRUE):

  1. Database migration 109_config_foundation.sql applied (4 config tables + remediation_ledger)
  2. ConfigService HTTP API serves on port 9001 with set/get/list/revert endpoints
  3. OutboxDispatcherAgent publishes to topic_config_updates (compacted)
  4. BaseAgent loads config snapshot on startup and subscribes to Kafka for OPS layer hot-reload
  5. SelfHealingAgent receives Alertmanager webhooks on port 9002
  6. SelfHealingEngine executes remediation strategies (disk cleanup, consumer restart, pool flush)
  7. Remediation outcomes recorded to remediation_ledger with success rate tracking
  8. 15 runtime params migrated from settings.py to config DB (regime.*, swarm.*, roll.*, etc.)
  9. _LAG_THRESHOLDS dict removed from service_auditor_agent.py, loaded from config instead
  10. Hardcoded shadow_only flags removed from AI agents, loaded from config instead

**Plans**: 5 plans in 5 waves

Plans:

**Wave 1**

- [x] 109-01-PLAN.md — Config foundation: DB tables, ConfigService, validation schemas

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 109-02-PLAN.md — OutboxDispatcherAgent + topic_config_updates + ConfigService integration
- [x] 109-03-PLAN.md — BaseAgent config snapshot + hot-reload subscription
- [x] 109-04-PLAN.md — SelfHealingAgent + webhook receiver + SelfHealingEngine
- [x] 109-05-PLAN.md — 15 runtime params migration + CLAUDE.md update

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 109-06-PLAN.md — Regression tests + full suite green

</details>

<details>
<summary>✅ v2.9 Signal Quality Renaissance — SHIPPED 2026-06-13</summary>

- [x] **Phase 117: PatternCompletion Fix + Data Pipeline Validation** — Complete (5/5 plans, 2026-06-08)
- [x] **Phase 118: Confidence Integrity + Top 5 Setup Refactoring** — Complete (7/7 plans, 2026-06-09)
- [x] **Phase 119: Remaining 16 Setup Refactoring** — Complete (4/4 plans, 2026-06-10)
- [x] **Phase 120: Shadow Mode Validation** — Complete (3/3 plans, 2026-06-10)
- [x] **Phase 121: Lifecycle Replay & Validation** — Complete (3/4 plans, 2026-06-11); 121-02 report deferred to Phase 127
- [x] **Phase 122: I2 Tier Persistence Fix + Param Store** — Complete (10/10 plans, 2026-06-13)

</details>

<details>
<summary>📋 v2.10 Data Architecture Evolution (Phases 123-130)</summary>

**Milestone Goal:** Establish correct signal architecture (3-table: signal_events / trade_frames / trade_executions), fully externalize APR (Adaptive Parameter Registry), and deliver clean replay for ML training data. ECL boundary (Phase 123) removes all extrinsic emission suppressors. APR migration (Phase 125) externalizes all 51 constants. Signal universe hardening (Phase 126) wires all confluence-exempt signal-generation plugins and fixes zone width mechanics. 3-table migration (Phases 128-130) separates detection/hypothesis/execution and wires CounterfactualTracker. Clean replay (Phase 127) runs last so the corpus lands directly in the final 3-table schema with counterfactual_pnl_r populated from day one.

**Execution order:** v2.9 → 123 → 124 → 125 → 126 → 128 → 129 → 130 → 127 → v2.8 Part 2 (resume)
*Phase 127 moved after 128-130: replay into the final schema avoids a second replay and produces counterfactual_pnl_r-populated training data immediately.*

**Architecture decision (made):** 3-table — `signal_events` / `trade_frames` / `trade_executions`. `counterfactual_pnl_r` on `trade_frames` is the ML training target, populated by CounterfactualTracker (Phase 130). See `docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md` for full spec.

**Cross-cutting constraints (v2.10):**
- None-vs-0.0 semantics (Phase 123): NULL = cold-start, 0.0 = genuine neutral — never OR fallbacks
- No new Kafka topics without named producer-consumer pair
- No new daemons without justification (compute is in-process)
- All timestamps UTC (datetime.now(UTC) only)
- ON CONFLICT IS NULL guard (feature_writer): `WHERE ctf_score IS NULL` — never `IS NULL OR = 0.0`

**v2.11 seeds unlocked by v2.10:**
- CounterfactualTracker daemon (Phase 130) — populates `counterfactual_pnl_r` on every trade frame regardless of execution
- I6 DB bootstrap at daemon startup — permanent cold-start elimination for live trading

---

### Phase 123: ECL Boundary Restoration

**Goal:** Remove all extrinsic emission suppressors across all I7 plugins. Add 5 ECL fields plus `context_features` to the signal schema. Promote `context_features` from the `_shadow` dict to a persisted top-level signal field. Collect `factor_scores` dict in all 37 plugins before compositing. Bump `SIGNAL_SCHEMA_VERSION`. Rename architecture doc from `i7-setup-confidence-patterns` to `setup-confidence-patterns` and add ECL definition.

This phase is split into three waves:
- **Wave A** — Gate removal + schema (replay-blocking, must ship first)
- **Wave B** — Factor score persistence (same phase, not replay-blocking)
- **Wave C** — Architecture doc rename and update

**Status:** ✅ Complete (2026-06-14; 3/3 plans executed)

---

### Phase 124: Signal Universe Integrity + Cold-Start Hardening — ✅ COMPLETE 2026-06-14

**Goal:** Tighten 5 over-firing plugins (15-30%/bar) to < 3%/bar via event vs state detection. Fix ON CONFLICT cold-start contamination in intelligence_features (IS NULL guard only). Add --warmup pass to historical replay.

**Depends on**: Phase 123
**Requirements**: QUALITY-01, QUALITY-02
**Success Criteria**:

  1. All 5 over-firing plugins at < 3% fire rate (SQL validated)
  2. ON CONFLICT uses `DO UPDATE ... WHERE ctf_score IS NULL` — not `IS NULL OR = 0.0`
  3. `--warmup` flag operational in run_historical_pipeline.py
  4. `pytest tests/unit/ -q` green

**Plans**: 7 plans in 2 waves

**Wave A** (deterministic, ship first):

- [x] 124-01-PLAN.md — Migration 130 (promote 4 CTF columns + backfill + JSONB strip) + feature_writer ON CONFLICT cold-start guard + CTF reader migration + `--warmup` flag

**Wave B** (behavioral, after Wave A):

- [x] 124-02-PLAN.md — TrendFollowing structural rewrite (pullback-to-MA reversal / consolidation breakout)
- [x] 124-03-PLAN.md — OFIContinuation structural rewrite (OFI acceleration/thrust bar)
- [x] 124-04-PLAN.md — PatternCompletion structural rewrite (target reached / neckline break + instance consumption)
- [x] 124-05-PLAN.md — LiquiditySweepReclaim structural rewrite (rising edge + close-above acceptance)
- [x] 124-06-PLAN.md — AnchoredVWAPReversion structural rewrite (departure + return + rejection/reclaim candle)
- [x] 124-07-PLAN.md — D6 fire-rate sanity SQL (aggregate + segmented)

---

### Phase 125: APR Full Migration — All Three Tiers

**Goal:** Externalize all 51 numeric constants across all three tiers to APR. Tier A (26 detection gate keys), Tier B (22 confidence weight keys), Tier C (6 zone engine geometry keys). Zero behavior change for Tiers A and B — seeds equal current hard-coded values. Tier C exception: `feature.zone_engine.min_zone_width_atr` seeds at 1.5/1.0/1.5 (equity/forex/futures) per noise-band analysis, not the current 0.25 hard-coded value — the gate is not yet wired (Phase 126 wires it), so DB seed value has no runtime effect. Weight sum invariant enforced in all Tier B plugins. Replay is not a blocker; get the parameters right first.

**Depends on**: Phase 124
**Requirements**: APR-01, APR-02, APR-03
**Success Criteria**:

  1. All 51 keys in `config_state` with seed values and provenance-tagged descriptions
  2. Zero hard-coded constants for any tier in src/ (grep confirms)
  3. Weight sum invariant enforced in all Tier B plugins (`_assert_weights_sum`)
  4. All plugins loading from ConfigService at compute_full() time
  5. `pytest tests/unit/ -q` green
  6. TODO 025 closed — all three tiers complete

**Plans**: 5 plans in 3 waves

**Wave 1** (parallel):

- [ ] 125-PLAN-A.md — Migration 132: seed 10 new APR keys (3 CIS gate + 4 zone_engine + 3 vwap_reversion weights)
- [ ] 125-PLAN-C.md — Add _validate_weights_sum to confidence_utils.py + fix cfg parameter name + capture 2 cleanup TODOs

**Wave 2** (depends on A + C):

- [ ] 125-PLAN-B.md — Wire anchored_vwap_reversion weights to ConfigService + _validate_weights_sum call
- [ ] 125-PLAN-D.md — Add _validate_weights_sum to 5 remaining Tier B plugins + rename BOOTSTRAP_WEIGHTS in cis_scorer.py

**Wave 3** (depends on A + D):

- [ ] 125-PLAN-E.md — Wire CIS gate constants to APR in cis_scorer.py + extend _THRESHOLD_KEYS + close TODO 025

---

### Phase 126: Signal Universe Hardening

**Goal:** Establish a mechanically correct signal universe: all emitted signals have structurally valid zones (ATR-bounded) and full confluence annotation, making the clean replay in Phase 127 usable as ML training data. Zone width enforcement eliminates phantom stopped_at_entry outcomes; confluence wiring closes the ECL annotation gap on all signal-generation plugins.

**Design doc**: `docs/plans/2026-06-14-phase-126-signal-universe-hardening.md`

**Depends on**: Phase 125
**Requirements**: SIGNAL-QUALITY-01, SIGNAL-QUALITY-02
**Success Criteria**:

  1. `frame_trade()` calls `_reject_frame()` when `zone_width < min_zone_width_atr × ATR` for all zone source types (supply_demand, fvg, ob, structural); gate is in `frame_trade()` not `_resolve_zone_bounds()` (geometry resolution and viability gating are separate concerns)
  2. `feature.zone_engine.min_zone_width_atr` in APR with per-asset-class seeds (equity_etf: 1.5, forex: 1.0, futures: 1.5) — derived from noise-band math: zone_width + buffer (0.25×ATR) must be ≥ 2.0×ATR for stop to be outside intrabar noise; seeds are initial estimates, Step 1 diagnostic in P126-01 confirms empirically
  3. `stopped_at_entry` rate < 15% on 10K-signal replay sample (from 47.6%)
  4. `_CONFLUENCE_EXEMPT_PLUGINS` frozenset deleted; all 8 formerly-exempt plugins have `requires_i6_confluence = True` and call `capture_signal_features()`
  5. All 37 registered signal-generation plugins emit > 0 signals in 30-day replay window
  6. `trad_MeanReversion` dual-gate conflict resolved (fires > 100 signals/30d) or demoted to `shadow_only=True` with documented rationale; stays in `TIER_I7`
  7. Detection correctness audit doc produced: per-plugin verification result; unverifiable plugins demoted to `shadow_only=True` with explicit rationale — removal from `TIER_I7` is not a valid disposition
  8. `pytest tests/unit/ -q` green

**Plans:** 6/6 plans complete
- [x] 126-00-PLAN.md — Wave 0: USDJPY anomaly diagnostic (SQL-only; verdict gates replay fitness)
- [x] 126-01-PLAN.md — Wave 1: Universal zone width gate in frame_trade() + per-asset-class APR seeds (migration 132)
- [x] 126-02-PLAN.md — Wave 2: Wire 8 confluence-exempt plugins, delete _I7_I6_EXEMPT, diagnose ORB/SessionExtremes, fix MeanReversion + FVGFill
- [x] 126-06-PLAN.md — Wave 3: Pipeline-layer annotation (_annotate_signal), formalize zone_friction_score, bump SIGNAL_SCHEMA_VERSION
- [x] 126-05-PLAN.md — Wave 4: IC validation + detection correctness audit; demote anti-signal/unverifiable plugins to shadow_only

---

### Phase 127: Clean Replay + Validation

**Goal:** Run full historical replay on corrected pipeline (Phases 123-126 in place) with `--warmup`. Produce Phase 121-02 validation report using correct methodology. Retrain calibration curves on clean corpus.

**Depends on**: Phase 123, 124, 125, 126
**Requirements**: REPLAY-02 (carried from Phase 121)
**Success Criteria**:

  1. Clean replay completes without errors
  2. `context_features` coverage > 99% for non-cold-start signals
  3. All previously over-firing plugins at < 3% (SQL validated)
  4. Validation report uses correct methodology — no cross-population Welch's t-test; measures: signal volume delta, CTF as feature, firing rates, null distribution
  5. Calibration curves retrained on clean corpus
  6. RCA Part VI updated

**Plans**: 3 plans across 3 waves
- [ ] 127-01-PLAN.md — Capture pre-replay baseline on 3-table schema + execute clean replay with --include-rolled
- [ ] 127-02-PLAN.md — 3-table validation report (NO Welch'''s t-test, null distribution, bootstrap CI) + RCA Part VI update
- [ ] 127-03-PLAN.md — Trigger ml-training calibration retrain on clean corpus with pre-flight schema check

---

### Phase 128: 3-Table Schema Design and ADR

**Goal:** Define full 3-table schema (signal_events / trade_frames / trade_executions) with column types, FK constraints, index strategy. Create ADR. `counterfactual_pnl_r` is a required first-class column on trade_frames — not optional.

**Depends on**: Phase 127
**Requirements**: ARCH-01
**Success Criteria**:

  1. ADR at `docs/architecture/signal-trade-separation-ADR.md`
  2. Full table schemas defined with types, FK, indexes
  3. `signal_ledger_full` view SQL defined
  4. Cardinality recorded: 1 signal → N frames (one per entry_type); 1 frame → 0-1 executions

**Plans**: 3 plans in 1 wave (Wave 1 — all parallel)

Plans:

- [ ] 128-01-PLAN.md — ADR: signal-trade-separation-ADR.md (Context, Decision, G0 Audit, Schema Tables, Alternatives Considered, Consequences)
- [ ] 128-02-PLAN.md — DDL: production/migrations/137_3table_schema.sql (signal_events hypertable + trade_frames + trade_executions + signal_ledger_full view)
- [ ] 128-03-PLAN.md — Cleanup: delete capture_signal_features() from confidence_utils.py + update src/intelligence/CLAUDE.md

---

### Phase 129: Database Migration

**Goal:** Create 3 new tables. Migrate signal_ledger data. Deploy signal_ledger_full view. Keep signal_ledger read-only during transition.

**Depends on**: Phase 128
**Requirements**: MIGRATE-01
**Success Criteria**:

  1. signal_events, trade_frames, trade_executions created with full schema
  2. signal_ledger_full view deployed and queryable
  3. Row counts verified: all signal_ledger rows migrated
  4. signal_ledger retained read-only (not dropped yet)

**Plans**:
- Wave 1: [129-01] Schema Finalization — apply Plan-04 columns to live DB (feature_ts, concurrent_signal_count, concurrent_plugins, regime_at_activation, regime_at_exit)
- Wave 1: [129-02] Data Migration Script — write migrate_signal_ledger.py (10K-row batches, column mapping, frame_details JSONB)
- Wave 2 *(blocked on Wave 1 completion)*: [129-03] Execute migration, verify counts, read-only, SIGNAL_SCHEMA_VERSION bump

**Status**: Planned (2026-06-16)

---

### Phase 130: Script Rewriting

**Goal:** Update all writers, trackers, auditors, API endpoints, historical backfill to use 3-table schema. Drop signal_ledger after 48-hour verification window.

**Depends on**: Phase 129
**Requirements**: REWRITE-01
**Success Criteria**:

  1. All writers/trackers/APIs use new 3-table schema
  2. `pytest tests/unit/ tests/integration/ -q` green
  3. signal_ledger dropped after 48-hour window

**Plans**: 7 plans in 4 waves

Plans:

**Wave 1**

- [x] 130-01-PLAN.md — OPS_PREFIXES (ui./weights.) + migration 142 APR seeds (22 keys)

**Wave 2** *(blocked on Wave 1)*

- [x] 130-02-PLAN.md — Repository rewrite: SignalLedgerRepository → SignalEventsRepository, 3-table SQL, shim + importers

**Wave 3** *(parallel, blocked on Wave 2; disjoint files)*

- [x] 130-03-PLAN.md — signal_writer (G0 grouping) + lifecycle_writer (status/frame_details) + APR
- [x] 130-04-PLAN.md — signal_tracker bootstrap rewrite + swarm_ledger_writer FK + signal_auditor + signal_probe_auditor
- [x] 130-05-PLAN.md — API routes: signals.py (drop 7 columns, ui.signals.* APR) + narrative.py (tf)
- [x] 130-06-PLAN.md — Backfill scripts: run_historical_pipeline + lifecycle_replay + feature_replay (3-table, G0)

**Wave 4** *(blocked on Wave 3 + 48h verification window)*

- [x] 130-07-PLAN.md — Migration 143 DROP + view rename + signal_ledger_full sweep + D-15 doc updates

---

**v2.10 Success Criteria:**

1. ✅ Phase 123 complete (ECL boundary restored)
2. ✅ Phase 124 complete (signal universe integrity + cold-start hardening)
3. ⏳ Phase 125 complete (APR full migration — all three tiers)
4. ⏳ Phase 126 complete (signal universe hardening)
5. ⏳ Phase 127 complete (clean replay + validation)
6. ⏳ Phase 128-130 complete (3-table signal architecture)

**v2.10-complete when:** All 8 phases shipped, clean replay validates corrected pipeline, ML training data integrity restored.

</details>

<details>
<summary>⏳ Phase 131: Signal Generation Integrity — IN PROGRESS</summary>

**Goal:** Every plugin that should fire does fire. Every active instrument produces signals. Corpus rebuild is reliable. Phase 133 cannot begin until Phase 131 verification gate passes.

**Verification gate:** Unit tests green; targeted 2-week replay shows 35 of 35 eligible plugins emitting signals (CrossAssetDivergence is the only exclusion — formally architectural live-only); no zero-signal instruments in active contract list from fixable bugs.

**Plans:** 7 plans

Plans:

- [x] 131-01-PLAN.md — A4 diagnostic: confirm asset_class=None for rolled-contract symbols via log trace + 10-symbol test replay
- [x] 131-02-PLAN.md — A6 BOCPD look-ahead fix (vol[-21:-1]) + B7 verify SQL fan-out fix (COUNT DISTINCT)
- [x] 131-03-PLAN.md — A4 fix (asset_class injection) + trad_PrevDayLevelTest (maxlen 200→800) + trad_CrossAssetDivergence (live-only annotation)
- [x] 131-04-PLAN.md — A7 fix: _seed_last_events_from_db() + intelligence_cache DB seed in replay_symbol() + --no-seed flag
- [x] 131-05-PLAN.md — trad_AnchoredVWAPReversion gate ordering fix (reclaim before state-clearing)
- [x] 131-06-PLAN.md — B6 backfill integrity crash fix (batched assertion + REBUILD_STATUS semantics)
- [x] 131-07-PLAN.md — Verification: 1-week sample replay (ctf_score >=85% non-zero) + 2-week plugin coverage (35/35)

</details>

<details>
<summary>📋 Phase 132: Stop-Zone Geometry + APR Migration — PLANNED</summary>

**Goal:** Stops are measured from actual entry price (not zone edge), and every tunable numeric constant in `trade_framer.py` lives in APR. Verify `stopped_at_entry` exit_reason < 5% of stop exits on a fresh 1-month sample replay + lifecycle_replay.

**Verification gate:** 1-month sample replay + lifecycle_replay shows stopped_at_entry < 5%; 35 trade_framer APR keys (19 module + 12 adaptive buffer + 4 per-class floor) visible in `/config/parameters`; APR at seed values produces identical signals to prior constants (regression tests); no migratable bare literals in trade_framer.py; 1-tick gate preserved.

**Plans:** 5 plans

Plans:

- [x] 132-01-PLAN.md — A2 measurement: 2-week sample replay + lifecycle_replay, measure stopped_at_entry rate, audit zone_engine for narrow-zone bypass, write A2 disposition (Wave 1)
- [x] 132-02-PLAN.md — APR migration 144: 19 module-level constants → _cfg() + _THRESHOLD_KEYS; fix run_historical_pipeline.py config wiring gap; seed-value regression test (Wave 1)
- [ ] 132-03-PLAN.md — APR migration 145: 12 adaptive buffer piecewise coefficients (coupled, tune-as-a-group); anchor-point regression test (Wave 2, depends 02)
- [ ] 132-04-PLAN.md — APR migration 146: 4 per-asset-class stop floor keys (commodity 1.5, others 1.0) + _min_stop_multiplier_floor router; 1-tick gate preserved (Wave 3, depends 03)
- [ ] 132-05-PLAN.md — Verification: 1-month replay + stopped_at_entry < 5% gate + 35-key audit + bare-literal audit + commit/push (Wave 4, depends 01-04)

</details>

<details>
<summary>📋 Phase 133: Clean Corpus Rebuild — PLANNED</summary>

**Goal:** One complete, verified, unbiased corpus. All Phase 131 signal bugs fixed. All Phase 132 stop geometry correct. Schema migrated (trade_frames hypertable). Scripts cleaned. Full rebuild produces a corpus satisfying ML training acceptance criteria. ML training is unblocked after this phase.

**Prerequisite gate:** Do not begin until Phase 131 AND Phase 132 verification gates both pass.

**Plans:** 7 plans in 5 waves

Plans:

- [ ] 133-01-PLAN.md — C2 column naming verification + MEMORY.md closure (Wave 1, parallel)
- [ ] 133-02-PLAN.md — Script cleanup: B2/B3/B4/B5/D items before TRUNCATE (Wave 1, parallel)
- [ ] 133-03-PLAN.md — C1 trade_frames hypertable migration 146 + lifecycle_replay writer update (Wave 2, depends 02)
- [ ] 133-04-PLAN.md — TRUNCATE + full backfill replay (Wave 3, depends 01+02+03)
- [ ] 133-05-PLAN.md — Lifecycle replay + _verify_replay 0/0/0 gate (Wave 4, depends 04)
- [ ] 133-06-PLAN.md — Corpus acceptance criteria: all D-04 hard gates + 133-ACCEPTANCE-REPORT.md (Wave 5, depends 05)
- [ ] 133-07-PLAN.md — Final cleanup, unit tests, commit, push, phase closure (Wave 5, parallel with 06, depends 05)

</details>

<details>
<summary>📋 Phase 134: Signal Classification Type Safety — PLANNED</summary>

**Goal:** All classification columns in the signal ledger are type-enforced end-to-end. `SignalOutcome` persisted to `trade_executions.outcome` (eliminates re-derivation and the stopped_at_entry query bug). `EntryType` Python enum created (replaces 15+ string literals). PostgreSQL ENUM types enforce valid values at write time across all classification columns. No classification can be written silently with an invalid value, and no gate query can trivially pass by referencing a value that doesn't exist.

**Prerequisite gate:** Phase 132 complete (trade_framer APR migration done; signal ledger schema stable).

**Plans:** 3 plans in 3 waves

Plans:

- [ ] 134-01-PLAN.md — Persist SignalOutcome to trade_executions: add outcome column, wire lifecycle_replay, backfill historical rows (Wave 1)
- [ ] 134-02-PLAN.md — EntryType enum: create Python enum, replace 15+ string literals in trade_framer.py, add DB CHECK constraint (Wave 2, depends 01)
- [ ] 134-03-PLAN.md — PostgreSQL ENUM type sweep: convert exit_reason, outcome, entry_type, signal_events.status to PG ENUM types; remove phantom values; verification (Wave 3, depends 01+02)

</details>
