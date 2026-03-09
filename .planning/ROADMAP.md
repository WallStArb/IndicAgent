# Roadmap: IndicAgent

## Milestones

- ✅ **v1.0 MVP** — Phases 0-9 (shipped 2026-02-28)
- ✅ **v1.1 Code Quality Sprint** — Phase 01 (shipped 2026-03-01)
- ✅ **v1.2 Intelligence Palette Expansion** — Phases 02-07 (shipped 2026-03-02)
- ✅ **v1.3 Signal Intelligence Expansion** — Phases 08-11 (shipped 2026-03-04)
- ✅ **v1.4 Quant Foundation** — Phases 12-17 (shipped 2026-03-07)
- 🚧 **v1.5 Production Hardening** — Phases 18-21 (planned)

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

### 🚧 v1.5 Production Hardening (Planned)

**Milestone Goal:** Financial safety, concurrency protection, API resilience, and efficiency improvements for robust production operation.

#### Phase 18: Financial Math Safety
**Goal**: Epsilon tolerance, magic number documentation, and characterization tests for mathematical correctness
**Depends on**: Phase 17
**Requirements**: FIN-01, FIN-02, FIN-03, FIN-04, FIN-05, FIN-06, API-01, API-02, API-03, API-04, API-05, API-06, API-07
**Success Criteria** (what must be TRUE):
  1. trade_framer.py uses epsilon tolerance (1e-9) for all floating-point comparisons
  2. CIS scorer uses epsilon tolerance for slope/MACD/ROC direction comparisons
  3. All magic numbers documented as named constants with inline comments
  4. Settings class exposes ibkr_timeout_sec (default 20.0s) and llm_timeout_sec (default 60.0s)
  5. IBKR provider and all LLM providers use configurable timeouts from Settings
  6. market_analysis_service, indicator_service, and ai_narrative_service have per-key asyncio.Lock() for shared state access
**Plans**: 7 plans (2 waves)

Plans:
- [ ] 18-01: Epsilon tolerance and magic number documentation
- [ ] 18-02: Configurable timeouts in Settings class
- [ ] 18-03: Timeout usage and concurrency locks in services
- [ ] 18-04: Configurable LLM provider timeouts
- [ ] 18-05: LLM provider configurable timeout (per-provider)
- [ ] 18-06: AI narrative service concurrency lock
- [x] 18-07: Phase 18 verification (completed 2026-03-08)

#### Phase 19: Financial Math Characterization
**Goal**: Characterization tests for RSI zero-loss behavior, trade_framer ATR fallback, and concurrent lock behavior
**Depends on**: Phase 18
**Requirements**: FIN-07, FIN-08, API-08
**Success Criteria** (what must be TRUE):
  1. Characterization test verifies RSI zero-loss behavior returns 100.0
  2. Characterization test verifies trade_framer zero ATR emergency fallback
  3. Characterization test verifies lock acquisition and release in concurrent access scenarios
**Plans**: 3 plans (1 wave)

Plans:
- [ ] 19-01-PLAN.md — RSI zero-loss guard: verify avg_loss==0 returns 100.0
- [ ] 19-02-PLAN.md — trade_framer zero-ATR emergency fallback: verify 0.1% price substitution
- [ ] 19-03-PLAN.md — concurrent lock: verify per-key idempotency, isolation, blocking, and release

#### Phase 20: Circuit Breaker Integration
**Goal**: retry_utils.py with exponential backoff/jitter, circuit breaker integration for IBKR and LLM providers
**Depends on**: Phase 19
**Requirements**: CB-01, CB-02, CB-03, CB-04, API-09
**Success Criteria** (what must be TRUE):
  1. retry_utils.py created with exponential_backoff_with_jitter() function
  2. retry_with_backoff() async wrapper with configurable max_attempts
  3. All LLM providers use PluginCircuitBreaker for generate() calls
  4. IBKR provider uses PluginCircuitBreaker for connection failures
  5. Circuit breaker metrics exposed on Prometheus endpoint
**Plans**: 4 plans (1 wave)

Plans:
- [ ] 20-01: retry_utils.py implementation
- [ ] 20-02: Circuit breaker integration for LLM providers
- [ ] 20-03: Circuit breaker integration for IBKR provider
- [ ] 20-04: Circuit breaker metrics exposure

#### Phase 21: Efficiency Optimizations
**Goal**: Buffer management, CIS scorer vectorization, plugin call metrics sampling
**Depends on**: Phase 20
**Requirements**: EFF-01, EFF-02, EFF-03, EFF-04
**Success Criteria** (what must be TRUE):
  1. indicator_service tracks buffer length, only invalidates DataFrame cache when capacity exceeded
  2. market_analysis_service tracks buffer length, only invalidates DataFrame cache when capacity exceeded
  3. CIS scorer uses numpy vectorization for bucket score computation
  4. Plugin call metrics use modulo sampling (record every N calls, not every call)
**Plans**: 4 plans (1 wave)

Plans:
- [ ] 21-01: Buffer management in indicator_service
- [ ] 21-02: Buffer management in market_analysis_service
- [ ] 21-03: CIS scorer vectorization
- [ ] 21-04: Plugin call metrics sampling optimization

## Backlog

Items decided but not yet scheduled. Pull into a milestone when ready.
Re-prioritized 2026-03-08 after v1.5 planning.

### Tier 1 — Ready now / v1.6 candidates (data exists, no blockers)

| Item | Notes | Analysis |
|------|-------|---------|
| Dashboard Complete | I7 all_ranked panel (new SSE route); signal history view; final audit across all symbol profiles. | `.planning/todos/pending/2026-03-06-dashboard-intelligence-field-gaps.md` |
| Auth and External Access | JWT + API key via single Depends(verify_auth); Cloudflare Tunnel; authenticated SSE. | — |
| HMA I1 indicator | Hull Moving Average (WMA of 2×WMA(n/2) − WMA(n), sqrt(n)). ~20 lines. Once added, HMA 2nd derivative is trivial via MomentumAcceleration pattern. | `ideas/2nd-derivative-indicator-research.md` |
| AC Oscillator I1 plugin | Todo exists, fully specced. | — |
| Derivative Oscillator I2 plugin | Todo exists, fully specced. | — |
| Extend MACD events | Histogram acceleration signal, ~10 lines added to existing I2 MACD event plugin. | — |
| Expand I5 candlestick + I7 setup | Add Tier 1 candlestick patterns (engulfing, pin bar, hammer); wire I7 setup from confirmed pattern. | — |
| Audit + remove dead DB tables | `technical_indicators` table appears orphaned — confirm unused and drop. | — |
| validate_alpha.py re-runs | Re-run `validate_alpha.py --promote` for bootstrap-promoted plugins (DerivOsc, AC Osc) once 30+ bars accumulate. | — |

### Tier 2 — v1.6 or v1.7 (moderate dependencies)

| Item | Notes | Analysis |
|------|-------|---------|
| ML Scoring Model | XGBoost/LightGBM on intelligence_features + signal_ledger outcomes. Needs ~90 days signal history — not yet accumulated. | — |
| Gap-fill service | Detect + backfill gaps in market_data_ohlcv from TWS downtime. Query gaps in 1m series, fetch only missing windows from IBKR, replay. | — |
| Roll premium/discount feature | Front/back month spread at roll = contango/backwardation signal. Needs back-month IBKR fetch. | — |
| Multi-TF S/R awareness for signal plugins | I7 plugins currently operate per-TF; expose higher-TF S/R levels as inputs for stop/target placement. | — |
| BSL/SSL level clusters | Schema change: list of levels vs single nearest level. More useful for signal proximity scoring. | — |
| Offload plugin pipeline to thread pool | CPU-bound plugin work starves event loop under load. Thread-safety audit required first. | — |
| Expand 2nd-derivative indicators | Volume accel, vol accel, structural accel. Research-first gate: confirm signal value before building. | `ideas/2nd-derivative-indicator-research.md` |
| Regime-adaptive plugin parameters | I1/I4 parameter values adapt to hmm_regime (e.g. shorter RSI period in trending regime). | — |
| Shadow signal gate tuning | Once sufficient regime_suppressed shadow data accumulates, analyze gate thresholds empirically. | — |

### Tier 3 — Longer horizon / separate products

| Item | Notes | Analysis |
|------|-------|---------|
| Orderflow Integration | reqTickByTickData; buy/sell delta metrics; delta divergence / absorption / imbalance continuation plugins. | — |
| Portfolio Management | Correlation matrix; sector exposure limits; symbol rotation. | — |
| Trade Journal Auto-Documentation | LLM daily summaries from signal_ledger — learning opportunities from losing trades, performance by setup/regime/TF. | — |
| Robinhood-Style Scaling | Consumer Proxy pattern; Changelog Streams for state recovery. | `analysis/2026-02-12-robinhood-scaling-patterns.md` |
| Broker-agnostic instrument provider | Defer until second broker integration is needed. | — |
| Redpanda migration | Migrate from DragonflyDB streams to Redpanda before QualAgent; not before v1.5. | `docs/ideas/tech-stack.md` |

## Progress

**Execution Order:**
Phases execute in numeric order: 0-17 (v1.4 complete) → 18 → 19 → 20 → 21

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
| 19. Financial Math Characterization | 3/3 | Complete    | 2026-03-09 | - |
| 20. Circuit Breaker Integration | 3/4 | In Progress|  | - |
| 21. Efficiency Optimizations | v1.5 | 0/4 | Not started | - |
