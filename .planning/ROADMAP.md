# Roadmap: IndicAgent

## Milestones

- ✅ **v1.0 MVP** — Phases 0-9 (shipped 2026-02-28)
- ✅ **v1.1 Code Quality Sprint** — Phase 01 (shipped 2026-03-01)
- ✅ **v1.2 Intelligence Palette Expansion** — Phases 02-07 (shipped 2026-03-02)
- ✅ **v1.3 Signal Intelligence Expansion** — Phases 08-11 (shipped 2026-03-04)
- ✅ **v1.4 Quant Foundation** — Phases 12-17 (shipped 2026-03-07)
- ✅ **v1.5 Production Hardening** — Phases 18-22 (shipped 2026-03-10)

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

## v1.6 Signal Quality

- [x] **Phase 23: Signal Generator Gate** — condition-vs-event onset detection, direction flip suppression, cross-bar signal memory, InputSpec cleanup (completed 2026-03-10)

### Phase 23: Signal Generator Gate

**Goal:** Fix signal generator to emit onset events (not persistent condition fires), add cross-bar memory with direction flip suppression, clean up dead InputSpec timeframe declarations, and make an explicit decision on 4h/1d processing scope.

**Depends on:** Phase 22

**Plans:** 3/3 plans complete

Plans:
- [ ] 23-01-PLAN.md — Wave 0 test stubs (RED) for gate cooldown, flip suppression, flip-after-resolution
- [ ] 23-02-PLAN.md — Signal gate implementation: _check_gate, _update_gate, resolution listener
- [ ] 23-03-PLAN.md — InputSpec timeframe cleanup (17 plugins) + 4h/1d exclusion comments

### Phase 24: second-derivative-acceleration

**Goal:** Add second-derivative (acceleration) intelligence to I2/I3 tiers — early inflection detection, exhaustion guards, and 17 new ML features per bar. Add HMA I1 indicator; extend MomentumAcceleration (+rsi_curvature, macd_hist_slope, price_accel, hma_slope, hma_accel); add ExhaustionScore and AccelerationRegime I2 plugins; add SwingMomentum I3 plugin; wire exhaustion awareness into LiquiditySweepReclaim/LiquidityHunt (boost) and MomentumBreakout/TrendFollowing (guard).

**Depends on:** Phase 23

**Plans:** 5 plans

Plans:
- [ ] 24-01-PLAN.md — Wave 0 TDD stubs (RED): extend test_momentum_accel, create test_exhaustion_score, test_acceleration_regime, test_swing_momentum, test_hma, test_i7_exhaustion_wiring
- [ ] 24-02-PLAN.md — Wave 1: HMA I1 plugin + extend MomentumAcceleration (+5 outputs, tuple inputs)
- [ ] 24-03-PLAN.md — Wave 2a: ExhaustionScore + AccelerationRegime I2 plugins
- [ ] 24-04-PLAN.md — Wave 2b: SwingMomentum I3 plugin (parallel with 24-03)
- [ ] 24-05-PLAN.md — Wave 3: register_plugins.py registration + I7 exhaustion wiring (4 setups)

## Backlog

Items decided but not yet scheduled. Pull into a milestone when ready.
Re-prioritized 2026-03-08 after v1.5 planning.

### Tier 1 — Ready now / v1.6 candidates (data exists, no blockers)

| Item | Notes | Analysis |
|------|-------|---------|
| Signal Generator DB Warmup | Seed bar_history from intelligence_features on startup — eliminates 50-min warmup after restart. | `.planning/todos/pending/2026-03-09-seed-signal-generator-bar-history-from-db-on-startup.md` |
| Renaissance Gaps (CIS + Signal Quality) | T0: fix CIS scoring in backfill + populate constituent_contributions. T1: alpha decay, signal freshness, volume confidence, killzone accel. T2: Hurst/entropy I4 plugins. T3: KS + CUSUM drift detection. | `docs/ideas/renaissance-gap-analysis.md` |
| Dashboard Complete | I7 all_ranked panel (new SSE route); signal history view; final audit across all symbol profiles. | `.planning/todos/pending/2026-03-06-dashboard-intelligence-field-gaps.md` |
| Auth and External Access | JWT + API key via single Depends(verify_auth); Cloudflare Tunnel; authenticated SSE. | — |
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
Phases execute in numeric order: 0-17 (v1.4 complete) → 18 → 19 → 20 → 21 → 22

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
| 24. Second-Derivative Acceleration | v1.6 | 0/5 | In Progress | — |
