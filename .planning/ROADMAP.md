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

### 🔲 v1.8 Signal Intelligence (Planned)

**Milestone Goal:** Complete the dashboard intelligence surface and close Renaissance signal quality gaps — constituent contributions, alpha decay, freshness decay, Hurst/entropy gates, and distribution drift detection.

- [x] **Phase 28: Dashboard Completion** — Signal Scorecard panel, drill panel history from DB, GARCH/Kalman I4 fields, SMC detail fields, tier tooltips (completed 2026-03-12)
- [x] **Phase 29: Renaissance Signal Quality** — constituent_contributions, alpha decay, signal freshness decay, volume/killzone CIS gates, Hurst/entropy I4 plugins, KS + CUSUM drift detection (completed 2026-03-13)

## Phase Details

### Phase 25: CIS Data Repair
**Goal**: All signal_ledger rows — historical and future — carry populated CIS fields, making the ML training dataset complete.
**Depends on**: Nothing (independent of Phase 26)
**Requirements**: CIS-01, CIS-02, CIS-03, CIS-04
**Success Criteria** (what must be TRUE):
  1. Running `historical_backfill.py` produces new `signal_ledger` rows with non-NULL `cis_score`, `cis_direction`, and `cis_bucket_breakdown` on every signal that has a matching `intelligence_features` row.
  2. A pre-repair audit query reports exact NULL counts, recoverable count (rows with a matching `intelligence_features` row), and unrecoverable count (orphaned rows with no feature match).
  3. After the repair UPDATE, a post-repair verification query shows NULL `cis_score` count = unrecoverable count (all recoverable rows now have values).
  4. Unrecoverable (orphaned) rows are logged at WARNING level with their signal IDs for investigation, not silently left NULL.
**Plans**: 2 plans

Plans:
- [ ] 25-01: Fix `historical_backfill.py` — pass `features=` kwarg to `aggregate()` and add tests
- [ ] 25-02: Audit and repair script — NULL count query, UPDATE recoverable rows, log orphans

### Phase 26: Signal Generator Warmup
**Goal**: The signal generator fires on the first live bar after startup, with no manual wait and no data loss during service restarts.
**Depends on**: Nothing (independent of Phase 25)
**Requirements**: WARM-01, WARM-02, WARM-03, WARM-04
**Success Criteria** (what must be TRUE):
  1. On `signal_generator_service` startup, `bar_history` is seeded with `min_bars_for_tf(tf)` bars per active contract × timeframe fetched from `intelligence_features` before the service begins consuming live stream data.
  2. The first live bar received after startup can trigger a signal — no warmup period elapses before signal evaluation begins.
  3. If `intelligence_features` is unreachable at startup, the service logs a loud WARNING ("DB seed failed — falling back to live warmup") and starts normally; it does not crash or hang.
  4. The startup log includes a seeding completion message with bar counts per symbol/TF (e.g., "Seeded ES 1m: 120 bars, ES 5m: 26 bars, ...").
**Plans**: TBD

Plans:
- [ ] 26-01: DB seed implementation — `_seed_bar_history_from_db()` method + startup integration + tests

### Phase 27: Signal Lifecycle Stream Events
**Goal**: The dashboard shows signal outcomes (EXPIRED, STOPPED, T1 HIT, etc.) in real time as `signal_lifecycle_service` closes signals — and never replays a stale signal on SSE reconnect.
**Depends on**: Nothing (independent of 25 and 26)
**Design**: `docs/plans/2026-03-06-signal-lifecycle-stream-events-design.md`
**Success Criteria** (what must be TRUE):
  1. When a signal exits (any outcome), a `direction=0` event with `signal_id`, `status`, `outcome`, and `exit_price` is published to `signals:SYMBOL:TF:aggregated` within the same bar evaluation loop.
  2. The dashboard renders a resolved signal as dimmed + outcome badge (`EXPIRED` / `STOPPED` / `T1 HIT` / `T1+T2 HIT` / `FULL TARGET`) and clears it when the next live signal arrives.
  3. On SSE reconnect, signal stream entries older than `2×TF` are skipped — no stale signal replays on page load.
  4. `GET /api/signals/{symbol}?timeframe=5m` returns only 5m signals (timeframe filter was previously accepted but silently ignored).

Plans: 8 plans
- [ ] 27-01: `_publish_terminal_event()` helper in signal_lifecycle_service + tests
- [ ] 27-02: Wire terminal event into both exit paths (normal + shadow)
- [ ] 27-03: SSE snapshot age filter — skip signal entries older than 2×TF on reconnect
- [ ] 27-04: REST API timeframe filter — fix silently-ignored `?timeframe=` param
- [ ] 27-05: Extend `SignalData` type with `resolved`, `outcome`, `exit_price`, `signal_id`
- [ ] 27-06: Handle resolved events in `use-market-stream.ts` signal_data handler
- [ ] 27-07: Render resolved state in `signal-panel.tsx` with outcome badge
- [ ] 27-08: Wire OutcomeBadge into signal-banner.tsx + eliminate three-way resolved rendering drift (gap closure)

### Phase 28: Dashboard Completion
**Goal**: The dashboard fully surfaces the intelligence pipeline — Signal Scorecard with all ranked signals, drill panel signal history from DB, GARCH/Kalman I4 fields, SMC detail fields, and tier tooltips.
**Depends on**: Phase 27 (SSE `signal_scorecard` event type)
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, DASH-06, DASH-07, DASH-08
**Success Criteria** (what must be TRUE):
  1. Drill panel Signal Scorecard shows all ranked signals for the current bar with confidence, direction, composite rank, regime eligibility, and suppression reason.
  2. Suppressed signals display human-readable suppression labels (`< 60% conf` / `< 5 bars` / `wrong regime`).
  3. `GET /api/signals/recent` returns paginated recent signals from signal_ledger; drill panel merges with live SSE history deduplicated by signal_id.
  4. Drill panel shows GARCH/Kalman I4 fields and SMC detail fields (BSL/SSL dist_atr/touches/significance, premium/discount fields).
  5. Tier labels (I1–I8) show hover tooltips.
**Plans**: 7 plans

Plans:
- [ ] 28-01-PLAN.md — SSE: wire intelligence_i7 stream domain + signal_scorecard event name
- [ ] 28-02-PLAN.md — Types + hook: RankedSignal, SignalScorecardData, scorecardByTf state
- [ ] 28-03-PLAN.md — New component signal-scorecard.tsx + drill panel wiring
- [ ] 28-04-PLAN.md — Backend: GET /api/signals/recent endpoint
- [ ] 28-05-PLAN.md — Drill panel: DB signal history fetch + dedup merge with SSE history
- [ ] 28-06-PLAN.md — Drill panel: GARCH/Kalman I4 fields + BSL/SSL detail + premium/discount
- [ ] 28-07-PLAN.md — TierTooltip component + wire to all I1-I8 tier labels

### Phase 29: Renaissance Signal Quality
**Goal**: Signal quality matches Renaissance-grade standards — constituent contributions populated, alpha decay applied, signal freshness decay active, volume/killzone CIS gates wired, Hurst/entropy I4 plugins gating setups, and KS + CUSUM drift detection monitoring.
**Depends on**: Phase 14 (setup_performance table), Phase 26 (bar_history seeding)
**Requirements**: QUAL-01, QUAL-02, QUAL-03, QUAL-04, QUAL-05, QUAL-06, QUAL-07, QUAL-08, QUAL-09, QUAL-10
**Success Criteria** (what must be TRUE):
  1. `cis_scorer.py` populates `constituent_contributions` JSONB with per-setup scores for each bucket on every CIS computation.
  2. Aggregator applies alpha decay: repeated same-direction signals from the same setup within `alpha_half_life` bars are down-weighted.
  3. Signal lifecycle applies freshness decay: active signal confidence decays as `exp(-λ × bars_since_fire)`.
  4. Per-setup cooldown prevents same setup firing in same direction within `_SIGNAL_COOLDOWN_BARS` (3 bars 1m, 2 bars 5m+).
  5. `rel_volume` wired into CIS momentum bucket; killzone context gates CIS time-of-day confidence.
  6. `HurstExponentPlugin` (I4) suppresses mean-reversion setups when H > 0.65 and trend setups when H < 0.45.
  7. `ShannonEntropyPlugin` (I4) reduces all signal confidence 30–50% when return entropy is high.
  8. KS drift detection background job emits monitoring flag when feature distributions deviate (p < 0.05).
  9. CUSUM performance drift detection alerts when per-setup win rates degrade relative to baseline.
**Plans**: 7 plans

Plans:
- [ ] 29-01-PLAN.md — CIS scorer: refactor 6 bucket methods to return (float, dict); populate constituent_contributions
- [ ] 29-02-PLAN.md — Per-setup cooldown + rel_volume CIS momentum + killzone CIS regime wire-ins
- [ ] 29-03-PLAN.md — Alpha decay in signal_generator + freshness decay in signal_lifecycle
- [ ] 29-04-PLAN.md — HurstExponentPlugin (I4) + TIER_I4 registration
- [ ] 29-05-PLAN.md — ShannonEntropyPlugin (I4) + quality multiplier wiring in _build_all_ranked()
- [ ] 29-06-PLAN.md — Migration 026 + stream_keys + KSDriftMonitor + drift_monitor_service skeleton
- [ ] 29-07-PLAN.md — CUSUMMonitor + weight_updater CUSUM integration + GET /api/drift + service completion

## Backlog

Items decided but not yet scheduled. Pull into a milestone when ready.
Re-prioritized 2026-03-10 after v1.6 shipped.

### Tier 1 — Ready now / v1.7 candidates (data exists, no blockers)

| Item | Notes | Analysis |
|------|-------|---------|
| Renaissance Gaps (Signal Quality) | → **Scheduled as Phase 29** | `docs/ideas/renaissance-gap-analysis.md` |
| Dashboard Complete | → **Scheduled as Phase 28** | `.planning/todos/pending/2026-03-06-dashboard-intelligence-field-gaps.md`, `.planning/todos/pending/2026-03-11-drill-panel-signal-history-from-db.md`, `.planning/todos/pending/2026-02-27-add-tooltips-to-intelligence-level-indicators.md` |
| Expand I5 candlestick + I7 setup | 18 patterns spec'd (Tier 1: Harami, Dark Cloud, Three Soldiers/Crows, Morning/Evening Star). Research doc complete. | `docs/ideas/candlestick-pattern-expansion-research.md` |
| VWAP/Session plugin TF guards | Research: VWAP and session plugins may fire on TFs where they're not meaningful (e.g. 1d). Add guards. | `.planning/todos/pending/2026-03-10-research-vwap-and-session-plugin-timeframe-guards.md` |
| LLM Call Tracking | Real token counts (Ollama eval counts), error details, cis_score/zone fields, retry chain visibility. | `.planning/todos/pending/2026-03-07-improve-llm-call-tracking.md` |
| Audit + remove dead DB tables | `technical_indicators` table appears orphaned — confirm unused and drop. | `.planning/todos/pending/2026-03-06-audit-and-remove-dead-database-tables.md` |
| CIS Null Repair Execution | Phase 25 repair script complete + tested (11 tests). Blocked by PostgreSQL shared memory error on 1.8M row JOIN. Investigate Docker cgroup limits, batch by symbol/TF, then run repair. Code: `production/scripts/repair_cis_nulls.py`. | memory: `Phase 25 Complete` |
| validate_alpha.py re-runs | Re-run `validate_alpha.py --promote` for bootstrap-promoted plugins (DerivOsc, AC Osc) once 30+ bars accumulate. | — |
| Auth and External Access | JWT + API key via single Depends(verify_auth); Cloudflare Tunnel; authenticated SSE. SSE fan-out: one Redis reader → broadcast to N clients (not N independent pollers). `next build` + nginx for prod dashboard. | — |

### Tier 2 — v1.7 or v1.8 (moderate dependencies)

| Item | Notes | Analysis |
|------|-------|---------|
| I6 Confluence Expansion | Cross-TF + cross-asset confluence (ES/NQ/RTY alignment, VIX regime, sector rotation). Design complete. Needs new IBKR subs. | `docs/ideas/i6-confluence-expansion.md` |
| Intelligence Stack Latency | Parallel plugin workers within tiers (2-7× speedup potential). Thread-safety audit required. | `docs/ideas/intelligence-stack-latency-reduction.md` |
| ML Scoring Model | XGBoost/LightGBM on intelligence_features + signal_ledger outcomes. Needs ~90 days signal history — not yet accumulated. | — |
| Gap-fill service | Detect + backfill gaps in market_data_ohlcv from TWS downtime. Query gaps in 1m series, fetch only missing windows from IBKR, replay. | `.planning/todos/pending/2026-03-04-add-gap-fill-service.md` |
| Roll premium/discount feature | Front/back month spread at roll = contango/backwardation signal. Needs back-month IBKR fetch. | `.planning/todos/pending/2026-03-04-add-roll-premium-discount-feature.md` |
| Volume Profile POC/VAH/VAL | Session volume profile as S/R anchors — I1 plugin. POC = magnetic price level, VAH/VAL = range boundaries for breakout/rejection setups. | `.planning/todos/pending/2026-02-27-add-volume-profile-poc-vah-val-as-sr-anchors.md` |
| Multi-TF S/R awareness for signal plugins | I7 plugins currently operate per-TF; expose higher-TF S/R levels as inputs for stop/target placement. | `.planning/todos/pending/2026-02-27-add-multi-timeframe-sr-awareness-to-signal-plugins.md` |
| BSL/SSL level clusters | Schema change: list of levels vs single nearest level. More useful for signal proximity scoring. | `.planning/todos/pending/2026-02-27-support-bsl-ssl-level-clusters-not-just-single-levels.md` |
| Offload plugin pipeline to thread pool | CPU-bound plugin work starves event loop under load. Thread-safety audit required first. | `.planning/todos/pending/2026-02-28-offload-plugin-pipeline-to-thread-pool.md` |
| Expand 2nd-derivative indicators | Volume accel, vol accel, structural accel (beyond v1.6 ExhaustionScore/AccelerationRegime). Research-first gate. | `docs/ideas/2nd-derivative-indicator-research.md` |
| API keyset pagination | Large features export endpoint has no pagination — blocks on full table scan. Keyset pagination on `intelligence_features`. | `.planning/todos/pending/2026-02-24-add-keyset-pagination-to-features-export-and-rest-endpoint.md` |
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
| Redpanda migration | Migrate from DragonflyDB streams to Redpanda before QualAgent; not before v1.8+. | `docs/ideas/tech-stack.md` |

## Progress

**Execution Order:**
Phases execute in numeric order: 0-24 complete (v1.0–v1.6 shipped). v1.7: phases 25-27 shipped. v1.8: phase 28 complete, phase 29 in progress.

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
| 29. Renaissance Signal Quality | 8/8 | Complete   | 2026-03-13 | — |
