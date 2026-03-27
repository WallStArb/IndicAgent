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
- 🚧 **v2.1 Data Foundation & Signal Confidence** — Phases 48-52 (in progress)
- ⏸ **v2.2 External Access** — Phase 53 (planned, deferred until v2.1 complete)
- ⏸ **v2.3 ML Foundation** — Phases 54-55 (deferred until 30+ days clean signal data)

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
- [x] **Phase 43: Performance & Stability Emergency** — market_data_ohlcv rebuilt (15,740→21 chunks), feature_writer i7/i8 buffering, asyncio.to_thread plugin execution, lifecycle O(1) active-signal index, ndarray calibration pre-alloc, _run_refresh_loop helper, 328K stale signals expired (executed 2026-03-20; 1 test gap remains — see Phase 49)
- [x] **Phase 44: I7 DAG Refactor** — ~458 LOC duplication extracted into shared utilities, validate_tier() enforcement, cross_timeframe decomposed, make_signal() factory + validate_signal() enforcement (completed 2026-03-21)
- [x] **Phase 44.1: Feature Pipeline Renaissance Refactor** — unified FeaturePipelineService replaces 3 services; 3 Kafka hops → 1; pipeline_latency_ms < 50ms p99 (completed 2026-03-22)
- [x] **Phase 44.2: SignalGeneratorService Consolidation** — 6 pipeline stage microservices absorbed in-process; 8 Kafka hops → 2; 6 systemd units retired (completed 2026-03-22)
- [x] **Phase 44.3: Atomic Persistence + OHLCV Unification** — single atomic INSERT per bar; DB migration for 10 new columns; FeaturePipelineService sole live OHLCV writer; 18 services → 9 (completed 2026-03-22)
- [x] **Phase 45: I6 → I7 Confluence Wiring + Exhaustion Standardization** — ctf_fvg_alignment + ctf_ob_alignment exposed; capture_confluence_features() + ConfluenceWeightProfile; all 36 I7 plugins capture _shadow dict; lifecycle O(1) index + chandelier write guard (completed 2026-03-22)
- [x] **Phase 46: I6 Confluence Expansion** — 4 new raw measurement fields (ctf_vix_level, ctf_vix_z, ctf_eq_spread_z, ctf_eq_pairs_confirming); vix_context.py pure function module (completed 2026-03-22)
- [x] **Phase 46.1: VIX + Cross-Asset to I4** — VIXRegimePlugin + CrossAssetContextPlugin promoted to I4; I4Context +4 fields / I6Confluence -4 fields; VIX injection fix (completed 2026-03-22)
- [x] **Phase 47: Shadow Mode Graduation** — CROSS_ASSET_ENABLED flag removed (unconditionally active); ROLL_MONITOR_ENABLED kept false pending D-21 re-validation; trad_DualDivergence promotion deferred (completed 2026-03-22)

</details>

<details open>
<summary>🚧 v2.1 Data Foundation & Signal Confidence (Phases 48-52.5) — IN PROGRESS</summary>

**Milestone Goal:** Earn the right to trust the numbers. Fix the live data foundation (tick aggregation), close DB performance gaps, validate every intelligence layer independently, graduate shadow modes with real evidence, and harden infrastructure so nothing requires manual intervention.

- [x] **Phase 48: Tick Aggregation & I7 Quality** — verify tick aggregation (5s→1m bars, eliminate bars_processed freeze); I7 refactoring: extract 3 shared utilities (550+ line savings), fix I6 confluence violations in 4 SMC/FVG plugins, optimize aggregator calibration batching (completed 2026-03-23)
- [ ] **Phase 49: DB Performance & Signal Ledger Hardening** — signal_ledger composite index + query optimization; CIS null repair (blocked PostgreSQL shared memory fix); close Phase 43 test gap (threading.Lock characterization test); REQUIREMENTS.md requirement ID traceability fix
- [ ] **Phase 50: Roll Monitor & DualDivergence Graduation** — D-21 validation after market_data_5m backfill; apply migration 049_roll_premium_pct.sql; enable ROLL_MONITOR_ENABLED; trad_DualDivergence promotion once D-07 gate passes
- [ ] **Phase 51: Signal & Indicator Validation Framework** — per-layer sanity checks (I1→I7 output values statistically sensible); signal outcome completeness audit; setup_performance gate verification; automated validation that runs on each deploy
- [ ] **Phase 52: Infrastructure Hardening** — Docker restart policies (timescaledb + redpanda); automated gap-fill on service restart; log rotation; deploy_dashboard.sh script; health check endpoints; no manual steps anywhere in the pipeline
- [ ] **Phase 52.1: Wiring Fixes + Doc Naming** — fix `topic_feature_processed` ImportError in feature_compute_agent + feature_writer_service; fix naive `datetime.now()` in indicator/intelligence compute agents; wire `persistence_batch_latency`/`persistence_consumer_lag` metrics in writer services; fix hardcoded topic strings in parity-auditor plan
- [ ] **Phase 52.2: BaseAgent Infrastructure + IndicatorComputeAgent Rename** — **Plans:** 2 plans
  Plans:
  - [x] 52.2-01-PLAN.md — TDD BaseAgent + AgentRegistry (new src/core/agent/ package)
  - [x] 52.2-02-PLAN.md — Rename IndicatorService to IndicatorComputeAgent, fix 4 broken tests, systemd unit
- [ ] **Phase 52.3: Dual-Write Shadow Writer** — migration `051_feature_snapshots_shadow.sql`; `FeatureRepository` configurable table name; `FeatureSnapshotWriterAgent` consuming `intelligence.journal` into shadow table; systemd unit
- [ ] **Phase 52.4: SignalTrackerAgent Refactor** — rename `SignalLifecycleService` → `SignalTrackerAgent`; extract SQL to `SignalLedgerRepository`; inject repository; inherit `BaseAgent`; retire `indicagent-signal-lifecycle.service`
- [ ] **Phase 52.5: Parity Auditor Agent** — `ParityRepository` + `FieldViolation` schema; `ParityAuditorAgent` timer loop comparing shadow vs primary per (symbol, tf); violation storage; automated `SHADOW_PARITY_CERTIFIED` gate; systemd unit

</details>

<details>
<summary>⏸ v2.2 External Access (Phase 53) — PLANNED, deferred until v2.1 complete</summary>

**Milestone Goal:** Secure, observable external access. Cloudflare Tunnel SSE fix is the only strictly required item; JWT auth can be replaced with Cloudflare Access (zero application code). Full auth layer if intentional multi-user access is needed.

- [ ] **Phase 53: Auth + External Access** — Cloudflare Tunnel `disableChunkedEncoding` SSE fix; Cloudflare Access or JWT cookie auth; CORS hardening; auth event logging; rate limiting
  - Plans already created in `.planning/phases/53-auth-external-access/` (moved from Phase 48 v2.0)
  - Revisit scope before executing — Cloudflare Access may replace JWT application code entirely

</details>

<details>
<summary>⏸ v2.3 ML Foundation (Phases 54-55) — DEFERRED, requires 30+ days clean signal data from v2.1</summary>

**Milestone Goal:** A statistically validated ML scoring layer trained on clean signal_ledger outcomes, with Renaissance-grade observability (attribution, A/B testing, causal inference) proving each pipeline stage earns its compute cost.

- [ ] **Phase 54: ML Scoring Model** — LightGBM feature builder with stationarity gates, global + regime-specific models, walk-forward retraining, shadow ml_score, blend promotion (α=0.20 after 8-week shadow gate), SHAP attribution
- [ ] **Phase 55: Renaissance Observability** — DAG performance attribution, A/B experiment framework, causal inference, counterfactual analysis, LLM gate optimizer, intelligence tier audit surface, staleness as first-class quality signal

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

**Status**: 📋 Planned

**Depends on**: Phase 48 completion

**Requirements**: DBPERF-01, DBPERF-02, CIS-REPAIR-01, TEST-01, REQ-01

**Success Criteria** (what must be TRUE):
  1. `signal_ledger` has composite index on (symbol, feature_ts DESC, feature_tf) for sub-500ms JOIN queries
  2. CIS null repair script runs successfully with adjusted PostgreSQL work_mem (shared memory fix)
  3. Threading.Lock characterization test exists and passes (closes Phase 43 gap)
  4. All REQUIREMENTS.md IDs traceable to validation tests or code locations

**Plans**: TBD (4-5 plans estimated)

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

**Status**: 📋 Planned

**Depends on**: Phase 49 (market_data_5m backfill required for D-21 validation)

**Requirements**: ROLL-01, ROLL-02, DUAL-01

**Success Criteria** (what must be TRUE):
  1. D-21 validation confirms roll detection works correctly with 5m backfilled data
  2. Migration `049_roll_premium_pct.sql` applied; `roll_premium_pct` populated in intelligence_features
  3. `ROLL_MONITOR_ENABLED=true` set in production environment
  4. trad_DualDivergence promoted (IS_SHADOW=False) after D-07 gate passes (N≥100, 95% CI E[PnL_R] > 0)

**Plans**: TBD (3-4 plans estimated)

### Phase 51: Signal & Indicator Validation Framework

**Goal**: Establish automated validation to ensure data quality across all intelligence layers.

**Status**: 📋 Planned

**Depends on**: None (can run in parallel with Phases 49-50)

**Requirements**: VAL-01, VAL-02, VAL-03, VAL-04

**Success Criteria** (what must be TRUE):
  1. Per-layer sanity checks validate I1→I7 output ranges (no NaN, no infinity, reasonable bounds)
  2. Signal outcome completeness audit confirms 100% of resolved signals have outcome populated
  3. setup_performance aggregates verified against raw signal_ledger outcomes
  4. Automated validation script runs as pre-deploy check or CI gate

**Plans**: TBD (4-5 plans estimated)

### Phase 52: Infrastructure Hardening

**Goal**: Eliminate manual intervention — Docker restart policies, automated gap-fill, log rotation, deploy scripts, health checks.

**Status**: 📋 Planned

**Depends on**: Phase 51 (validation framework ensures stability before hardening)

**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-06

**Success Criteria** (what must be TRUE):
  1. timescaledb and redpanda containers have `restart: unless-stopped` policy
  2. Gap-fill service detects and fills missing bars automatically on service restart
  3. Log files rotate (max size, retention policy) — no unbounded growth
  4. `deploy_dashboard.sh` script builds and deploys dashboard in one command
  5. All services respond to GET /health with {status: "ok" | "degraded"}
  6. Full pipeline recovery from cold start requires zero manual steps

**Plans**: TBD (5-6 plans estimated)

</details>
## Backlog

Items decided but not yet scheduled. Pull into a milestone when ready.
Re-prioritized 2026-03-19 after v2.0 roadmap defined.

### Tier 1 — v2.3 candidates (ML Foundation)

| Item | Notes | Analysis |
|------|-------|---------|
| **Phase 54: ML Scoring Model** | Deferred from v2.0 — requires 30+ days of clean signal_ledger outcomes from v2.1 + roll monitor graduated + market_data_5m populated. Feature builder, stationarity gates, global + regime-specific LightGBM, walk-forward retraining, shadow ml_score, blend promotion, SHAP attribution. `_shadow` dict already captured in all I7 plugins (Phase 45). | Phase Detail: see `### Phase 54` in Phase Details section |
| **Phase 55: Renaissance Observability** | Deferred from v2.0 — depends on Phase 54 (ML provides causal analysis features). Performance attribution per DAG stage, A/B test framework, causal inference, counterfactual analysis, LLM gate optimizer; intelligence tier audit surface, staleness as first-class quality signal. | Phase Detail: see `### Phase 55` in Phase Details section |
| VWAP/Session plugin TF guards | Research: VWAP and session plugins may fire on TFs where they're not meaningful (e.g. 1d). Add guards. | `.planning/todos/pending/2026-03-10-research-vwap-and-session-plugin-timeframe-guards.md` |
| LLM Call Tracking | Real token counts (Ollama eval counts), error details, cis_score/zone fields, retry chain visibility. | `.planning/todos/pending/2026-03-07-improve-llm-call-tracking.md` |
| BSL/SSL level clusters | Schema change: list of levels vs single nearest level. More useful for signal proximity scoring. | `.planning/todos/pending/2026-02-27-support-bsl-ssl-level-clusters-not-just-single-levels.md` |

### Tier 2 — Longer horizon

| Item | Notes | Analysis |
|------|-------|---------|
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
| Orderflow Integration | reqTickByTickData; buy/sell delta metrics; delta divergence / absorption / imbalance continuation plugins. | — |
| Portfolio Management | Correlation matrix; sector exposure limits; symbol rotation. | — |
| Trade Journal Auto-Documentation | LLM daily summaries from signal_ledger — learning opportunities from losing trades, performance by setup/regime/TF. | — |
| Robinhood-Style Scaling | Consumer Proxy pattern; Changelog Streams for state recovery. | `analysis/2026-02-12-robinhood-scaling-patterns.md` |
| Broker-agnostic instrument provider | Defer until second broker integration is needed. | — |

## Progress

**Execution Order:**
Phases execute in numeric order. v1.0–v1.9 complete (Phases 0-38 shipped). v2.0 complete (Phases 39-47 shipped 2026-03-22). v2.1 in progress (Phase 48).

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
| 49. DB Performance | v2.1 | 0/TBD | Not started | — |
| 49.1. Regime Gate Fix — write all signals to signal_ledger | v2.1 | 1/1 | Complete | 2026-03-23 |
| 49.2. HMM Operational Fixes — observability, fallback logging, warm-up noise | v2.1 | 1/1 | Complete    | 2026-03-23 |
| 50. Roll Monitor Graduation | v2.1 | 0/TBD | Not started | — |
| 51. Signal Validation Framework | v2.1 | 0/TBD | Not started | — |
| 52. Infrastructure Hardening | v2.1 | 0/1 | Planned    |  |
