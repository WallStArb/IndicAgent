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
- ✅ **v2.10 Data Architecture Evolution** — Phases 123-136 (SHIPPED 2026-06-20; ECL + APR + signal hardening + clean replay + 3-table migration + type safety + post-reboot repair)
- ⏸️ **v2.8 AI Platform — Part 2** — Phases 096-099, 101-103 (unblocked; deprioritized until v3.0 validated)
- ✅ **v3.0 Intelligence Vectors — AlphaEngine** — Phases 137-140 (SHIPPED 2026-06-25; Feature Factory + IC Engine + Ensemble + Alpha Emission + IC Engine Correctness; full corpus run underway)
- 🔄 **v3.1 IC Empirical Proof + Counterfactual Scoring** — Phase 140.5 COMPLETE 2026-06-26; corpus pipeline COMPLETE 2026-06-28 (12.47M alpha_events); Phase 141 COMPLETE 2026-06-29; Phase A COMPLETE 2026-06-30 (ic_engine methodology fixes + Renaissance IC gate redesign); Phase B (corpus re-run on corrected engine) COMPLETE 2026-07-01 (3rd rebuild: feature_vectors 10.08M, feature_ic_scores 254,126, qualifying features 5m=37/15m=28/1h=15/1d=28); Phase 141.1 COMPLETE 2026-07-02 (measurement/decision integrity foundation — OOS enforcement, weight-epoch fix, regime_scope schema fix, cost-hurdle calibration); Phase 142A planned and unblocked, ready to execute (142A: ensemble IC proof; 142B: single primary frame counterfactual validation + SHADOW-REVIEW.md pre-commitment; no cost model, no UX) — see `docs/plans/2026-06-30-alphaengine-v1-execution-plan.md`
- 📋 **v3.2 Signal Diversification — AnalogEngine + Feature Expansion** — Phases 145-147 (planned; hard-gated on v3.1 OOS IC > 0 at 95% CI; Renaissance: more diverse weak signals, not stronger strong ones)
- 📋 **v3.3 Foundational Hardening** — Phases 148-149 (planned; scope TBD — review before v3.2 completes)
- 📋 **v4.0 Execution Layer** — Phases TBD (planned; hard-gated on v3.3 complete + alpha_events schema frozen; consumes alpha_events, never modifies signal weights)
- 📋 **v4.1 IC Governance + Drift Monitoring** — Phases 149A, 149B, 150 (regime-conditioned distribution drift + IC lifecycle shadow governance + ensemble health gates; replaces DataIntegrityMonitor + SystemHealthMonitor + PredictiveDecayDetector; see `docs/plans/2026-06-27-health-guardian-design.md`). 149A and 149B depend only on `feature_vectors`/`feature_ic_scores` (exist today) — no dependency on live alpha emission or v4.0. Only 150 (EnsembleHealthMonitor) depends on Phase 142A (`alpha_ensemble_ic`).

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

**Phases (Part 2 — re-evaluated 2026-06-25 post-v3.0 ship)**:

v3.0 (AlphaEngine) shipped and IC measurement now replaces binary signal scoring. These phases were designed for the v2.x signal-quality problem. Dispositions updated:

- Phase 096: Agent Registry — **REFRAME**: still relevant for narrative/swarm agents that persist in v3.0; scope to non-I7 agents only
- Phase 097: Zep Episodic Memory — **REFRAME**: lower priority; potentially useful as regime memory in AnalogEngine (Phase 145+); evaluate after AnalogEngine ships
- Phase 098: DSPy Offline Prompt Optimizer — **PARTIAL RETIRE**: I7 prompt optimization is irrelevant (I7 archived); narrative agent prompts still exist; scope DSPy to narrative/swarm agents only if parse failure rate justifies it
- Phase 099: Guardrails AI Validation — **RETIRE**: Instructor structured output shipped in Phase 094; adds no marginal value; parse failure rate on Instructor output is the gate that would have triggered this phase; remove from active planning
- Phase 101: Composite Fitness Function — **RETIRE**: designed for signal genetic operators under v2.x binary paradigm; IC measurement via ICEngine supersedes composite fitness scoring; remove from active planning
- Phase 102: Genetic Infrastructure — **RETIRE**: superseded by AlphaEngine IC measurement as the arbiter of signal quality; genetic evolution of I7 plugins no longer applies; remove from active planning
- Phase 103: Reproductive Operators — **RETIRE**: same as 102; remove from active planning

Phases 099, 101, 102, 103 are formally retired. Phases 096, 097, 098 remain in backlog with reduced/reframed scope.

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
<summary>✅ v2.10 Data Architecture Evolution — SHIPPED 2026-06-20</summary>

- [x] **Phase 123: ECL Boundary Restoration** — Complete (3/3 plans, 2026-06-14)
- [x] **Phase 124: Signal Universe Integrity + Cold-Start Hardening** — Complete (7/7 plans, 2026-06-14)
- [x] **Phase 125: APR Full Migration** — Complete (5/5 plans, 2026-06-15)
- [x] **Phase 126: Signal Universe Hardening** — Complete (6/6 plans, 2026-06-15)
- [x] **Phase 127: Clean Replay + Validation** — Complete (3/3 plans, 2026-06-17)
- [x] **Phase 128: 3-Table Schema Design and ADR** — Complete (3/3 plans, 2026-06-16)
- [x] **Phase 129: Database Migration** — Complete (3/3 plans, 2026-06-16)
- [x] **Phase 130: Script Rewriting** — Complete (7/7 plans, 2026-06-16)
- [x] **Phase 131: Signal Generation Integrity** — Complete (7/7 plans, 2026-06-17)
- [x] **Phase 132: Stop-Zone Geometry + APR Migration** — Complete (5/5 plans, 2026-06-18)
- [x] **Phase 134: Signal Classification Type Safety** — Complete (3/3 plans, 2026-06-18)
- [x] **Phase 136: Post-Reboot System Repair** — Complete (6/6 plans, 2026-06-19)
- ~~**Phase 133: Clean Corpus Rebuild**~~ — CANCELLED (superseded by v3.0 Intelligence Vectors; IC measurement runs on `intelligence_features`, not `signal_events`)

Full details: `.planning/milestones/v2.10-ROADMAP.md`

</details>

<details>
<summary>✅ Phase 131: Signal Generation Integrity — COMPLETE 2026-06-17</summary>

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
<summary>✅ Phase 132: Stop-Zone Geometry + APR Migration — COMPLETE 2026-06-18</summary>

**Goal:** Stops are measured from actual entry price (not zone edge), and every tunable numeric constant in `trade_framer.py` lives in APR. Verify `stopped_at_entry` exit_reason < 5% of stop exits on a fresh 1-month sample replay + lifecycle_replay.

**Verification gate:** 1-month sample replay + lifecycle_replay shows stopped_at_entry < 5%; 35 trade_framer APR keys (19 module + 12 adaptive buffer + 4 per-class floor) visible in `/config/parameters`; APR at seed values produces identical signals to prior constants (regression tests); no migratable bare literals in trade_framer.py; 1-tick gate preserved.

**Plans:** 5 plans

Plans:

- [x] 132-01-PLAN.md — A2 measurement: 2-week sample replay + lifecycle_replay, measure stopped_at_entry rate, audit zone_engine for narrow-zone bypass, write A2 disposition (Wave 1)
- [x] 132-02-PLAN.md — APR migration 144: 19 module-level constants → _cfg() + _THRESHOLD_KEYS; fix run_historical_pipeline.py config wiring gap; seed-value regression test (Wave 1)
- [x] 132-03-PLAN.md — APR migration 145: 12 adaptive buffer piecewise coefficients (coupled, tune-as-a-group); anchor-point regression test (Wave 2, depends 02)
- [x] 132-04-PLAN.md — APR migration 146: 4 per-asset-class stop floor keys (commodity 1.5, others 1.0) + _min_stop_multiplier_floor router; 1-tick gate preserved (Wave 3, depends 03)
- [x] 132-05-PLAN.md — Verification: 1-month replay + stopped_at_entry < 5% gate + 35-key audit + bare-literal audit + commit/push (Wave 4, depends 01-04)

</details>

<details>
<summary>✅ Phase 134: Signal Classification Type Safety — COMPLETE 2026-06-18</summary>

**Goal:** All classification columns in the signal ledger are type-enforced end-to-end. `SignalOutcome` persisted to `trade_executions.outcome` (eliminates re-derivation and the stopped_at_entry query bug). `EntryType` Python enum created (replaces 15+ string literals). PostgreSQL ENUM types enforce valid values at write time across all classification columns. No classification can be written silently with an invalid value, and no gate query can trivially pass by referencing a value that doesn't exist.

**Prerequisite gate:** Phase 132 complete (trade_framer APR migration done; signal ledger schema stable).

**Sequencing note:** Runs BEFORE Phase 133 (clean corpus rebuild). Phase 134 Plan 01 wires `lifecycle_replay.py` to write `outcome` directly — Phase 133's rebuild then writes outcomes in a single pass rather than requiring a backfill. Phase 134 Plan 03's PG ENUM constraints on `signal_events.status` and `trade_executions.outcome` enforce valid values at write time during the corpus rebuild.

**Plans:** 3 plans in 3 waves

Plans:

- [x] 134-01-PLAN.md — Persist SignalOutcome to trade_executions: add outcome column, wire lifecycle_replay, backfill historical rows (Wave 1)
- [x] 134-02-PLAN.md — EntryType enum: create Python enum, replace 15+ string literals in trade_framer.py, add DB CHECK constraint (Wave 2, depends 01)
- [x] 134-03-PLAN.md — PostgreSQL ENUM type sweep: convert exit_reason, outcome, entry_type, signal_events.status to PG ENUM types; remove phantom values; verification (Wave 3, depends 01+02)

</details>

<details>
<summary>📋 Phase 135: Controlled Vocabulary System — PLANNED</summary>

**Goal:** A central, reusable vocabulary and taxonomy registry — the APR equivalent for symbolic codes. Three DB tables (`controlled_vocabulary`, `vocabulary_group`, `vocabulary_group_member`), one `VocabularyService`, one `/api/vocabulary/{namespace}` endpoint. Any domain registers its enum vocabulary into a namespace; any consumer reads it without hardcoding. First consumer: dashboard signal filter dropdowns.

**Prerequisite gate:** Phase 134 complete (PG ENUM types in place; vocabulary seeding must reference values already enforced at the DB level).

**Sequencing note:** Independent of Phase 133 (corpus rebuild). Can run in parallel or after 133 — no shared schema dependencies. Should run before any dashboard or API work that needs filter dropdowns.

**Design doc:** `docs/ideas/controlled-vocabulary.md`

**Plans:** TBD (plan-phase to produce)

</details>

<details>
<summary>✅ Phase 136: Post-Reboot System Repair — COMPLETE 2026-06-19</summary>

**Goal:** Restore data integrity and pipeline correctness after 2026-06-18 reboot. Six work units: recover 1,343 orphaned intelligence_features rows (W1 replay), add feature_writer startup pre-flight schema check + JSONB write path fix (W2), fix intelligence pipeline graceful SIGTERM shutdown (W3), disable FVGFill plugin noise (W4), add validate_signal failure reason via ValidationResult NamedTuple (W5), fix plugin_utils ATR unit label + epsilon guard (W6).

**Prerequisite gate:** None — all fixes are self-contained. Must execute before Phase 133 (corpus rebuild) to ensure data integrity and clean signal generation.

**Sequencing note:** Runs before Phase 133. W2-W6 are code changes deployed together; W1 (replay) and Migration 130 Statement 3 are operational steps run after deploy.

**Design doc:** `docs/plans/2026-06-18-post-reboot-repair-design.md`
**Review:** `docs/plans/135-REVIEWS.md` (cross-AI review: Codex + Ollama)

**Plans:** 6 plans in 4 waves

Plans:

- [x] 136-01-PLAN.md — W6 ATR label fix + W5 ValidationResult NamedTuple (Wave 1, parallel)
- [x] 136-02-PLAN.md — W4 FVGFill disable + test sweep (Wave 1, parallel)
- [x] 136-03-PLAN.md — W3 intelligence_pipeline graceful SIGTERM (3a+3b+3c) (Wave 1, parallel)
- [x] 136-04-PLAN.md — W2 feature_writer pre-flight schema check + JSONB CTF-key exclusion (Wave 2)
- [x] 136-05-PLAN.md — W1 historical replay to recover 1,343 orphaned rows (Wave 3, depends 04)
- [x] 136-06-PLAN.md — Migration 130 Statement 3 JSONB cleanup (Wave 4, depends 04+05)

</details>

<details>
<summary>❌ Phase 133: Clean Corpus Rebuild — CANCELLED 2026-06-20</summary>

**Cancellation reason:** Superseded by v3.0 Intelligence Vectors architecture. IC measurement eventually runs on `intelligence_features` (all bars, no selection bias) rather than `signal_events` (only bars where a plugin fired). The binary corpus rebuild would have produced training data for the old paradigm — irrelevant once I7 plugins emit continuous scores. Phase 137 of v3.0 (IC measurement on existing signal_events corpus as exploratory baseline) replaces this phase.

Plans archived at: `.planning/milestones/v2.10-phases/` (directory removed from active phases)

</details>

<details>
<summary>✅ v3.0 Intelligence Vectors — AlphaEngine (Phases 137-140) — SHIPPED 2026-06-25</summary>

- [x] **Phase 137: Feature Factory** — 54-feature typed `feature_vectors` hypertable; `FeatureFactory.compute()`; `BaseBatch` Ring 0 base class; I5/I6/I7 archived (7/7 plans, 2026-06-21)
- [x] **Phase 138: IC Engine + Forward Returns** — Vectorized Spearman IC, circular-block-bootstrap CI, BH-FDR, 3-fold walk-forward, causal HMM regime labeling, forward returns via LEAD() (9/9 plans, 2026-06-23)
- [x] **Phase 139: Ensemble + Alpha Emission** — Ledoit-Wolf ensemble weights, IC-weighted alpha matmul, direction-aware CI gate, shadow `alpha_events` emission (3/3 plans, 2026-06-24; 14/14 verification truths)
- [x] **Phase 140: IC Engine Correctness** — Fix stride-per-scale bug, overnight gap contamination in forward returns, BH-FDR meta-level gate, feature collinearity clustering, IC Sharpe min_windows, OOM cleanup, training-window-end CLI arg (4/4 plans, 2026-06-25; 4 items deferred to todo 015)

Full details: `.planning/milestones/v3.0-ROADMAP.md`

</details>

<details>
<summary>📋 v3.0a Signal Integrity — IntegrityMonitor (Phases 149A, 149B, 150) — PLANNED</summary>

- [ ] **Phase 149A: DistributionDriftMonitor** — Regime-conditioned KS + chi-squared + signed Wasserstein on all 54 features; adaptive penalties (APR-scaled by Wasserstein magnitude); piggybacked recovery; `indicagent-integrity-monitor` service skeleton — see `docs/plans/2026-06-27-health-guardian-design.md`
- [ ] **Phase 149B: ICLifecycleMonitor** — Shadow governance: `active → shadow → active` (evidence-based, no cooldown); `pre_shadow_weight` restored on promotion; `shadow_corpus_runs` deprecation gate; rename `is_decaying → is_shadowed` — see `docs/plans/2026-06-27-health-guardian-design.md`
- [x] **Phase 150: EnsembleHealthMonitor** — 3-gate AND logic (E1: IC Sharpe, E2: regime-conditioned conviction stability, E3: non-shadow coverage); halt/reduce via APR keys; requires Phase 142A (`alpha_ensemble_ic`) — see `docs/plans/2026-06-27-health-guardian-design.md` (completed 2026-07-02)

**Dependencies:** Phase 142A (`alpha_ensemble_ic` table exists) for Phase 150 only; 149A and 149B independent

**Spec:** `docs/plans/2026-06-27-health-guardian-design.md` — replaces three prior idea docs

</details>

### Phase 140: IC Engine Correctness ✅ COMPLETE 2026-06-25

**Goal:** Fix seven correctness and methodology issues in the IC engine identified by first-principles review (todo 001). P0 issues must be resolved before the next corpus run. P2 item 6 (rolling HMM refit) is excluded — separate phase.

**Depends on:** Phase 139

**Issues addressed (ordered by impact):**

P0 — Correctness blockers:

1. Stride = max_lookahead applied to all scales — subsample per scale with `stride = lookahead_bars`
2. Overnight gap contamination in intraday forward returns — flag cross-session transitions, set `complete_{scale} = false`

P1 — Statistical methodology:

3. BH-FDR meta-level gate — require feature to pass FDR in >50% of (symbol, tf) cells for ensemble weight
4. Feature collinearity corrupts BH-FDR — hierarchical clustering on correlation matrix, one representative per cluster
5. IC Sharpe min_windows = 10 too low — raised `alpha.ic.sharpe_min_windows` to 30

P2 — Quick cleanups:

7. Remove `all_results_global` accumulation — list never read after loop
8. `--training-window-end` CLI arg — defaults to MAX with warning

**Deferred to todo 015:** 4 architectural cleanup items (service_utils + ic_engine shared-utility extraction)

**Plans:** 4 plans in 2 waves

Plans:

- [x] 140-P0-PLAN.md — P0 correctness (per-scale stride fix + ET session-boundary forward returns) + P2 cleanups
- [x] 140-P1-PLAN.md — Migration 171 (cluster_id column + alpha.ensemble.meta_fdr_min_fraction + alpha.ic.cluster_max_corr + sharpe_min_windows 10→30)
- [x] 140-P2-PLAN.md — Feature collinearity hierarchical clustering + representative-only BH-FDR + cluster_id persistence
- [x] 140-P3-PLAN.md — BH-FDR meta-level gate in ensemble_trainer (require feature to pass FDR in ≥50% of cells)

---

### Phase 140.5: Corpus Foundations + Feature Governance ✅ COMPLETE 2026-06-26

**Goal:** Five prerequisites that must exist before Phase 141 touches a single IC score: (1) fix silent constant features in the batch path so the corpus is clean, (2) validate HMM state count K before regime labels are trusted, (3) build the Feature Registry so the ensemble has lifecycle governance from day one, (4) replace per-symbol HMM with a cross-sectional equity regime model so IC stratification pools observations across symbols, (5) separate daily-cadence macro features into a `context_features` table so they do not inflate IC through artificial autocorrelation. None of these can be deferred to Phase 141 — they are Phase 141's foundation.

**Depends on:** Phase 140 complete (Phase 140.5 begins while the existing 58-symbol corpus pipeline runs in the background).

**Parallelism contract:** All plans run in parallel waves. Compute is CPU-bound and runs in `ProcessPoolExecutor` worker pools — never on the asyncio event loop. Persistence is fully async (`asyncpg`); DB writes are fire-and-forget where ordering permits. No plan blocks another except at hard data dependencies noted below.

---

**P1 — Batch Primitives Fix + Corpus Re-Run (todo 001)**

Three silent-constant groups remain in the batch path after Phase 139/140:

- **Group 2 (CTF):** `FeatureCache` has no `update_ctf_from_bars()`; batch path never loads HTF bars — `ctf_momentum/vwap_align/regime_align` stay at 0.000.
- **Group 3 (VP/SR):** Causal batch computation of `poc_dist_atr/va_position/sr_support_dist/sr_resist_dist` requires 1m intraday bars per session — architectural complexity not justified. Correct answer: `NULL`, not 0.000. Make columns nullable via migration; set `None` in `compute_batch()`.
- **Group 4 (HMM):** `compute_batch()` passes a hard 50-bar window to `refresh_regime()` — GaussianHMM on 50 bars either fails warmup (returns 0.000) or fits degenerate single-state (returns 1.000/0.000). Fix: pass full available history `bars[:i+1]`.

**Async/parallelism requirements:**

- `_compute_symbol_tf()` runs in `ProcessPoolExecutor` — pure CPU, no DB calls inside the worker. All DB reads (OHLCV history, HTF bars) fetched async before the worker call; all DB writes (feature_vectors upserts) buffered and flushed async after.
- HTF bar loading for CTF: async batch fetch per (symbol, htf) before compute loop, passed as an immutable dict into the worker. No DB calls inside `compute_batch()`.
- VP/SR `None` values: asyncpg accepts `None` natively for nullable float columns — no sentinel magic.
- Corpus re-run: `backfill_feature_factory --compute-only` with `--workers 12`; symbol-level parallelism via `ProcessPoolExecutor`. Re-seed `backfill_status` to `pending` before re-run (backfill_status gotcha — see memory).

**Output gate:** `std(ctf_momentum) > 0`, `std(hmm_regime_prob) > 0` across all (symbol, tf). `poc_dist_atr IS NULL` everywhere. No feature with `std = 0` except cross-sectional rank features and the 4 VP/SR columns.

---

**P2 — HMM State Count K via BIC (todo 002)**

The current corpus uses K=3 (hard-coded). K was never validated — it was a reasonable initial estimate. If K=4 better fits the data, all regime labels in `feature_vectors` are systematically wrong, and Phase 141's IC results stratify by the wrong regimes.

**Study design:**

- For each (symbol, tf), fit `GaussianHMM` for K ∈ {2, 3, 4, 5} on full available history (causal: no future data).
- Compute BIC: `BIC = -2 × log_likelihood + n_params × ln(n_obs)`. `n_params` for full covariance: `K × d + K × d(d+1)/2 + (K-1)` where d=5 (observation dimensions).
- Minimum BIC wins. Aggregate winner histogram across all (symbol, tf) pairs. If K=3 wins in ≥ 70% of cases, keep K=3. If another K wins decisively, update `alpha.hmm.n_components` APR key and re-run regime labels.

**Async/parallelism requirements:**

- BIC fitting is CPU-bound. One `ProcessPoolExecutor` task per (symbol, tf). No DB calls inside worker — OHLCV history fetched async before dispatch.
- Results written to a `bic_study_results` temp table (or CSV) via async batch INSERT after all workers complete. No per-row DB round-trips during fitting.
- If K changes: `regime_writer --refit` parallelized per symbol via `ProcessPoolExecutor`; async batch upsert of new regime labels into `feature_vectors`. P1 corpus re-run must complete before this step (hard dependency: needs fixed feature values for BIC fitting on clean data).

**Output gate:** BIC histogram documented. K decision recorded in APR with provenance `[bic_study_2026]`. If K unchanged, no re-run needed. If K changes, regime labels re-run completes before Phase 141 starts.

---

**P3 — Feature Registry + FeatureRegistryService (todo 008)**

The feature catalog is currently implicit — 61 fields on `FeatureVector`, no metadata, no lifecycle, no on/off switch. `feature_ic_scores` has no join surface for feature status. The ensemble trainer has no promotion gate. This is the governance layer that makes IC-driven feature lifecycle non-optional.

**Schema:** `feature_registry` (PK: `feature_name`; columns: `group_name`, `tier` {0_atomic/1_interaction/2_theory}, `formula_short`, `normalization`, `linear_ready`, `requires_htf`, `window_apr_keys[]`, `parent_features[]`, `status` {candidate/active/shadow_only/deprecated}, `min_ic_sharpe`, `min_ic_n`, `fdr_required`, `fdr_alpha`, `last_ic_*` snapshot, `added_phase`). `feature_transition_log` (append-only audit trail). DB trigger `trg_cascade_parent_deprecation` auto-demotes tier-1 children when a tier-0 parent is deprecated.

**FeatureRegistryService:** Async singleton (`asyncpg` pool). Loaded at daemon startup before the alignment gate runs. All reads go through the service — no direct `feature_registry` queries in application code. `get_active_features()`, `get_ic_sharpe_gate()` (per-feature override else APR floor), `record_transition()` (async, non-blocking).

**Startup alignment gate:** Crash-loud `RuntimeError` if `feature_registry` rows ≠ `FeatureVector` dataclass fields. Adding a feature = FeatureVector field + migration + registry INSERT — all three in the same migration. The gate enforces this at every startup.

**Async/parallelism requirements:**

- `FeatureRegistryService.load()` is a single async fetch at startup — one query, result cached in memory for the daemon lifetime.
- `record_transition()` is fire-and-forget async: caller does not `await` the DB write. Transition logging never blocks the compute path.
- IC engine integration: records `feature_status_at_eval` on every `feature_ic_scores` row. This is a single-column addition to the existing async batch INSERT — no separate round-trip.
- `EnsembleBuilder` filter: `WHERE status = 'active' AND feature_status_at_eval = 'active'` — added to existing async query, no new service calls.

**Seed:** Migration inserts all 61 current `FeatureVector` fields as `status = 'active'`. Theory-embedded features (`poc_dist_atr`, `va_position`, `sr_*`, `hmm_*`, `ctf_*`, `flight_quality`) seeded as `tier = '2_theory'`; all others as `tier = '0_atomic'`.

**APR keys (insert in same migration):** `alpha.feature_registry.min_ic_sharpe_default` (0.5 initial), `alpha.feature_registry.fdr_alpha` (0.05), `alpha.feature_registry.demotion_periods` (3).

**Ensemble weight aging (ship with P3):** Between weekly IC engine runs, ensemble weights are frozen. In fast-moving markets, IC can decay within days — frozen stale weights silently degrade the ensemble. Add one APR key (`alpha.ensemble.weight_half_life_days`, initial 30) and one line in `EnsembleBuilder`: `effective_weight(t) = ic_weight × exp(-days_since_ic_run / weight_half_life_days)`. At 30-day half-life, weights decay ~2.3% per day toward equal-weight. Reverts to equal-weight when IC data is 90+ days stale. No new service, no schema migration — one APR key and one formula.

**Output gate:** Registry row count matches IC-measurable `FeatureVector` fields. Alignment gate passes on IC engine and ensemble trainer startup. `FeatureRegistryService.get_active_features()` returns all 61 features. `feature_transition_log` is empty (no transitions yet). `record_transition()` verified non-blocking under concurrent IC engine load. Weight aging formula verified: `effective_weight` decreases monotonically with days elapsed.

---

**P4 — Cross-Sectional Equity Regime Model (todo 011)**

Per-symbol HMM produces incomparable regime labels across symbols — "trending_up" on SPY and "trending_up" on TLT are independent states with no shared meaning. IC stratification cannot pool observations across symbols within a regime cell. At 58 equity ETFs, per-symbol stratification means every IC regime cell has ~1× the observations it should; cross-sectional labels provide ~58× pooling. This is a correctness fix for IC statistical power, not an enhancement.

**Design:** One regime model for the equity universe, fitted on cross-sectional signals: VIX level (bucketed low/mid/high via APR percentile thresholds), SPY 50/200 MA breadth (% names above each), market-level realized vol z-score. Output: `market_regimes` table — `(asset_class TEXT, tf TEXT, ts TIMESTAMPTZ, regime_label TEXT, regime_prob_vector JSONB)`. PK: `(asset_class, tf, ts)`. IC engine joins on `(asset_class='equity', tf, DATE_TRUNC('minute', bar_ts))` instead of reading `feature_vectors.regime`. Per-symbol HMM features (`hmm_regime_prob_*`) remain in `feature_vectors` as predictive signals capturing idiosyncratic momentum — but are no longer the IC stratification key.

**Async/parallelism:** Single `ProcessPoolExecutor` task per tf — fits on equity breadth time series. Async batch upsert to `market_regimes` after worker completes. No DB calls inside worker.

**APR keys:** `alpha.regime.vix_low_pct` (0.33), `alpha.regime.vix_high_pct` (0.67), `alpha.regime.breadth_bear` (0.40), `alpha.regime.breadth_bull` (0.60) [all `initial_estimate`]. `alpha.regime.equity_model_enabled` (true) — allows revert to per-symbol HMM if cross-sectional model fails Phase 141 validation.

**Hard dependency:** Must complete before Phase 141 IC engine re-run. CORPUS-04 IC discovery report must use cross-sectional regime labels.

**Output gate:** `market_regimes` populated for all (tf, bar_ts) in `feature_vectors` date range. IC engine reads regime from `market_regimes` join. Phase 141 CORPUS-04 produces regime-stratified IC scores that pool across symbols.

---

**P5 — Context Features Table (todo 013)**

`feature_vectors` is one row per (symbol, tf, bar_ts). Features without a natural bar cadence (VIX level, yield curve, macro indicators, cross-asset correlations) currently inject daily values into every 5m bar row for the same calendar day. A VIX reading at 9:30 and 9:35 are not two independent observations — they are the same observation duplicated 78 times per day. This inflates Spearman IC for any feature correlated with VIX via artificial autocorrelation. The IC engine's existing NaN/independence stride correction does not fix this — it corrects temporal dependence within a series, not cross-row duplication.

**Schema:**

```sql
context_features (
  feature_date  DATE,
  feature_name  TEXT,
  symbol        TEXT NULL,   -- NULL for market-wide (VIX, yield curve)
  value         DOUBLE PRECISION,
  source        TEXT,        -- 'ibkr', 'fred', 'derived'
  computed_at   TIMESTAMPTZ,
  PRIMARY KEY (feature_date, feature_name, COALESCE(symbol, ''))
)
```

IC engine joins `feature_vectors` with `context_features` via `DATE(bar_ts) = feature_date`. TF-native features pull from `feature_vectors` at bar cadence; daily-cadence features pull from `context_features` with one observation per calendar day — the IC engine treats them at their true observation frequency. Affected features (move out of `feature_vectors`): any macro series updated daily or less frequently. Cross-asset correlation features computed at daily horizon.

**IC gate for daily-cadence features:** The 20K independent observation gate was calibrated for intraday bar data. Daily-cadence features (VIX, yield curve, macro indicators) have ~252 obs/year; at 5 years of history that is ~1,260 observations — structurally below the 20K gate. Add APR key `alpha.ic.min_obs_daily_features = 1000` [initial_estimate, ~4 years daily data] applied exclusively to features read from `context_features`. Document the tradeoff: lower statistical power, wider bootstrap CI, higher type-II error risk. Do not apply the 20K gate to daily-cadence features — it was not calibrated for that observation frequency and will permanently block these features from IC measurement.

**Hard dependency:** Build schema before Phase 141 CORPUS-01 audit. CORPUS-01 will flag near-constant variance in duplicated daily features — the fix is migration to `context_features`, not ignoring the flag.

**Output gate:** IC engine accepts `context_features` as join input with separate gate applied. CORPUS-01 shows no duplicated daily-cadence features with artificial autocorrelation in `feature_vectors`. Per-feature IC measurement uses the correct observation frequency and the correct gate for its cadence.

---

**Wave structure:**

- Wave 1 (parallel): P1 code fixes + P3 migration/service build + P5 context_features schema. No dependencies between them.
- Wave 2: P1 corpus re-run (requires P1 fixes). P4 cross-sectional regime model fitting + `market_regimes` population (requires clean corpus). P2 BIC study (requires clean corpus — hard dependency).
- Wave 3: P2 regime label re-run if K changes (requires BIC decision). P3 IC engine + ensemble trainer integration + weight aging (requires P3 registry from Wave 1). P4 IC engine regime-join wiring (requires P4 model from Wave 2). P5 IC engine context-features join (requires P5 schema from Wave 1).

**Plans:** 5/5 plans complete

Plans:

- [x] 140.5-P1-PLAN.md — Batch Primitives Validation + Corpus Re-Run
- [x] 140.5-P2-PLAN.md — HMM K via BIC Study + Conditional Regime Re-Run
- [x] 140.5-P3-PLAN.md — Feature Registry Schema + FeatureRegistryService + IC/Ensemble Integration
- [x] 140.5-P4-PLAN.md — Cross-Sectional Equity Regime Model + market_regimes + IC Engine Wiring
- [x] 140.5-P5-PLAN.md — Context Features Table + context_features_writer + IC Engine Join

---

## v3.1 AlphaEngine Validation + Alpha Scoring (Phases 140.5-144)

**Milestone Goal:** Validate that AlphaEngine produces real, measurable edge on the full 58-symbol corpus. Close the intelligence feedback loop: alpha_events → hypothetical trade lifecycles → counterfactual P&L → scoring system that proves (or disproves) the engine produces alpha. Retire v2.x after gate-validated superiority. Portfolio construction (Kelly sizing, VaR, IBKR execution) is explicitly out of scope — that is v4.0.

**Input/output contract:** This milestone's output is a scored intelligence engine. `alpha_events` is the output contract. Anything that consumes `alpha_events` for live execution belongs in v4.0.

**Hard prerequisite:** Phase 141 corpus validation must pass ALL gate criteria before Phase 142 begins. No scoring work on unvalidated IC — this is the Simons rule.

---

### Phase 141: Corpus Quality Gate + IC Validation + HMM JIT ✅ COMPLETE 2026-06-29

**Plan:** `docs/plans/2026-06-28-validity-fixes-and-phase-141.md` (Tasks 1-10)
**Obstacle map:** `docs/plans/2026-06-28-renaissance-obstacle-map.md`

**Goal:** Fix two validity threats in the corpus, rerun affected pipeline steps, validate IC on the clean corpus, and ship HMM Numba JIT (40x speedup needed before primitives expansion).

**Prerequisite validity fixes (before any CORPUS task runs):**

- **V3 — BaseBatch JSONB codec** (Task 1-2): `BaseBatch._setup_pool` calls bare `asyncpg.create_pool` without codec registration; `alpha_publisher` works around it with `json.dumps()` — CLAUDE.md violation and latent corruption vector. Fix: `database_manager.create_pool`. Atomic two-file commit.
- **V1 — equity_regime_model look-ahead bias** (Tasks 3-5): `_compute_vix_pct_rank` uses `.rank(pct=True)` over full corpus — global rank knowing all future values. Fix: causal expanding rank via `bisect`. Also fix TF-normalized windows (V1b). Then rerun market_regimes → ic_engine --cross-sectional-only → ensemble_trainer → alpha_publisher (Task 6).
- **Note on V2 (cost-aware net scoring):** Deferred — `alpha_score` is in weighted z-score product units, not return units. Cost subtraction requires `IC × return_scale` calibration from Task 7.5. V2 gets its own plan after Phase 141.

**Scope additions vs original plan:**

- Task 7.5 produces V2 IC calibration constants (ic_x_return_scale per tf/regime)
- Tasks 8-10: HMM Numba JIT — `src/intelligence/hmm_jit.py` + wire into `regime_writer.py` (runs in parallel with CORPUS analysis tasks; needed before primitives expansion)

**Depends on:** Phase 140.5 complete — clean corpus (P1), validated K (P2), Feature Registry live (P3).

**Requirements (all must pass before Phase 142 starts):**

**CORPUS-01 — Feature distribution audit:**
Every feature in `feature_vectors` passes: (a) variance > epsilon (no silent constants), (b) NaN rate < 5% post-warmup, (c) no distributional cliff (rolling mean/std stable within 2σ across time). Audit runs as a one-shot script; output is a per-feature quality table. Features failing (a) are blocked from IC measurement. Features failing (b) or (c) are flagged with warnings but not blocked — the IC engine's existing NaN exclusion handles them.

**CORPUS-02 — OOS holdout split:**
The most recent 6 months of data in `feature_vectors` is designated as the OOS test set. No IC is measured on this window during Phase 141 or Phase 142. Walk-forward validation uses data prior to the OOS boundary only. OOS boundary stored in APR as `alpha.validation.oos_start` (timestamptz). IC measured in-sample; OOS used for final validation at Phase 142 exit gate only.

**CORPUS-03 — Null model baseline (OOS window only):**
Compute equal-weight ensemble alpha (all features weighted 1/N, no IC gate) on the OOS holdout established in CORPUS-02. Compute IC-weighted ensemble alpha on the same OOS window — weights derived in-sample, applied to OOS bars with no leakage. Gate: IC-weighted ensemble IC Sharpe must exceed equal-weight IC Sharpe on OOS data by > 0.1. Running this comparison in-sample is trivially favorable by construction — IC weights were fit on that data. The only meaningful test is OOS generalization. If IC weighting does not beat equal-weight on OOS, the weights are overfit — diagnose before proceeding.

**CORPUS-04 — IC discovery report (58-symbol):**
Re-run IC engine on full 58-symbol corpus. Report: features surviving BH-FDR by regime × TF × lookahead. Document the explicit decision tree:

- ≥ 15 features survive → proceed to Phase 142 as designed
- 5-14 features survive → proceed but note ensemble effective_N will be low; adjust min_effective_n APR key
- < 5 features survive → STOP, diagnose before Phase 142 (root cause: overfitting? corpus quality? wrong features?)

**CORPUS-05 — IC Sharpe stability:**
For features surviving BH-FDR, IC Sharpe across walk-forward folds must not oscillate (min/max fold IC Sharpe ratio < 3×). High variance IC = regime-specific, not structural. Features failing stability are downweighted, not promoted.

**CORPUS-06 — Per-regime observation floor:**
Every (symbol, tf, regime) cell that produces an IC score must meet `n_independent_obs >= alpha.ic.min_obs_per_regime` (APR, initial: 3000 `[initial_estimate]`). IC scores from minority-regime cells below this floor are excluded from the meta-FDR gate and ensemble weighting regardless of p-value — Spearman IC Sharpe on fewer than ~3K independent observations is too noisy to survive BH-FDR meaningfully. APR key inserted in Phase 141 migration. Cross-sectional regime labels from Phase 140.5 P4 make this floor easier to satisfy by pooling observations across symbols.

**Plans:** 1/4 plans executed

---

### Phase 141.1: Measurement and Decision Integrity Foundation ✅ COMPLETE 2026-07-02

**Goal:** Make everything that feeds ensemble IC measurement — and any future decision/action layer built on top of it — causal, provenance-tracked, and honestly calibrated, before Phase 142A measures OOS ensemble IC on top of it. Full rationale and verification: `.planning/research/2026-07-02-v3-bottomup-audit.md` (Fable 5) §5.3-5.6, cross-checked against the live codebase 2026-07-02.

1. **OOS holdout enforcement.** `alpha.validation.oos_start` has zero readers anywhere in `src/`/`services/`/`scripts/` today — the corpus orchestrator derives `TRAINING_WINDOW_END` as bare `SELECT MAX(bar_ts) FROM feature_vectors`, no holdout at all. Implement: `TRAINING_WINDOW_END = min(MAX(bar_ts), alpha.validation.oos_start)`, plus a separate, rare, pre-committed OOS evaluation step. This is the single most important rigor gap found — proving "ensemble IC > 0" without it would be a hollow gate.
2. **Weight-epoch / silent-retrain fix.** `ensemble_weights` and `ensemble_alpha` both use `ON CONFLICT ... DO NOTHING` keyed partly on a static APR `weight_version='v1'`. Re-running the trainer after IC scores change silently keeps the stale weights — no error, no warning. Fix via real per-run epoch identity (minimal version: derive/increment `weight_version` per run rather than a static APR string; full `corpus_runs`/`run_id` lineage threading is a separable follow-on hardening item, not required here).
3. **`regime_scope` schema fix.** `feature_ic_scores.regime` mixes 9 cross-sectional labels and 5 per-symbol HMM labels in one column with no scope qualifier. Add a `regime_scope` column disambiguating `symbol_hmm` vs `cross_sectional`. Note: the bottom-up audit's original claim that both label sources were look-ahead was partially wrong and corrected 2026-07-02 — `equity_regime_model.py`'s VIX-proxy and breadth computations are already causal (fixed under todo 026 P1a; the module docstring was just stale and has been corrected). Only the schema-ambiguity concern stands here. The per-symbol HMM's full-history-fit concern remains separately tracked under todo 026 — not duplicated in this phase.
4. **Cost hurdle calibration.** `alpha.quant.cost_hurdle.*` APR keys are all `0.0` today — a real no-op gate. 98.3% of current `alpha_events` sit in the 5m/15m band todo 030 already found net-negative-to-marginal after external costs. Run todo 030's Step 0 calibration here so `alpha_events` reflects a real tradeable population before Phase 142B's frame simulation runs on it.

**Requirements**: TBD — no REQUIREMENTS.md for this project
**Depends on:** Phase 141 complete (done). Phase B corpus re-run completed 2026-07-01; these fixes apply to the corpus pipeline scripts and take effect on the next re-run after Phase B.
**Plans:** 4/4 plans complete

**Wave 1** (parallel — no shared files):
- [x] 141.1-01 — OOS holdout enforcement: `TRAINING_WINDOW_END = LEAST(MAX(bar_ts), oos_start)` in the corpus orchestrator, plus a pre-committed, strictly read-only OOS evaluation script
- [x] 141.1-02 — `regime_scope` schema (migration 192): NOT-NULL CHECK column (`cross_sectional` / `symbol_hmm` / `pooled`) on `feature_ic_scores`, written from all 3 `ic_engine.py` insert paths
- [x] 141.1-03 — Cost hurdle calibration: implements todo 030 Steps 0-3, writes empirical `alpha.quant.cost_hurdle.*`/`threshold.*` via `ConfigService.set` (audited)

**Wave 2** *(depends on Wave 1 — plan 04 shares `ops_corpus_pipeline_run.sh` with plan 01)*:
- [x] 141.1-04 — Weight-epoch fix (migration 193): `DO NOTHING → DO UPDATE SET` on both `ensemble_weights`/`ensemble_alpha` writes, per-run `WEIGHT_EPOCH` threaded to `ensemble_trainer` + `alpha_publisher`, folds in todo 043 (90-day cliff → APR)

Cross-cutting constraints: none (each plan touches a disjoint file set except the declared 01→04 dependency).

### Phase 142A: Ensemble IC Measurement 📋 PLANNED

**Schema design:** `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — `alpha_ensemble_ic` table + `alpha.ensemble_ic.*` APR keys. Migration must land before this phase begins.

**Goal:** Prove the ensemble OUTPUT has IC before testing any execution rules. Measure `IC(alpha_score, forward_return_*)` per (symbol, tf, regime, lookahead) using the same BH-FDR + bootstrap CI + walk-forward machinery as feature IC. No stops, no targets, no frame assumptions — pure signal measurement. The IC decay curve across lookaheads calibrates `hold_max_bars` APR keys empirically. This is the primary OOS gate for Phase 144.

**Depends on:** Phase 141.1 complete (Measurement and Decision Integrity Foundation — OOS enforcement, weight-epoch fix, regime_scope schema fix, cost hurdle calibration; inserted 2026-07-02 so this phase's IC measurement isn't done in-sample or against ambiguous regime labels). `alpha_events` accumulating (Phase 139 running). `forward_returns` populated (Phase 138).

**Why before frame simulation:** If `alpha_score` does not predict forward returns, no frame definition will save it. You'd be measuring the frame, not the signal — a silent wrong answer. Signal proof must precede execution proof.

**Requirements:**

**EIC-01 — EnsembleICEngine (weekly oneshot, `BaseBatch`):**
Reads `alpha_events` joined to `forward_returns` on (symbol, tf, bar_ts). Computes Spearman IC(alpha_score, forward_return_fast/mid/slow/extended) per (symbol, tf, regime). Applies same BH-FDR correction, circular-block-bootstrap 95% CI, and 3-fold walk-forward as `ICEngine`. Writes to `alpha_ensemble_ic`. Parallelized: one `ProcessPoolExecutor` task per (symbol, tf) — CPU-bound IC computation fully decoupled from async DB reads/writes.

**EIC-02 — IC decay curve analysis:**
For each (symbol, tf, regime), find the first lookahead where IC Sharpe drops below `alpha.ensemble_ic.decay_threshold`. Update `alpha.frame.hold_max_bars.<regime>.<tf>` APR keys to match. This replaces initial estimates with data-derived values before Phase 142B runs any frames.

**EIC-03 — Walk-forward stability gate:**
IC Sharpe max/min fold ratio < 3× across walk-forward folds. Features with high IC variance are regime-specific, not structural. Gate written to `alpha_ensemble_ic.walk_forward_stable` — Phase 144 OOS validation reads this column.

**EIC-04 — Phase gate (hard):**
`ic_ci_lower > 0` at 95% CI on in-sample data in at least `alpha.ensemble_ic.min_qualifying_fraction` of (symbol, tf, regime) cells before Phase 142B begins. APR key seeded at 0.60 `[initial_estimate]` — no empirical basis yet, recalibrate after first run reveals how many cells have sufficient N. If gate fails, run EIC-05 diagnosis before any changes.

**EIC-05 — Gate failure diagnosis script:**
When EIC-04 fails, run structured diagnosis (output as a markdown report) before any remediation:

1. N per cell — low N (`< alpha.ic.min_obs_per_regime`) = data starvation, not signal absence; expect more cells to pass as alpha_events accumulates
2. Pooled vs per-symbol IC gap — if pooled `ic_ci_lower > 0` but per-symbol fails = regime label granularity issue (cross-sectional label too coarse for per-symbol variation)
3. TF breakdown — if 1h passes but 5m fails = TF-specific problem (5m has fewer independent obs per regime), not a global ensemble problem
4. Regime coverage — if ≥ 3 regimes have zero qualifying cells = regime label quality issue (check `market_regimes` coverage and `equity_regime_model` correctness)

This script ships with Wave 2. "Diagnose ensemble" without this structure wastes a week chasing the wrong layer.

**Plans:** 2/2 plans complete

Plans:
**Wave 1**

- [x] 142A-01-PLAN.md — Wave 1: migration 187 (alpha_ensemble_ic hypertable + APR seeds + 36 hold_max_bars keys) + EnsembleICEngine service (BaseBatch, compose ic_engine Fisher-z math, ProcessPoolExecutor compute-only, corpus BH-FDR, 9-regime stratification) + service_auditor registration + 5 unit test files (EIC-01, EIC-03)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 142A-02-PLAN.md — Wave 2 (depends on 142A-01): EIC-02 decay-curve to hold_max_bars APR calibration + EIC-04 gate script (threshold from APR, not baked in) + EIC-05 diagnosis script (4-section markdown report) + 2 unit test files

---

### Phase 142B: Frame Simulation + Counterfactual Tracking 📋 PLANNED

**Schema design:** `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — `alpha_frames` table + `alpha.frame.*` APR keys. No cost model (`alpha.cost.*`) — real cost data (slippage, commission) does not exist until v4.0 execution; cost model belongs there.

**Goal:** Prove that a reasonable execution rule (stop/target/hold) can capture the signal IC proven in Phase 142A as positive counterfactual P&L. This is a binary question: does any sensible frame work? Calibration of which frame variant is optimal is a refinement question that belongs after this validation passes, not during it. This is the secondary OOS gate for Phase 144.

**Depends on:** Phase 142A complete — EIC-04 gate passed, `hold_max_bars` APR keys calibrated from EIC-02 decay curve.

**Renaissance pre-commitment (ships at Phase 142B launch, before shadow emissions start):**
Write `docs/plans/SHADOW-REVIEW.md` — a one-page document committed to the repo before any counterfactual data is collected, specifying the exact numeric criteria required for Phase 144 live promotion. Criteria are defined before you can see the data; they are not negotiated post-hoc. Proposed criteria (final values committed in the document):

- ≥ 60 trading days of closed alpha_frames (primary variant)
- `mean(counterfactual_pnl_r) > 0` at 95% CI (bootstrap, one-tailed) on OOS data
- Sharpe of counterfactual_pnl_r > 0.5 annualized
- Max drawdown of cumulative counterfactual_pnl_r < 25%
- EnsembleICEngine IC Sharpe stable across the shadow period (no cliff in last 20 days)

Post-hoc gate negotiation ("the numbers were close, lower the threshold") is not permitted. If the gate fails, diagnose — don't renegotiate.

**Requirements:**

**FRAME-01 — AlphaFrameWriter (nightly oneshot, `BaseBatch`):**
For each `alpha_events` row, writes one `alpha_frames` row with `frame_variant='primary'`. Stop at `alpha.frame.stop_atr_mult` (APR, default 1.5 `[initial_estimate]`); target at `alpha.frame.target_r_multiple × stop_distance` (APR, default 2.0 `[initial_estimate]`); hold horizon from `alpha.frame.hold_max_bars.<regime>.<tf>` calibrated by EIC-02. Fully async: single batch INSERT per symbol/tf chunk. No per-row DB round-trips.

**FRAME-02 — CounterfactualTracker (nightly oneshot, `BaseBatch`):**
Reads open `alpha_frames`. For each: fetch T+1 open → populate geometry (`entry_price`, `stop_price`, `target_price`, `r_multiple`). Scan subsequent bars via single range query per (symbol, tf, bar_ts_range) — no per-bar queries. Write outcome in single async batch upsert. Parallelized per symbol via `ProcessPoolExecutor`; DB writes fire-and-forget async after all workers complete.

Exit triggers in priority order: (1) stop hit (`low <= stop_price`); (2) target hit (`high >= target_price`); (3) `hold_max_bars` exceeded — closes at bar where `bars_elapsed >= alpha.frame.hold_max_bars.<regime>.<tf>`, values data-derived from EIC-02 IC decay curve; (4) IC-decay trigger — `alpha_ensemble_ic.ic_ci_lower < 0` for this (symbol, tf, regime) in the most recent weekly IC engine run. Bar-level alpha score sign reversal is NOT an exit trigger — at intraday resolution it is noise, and using it produces excessive turnover that destroys net returns. The IC-decay trigger (4) operates at weekly IC engine cadence, providing a signal-based early exit without bar-level churn.

**FRAME-03 — Frame lifecycle state machine:**
`open → closed_stop | closed_target | closed_max_hold | closed_ic_decay`. Single UPDATE per transition. Immutable once closed. `closed_reversal` (bar-level alpha sign flip) deliberately excluded — this is a noise-driven exit at intraday resolution. `closed_ic_decay` is the correct signal-based early exit, triggered by the weekly IC engine detecting `ic_ci_lower < 0` for the frame's (symbol, tf, regime) cell.

**FRAME-04 — Phase 142B exit gate:**
`mean(counterfactual_pnl_r) > 0` at 95% CI (bootstrap, one-tailed) on in-sample closed frames with N ≥ `alpha.scoring.min_strategy_n` per (tf, regime) cell. If gate passes: proceed to Phase 143 and begin accumulating OOS data toward SHADOW-REVIEW.md criteria. If gate fails: frame geometry problem — diagnose stop/target/hold calibration against IC decay curve from EIC-02 before touching the ensemble. Do not look at signal quality; that was proven in Phase 142A.

**Services to build:** `AlphaFrameWriter` (`BaseBatch`), `CounterfactualTracker` (`BaseBatch`).

**Plans:** 2 plans (Wave 1: AlphaFrameWriter + SHADOW-REVIEW.md pre-commitment; Wave 2: CounterfactualTracker + state machine + gate evaluation)

---

### Phase 142B.1: Ensemble Weighting Methodology 📋 PLANNED (INSERTED)

**Goal:** Replace `ensemble_trainer.py`'s IC-proportional weighting with better-validated alternatives, judged by Phase 142A's `EnsembleICEngine` on OOS data. Full rationale: `.planning/research/2026-07-01-v3-architecture-review.md` §2, §6.

- **E1 — shrunk-IC inputs.** Rides on todo 029's `ic_shrunk` column; consume it instead of raw `ic_sharpe_hac`. Do first — corrects decisions being made today and gives every later variant a de-noised baseline.
- **E2 — mean-variance combination.** `w ∝ Σ⁻¹·IC` using the Ledoit-Wolf covariance `ensemble_trainer.py` already computes but currently only uses for a binary correlation-cluster cap. Textbook Grinold-Kahn combination; gate on covariance condition number.
- **E3 — hierarchical partial pooling** for sparse regime strata. Deferred pending E1/E2 proving insufficient — do not amend the "pooled IC is diagnostic only" load-bearing decision (STATE.md) until then.
- **E4 — per-feature decay half-lives**, replacing the single global `weight_half_life_days`. Sequence after todo 029's decay-curve item ships.

Every variant is a new `weight_version` in the existing `ensemble_weights` PK — zero schema change needed for A/B testing. First commit folds in todo 043 (APR-backed ensemble stale-weight cliff — `ensemble_trainer.py:509` hardcodes `if days_since > 90` while its sibling `weight_half_life_days` is already APR-backed).

**Requirements**: TBD — break down at plan time
**Depends on:** Phase 142A complete (not 142B — 142A's ensemble IC measurement is the judge; kept separate from 142B's frame simulation work, which this phase does not need)
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 142B.1 to break down)

### Phase 143: Feature Vector Lifecycle + Alpha Decay Infrastructure 📋 PLANNED

**Goal:** Features that lose IC must be demoted automatically. Demotion mechanics close the open-ended ensemble: features enter through IC gate, exit through decay gate. Alpha Decay Monitor runs daily, detects cell-level IC collapse, triggers EnsembleBuilder re-solve. Regime-shift guard prevents mass zeroing during market dislocations.

**Depends on:** Phase 141 complete (`feature_ic_scores` populated). LIFECYCLE-01..06 read `feature_ic_scores` only — no dependency on `alpha_frames` or Phase 142A/142B.

**Requirements:**

**LIFECYCLE-00 — HMM Regime Label Validation (todo 026 P1-P3):** LIFECYCLE-04's regime-shift
guard is only as trustworthy as the regime labels it reads, so this ships first, same phase.
Plan: `docs/plans/2026-06-28-hmm-regime-audit-optimization.md`. P1a/P1b: fix look-ahead bug in
cross-sectional VIX proxy (expanding rank) and TF-normalize the VIX z-score/200MA windows
(`equity_regime_model.py`). P2a/P2b/P2c: multiple HMM restarts picking max log-likelihood,
degenerate-model detection (occupation-fraction gate), regime-churn feature (`hmm_churn`
column) in `regime_writer.py`. P3: empirical threshold calibration for the vix/breadth cuts via
APR. Also run todo 034's Step 1 baseline-separation query (regime-IC gap by label) against this
corpus run before trusting LIFECYCLE-04 in production — gap < 0.01 escalates to root-cause
analysis per todo 026's P4a decision gate; gap > 0.05 means labels are fine, no further action.
Effort 3-5 days, no gate, P0 (Numba) already shipping separately in Phase B.

**LIFECYCLE-01 — Feature state machine:**
States: `candidate` → `active` → `decaying` → `deprecated`. Transitions:

- `candidate → active`: IC Sharpe gate passes (existing Phase 139 logic, already wired)
- `active → decaying`: IC Sharpe drops below `alpha.ic.decay_ic_sharpe_threshold = 0.0` OR `ic_ci_lower < 0` in rolling window; `decay_detected_at` populated
- `decaying → active` (recovery): `recovery_eligible_at` must have passed (cooldown) AND IC re-passes gate with `>= alpha.ic.decay_recovery_min_observations = 2000` new independent observations; recovery re-solve uses current data only, no partial restore
- `active/decaying → deprecated`: manual operator action only; requires explicit reason in `config_history`

Schema already has `is_decaying`, `decay_detected_at`, `recovery_eligible_at` columns — nothing reads or writes them. This phase wires the state machine.

**LIFECYCLE-02 — Ensemble query enforcement:**
EnsembleBuilder filters: `WHERE is_decaying = false AND feature_name NOT IN (SELECT feature_name FROM feature_deprecations)`. Weight re-solve triggered on any state transition.

**LIFECYCLE-03 — Alpha Decay Monitor (daemon):**
Daily scan of `feature_ic_scores` rolling window per (feature, symbol, tf, regime). Flags cells where rolling IC Sharpe drops below threshold. Writes `is_decaying = true` to `feature_ic_scores`. Triggers `EnsembleBuilder` re-solve if any materiality threshold crossed: `weight × |ic_ci_lower| > alpha.decay.materiality_threshold = 0.005` (prevents re-solve on negligible-weight features). OTel metrics: `alpha_decay_cells_flagged`, `alpha_decay_ensemble_rebuild_total`. **Refinement candidate (todo 029, 2026-07-01 review):** the flat IC-Sharpe threshold here is a blunt instrument compared to todo 029's IC decay curve (per-feature predictive half-life) — consider reading the decay curve's estimated half-life as an additional signal alongside the threshold rather than a bare cutoff, once todo 029's near-term items ship. Not a blocker for this phase; the threshold approach ships first, decay-curve refinement is additive. **Initial candidate list:** todo 033's 7 zero-IC features (momentum_rank_z, volume_rank_z, volatility_rank_z, poc_dist_atr, va_position, sr_support_dist, sr_resist_dist) are the natural first cells to run through this state machine once it's wired — but per todo 033's 2026-07-01 update, don't treat their current zero-IC readings as final until the todo 034/026 regime-label validation (below) has run, since 3 of the 7 are regime-stratified cross-sectional-rank features.

**LIFECYCLE-04 — Regime-shift guard:**
If ≥ `alpha.decay.regime_shift_fraction = 0.60` of active feature-regime cells decay simultaneously, classify as market regime shift — hold all weights rather than mass-zero. Emit `alpha_decay_regime_shift_total` counter. Human review before any weight changes during a regime-shift event. Depends on LIFECYCLE-00 (above) having run first.

**LIFECYCLE-05 — IC/ensemble coherence contract:**
IC engine runs weekly. Decay monitor runs daily. Contract: decay monitor reads rolling IC computed from the most recent IC engine run (0-7 days stale). This is acceptable given IC Sharpe has a daily resolution anyway; the 7-day lag is documented as the decay detection SLA. Decay monitor SLA = "detects decay within 7 days of IC engine run after collapse."

**IC staleness alerting (ships with Phase 143):** Add APR key `alpha.ic.staleness_alert_days = 5` [initial_estimate]. Decay monitor emits OTel gauge `ic_engine_last_run_age_days` on every daily run. Alert rule: if `ic_engine_last_run_age_days > staleness_alert_days`, fire `IC_ENGINE_STALE` alert to Alertmanager. Without this, a missed IC engine run silently degrades decay detection for up to 14 days before anyone notices.

**LIFECYCLE-06 — Decay diagnostics:**
Query `feature_ic_scores` directly via SQL for decay analysis. No dashboard infrastructure until the decay system has been validated in production. SQL queries for the key questions (which features are decaying, in which regimes) are documented in `docs/analysis/feature-decay-queries.sql` and run ad-hoc. Superset dashboard deferred until Phase 143 state machine has operated for ≥ 30 days and the query patterns are stable.

**Plans:** 4 plans (Wave 0: HMM regime label validation [LIFECYCLE-00]; Wave 1: state machine + EnsembleBuilder filter; Wave 2: AlphaDecayMonitor daemon; Wave 3: regime-shift guard + gate evaluation)

---

### Phase 143.5: I7 Alpha Scorer Transition 📋 PLANNED (Conditional on CORPUS-07)

**Conditional gate:** Phase 143.5 does not begin until Phase 141 CORPUS-07 is complete and evaluated. CORPUS-07 maps each I7 plugin to its constituent `feature_vectors` dimensions and determines whether the plugin introduces information not captured in the 54 atomic features. If CORPUS-07 shows ≥ 80% of plugins are fully captured (no marginal IC beyond existing features), Phase 143.5 scope collapses to retirement-only — no conversion infrastructure is built. Only build the alpha-scorer conversion layer if CORPUS-07 reveals material uncaptured information that justifies the added complexity.

**Default path is retirement, not conversion.** The 54 features were designed to capture I7 signals. Conversion is the exception; retirement is the rule.

**Goal:** For plugins with confirmed marginal IC beyond feature_vectors, convert from binary emitters to continuous alpha scorers (`alpha_score = raw_confidence × direction` every bar, no fire/no-fire decision). This is the structural prerequisite for Phase 144's retirement gate: a binary v2.x signal vs. a continuous v3.0 alpha score cannot be compared on outcome quality — the comparison surface requires both systems to produce continuous scores.

**Depends on:** Phase 141 CORPUS-07 evaluated (see Conditional gate above). No dependency on Phase 143.

**Design doc:** `docs/plans/2026-06-20-i7-alpha-scorer-transition.md` (canonical — read before planning)

**Requirements:**

**I7-01 — Plugin emission layer removal + IC-informed retirement decisions:**
For each active I7 plugin, analyze which dimensions in `feature_vectors` encode the same information (by inspecting plugin code directly during this phase) and combine with IC discovery results from Phase 141 CORPUS-04. For each plugin apply one of three outcomes:

- **Retire (default):** Plugin's constituent dimensions are fully captured in `feature_vectors` OR no constituent feature has confirmed IC. Mark `status='deprecated'` in `shadow_registry`, add retirement reason to `config_history`. This should be the outcome for the majority of plugins.
- **Convert to alpha scorer (exception):** Plugin has confirmed IC on dimensions NOT present in `feature_vectors` — plugin introduces genuinely new information. Replace `if confidence > threshold: emit` with `alpha_score = confidence × direction` computed every bar. No emission decision in the plugin — emission is solely the ensemble's responsibility.
- **Direct IC measurement (ambiguous):** Plugin logic is ambiguous (>5 constituent features or cross-cutting logic). Treat the plugin's continuous output as a candidate feature and measure its IC directly via the IC engine before deciding. Default to alpha scorer mode during evaluation.

Only plugins in the second or third category justify conversion infrastructure. If all fall in the first, Phase 143.5 is retirement-only — no adapter, no mixing weights, no I7 emission layer changes beyond flagging deprecated.

**I7-02 — signal_events enrichment:**
Add `alpha_score float` column to `signal_events`. Populated prospectively as plugins convert. Legacy rows have `NULL`. This column is the comparison surface for todo 007 dual-pipeline shadow comparison.

**I7-03 — Ensemble score ingestion:**
`AlphaEmitter` ingests I7 continuous scores as supplementary evidence alongside IC-weighted feature scores. Mixing weights are APR-backed (`alpha.i7.mixing_weight_<plugin_name>`). Default = 0.0 until IC evidence for the continuous score is established.

**I7-04 — Observability during migration:**

- `i7_plugin_mode` gauge per plugin: 1=alpha scorer, 0=legacy emitter
- `i7_plugin_alpha_score_null_total` counter: detects incomplete conversions at runtime
- `i7_conversion_complete` gauge: 1 when all plugins converted

**I7-05 — Retirement eligibility gate:**
Phase 144 LIVE-04 (v2.x retirement) requires all active I7 plugins to be in alpha-scorer mode. `i7_conversion_complete = 1` is a hard prerequisite for the retirement script — enforced at Phase 144 startup, not as a soft check.

**Plans:** 3 plans (Wave 1: plugin adapter contract + first 10 plugins; Wave 2: remaining ~25 plugins; Wave 3: ensemble ingestion + mixing weights + observability)

---

### Phase 144: Alpha Scoring System + v2.x Retirement Gate 📋 PLANNED

**Schema design:** `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — `alpha_strategy_scores` table + `alpha.scoring.*` APR keys. Full two-gate retirement logic in "Phase Sequencing" section.

**Goal:** Build the scoring system and run the two independent OOS gates that prove the intelligence engine works. Retire v2.x only after both pass. No live execution — that is v4.0.

**Depends on:** Phase 143.5 complete (`i7_conversion_complete = 1`) + Phase 142A OOS ensemble IC data available + Phase 142B production `alpha_frames` accumulating ≥ 60 trading days of closed rows.

**Two-gate retirement model (non-negotiable):**
Gate 1 and Gate 2 are independent. Failure modes are different. Never conflate.

- **Gate 1 — Signal proof (from Phase 142A):** `alpha_ensemble_ic.ic_ci_lower > 0` at 95% CI on OOS holdout. IC Sharpe stable (walk_forward_stable = true). If Gate 1 fails: signal problem — diagnose ensemble, feature decay, regime labels. Do not look at P&L.
- **Gate 2 — Execution proof (from Phase 142B):** `mean(counterfactual_pnl_r) > 0` at 95% CI on OOS `alpha_frames` (primary variant), per SHADOW-REVIEW.md criteria pre-committed at Phase 142B launch. `corr(alpha_score_decile, mean_pnl_r)` is computed as a diagnostic column in SCORE-01 but is not a gate — it informs whether score decile monotonically tracks P&L. If Gate 2 fails but Gate 1 passes: frame problem — recalibrate stop/target/hold against IC decay curve, not the ensemble.

Both gates must pass before SCORE-04 (v2.x retirement) executes. Gate 1 passing without Gate 2 = real signal, bad execution rules. Gate 2 passing without Gate 1 = overfitted frame on noise. Neither alone is sufficient.

**Requirements:**

**SCORE-01 — AlphaScorer (weekly oneshot, `BaseBatch`):**
Aggregates closed primary `alpha_frames` into `alpha_strategy_scores` by (symbol, tf, regime, alpha_score_decile). Computes: mean `counterfactual_pnl_r`, win rate, Sharpe, max drawdown, bootstrap CI, `ic_alpha_score_corr`. Filters cells with N < `alpha.scoring.min_strategy_n`. Parallelized per (tf, regime) cohort; async batch INSERT.

**SCORE-02 — OOS Gate 1 evaluation (signal proof):**
Queries `alpha_ensemble_ic` for OOS window (bar_ts >= `alpha.validation.oos_start`). Reports: ic_ci_lower, walk_forward_stable, regime coverage. Binary pass/fail written to a `gate_evaluations` audit log with timestamp, gate_id, result, and evidence JSON.

**SCORE-03 — OOS Gate 2 evaluation (execution proof):**
Queries `alpha_strategy_scores` for OOS `alpha_frames`. Reports: mean_pnl_r CI, ic_alpha_score_corr, Sharpe, max drawdown. Binary pass/fail written to `gate_evaluations`. Gate 2 evaluation runs regardless of Gate 1 result — the data is informative even if retirement is blocked.

**SCORE-04 — v2.x comparison:**
v3.0 mean `counterfactual_pnl_r` > v2.x mean `trade_frames.counterfactual_pnl_r` at 80% CI on same symbols/period (todo 007 dual-pipeline data). This is a supplementary check, not a third gate — but must be documented in the retirement decision record.

**SCORE-05 — v2.x retirement:**
Executes only when Gate 1 + Gate 2 both pass AND `i7_conversion_complete = 1`. Retirement = disable `intelligence_pipeline` systemd unit, archive I7 plugin dispatch, migrate all SSE/dashboard feeds to `alpha_events`. Requires explicit operator migration script with pre-flight check of all three conditions — not a flag flip.

**Plans:** 2 plans (Wave 1: AlphaScorer + gate evaluation scripts; Wave 2: OOS gate runs + v2.x comparison + retirement script)

---

## v3.2 AnalogEngine + Feature Expansion (Phases 145-147)

**Milestone Goal:** Build System 2 (non-parametric K-NN retrieval) as an independent complement to AlphaEngine. Expand the feature set with new primitives and compound interactions. Phases 145-146 (AnalogEngine substrate + scoring) are strictly sequential — each gated on the prior. Phase 147 (primitives + interaction layer) is a System-1 feature-engineering track with no real dependency on 145/146 (see Phase 147 sequencing note) and may run in parallel with, or before, the AnalogEngine phases — only the milestone-level v3.1 OOS IC gate applies to all three.

**Hard prerequisite:** v3.1 complete + live IC > 0 at 95% CI confirmed on OOS holdout.

---

### Phase 145: AnalogEngine — Embedding Substrate + Retrieval 📋 PLANNED

**Goal:** Build the non-parametric retrieval substrate. Embed bar states into pgvector HNSW index. Validate retrieval quality before committing to a dimension and building the full corpus. "Have we seen a bar like this before, and what happened next?"

**Depends on:** Phase 142A OOS validation showing `ic_ci_lower > 0` at p < 0.05. ANALOG-01..05 read `feature_vectors` only — no dependency on `alpha_events`, `alpha_frames`, or v2.x retirement.

**Requirements:**

**ANALOG-01 — Embedding dimension calibration (one-way door):**
Before committing to an embedding dimension, run a calibration study: embed 6 months of `feature_vectors` bars at three candidate dimensions (64, 128, 256) using variance-normalized features (z-score per feature, L2-normalize). Measure retrieval quality: recall@10, mean reciprocal rank, analog distance distribution on known-outcome bars. Pick the winning dimension. Lock `embedding_version = 1`. This step happens BEFORE any full historical embedding run — changing the dimension after is prohibitively expensive.

**Why not IC-weighted at index time:** IC weights update weekly from the IC engine. Baking them into the HNSW index would require a full re-embedding of the historical corpus (O(N×D)) on every IC recalibration cycle. ANALOG-08 already handles IC-weighted re-ranking at query time — encoding IC into the embedding double-counts the signal while coupling index freshness to IC engine cadence. Keep the embedding stable; put IC discrimination in ANALOG-08 where it belongs.

**ANALOG-02 — Embedding serialization contract (variance-normalized):**
For each bar: (1) per-feature rolling z-score, point-in-time trailing window, no lookahead; (2) L2-normalize the result. No IC-weight multiplication at index time. Regime and session applied as hard retrieval filters (not encoded in vector). Stable feature ordering in `embedding_feature_registry` table. `embedding_version` bump on any change — feature set or z-score window — invalidates all stored vectors; treat as a database migration. IC-weighted re-ranking is handled entirely by ANALOG-08 at query time. **Dependency note (2026-07-01 review):** "regime applied as a hard retrieval filter" means AnalogEngine's retrieval quality directly inherits any bias in the regime labels themselves — same open question as Phase 143's LIFECYCLE-04 (see todo 034/026). If that validation finds the per-symbol HMM labels are empirically fine, no action needed here; if it finds material bias, ANALOG-02's regime filter should wait for the corrected labels rather than hard-filtering on known-biased strata — a "have we seen a bar like this before" retrieval is especially sensitive to a wrong stratification since it can silently retrieve analogs from the wrong regime bucket.

**ANALOG-03 — bar-embedder (oneshot, nightly):**
Reads `feature_vectors`. Writes to `embeddings` table (entity_type='bar'). Processes in chronological order; skips bars already embedded at current `embedding_version`. HNSW index built/updated after batch.

**ANALOG-04 — OOD monitor (first-class output):**
`vil_ood_rate`: rolling fraction of recent retrievals returning null (no analogs within `max_distance`). `vil_nearest_distance`: distance to nearest neighbor even on null results. Rising `vil_ood_rate` is a regime-break early warning — surfaces it, never hides it. APR key: `alpha.analog.max_distance = 0.3` [initial_estimate, calibrate from distance distribution on full corpus].

**ANALOG-05 — Null result contract:**
Empty retrieval (`[]`) when no analogs within `max_distance`. This is a named, surfaced event — not a fallback to nearest-available. AnalogEngine must never silently return the nearest bar when it is out-of-distribution. OOD is information.

**ANALOG-RESEARCH-01 — Hypothesis backtester script (todo 018):**
Thin research utility built on top of the retrieval primitive. Accepts an arbitrary query feature vector, runs K-NN against `feature_embeddings`, reads empirical outcome distributions from `forward_returns`. Answers "Is this edge real?" with zero new infrastructure. Ships as `production/scripts/analog_backtest.py` alongside the retrieval primitive in Wave 4.

**Plans:** 4 plans (Wave 1: dimension calibration study; Wave 2: embedding contract + registry; Wave 3: bar-embedder + HNSW; Wave 4: OOD monitor + retrieval primitive + hypothesis backtester script)

---

### Phase 146: AnalogEngine — IC Factory + Scoring Engine + Enrichment 📋 PLANNED

**Goal:** Feature-level IC within the embedding space (for k-NN re-ranking). Correlation service (effective-N). Scoring engine (transforms retrieval results into Score Objects). Analog enricher (annotates alpha_events). Complete the System 2 pipeline.

**Depends on:** Phase 145 (embedding substrate live, HNSW populated).

**Key distinction:** `feature_ic_stats` here measures IC at the feature level within the embedding (used for k-NN re-ranking weights). This is NOT the same as `feature_ic_scores` (System 1 ensemble weights). Different grain, different table ownership, different purpose.

**Requirements:**

**ANALOG-06 — analog-ic-factory (weekly oneshot):**
Reads `embeddings` + `forward_returns`. Computes per-feature IC within the embedding — "which features in the bar state best predict outcomes among retrieved analogs." Writes `feature_ic_stats`. Used only for `candidate_k` re-ranking, not for ensemble weighting.

**ANALOG-07 — correlation-svc (weekly oneshot):**
Reads `embeddings` (entity_type='bar'). Computes pairwise cosine similarity between plugin score histories. Writes `similarity_pairs` + `effective_n_scores`. Effective-N for the analog retrieval context.

**ANALOG-08 — scoring-engine (nightly oneshot):**
Reads `embeddings` + `feature_ic_stats` + `forward_returns`. For each bar, retrieves K nearest analogs, re-ranks by IC-weighted feature importance (`candidate_k` oversample → re-rank → trim to K), computes Score Object (E[R] distribution, direction, OOD flag, analog count). Writes `score_cache`. Does NOT execute k-NN internally on live path — batch only.

**ANALOG-09 — analog-enricher (nightly oneshot):**
Joins `score_cache` to `alpha_events` on (symbol, tf, bar_ts). Writes `alpha_events.analog_score`, `alpha_events.analog_count`, `alpha_events.analog_conviction_lower`, `alpha_events.ood_flagged`. Cold path, never at emission time.

**Plans:** 3 plans (Wave 1: analog-ic-factory + correlation-svc; Wave 2: scoring-engine; Wave 3: analog-enricher + integration)

**Note (2026-07-01):** ANALOG-08's Score Object (`E[R]` distribution, direction, OOD flag, analog
count) is a partial precursor to the calibrated confluence-detection layer proposed in
`docs/ideas/intel-10-confluence-detection-persistence-layer.md`. Once this phase produces validated
analog-based confluences, revisit that idea doc to scope it as a phase — it consumes this phase's
output, don't build it standalone before this exists.

---

### Phase 147: Feature Primitives Expansion + Theory-Motivated Interaction Layer 📋 PLANNED

**Goal:** Expand the atomic feature set (~60 new candidates, full priority-tiered list in todo 014 — corrected 2026-07-01, ROADMAP previously cited a phantom "todo 003" that doesn't exist in the tree), screen through IC machinery, promote survivors. Build a Theory-Motivated Interaction Layer of ≤50 curated compound features — not a combinatorial factory. Gated on Feature Registry (todo 008, COMPLETE).

**Note (2026-07-01):** the interaction terms this phase validates are one of two inputs to the
confluence-detection-and-persistence layer proposed in
`docs/ideas/intel-10-confluence-detection-persistence-layer.md` (the other being Phase 146's analog
matches). Once ≥1 interaction term clears this phase's IC/OOS gates, revisit that idea doc to scope
it as a phase.

**Depends on:** Feature Registry shipped (todo 008 — COMPLETE) — ratio operation validity requires feature metadata (sign_type, scale). No dependency on Phase 145/146.

**Why not a combinatorial Interaction Factory:**
~30K compound candidates in a separate BH-FDR pool at FDR=0.05 produces ~1,500 expected false discoveries regardless of pre-screening. BH-FDR was designed for focused hypothesis testing, not combinatorial enumeration — at 30K tests, the correction loses meaningful power-versus-discovery-rate guarantees. Every surviving compound feature would have no stated reason to survive, making it impossible to distinguish genuine signal from leakage. Renaissance does not enumerate pairwise products. They test theory-motivated combinations where the researcher states WHY the compound should predict returns, so the surviving features can be reasoned about and decay patterns explained.

**Theory-Motivated Interaction Layer — design rules:**

- Cap: ≤50 compound interactions defined before any IC measurement begins.
- Every interaction must have a one-sentence finance-theory hypothesis (example: "momentum_z_fast × low_vol_regime — momentum carries more strongly in calm regimes; Frazzini & Pedersen 2014").
- Candidate sources: momentum × volatility regime, volume × trend direction, cross-asset divergence × regime transition, breakout × volume confirmation, mean-reversion × regime label, carry × term structure.
- Each compound is a single operation: product, ratio, or conditional. No multi-step compositions — that is a model, not a feature.
- Separate BH-FDR pool from atomics (50 tests at FDR=0.05 has well-understood power vs 30K tests).
- Feature Registry entry required at registration: `tier='1_interaction'`, `parent_features=[]`, hypothesis text in `formula_short`. Auto-deprecation if IC gate not passed within `alpha.feature_registry.demotion_periods` IC runs.

**Regime-conditioned cluster membership (extension of Phase 140 P2):**
Phase 140's collinearity clustering is global. Extend to regime-conditioned clusters: one cluster membership table per HMM state. Features uncorrelated in trending may be 0.8 correlated in ranging — global clustering misses this. APR key: `alpha.ensemble.cluster_regime_conditioned = true` [planned].

**Plans:** 4 plans (Wave 1: primitives expansion IC sweep; Wave 2: Theory-Motivated Interaction Layer — 50 interaction proposals with stated hypotheses; Wave 3: interaction IC sweep + Feature Registry integration; Wave 4: regime-conditioned clusters)

---

## v3.3 Foundational Hardening (Phases 148-149)

**Milestone Goal:** Replace the remaining manually-asserted foundations with empirically-derived ones. Instrument tag calibration replaces belief-based tags with measured OLS betas. Alternative data vectors add new IC-measurable signal sources per the vector-agnostic architecture.

---

### Phase 148: Empirical Instrument Tag Calibrator 📋 PLANNED

**Goal:** Replace manually-asserted instrument tags (e.g., `equity_beta`, `rate_sensitive`) with measured OLS factor betas computed nightly. Tags auto-expire when the statistical relationship stops holding. Renaissance demands falsifiable hypotheses.

**Depends on:** Nothing upstream of Phase 141. TAG-01's OLS regression runs on instrument daily returns vs. factor ETF series (`instruments`, `market_data_ohlcv`), not `feature_vectors` — no dependency on Phase 145-147.

**Requirements:**

**TAG-01 — Measured betas (nightly batch, `TagAuditor`):**
8 core factor betas via OLS regression of instrument daily returns vs. factor series: equity_beta (SPY), rate_beta (TLT), gold_beta (GLD), credit_beta (HYG), dollar_beta (DXY), vol_beta (VIX), oil_beta (USO), china_beta (FXI). Gate per tag: bootstrap CI, p-value < 0.05, min_r2 floor. Exponential decay: `effective_weight = weight × exp(-days_since_estimated / half_life_days)` — stale measurements auto-expire.

**TAG-02 — Regime conditioning (Phase 2 extension):**
Initially PK is `(symbol, tag)`. Phase 2 extends to `(symbol, tag, regime)` — different regimes produce different factor exposures (e.g., flight-to-quality regime makes TLT beta unreliable for equity instruments). Phase 2 does not ship in Phase 148 — it ships when IC stratification by tag shows regime-dependent divergence.

**TAG-03 — Discovery gate:**
Tags that are fully computable from the factor vector (all 8 OLS betas) must not exist as permanent human assertions. They are query-time threshold applications on the `instrument_tags` empirical table. Human-only tags (`definitional`, `classification`) remain — but must be annotated as measurement_type='definitional' with owner.

**Plans:** 3 plans (Wave 1: TagAuditor batch service + OLS pipeline; Wave 2: DB migration + expiry mechanics; Wave 3: regime conditioning Phase 2 design)

---

### Phase 151: Cross-Sectional Regime Model (`regime_group`) 📋 PLANNED

**Goal:** Replace `market_regimes.asset_class` with `regime_group` — a named peer group with a pluggable regime signal (breadth_vol for equity, curve_credit for rates, commodity/fx signal modules). Migration 189. Full design: `docs/plans/2026-07-01-cross-sectional-regime-model.md`.

**Status per 2026-07-01 architecture review** (`.planning/research/2026-07-01-v3-architecture-review.md` §4): confirmed live today, not a future risk — 15/58 corpus symbols (all `fi_*` bonds + GLD/SLV/VNQ/IBIT) are excluded from equity breadth by `equity_regime_model.py`'s own filter yet get equity regime labels in IC stratification and ensemble scoring. This phase fixes 11/15 via the rates group. Two decisions made (first-principles, not re-opened for user input):
- **Unrouted symbols (GLD/SLV/VNQ/IBIT):** exclude from regime-stratified IC with loud startup logging of unrouted symbols, NOT the plan's current silent default-to-equity (plan `:1618-1622` asserts `GLD → "equity"` — that assertion must change before execution). Pooled IC still covers them; no data lost. "Silent wrong answers are worse than loud crashes."
- **Commodity/fx group enablement is blocked** on todo 041 (tag exposure-vs-sensitivity taxonomy audit) — OIH/XLE/XOP carry both `eq_*` and `commodity_energy_*` tags and will raise `AmbiguousRegimeGroupError` the moment `commodity_energy` is enabled. Add this as an explicit dependency edge, not just a scope-note aside.
- Job-1 peer-set purity (OIH/XLE staying in equity breadth despite commodity sensitivity tags) is NOT a blocker — defensible by convention (equity sector funds), revisit only if Phase 148 tag calibration shows material contamination.

**Sequencing:** land Phase 142A's ensemble-IC baseline first (pre-151 equity-only strata), then batch this phase with todo 026 P1-P3 into one ic_engine re-run — empirical pre/post comparison over blind trust that the new strata help.

### Phase 152: ETF Universe Expansion (58→79) 📋 PLANNED

**Goal:** Add 21 new ETFs (commodity, international, FX, factor) with fine-grained tag_vocabulary entries for the Phase 151 regime groups. Migration 188. Full design: `docs/plans/2026-06-27-etf-universe-expansion.md`.

**Sequencing decision (operator, 2026-07-01):** universe expansion (this phase, and any future
single-name expansion beyond it) waits until the end-to-end system is proven — pipeline through
P&L, validated via the canonical simulator concept (`docs/ideas/canonical-simulator.md`).
Breadth is the biggest lever on IR (see `docs/ideas/edge-source-thesis.md`, breadth section)
and is deliberately pulled last: multiplying the universe before the path is trusted multiplies
unvalidated machinery, not returns.

### Phase 149: Alternative Data Vectors 📋 PLANNED

**Goal:** Add new IC-measurable signal sources to the vector-agnostic architecture. Each vector enters at weight=0, earns weight through IC measurement independently, and never blends with price IC until independently validated. Recommended order: Flows first (highest signal/infra delta ratio), then Kalshi as regime conditioning, then Fundamentals.

**Depends on:** `alt_feature_vectors` table + IC engine capable of joining it (Phase 138 pattern). No dependency on Phase 148. Each vector gated on its own IC validation before any ensemble weight is assigned.

**Requirements:**

**ALTDATA-01 — `alt_feature_vectors` table:**
Keyed on `(symbol, ts, data_source)`. IC engine joins both `feature_vectors` and `alt_feature_vectors`. Separate IC gate per data source — never blend alt-data IC with price IC until independently validated. Shorter history than price is expected; the IC gate min_observations applies per data source independently.

**ALTDATA-02 — V2 Flows (first):**
Options net delta, dark pool %. Same cadence as price, lowest infra delta. Direct IC measurement at 5m/15m TF. Priority: highest among alt-data sources.

**ALTDATA-03 — Kalshi (second, as regime conditioning):**
Prediction market event probabilities. Not return prediction — stratifies existing price IC by macro event probability. Treat as a filter/modifier on regime labels, not a standalone predictor.

**ALTDATA-04 — V8 Fundamentals (later):**
EPS surprises, P/B. Quarterly data → daily TF only via fill-forward join. History is typically shorter than price (5K rows vs 20K minimum). Separate IC gate with longer accumulation period before ensemble weight is assigned.

**Plans:** TBD per vector — plan each vector as its own sub-phase when infra prerequisites are clear.

---

## v4.0 Execution Layer (Phases TBD)

**Milestone Goal:** Consume `alpha_events` from the intelligence engine and execute live trades through IBKR. Position sizing, risk management, fill model, slippage feedback, and P&L accounting. Strict architectural boundary: the execution layer is a consumer of `alpha_events` — it does not modify, re-score, or re-weight signals. Signal quality improvements belong in the intelligence engine (v3.x).

**Hard prerequisite:** v3.3 complete. Intelligence engine OOS-validated (`ic_ci_lower > 0` at 95% CI, stable across regimes). `alpha_events` schema frozen — no breaking changes after v4.0 begins.

**Input contract:** `alpha_events` (direction, alpha_score, ci_lower, ci_upper, regime, tf, bar_ts). The execution layer treats this as an opaque signal — it sizes, routes, and tracks fills. It does not touch feature weights or IC scores.

**Planned scope (not yet phased):**

- **Portfolio construction:** Portfolio Kelly using Ledoit-Wolf covariance on realized daily returns (NOT the EnsembleBuilder covariance). This distinction is load-bearing: EnsembleBuilder's LW covariance is estimated in feature-IC space to decorrelate ensemble feature weights. Portfolio Kelly requires covariance in return space — estimated from realized daily returns per symbol. These are different matrices applied to different vectors; conflating them produces wrong position sizes with no error signal. A separate `ReturnCovarianceEstimator` service applies LW shrinkage to the realized daily return matrix (reusing the same LW machinery as EnsembleBuilder, but on a different input). `weights ∝ Sigma_return^-1 × mu` where `mu` is the vector of `net_expected_r` per open position. Single-instrument Kelly (`kelly_fraction × E[R]_net / garch_vol`) applied independently to correlated positions overstates diversification — 58 equity ETFs all load on common SPY/sector factors, and independent sizing treats them as uncorrelated when they are not. Portfolio Kelly accounts for this by allocating less to positions that move together. Minimum position notional filter. Max portfolio VaR ceiling (95% historical simulation).
- **Risk management:** Portfolio VaR ceiling (95% historical simulation), per-symbol drawdown limits, regime-conditioned position caps.
- **Execution layer:** IBKR market order routing at T+1 open. Fill model: `expected_fill = open × (1 + slippage)`. No-fill handler (timeout → cancel + log). `trade_executions` table for actual fills.
- **Cost calibration feedback loop:** `ActualSlippageWriter` (daily oneshot) regresses realized slippage vs expected per (symbol, TF, time_of_day). Updates `alpha.cost.slippage_r` APR key. Closes the cost model loop established in Phase 142.
- **Execution scoring:** Compare `actual_pnl_r` vs `counterfactual_pnl_r`. Execution quality measured independently of signal quality — keeps the two layers honest.

**Note:** Emission thresholds (`alpha_score` floor where `E[R]_net > cost`) are set here, not in the intelligence engine. The intelligence engine emits all signals above a statistical significance gate; the execution layer decides what to act on based on net expected value after costs.
