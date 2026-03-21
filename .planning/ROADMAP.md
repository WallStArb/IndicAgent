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
- 🚧 **v2.0 Signal Integrity & ML Foundation** — Phases 39-50 (in progress)

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

<details open>
<summary>🔄 v2.0 Signal Integrity & ML Foundation (Phases 39-46) — IN PROGRESS</summary>

- [x] **Phase 39: Data Quality + DB Health (Expanded)** — CIS null repair, ohlcv chunk compress, signal_ledger generated columns (effective_ts, pipeline_lag_ms), CHECK constraints (status/outcome/direction), signal_performance_segmented table, IC computation, data quality monitoring infrastructure (completed 2026-03-19)
- [x] **Phase 39.1: Intelligence Layer Enforcement (INSERTED)** — regime_type Protocol enforcement, SignalStatus + SignalOutcome enums, pre-commit hooks, VWAP/ShannonEntropy bug fixes, SQL hardening, topic namespace cleanup (6/6 plans) (completed 2026-03-19)
- [x] **Phase 40: DAG Refactor — Clean Foundation** — signal_generator decomposed into 6 DAG microservices (calibrator, ranker, regime_gate, tod_adjuster, winner_selector, quality_gate), 8 Redpanda topics, systemd units, E2E DAG pipeline integration test (completed 2026-03-19)
- [x] **Phase 41: Intelligence Gap Fill** — i6 FVG/OB alignment from real data, POC/VAH/VAL as T1/T2 targets, roll premium/discount, multi-TF S/R context; VWAP/session plugin TF guards, aggregator active-from-all-ranked assertion, plugin state-writeback comments (completed 2026-03-20)
- [x] **Phase 42: Candlestick Pattern Expansion** — 18 new I5 patterns + CandlestickPatternSetup confidence tier weights (completed 2026-03-20)
- [ ] **Phase 43: Performance & Stability Emergency** — ohlcv table rebuild (15,721 → ~365 chunks, fix 4-5s query timeouts), feature_writer sequential polling fix (920ms → <50ms lag), plugin pipeline thread-pool offload, lifecycle O(N) loop + chandelier write guard, calibration ndarray pre-alloc, refresh loop shared helper coroutine
- [x] **Phase 44: I7 DAG Refactor** — extract atr_utils, position_utils, confidence_utils, BaseI7Plugin mixin (OHLCV extraction, _no_signal, compute_next), direction→signal_type helper, confidence system contract [0.10, 0.95]; validate_tier() enforcement; cross_timeframe.py → 3 focused modules; composites/common.py → utils/common.py (tier-agnostic); OFI type fixes + make_signal() factory + validate_signal() enforcement (~458 LOC duplication eliminated, zero signal behavior change) (completed 2026-03-21)
- [ ] **Phase 44.1: Feature Pipeline Renaissance Refactor** — replace indicator_service + market_analysis_service + timeframes_builder_service with unified FeaturePipelineService; shared BarHistory + BarAccumulator modules; typed BarMessage schema; in-pipeline HTF derivation (no DB queries in hot path); 3 Kafka hops → 1; pipeline_latency_ms < 50ms p99; SignalGeneratorService simplified (remove DB seed, wire BarHistory to IntelligenceEvent stream)
- [ ] **Phase 44.2: SignalGeneratorService Consolidation** — absorb 6 pipeline stage microservices (quality_gate, regime_gate, tod_adjuster, calibrator, ranker, winner_selector) into in-process pure functions; `src/intelligence/pipeline/` module dir; bounded async audit queue; publish BarIntelligenceRecord to `development.intelligence.record`; 8 Kafka execution hops → 2; retire 6 systemd units
- [ ] **Phase 44.3: Atomic Persistence + OHLCV Unification** — FeatureWriterService consumes `intelligence.record` only; single atomic INSERT per bar (no UPSERTs, no partial rows); DB migration for 10 new `intelligence_features` columns; i8 UPSERT migrated to LLMWriterService; FeaturePipelineService as sole live writer to `market_data_ohlcv`; 18 services → 9 pipeline complete
- [ ] **Phase 45: I6 → I7 Confluence Wiring + Exhaustion Standardization** — wire ctf_score + relevant I6 sub-scores into all 28 I7 plugin confidence calculations, weighted by setup family; wire exhaustion_utils (guard/boost) to all applicable I7 plugins (32/36 currently unwired — Renaissance violation); both ship in single shadow mode window (logs old vs new confidence, no live score change); prerequisite for Phase 46 amplification
- [ ] **Phase 46: I6 Confluence Expansion** — cross-asset topic injection, VIX regime scoring, sector rotation scoring, FVG/OB alignment weights non-zero
- [ ] **Phase 47: Shadow Mode Graduation** — hmm_regime threshold validation, enable cross-asset + roll monitor, promote trad_DualDivergence
- [ ] **Phase 48: Auth + External Access** — JWT cookie auth, CORS hardening, Cloudflare Tunnel, standalone Next.js prod build, auth event logging; keyset pagination for features export + REST endpoint (before_ts cursor)
- [ ] **Phase 49: ML Scoring Model** — feature builder, stationarity gates, global + regime-specific LightGBM, walk-forward retraining, shadow ml_score, blend promotion, SHAP attribution; LLM call audit trail complete (token counts, retry chain, outcome back-fill) as ML training data feed
- [ ] **Phase 50: Renaissance Observability** — performance attribution per DAG stage, A/B test framework, causal inference, counterfactual analysis, LLM gate optimizer; intelligence tier audit surface (all I3/I4/I5/I6 fields inspectable in dashboard), staleness as first-class quality signal (confidence penalty + signal_ledger flag + display)

</details>

## Phase Details

<details>
<summary>✅ Pre-renumber specs (Phases 25-38, now renumbered 39-50) — archived 2026-03-20</summary>

> Phase details for v1.9 (Phases 31-38) are archived in `.planning/milestones/v1.9-ROADMAP.md`

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
- [x] 25-01: Fix `historical_backfill.py` — pass `features=` kwarg to `aggregate()` and add tests
- [x] 25-02: Audit and repair script — NULL count query, UPDATE recoverable rows, log orphans

### Phase 26: Signal Generator Warmup
**Goal**: The signal generator fires on the first live bar after startup, with no manual wait and no data loss during service restarts.
**Depends on**: Nothing (independent of Phase 25)
**Requirements**: WARM-01, WARM-02, WARM-03, WARM-04
**Success Criteria** (what must be TRUE):
  1. On `signal_generator_service` startup, `bar_history` is seeded with `min_bars_for_tf(tf)` bars per active contract × timeframe fetched from `intelligence_features` before the service begins consuming live stream data.
  2. The first live bar received after startup can trigger a signal — no warmup period elapses before signal evaluation begins.
  3. If `intelligence_features` is unreachable at startup, the service logs a loud WARNING ("DB seed failed — falling back to live warmup") and starts normally; it does not crash or hang.
  4. The startup log includes a seeding completion message with bar counts per symbol/TF (e.g., "Seeded ES 1m: 120 bars, ES 5m: 26 bars, ...").
**Plans**: 1 plan

Plans:
- [x] 26-01: DB seed implementation — `_seed_bar_history_from_db()` method + startup integration + tests

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
- [x] 27-01: `_publish_terminal_event()` helper in signal_lifecycle_service + tests
- [x] 27-02: Wire terminal event into both exit paths (normal + shadow)
- [x] 27-03: SSE snapshot age filter — skip signal entries older than 2×TF on reconnect
- [x] 27-04: REST API timeframe filter — fix silently-ignored `?timeframe=` param
- [x] 27-05: Extend `SignalData` type with `resolved`, `outcome`, `exit_price`, `signal_id`
- [x] 27-06: Handle resolved events in `use-market-stream.ts` signal_data handler
- [x] 27-07: Render resolved state in `signal-panel.tsx` with outcome badge
- [x] 27-08: Wire OutcomeBadge into signal-banner.tsx + eliminate three-way resolved rendering drift (gap closure)

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
- [x] 28-01-PLAN.md — SSE: wire intelligence_i7 stream domain + signal_scorecard event name
- [x] 28-02-PLAN.md — Types + hook: RankedSignal, SignalScorecardData, scorecardByTf state
- [x] 28-03-PLAN.md — New component signal-scorecard.tsx + drill panel wiring
- [x] 28-04-PLAN.md — Backend: GET /api/signals/recent endpoint
- [x] 28-05-PLAN.md — Drill panel: DB signal history fetch + dedup merge with SSE history
- [x] 28-06-PLAN.md — Drill panel: GARCH/Kalman I4 fields + BSL/SSL detail + premium/discount
- [x] 28-07-PLAN.md — TierTooltip component + wire to all I1-I8 tier labels

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
  6. `HurstExponentPlugin` (I4) suppresses mean-reversion setups when H > 0.65 and trend setups when H < 0.48.
  7. `ShannonEntropyPlugin` (I4) reduces all signal confidence 30–50% when return entropy is high.
  8. KS drift detection background job emits monitoring flag when feature distributions deviate (p < 0.05).
  9. CUSUM performance drift detection alerts when per-setup win rates degrade relative to baseline.
**Plans**: 7 plans

Plans:
- [x] 29-01-PLAN.md — CIS scorer: refactor 6 bucket methods to return (float, dict); populate constituent_contributions
- [x] 29-02-PLAN.md — Per-setup cooldown + rel_volume CIS momentum + killzone CIS regime wire-ins
- [x] 29-03-PLAN.md — Alpha decay in signal_generator + freshness decay in signal_lifecycle
- [x] 29-04-PLAN.md — HurstExponentPlugin (I4) + TIER_I4 registration
- [x] 29-05-PLAN.md — ShannonEntropyPlugin (I4) + quality multiplier wiring in _build_all_ranked()
- [x] 29-06-PLAN.md — Migration 026 + stream_keys + KSDriftMonitor + drift_monitor_service skeleton
- [x] 29-07-PLAN.md — CUSUMMonitor + weight_updater CUSUM integration + GET /api/drift + service completion

### Phase 30: Redpanda Migration
**Goal**: Replace DragonflyDB (Redis Streams) with Redpanda as the event bus across all 8 services, removing DragonflyDB from the stack entirely. Pure transport-layer migration — no business logic changes.
**Depends on**: Phase 29
**Requirements**: KAFKA-01, KAFKA-02, KAFKA-03, KAFKA-04, KAFKA-05, KAFKA-06, KAFKA-07, KAFKA-08
**Plans:** 5/5 plans complete

Plans:
- [x] 30-01-PLAN.md — Infrastructure + Core Abstractions: Redpanda compose, aiokafka, stream_utils rewrite, stream_keys rewrite, topic init script
- [x] 30-02-PLAN.md — Hot Tier + Intelligence Pipeline: tws_daemon, timeframes_builder, indicator_service, market_analysis_service
- [x] 30-03-PLAN.md — Signal + AI Services: signal_generator, signal_lifecycle, ai_narrative; _live_quotes dict + _llm_scores_cache
- [x] 30-04-PLAN.md — Writer Services + API/SSE: feature_writer, llm_writer, SSE broadcaster fan-out
- [x] 30-05-PLAN.md — Cache Migration + DragonflyDB Removal + E2E Validation

---

### Phase 31: CIS Learning Loop + Signal Feature Snapshots
**Goal**: The CIS scorer self-improves — loading learned weights from DB at runtime, training on binary win/loss labels, segmenting by asset cluster and timeframe, and capturing mid-bar feature snapshots for every new signal as the ML training dataset foundation.
**Depends on**: Phase 30 (Redpanda pipeline live, weight_updater.py exists, cis_weights table exists)
**Requirements**: LEARN-01, LEARN-02, LEARN-03, LEARN-04, FEAT-01, FEAT-02, SHAD-01, SHAD-02
**Success Criteria** (what must be TRUE):
  1. After `weight_updater` timer runs with N ≥ 100 resolved signals in a cluster, CIS scorer loads those weights from DB on next 30-min refresh cycle — observable via service log "Loaded weights from DB for cluster=eq_index tf=1m" rather than the bootstrap fallback message.
  2. `signal_features` rows appear in TimescaleDB atomically with every new `signal_ledger` row — a query joining the two tables on `signal_id` returns zero NULL feature rows for signals fired after the migration.
  3. `signal_ledger` has an `is_shadow BOOLEAN NOT NULL DEFAULT FALSE` column; shadow signals written alongside production signals share the same bar timestamp and are distinguishable by this field alone.
  4. The CLI promotion script exits non-zero when given fewer than 200 matched pairs and prints a human-readable reason; exits zero and prints "PROMOTED" only when p < 0.05 AND N ≥ 200.
  5. `cis_weights` rows have non-NULL `asset_cluster` and `timeframe` values; the five cluster values (`eq_index`, `commodity`, `rates`, `crypto`, `ag`) cover all 60 active instruments with no unassigned symbols.
**Plans**: 3 plans

Plans:
- [x] 031-01-PLAN.md — Migration 034 + CISScorer.update_weights() + 30-min refresh loop
- [x] 031-02-PLAN.md — Binary win labels + asset-cluster segmented training
- [x] 031-03-PLAN.md — signal_features atomic write + is_shadow LedgerEntry + CLI promotion gate

### Phase 32: Stop Architecture + Extended Divergence Stack
**Goal**: Every signal carries a verifiable stop basis — structural snap, GARCH-adaptive, or ATR static — computed once in `trade_framer.py` so all 17 plugins inherit it without change, while the divergence stack expands from a hard AND-gate to a 5-input weighted convergence score.
**Depends on**: Phase 31 (learning loop active, signal_features schema in place)
**Requirements**: SIG-01, SIG-02, SIG-03, SIG-04, SIG-05, DIV-01, DIV-02, DIV-03, DIV-04
**Success Criteria** (what must be TRUE):
  1. Every row in `signal_ledger` has a non-NULL `stop_basis` field with one of three values: `"structure_snap"`, `"garch_adaptive"`, or `"atr_static"` — verifiable by querying `SELECT DISTINCT stop_basis FROM signal_ledger WHERE computed_at > now() - interval '1 hour'`.
  2. `structure_snap` fires when an OB low, demand zone boundary, swing low, or FVG low exists within 1.5×ATR of the raw ATR stop level — and logs the structural level used; no per-plugin stop logic remains outside `trade_framer.py`.
  3. Active signals show a `trailing_stop_price` logged per lifecycle update in `signal_lifecycle_service` — the value tightens monotonically (Chandelier: `highest_high_since_entry - 3×ATR` for longs) and never widens.
  4. Signals with an expired regime or vol-drift beyond threshold receive outcome `condition_expired` — observable in `signal_ledger` after a simulated regime flip in a replay run.
  5. `DivergenceStackPlugin` fires when weighted convergence score > 0.40 AND n_agreeing ≥ 3 across RSI, MACD histogram, volume, OBV, and CMF inputs — with individual weights (0.30, 0.25, 0.20, 0.15, 0.10) logged on each fire.
**Plans**: 3 plans

Plans:
- [x] 32-01-PLAN.md -- DB migration 035 + TradeFrame/LedgerEntry + GARCH multiplier + FVG tier + stop_basis + TTL constants
- [x] 32-02-PLAN.md -- Chandelier trailing stop + staleness score + condition_expired + shadow tracking
- [x] 32-03-PLAN.md -- MACD/OBV/CMF divergence I5 plugins + DivergenceStack 5-input weighted score

### Phase 33: Five New I7 Signal Plugins
**Goal**: Five market conditions previously invisible to I7 — failed breakouts, opening range setups, previous-day level tests, second-leg continuations, and volatility contractions — are now covered by registered plugins that fire in replay runs.
**Depends on**: Phase 32 (stop architecture and divergence stack complete; BOS/CHoCH features available from SMC tier; swing detection from I3)
**Requirements**: PLUG-01, PLUG-02, PLUG-03, PLUG-04, PLUG-05
**Success Criteria** (what must be TRUE):
  1. `TIER_I7` in `register_plugins.py` contains all five new plugin names; `registry.validate_tier()` passes without error on service startup.
  2. Each of the five plugins fires at least once in a historical replay run over a one-week window on ES/NQ 1m — observable via `SELECT setup_plugin, COUNT(*) FROM signal_ledger WHERE computed_at > now() - interval '7 days' GROUP BY setup_plugin` showing non-zero rows for each new setup name.
  3. `trad_OpeningRangeBreakout` fires only between 09:30 and 11:30 ET — no signals appear outside this window in the replay output.
  4. `trad_SecondLegContinuation` sets targets at 100%, 127.2%, and 161.8% of leg 1 amplitude — verifiable in signal_ledger `target_1`, `target_2` fields.
  5. `trad_VCP` requires three or more successive range contractions with decreasing volume before firing — the contraction count is logged in signal metadata.
**Plans**: 3 plans

Plans:
- [x] 33-01-PLAN.md — FailedBreakout + ORB15 + ORB30 plugins with TDD tests
- [x] 33-02-PLAN.md — PrevDayLevelTest + SecondLegContinuation + VCP plugins with TDD tests
- [x] 33-03-PLAN.md — Register all 6 plugins in TIER_I7 + TREND_SETUPS wiring

### Phase 34: I4 Infrastructure — Anchored VWAP + Volume Profile
**Goal**: Anchored VWAP and Volume Profile are live I4 features in every `IntelligenceEvent`, enabling two new I7 plugins that trade VWAP extensions and volume-node reactions.
**Depends on**: Phase 33 (TIER_I7 plugin count stable; I4 DAG ordering confirmed clean)
**Requirements**: VWAP-01, VWAP-02, VOL-01, VOL-02
**Success Criteria** (what must be TRUE):
  1. `intelligence_features` rows for ES/NQ 1m bars contain non-NULL `avwap_session`, `avwap_swing`, `avwap_deviation_pct`, `poc_price`, `vah`, and `val` fields after the migration — verifiable by querying one recent feature row.
  2. `trad_AnchoredVWAPReversion` fires only when price is extended more than 1.5 std from anchored VWAP AND HMM regime is ranging AND Hurst < 0.55 — regime and Hurst values logged on each fire for auditability.
  3. `trad_VolumeProfileReaction` fires in all three variants (POC rejection, HVN rejection, LVN breakout) across a one-week replay window — each variant label appears in signal_ledger metadata.
  4. Both new I7 plugins appear in `TIER_I7` and pass `registry.validate_tier()` at startup.
**Plans**: 3 plans

Plans:
- [x] 34-01-PLAN.md — Migrate AnchoredVWAP to I4/context/ with std bands, sigma, velocity (VWAP-01)
- [x] 34-02-PLAN.md — Migrate VolumeProfile to I4/context/ with session-reset + rolling dual-track POC/VAH/VAL (VOL-01)
- [x] 34-03-PLAN.md — Five I7 plugins (VWAPReversion, VWAPReclaim, POCRejection, HVNRejection, LVNBreakout) + registration (VWAP-02, VOL-02)

### Phase 35: Calibration + TOD Multiplier + CIS Kalman Filter
**Goal**: Signal confidence is calibrated against historical outcomes, adjusted by time-of-day win rates, and smoothed through a Kalman filter — making every confidence number a reliable probability estimate rather than a raw score.
**Depends on**: Phase 34 (full plugin set stable; `signal_ledger` accumulating data; `setup_performance` table populated)
**Requirements**: CAL-01, CAL-02, CAL-03, TOD-01, TOD-02, KAL-01, KAL-02
**Success Criteria** (what must be TRUE):
  1. `signal_ledger` rows contain a non-NULL `calibrated_confidence` field for signals where the isotonic regression calibration curve exists (N ≥ 100 per plugin/TF); signals without sufficient history fall back to raw confidence gracefully.
  2. TOD multiplier varies by hour in service logs — a signal fired at 09:30 ET shows a different multiplier than the same setup at 12:00 ET, observable via `grep "tod_multiplier"` in the signal_generator log.
  3. `filtered_cis_score` and `raw_cis_score` are both logged per signal; the updated fire condition (`filtered_cis > 0.35 AND raw_cis > 0.28 AND buckets_agreeing ≥ 3`) is enforced — signals that would have fired under the old condition but fail the new one are suppressed.
  4. The calibration batch job runs alongside the weight_updater timer without conflict — both complete without error in a single timer execution cycle.
**Plans**: 3 plans

Plans:
- [x] 35-01-PLAN.md — DB migration 038 + LedgerEntry extension + confidence_calibrator module
- [x] 35-02-PLAN.md — TOD multiplier (pre-CIS Bayesian-smoothed) + calibrated_confidence sort key in aggregator
- [x] 35-03-PLAN.md — CIS Kalman filter + shadow fire condition + dashboard confidence fields

### Phase 36: Microstructure Plugins
**Goal**: Order flow imbalance and cumulative volume delta are live I1 features and drive two new I7 plugins, giving the system its first microstructure signal layer.
**Depends on**: Phase 35 (calibration and Kalman filter in place; signal confidence pipeline stable before adding new firing sources)
**Requirements**: OFI-01, OFI-02, OFI-03, CVD-01, CVD-02
**Success Criteria** (what must be TRUE):
  1. `intelligence_features` rows for all active instruments contain non-NULL `ofi_ewma_20`, `ofi_divergence`, `cvd`, `cvd_slope_5bar`, and `cvd_divergence` fields — or the implementation variant (bar-level proxy vs tick) is documented in a comment and the OFI audit result is logged at service startup.
  2. `trad_OrderFlowImbalance` and `trad_CVDDivergence` appear in `TIER_I7`; `registry.validate_tier()` passes; both plugins fire at least once in a one-week replay on ES 1m.
  3. `trad_CVDDivergence` logs a `dual_divergence=True` flag when both CVD and OFI diverge simultaneously — the highest-conviction variant is distinguishable in signal_ledger metadata.
  4. The bar-level OFI proxy formula `(close - low) / (high - low + ε) × volume` is used as fallback when tick data is unavailable, with the implementation variant documented in `OFI-01` audit output.
**Plans**: 2 plans

Plans:
- [x] 036-01-PLAN.md — I1 OFI + CVD plugins, tick buffer wiring in indicator_service
- [x] 036-02-PLAN.md — 7 I7 microstructure trading plugins + TIER_I7 registration

### Phase 37: Cross-Asset Intelligence Service
**Goal**: A new `cross_asset_service` microservice monitors equity index spread dynamics across ES, NQ, RTY, and YM and publishes cross-asset divergence signals when spread z-scores exceed meaningful thresholds.
**Depends on**: Phase 36 (microstructure layer complete; all I7 plugins stable before adding a new microservice dependency)
**Requirements**: XA-01, XA-02, XA-03
**Success Criteria** (what must be TRUE):
  1. `indicagent-cross-asset` systemd service starts, subscribes to `intelligence:ES:1m`, `intelligence:NQ:1m`, `intelligence:RTY:1m`, and `intelligence:YM:1m` Redpanda topics, and publishes to `cross_asset:EQ_INDEX:1m` — observable via `rpk topic consume cross_asset.EQ_INDEX.1m` showing live messages.
  2. `es_nq_spread_z`, `es_rty_spread_z`, and `eq_corr_break` appear as fields in the cross-asset topic payload — verifiable by consuming one message and inspecting the JSON keys.
  3. `trad_CrossAssetDivergence` fires in `signal_generator_service` when `|spread_z| > 2.0` — at least one fire is observable in a replay run with an injected spread event; the signal's direction reflects regime bias (reversion in ranging, continuation in trending).
  4. The new service is registered in `CLAUDE.md` service table with its metrics port and in the systemd unit file inventory.
**Plans**: 3 plans

Plans:
- [x] 037-01-PLAN.md — Core service + spread feature computation + stream key + Settings + systemd unit
- [x] 037-02-PLAN.md — CrossAssetDivergence I7 plugin (stateless, regime-biased direction)
- [x] 037-03-PLAN.md — Pipeline wiring: TIER_I7 registration + signal_generator frame injection + feature_writer persistence

### Phase 38: Automated Futures Roll Detection
**Goal**: The TWS daemon automatically detects futures roll events using volume-based statistical analysis and propagates roll events through the pipeline without service restarts, ensuring continuous data capture across contract transitions.
**Depends on**: Phase 34 (I4 infrastructure stable; contract data flowing reliably)
**Requirements**: ROLL-01, ROLL-02, ROLL-03, ROLL-04, ROLL-05, ROLL-06
**Success Criteria** (what must be TRUE):
  1. `contract_metadata` table has `is_front_month`, `roll_gap`, `roll_direction`, `roll_detected_at`, `confirmation_count` columns and `system_events` table exists — verifiable via `\d contract_metadata` and `\d system_events` in psql.
  2. `derive_roll_chain("ES")` returns a 3-contract list with correct month codes and `roll_from`/`roll_to` linkage — verifiable by unit test.
  3. With `ROLL_MONITOR_ENABLED=false` (default), the system behaves identically to current behavior — no roll events published, services use `Settings().contracts` — verifiable by confirming no `system_events` rows exist after a normal run.
  4. With `ROLL_MONITOR_ENABLED=true` and a simulated volume shift, tws_daemon logs "Roll detected" and `contract_metadata.is_front_month` toggles after 3 confirmation bars — verifiable in logs and DB.
  5. Roll boundary marker (`{"roll_boundary": "ESM6->ESU6"}`) appears in `intelligence_features.i7` JSONB for the bar at roll time — verifiable by querying `intelligence_features` near roll timestamp.
**Plans**: 3 plans

Plans:
- [x] 38-01-PLAN.md — DB foundation: migration 037, roll chain utility, DB-backed get_active_contracts(), stream key (ROLL-01, ROLL-02, ROLL-03)
- [x] 38-02-PLAN.md — Roll detection engine: tws_daemon volume tracking, z-score detection, confirmation window, cooldown, roll event publishing (ROLL-04)
- [x] 38-03-PLAN.md — Pipeline integration: downstream service consumption, plugin state migration, roll boundary markers, backfill seeding (ROLL-05, ROLL-06)

### Phase 50: Signal Pipeline DAG Refactor: monolithic→DAG microservices + Renaissance observability

**Goal**: Refactor the signal pipeline from a monolithic aggregator to a clean DAG of independent microservices, then add Renaissance-grade observability: performance attribution, live A/B experimentation, causal inference, data quality monitoring, and fault tolerance.
**Requirements**: None (architectural refactor)
**Depends on**: Phase 49
**Success Criteria** (what must be TRUE):
  1. Pipeline is clean DAG of 6 independent stages (QualityGate → RegimeGate → TODAdjuster → Calibrator → Ranker → WinnerSelector)
  2. Each stage is separate microservice with systemd unit
  3. Stages communicate via Redpanda streams only (no direct coupling)
  4. Each stage has single responsibility (quality gating, regime filtering, TOD adjustment, calibration, ranking, winner selection)
  5. Fault tolerance: bypass on stage failure with circuit breaker
  6. Data quality: validation at each stage drops invalid signals
  7. < 10ms latency per stage
  8. Monolithic aggregator removed from signal_generator_service.py
  9. All stages emit attribution to side channel
**Plans**: 4 plans

Plans:
- [ ] 47-01-PLAN.md — DAG infrastructure: Stage base class, CircuitBreaker, DataQualityMonitor [wave 1]
- [ ] 47-02-PLAN.md — 6 stage implementations: QualityGate, RegimeGate, TODAdjuster, Calibrator, Ranker, WinnerSelector [wave 2]
- [ ] 47-03-PLAN.md — Redpanda topics + systemd services: 8 topics (7-day retention), 6 services (:9119-:9124) [wave 2]
- [ ] 47-04-PLAN.md — Integration: refactor signal_generator_service, E2E test, verify fault tolerance [wave 3]

**Renaissance Principles (LOCKED):**
1. **Instrument everything** — Every decision, transformation, attribution tracked
2. **Let the system run** — Fully automated feedback loops, no manual reviews
3. **Earn the right** — Statistical proof (p < 0.05) before any change
4. **Segment relentlessly** — Regime/context-specific analysis, never global
5. **Degrade gracefully** — Fault tolerance with circuit breakers and bypass modes
6. **Data quality over model complexity** — Validate at each stage, drop invalid signals
7. **Never drop data** — Full retention of all intermediate outputs (7-day topic retention)

**Out of scope for Phase 0 (DAG Refactor):**
- Performance Attribution Service (Phase 1)
- Counterfactual Analysis (Phase 2)
- A/B Test Framework (Phase 3)
- Causal Inference (Phase 4)
- Dashboard & Monitoring (Phase 5)

</details>

### Phase 39: Data Quality + DB Health
**Goal**: The ML training dataset is clean and self-monitoring — CIS nulls repaired, market_data_ohlcv rebuilt for fast queries, signal_ledger hardened with generated columns and CHECK constraints, missing RTH bars auto-fetched, signal performance quantified via Information Coefficient per regime, and data quality monitored continuously via Prometheus.
**Depends on**: Nothing (independent foundation work; unblocks Phase 40+)
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, DATA-08, DATA-09, DATA-10, DATA-11, DATA-12, DATA-13
**Note**: DATA-06 (SignalStatus enum) and DATA-07 (SignalOutcome enum) moved to Phase 39.1 — code-level enum work lives there; DB-level CHECK constraints for status/direction live here (DATA-10).
**Success Criteria** (what must be TRUE):
  1. `market_data_ohlcv` chunk count < 200 (from 15,740); aggregate queries < 500ms.
  2. `signal_ledger` composite index in place; lifecycle UPDATE latency < 5ms (from 34ms).
  3. `cis_score` non-NULL for all recoverable rows — repair_cis_nulls.py exits 0 with 0 repairable NULLs.
  4. `validate_alpha.py --promote` exits 0 for DerivOsc and AC Osc (or explicit "insufficient data" if N < 30).
  5. Gap-fill service running — running twice on same symbol produces no duplicates.
  6. `signal_ledger.effective_ts` and `pipeline_lag_ms` generated columns exist.
  7. CHECK constraints on status and direction block invalid writes at DB level.
  8. IC computed for all plugins with N >= 30; results in `signal_performance_segmented`.
  9. `data_quality_check.py` scheduled every 15 min; Prometheus gauges active.
**Plans**: 6 plans

Plans:
- [x] 039-01-PLAN.md — DB schema hardening: effective_ts + pipeline_lag_ms generated columns, status/direction CHECK constraints, signal_stats_daily view (DATA-08, DATA-09, DATA-10) [wave 1]
- [x] 039-02-PLAN.md — CIS null repair exit-1 gate + alpha validation re-run (DATA-01, DATA-02) [wave 1]
- [x] 039-03-PLAN.md — OHLCV rebuild script + signal_ledger composite index (DATA-03, DATA-04) [wave 1]
- [x] 039-04-PLAN.md — Gap-fill service with RTH detection + systemd timer (DATA-05) [wave 1]
- [x] 039-05-PLAN.md — signal_performance_segmented table + Information Coefficient computation (DATA-11, DATA-12) [wave 1]
- [x] 039-06-PLAN.md — Data quality monitoring: Prometheus metrics + data_quality_check.py + 15-min timer (DATA-13) [wave 2, after 01-04]

### Phase 39.1: Intelligence Layer Enforcement (INSERTED)

**Goal:** Code quality gaps are closed — `regime_type` is enforced by Protocol, signal status strings are replaced with `SignalStatus` enum, naming conventions are enforced by pre-commit hooks, and documentation is consolidated.
**Why urgent:** `regime_type` silent misfire corrupts training data (wrong signals fire), raw status strings across 4 files risk typos, and these gaps block Phase 40+ work that assumes clean enforcement.
**Depends on**: Nothing (independent enforcement work; can run in parallel with Phase 39)
**Requirements**: CODE-Q-01, CODE-Q-02, CODE-Q-03
**Success Criteria** (what must be TRUE):
  1. `PatternPlugin` Protocol includes `regime_type: ClassVar[str]` field — any I7 plugin missing it fails at import time.
  2. `validate_tier()` runtime check verifies `regime_type` value is `"trend"`, `"mean_reversion"`, or `"any"` — service startup crashes on invalid values.
  3. `SignalStatus` enum exists and is used throughout codebase — `grep -r '"pending"\|"active"\|"regime_suppressed"' src/` returns zero results.
  4. Pre-commit hook checks plugin class names end in `Plugin` and files use `snake_case.py` — new violations are caught before commit.
  5. Documentation consolidated in `docs/analysis/intelligence-workflow-audit.md` — all gotchas, conventions, and enforcement gaps are recorded.
**Plans**: 6 plans

Plans:
- [x] 39.1-01-PLAN.md — PatternPlugin Protocol regime_type enforcement + validate_tier() runtime checks (CODE-Q-01) [wave 1]
- [x] 39.1-02-PLAN.md — SignalStatus enum migration across 4 files (signal_ledger.py, signal_generator_service.py, signal_lifecycle_service.py, signals.py) (CODE-Q-02) [wave 1]
- [x] 39.1-03-PLAN.md — Pre-commit hooks (plugin class/file naming, regime_type, dead imports) + intelligence-workflow-audit.md documentation (CODE-Q-03) [wave 1]
- [x] 39.1-04-PLAN.md — Bug fixes: VWAP utc=True (BUG-01), ShannonEntropy NaN guard (BUG-02); SQL hardening: /signals/recent parameterized query (CODE-Q-05) [wave 1]
- [x] 39.1-05-PLAN.md — SignalOutcome enum (8-class taxonomy) + DB CHECK constraint + WIN/STOP/TTL sets in signal_outcome.py (CODE-Q-04) [wave 2, depends on 02]
- [x] 39.1-06-PLAN.md — Topic namespace cleanup: audit dev.* references, fix any hardcoded strings, delete orphaned dev.* topics (INFRA-01) [wave 1]

### Phase 40: DAG Refactor (Clean Foundation)
**Goal**: Refactor the monolithic signal pipeline into a clean DAG of independent microservices — 6 stages (QualityGate → RegimeGate → TODAdjuster → Calibrator → Ranker → WinnerSelector) communicate via Redpanda streams, each with circuit breakers and basic attribution tracking.
**Depends on**: Phase 39 (clean data and indexes in place before architectural refactor)
**Requirements**: None (architectural refactor)
**Success Criteria** (what must be TRUE):
  1. Pipeline is clean DAG of 6 independent stages (QualityGate → RegimeGate → TODAdjuster → Calibrator → Ranker → WinnerSelector)
  2. Each stage is separate microservice with systemd unit
  3. Stages communicate via Redpanda streams only (no direct coupling)
  4. Each stage has single responsibility (quality gating, regime filtering, TOD adjustment, calibration, ranking, winner selection)
  5. Fault tolerance: bypass on stage failure with circuit breaker
  6. Data quality: validation at each stage drops invalid signals
  7. < 10ms latency per stage
  8. Monolithic aggregator removed from signal_generator_service.py
  9. All stages emit basic attribution to side channel (before, after, value_added, reason)
**Plans**: 4 plans

Plans:
- [ ] 40-01-PLAN.md — DAG infrastructure: Stage base class, CircuitBreaker, DataQualityMonitor [wave 1]
- [ ] 40-02-PLAN.md — 6 stage implementations: QualityGate, RegimeGate, TODAdjuster, Calibrator, Ranker, WinnerSelector [wave 2]
- [ ] 40-03-PLAN.md — Redpanda topics + systemd services: 8 topics (7-day retention), 6 services (:9119-:9124) [wave 2]
- [ ] 40-04-PLAN.md — Integration: refactor signal_generator_service, E2E test, verify fault tolerance [wave 3]

**Renaissance Principles (LOCKED):**
1. **Instrument everything** — Every decision, transformation, attribution tracked
2. **Let the system run** — Fully automated feedback loops, no manual reviews
3. **Earn the right** — Statistical proof (p < 0.05) before any change
4. **Segment relentlessly** — Regime/context-specific analysis, never global
5. **Degrade gracefully** — Fault tolerance with circuit breakers and bypass modes
6. **Data quality over model complexity** — Validate at each stage, drop invalid signals
7. **Never drop data** — Full retention of all intermediate outputs (7-day topic retention)

**Out of scope (deferred to Phase 50):**
- Performance Attribution Service (aggregates attribution into DB)
- A/B Test Framework (continuous experimentation)
- Causal Inference Engine (prove causality vs correlation)
- Counterfactual Analysis (track missed opportunities)
- LLM Gate Optimizer (automated config tuning)
- Dashboard DAG Visualization

### Phase 43: Performance & Stability Emergency
**Goal**: Eliminate the two production bottlenecks causing active pain (OHLCV 4-5s query timeouts, feature_writer 920ms lag) and harden the runtime before Phase 41 cross-timeframe work adds more load.
**Depends on**: Phase 40 (DAG refactor in place; aggregator eliminated before these optimizations land)
**Requirements**: PERF-01, PERF-02, PERF-03, PERF-04, PERF-05, PERF-06
**Success Criteria** (what must be TRUE):
  1. `market_data_ohlcv` chunk count drops from 15,721 to ~365 (time-only partitioning, no space partitioning) — `SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name = 'market_data_ohlcv'` returns ≤ 400.
  2. Feature writer p99 ingestion lag < 50ms — achievable by consolidating 3 sequential `xreadgroup` calls into a single batch poll matching the pattern in `market_analysis_service`.
  3. Plugin pipeline CPU work is dispatched to a thread pool via `asyncio.to_thread()` — event loop is unblocked during minute-boundary bursts; a threading.Lock guards shared plugin state.
  4. Signal lifecycle service active-signal lookup is O(1) via index dict `{(symbol, tf): [sids]}` — shadow loop and chandelier are indexed the same way; chandelier state is written to DB only when the stop price changes by ≥ 0.01%.
  5. Calibration curves pre-converted to numpy arrays at cache load time (not per-bar in `_build_all_ranked()`).
  6. All 5 service refresh loops (perf weights, drift penalties, calibration, etc.) use a shared `_run_refresh_loop(name, interval_s, fn)` coroutine — behavioral divergence between loops eliminated.
**Plans**: 3 plans

Plans:
- [ ] 40.5-01-PLAN.md — OHLCV hypertable rebuild: time-only partitioning, 7-day intervals (PERF-01)
- [ ] 40.5-02-PLAN.md — Plugin thread pool + calibration ndarray pre-alloc + refresh loop helper (PERF-03, PERF-05, PERF-06)
- [ ] 40.5-03-PLAN.md — Feature writer i7/i8 batch buffering + lifecycle O(1) index + chandelier write guard + stale signal cleanup (PERF-02, PERF-04)

### Phase 44: I7 DAG Refactor
**Goal**: The I7 trading layer has clean DAG structure — ~458 LOC of duplication extracted into shared utility functions (plugin_utils, atr_utils, confidence_utils), Protocol enforcement tightened, I6 cross_timeframe.py decomposed into 3 focused modules, signal construction standardized via make_signal() factory with validate_signal() enforcement, composites/common.py promoted to tier-agnostic utils/common.py, and all 8 microstructure plugin type contracts fixed. Zero signal behavior change — pure structural refactor, all existing tests pass unchanged.
**Depends on**: Phase 40 (DAG foundation complete)
**Requirements**: DAG-01, DAG-02, DAG-03, DAG-04

**Duplication patterns to eliminate:**
- `_no_signal()` identical method — 36/36 plugins (~72 LOC) → `plugin_utils.no_signal()` import
- OHLCV extraction boilerplate (`frames.get("main")`, null guard, `to_numpy()`) — 36/36 plugins (~108 LOC) → `plugin_utils.extract_ohlcv()`
- ATR fallback (features → compute fallback → zero-guard) — 17/36 plugins (~68 LOC) → `atr_utils.get_atr()` null-guard wrapper (no recomputation)
- Stop/target ATR placement (direction-aware) — 14/36 plugins (~112 LOC) → route through `trade_framer.frame_trade()`
- Confidence clamping with inconsistent bounds — 36/36 plugins (~72 LOC) → `confidence_utils.compose_confidence()` with system contract `[0.10, 0.95]`
- Direction → `signal_type` string (`"_long"`/`"_short"` suffix) — 15/36 plugins (~30 LOC) → `plugin_utils.signal_type_for_direction()`

**Additional structural work (from utility audit):**
- `composites/common.py` promoted to `src/intelligence/utils/common.py` — `is_num`, `crossover_detect`, `threshold_cross`, `track_bars_ago` available to all tiers; I2 composites updated to import from new path
- All 8 microstructure plugin type gaps fixed: `stop_loss` (float), `targets` (non-empty list), `regime_context` (str) — prerequisite for make_signal() factory
- `signal_schema.make_signal()` wired as the single signal construction factory in signal_generator_service (replaces manual dict assembly); `validate_signal()` called on every signal before aggregation — validation failures logged + Prometheus counter + dropped

**Success Criteria** (what must be TRUE):
  1. `plugin_utils.py`, `atr_utils.py`, `confidence_utils.py` exist in `src/intelligence/trading/`; grep confirms zero inline ATR fallback, zero inline stop/target placement in affected plugins
  2. All 36 I7 plugins use `plugin_utils` functions — grep confirms no plugin declares its own `_no_signal()` or duplicates OHLCV extraction
  3. `confidence_utils.compose_confidence()` enforces system contract `floor=0.10, ceil=0.95` — grep confirms no plugin uses raw `min()`/`max()` clamping; all 36 plugins use the utility
  4. `cross_timeframe.py` split into `confluence_weights.py`, `confluence_alignment.py`, `confluence_smc.py` — all existing I6 tests pass unchanged
  5. `src/intelligence/utils/common.py` exists; all I2 composites import from new path; composites/common.py is re-export shim
  6. All 8 microstructure plugins return valid `stop_loss` (float), `targets` (non-empty list), `regime_context` (str)
  7. `make_signal()` is the only signal dict construction point in signal_generator_service; `validate_signal()` called pre-aggregation; failures log ERROR + increment Prometheus counter + drop
**Plans**: 5 plans

Plans:
- [x] 44-01-PLAN.md — Create utility modules (plugin_utils, atr_utils, confidence_utils) + promote utils/common.py + tests (DAG-01, DAG-03, DAG-04)
- [x] 44-02-PLAN.md — Wire all 36 I7 plugins + I2 composite import migration (DAG-01, DAG-02, DAG-03)
- [x] 44-03-PLAN.md — cross_timeframe.py decomposition into 3 focused modules (DAG-04)
- [x] 44-04-PLAN.md — Microstructure type fixes + make_signal() factory + validate_signal() enforcement (DAG-01, DAG-02, DAG-03, DAG-04)
- [x] 44-05-PLAN.md — Gap closure: wire divergence_stack.py to shared utilities (DAG-01, DAG-02, DAG-03)

### Phase 44.1: Feature Pipeline Renaissance Refactor
**Goal**: The intelligence observation pipeline (I1–I6) runs inside a single service (FeaturePipelineService), reducing hot-path Kafka hops from 3 to 1, eliminating 3 diverging bar history implementations, fixing stale HTF context at I6, and delivering typed BarMessage/IntelligenceEvent schemas. pipeline_latency_ms < 50ms at p99.
**Depends on**: Phase 44 (I7 utility modules in place; signal_generator already uses make_signal() factory)
**Requirements**: PIPE-01, PIPE-02, PIPE-03, PIPE-04
**Spec**: `docs/superpowers/specs/2026-03-21-renaissance-pipeline-refactor-design.md`

**Services replaced:**
- `indicagent-indicator` (indicator_service.py) → removed
- `indicagent-market-analysis` (market_analysis_service.py) → removed
- `indicagent-timeframes` (timeframes_builder_service.py) → removed
- `indicagent-feature-pipeline` (feature_pipeline_service.py) → NEW

**Shared modules added:**
- `src/core/bar_history.py` — single BarHistory implementation (replaces 3 diverging copies)
- `src/core/bar_accumulator.py` — in-pipeline HTF bar derivation (replaces DB aggregate view queries)
- `src/core/schemas/bar_message.py` — typed BarMessage + SessionType (replaces stringly-typed dicts)

**Success Criteria** (what must be TRUE):
  1. `development.intelligence` published for all 61 symbols on every bar — verify with `rpk topic consume`
  2. `development.market.bars.htf` published when HTF windows close — SignalLifecycleService unaffected
  3. `pipeline_latency_ms` metric present and < 50ms at p99 in Prometheus at `:9119`
  4. I6 `ctf_*` scores reflect in-pipeline HTF state — no DB queries during per-bar execution
  5. All existing I1–I6 plugin unit tests pass unchanged
  6. `BarHistory` module is the single implementation used by both FeaturePipelineService and SignalGeneratorService — grep confirms no other bar deque/OrderedDict in services/
  7. `indicagent-indicator`, `indicagent-market-analysis`, `indicagent-timeframes` systemd units do not exist
  8. No `float(bar["open"])` string coercions in services/ — grep confirms zero
  9. Roll events handled: `BarHistory.migrate_symbol()` called, I1 price state adjusted by roll gap
  10. I2 crossover detection correct on bar 2+ (`_prev_i1_features` injected per (symbol, tf))

**Plans**: 5 plans

Plans:
- [x] 44.1-01-PLAN.md — Test stubs + module shells (BarMessage, BarHistory, BarAccumulator, IntelligenceEvent extension) (PIPE-01, PIPE-02, PIPE-03, PIPE-04)
- [ ] 44.1-02-PLAN.md — Implement BarHistory + BarAccumulator (TDD) (PIPE-02, PIPE-03)
- [ ] 44.1-03-PLAN.md — Build FeaturePipelineService + systemd unit + service tests (PIPE-01, PIPE-03)
- [ ] 44.1-04-PLAN.md — Simplify SignalGeneratorService + live cutover (PIPE-01, PIPE-04)
- [ ] 44.1-05-PLAN.md — Post-cutover cleanup: retire old units + topic + regression (PIPE-01, PIPE-02, PIPE-03, PIPE-04)

### Phase 44.2: SignalGeneratorService Consolidation
**Goal**: The 6 pipeline stage microservices built in Phase 40 (quality_gate, regime_gate, tod_adjuster, calibrator, ranker, winner_selector) are absorbed into SignalGeneratorService as in-process pure functions. 8 Kafka execution hops become 2. Observability preserved via bounded async audit queue. SignalGeneratorService publishes `BarIntelligenceRecord` to `development.intelligence.record`.
**Depends on**: Phase 44.1 (BarHistory shared module, BarMessage typed schema, IntelligenceEvent schema extended with session_type + pipeline_latency_ms)
**Requirements**: PIPE-05, PIPE-06, PIPE-07
**Spec**: `docs/superpowers/specs/2026-03-21-renaissance-pipeline-refactor-design.md`

**Services retired:**
- `indicagent-quality-gate` (quality_gate_service.py) → removed
- `indicagent-regime-gate` (regime_gate_service.py) → removed
- `indicagent-tod-adjuster` (tod_adjuster_service.py) → removed
- `indicagent-calibrator` (calibrator_service.py) → removed
- `indicagent-ranker` (ranker_service.py) → removed
- `indicagent-winner-selector` (winner_selector_service.py) → removed

**Modules added:**
- `src/intelligence/pipeline/` directory (rename from `src/intelligence/stages/`)
- `apply_quality_gate()`, `apply_regime_gate()`, `apply_tod_adjustment()`, `apply_calibration()`, `rank_signals()`, `select_winner()` — pure functions, no Kafka, no DB

**Topics added:**
- `development.intelligence.record` — BarIntelligenceRecord, consumed by FeatureWriterService

**Success Criteria** (what must be TRUE):
  1. `src/intelligence/pipeline/` exists with 6 pure-function modules; `src/intelligence/stages/` deleted
  2. `signal_generator_service.py` calls all 6 pure functions in-process per bar — no Kafka round-trips for pipeline stages
  3. `development.intelligence.record` published with `BarIntelligenceRecord` including `ranked_signals`, `ledger_written`, `pipeline_latency_ms`, `session_type`, `days_to_expiry`
  4. Bounded audit queue: `signal_generator_audit_queue_drops_total = 0` under normal load; `signal_generator_ledger_write_failures_total = 0` under normal operation
  5. All 6 retired systemd units absent from `systemctl list-units`
  6. `development.intelligence.i7` still published (backward compat for dashboard SSE)
  7. `development.signals.aggregated` still published (for SignalLifecycleService)
  8. All existing signal_generator unit tests pass; new unit tests for each pipeline pure function
  9. Prometheus metrics: `signal_generator_pipeline_stage_input_total{stage}` and `signal_generator_pipeline_stage_output_total{stage}` visible
**Plans**: 4 plans

Plans:
- [ ] 44.2-01-PLAN.md — Pipeline pure functions: extract logic from stage services into `src/intelligence/pipeline/` modules + unit tests (PIPE-05)
- [ ] 44.2-02-PLAN.md — Wire pipeline functions into SignalGeneratorService + audit queue + BarIntelligenceRecord publish (PIPE-06)
- [ ] 44.2-03-PLAN.md — Retire 6 stage services + systemd units + live cutover (PIPE-06)
- [ ] 44.2-04-PLAN.md — Integration test: E2E bar → BarIntelligenceRecord validation + metrics check (PIPE-07)

### Phase 44.3: Atomic Persistence + OHLCV Unification
**Goal**: FeatureWriterService consumes `development.intelligence.record` only and performs a single atomic INSERT per bar — no UPSERTs, no partial rows, no race conditions. i8 persistence migrated from FeatureWriterService to LLMWriterService. FeaturePipelineService becomes the sole live writer to `market_data_ohlcv`, creating a single OHLCV ground truth. All `intelligence_features` rows complete at insert time.
**Depends on**: Phase 44.2 (BarIntelligenceRecord flowing on `development.intelligence.record`)
**Requirements**: PIPE-08, PIPE-09, PIPE-10
**Spec**: `docs/superpowers/specs/2026-03-21-renaissance-pipeline-refactor-design.md`

**DB migration (in scope):**
- `production/migrations/NNN_intelligence_features_record_columns.sql`
- Adds: `winner_plugin`, `winner_confidence`, `winner_direction`, `signals_evaluated`, `signals_after_quality`, `signals_after_regime`, `signals_after_tod`, `signals_after_calibration`, `ledger_written`, `i7_computed_at`

**Success Criteria** (what must be TRUE):
  1. `intelligence_features` rows arrive with `i7` not null at insert time — query confirms zero rows with `i7 IS NULL AND computed_at > now() - interval '1 hour'`
  2. `ledger_written` column populated on all new rows — `TRUE` for winners, `FALSE` on ledger write failure
  3. `market_data_ohlcv` receiving live 1m bars from FeaturePipelineService — `SELECT count(*) FROM market_data_ohlcv WHERE timestamp > now() - interval '5 minutes'` returns > 0 during market hours
  4. FeatureWriterService consumes only `development.intelligence.record` — no subscriptions to `development.intelligence` or `development.intelligence.i7`
  5. LLMWriterService UPSERTs `intelligence_features.i8` — confirmed by checking a recent `llm_calls` row maps to a populated `intelligence_features.i8` JSONB column
  6. All `_process_i7_message()`, `_process_i8_message()`, `_flush_i7_i8()` code removed from FeatureWriterService — grep confirms absence
  7. DB migration applied and verified: `SELECT column_name FROM information_schema.columns WHERE table_name = 'intelligence_features'` includes all 10 new columns
  8. All FeatureWriterService unit tests pass against simplified single-buffer logic
**Plans**: 3 plans

Plans:
- [ ] 44.3-01-PLAN.md — DB migration + FeatureWriterService simplification: single-buffer atomic INSERT (PIPE-08, PIPE-09)
- [ ] 44.3-02-PLAN.md — LLMWriterService i8 UPSERT wiring: subscribe intelligence.i8, buffer, UPDATE intelligence_features (PIPE-09)
- [ ] 44.3-03-PLAN.md — FeaturePipelineService live OHLCV writes + post-cutover regression (PIPE-08, PIPE-10)

### Phase 45: I6 → I7 Confluence Wiring + Exhaustion Standardization
**Goal**: All 28 I7 plugins incorporate I6 confluence scores AND exhaustion scoring into confidence calculations, weighted by setup family. Both ship in a single shadow mode window — old and new confidence logged side-by-side with no live score change until Phase 46 graduation. Exhaustion is computed signal being discarded by 32/36 I7 plugins today — Renaissance violation.
**Depends on**: Phase 44 (confidence_utils in place, BaseI7Plugin provides consistent confidence contract, make_signal() factory wired)
**Requirements**: CONF-01, CONF-02, CONF-03

**Exhaustion wiring by setup family (applicability map built during planning):**
- `apply_exhaustion_guard` (-0.15 penalty) → trend-following, momentum, breakout families (penalize chasing tired moves)
- `apply_exhaustion_boost` (+0.10 reward) → sweep/reclaim, reversal, mean-reversion families (reward sweep completion)
- Microstructure (OFI/CVD/delta) → evaluate per-plugin: exhaustion as gate (suppress) vs boost vs neither
- Session/ORB/gap setups → evaluate per-plugin during planning

**Success Criteria** (what must be TRUE):
  1. Every I7 plugin reads `ctf_score` (and ≥1 relevant sub-score) from `frames["features"]` — grep confirms no plugin body ignores all `ctf_*` fields
  2. Every applicable I7 plugin calls `apply_exhaustion_guard` or `apply_exhaustion_boost` from `exhaustion_utils.py` — grep confirms zero plugins re-implement exhaustion logic inline; plugins with neither document why in a comment
  3. Shadow logging in each plugin emits `{"old_confidence": X, "new_confidence": Y, "ctf_contribution": Z, "exhaustion_contribution": W}` per fired signal — visible in `intelligence_features.i7` JSONB
  4. Live `calibrated_confidence` in `signal_ledger` is unchanged (shadow mode confirmed by querying a 24h window and verifying zero change in score distribution)
  5. Each plugin family uses the correct I6 sub-score weight: trend-following → `ctf_trend_alignment`; mean-reversion → `ctf_regime_agreement`; SMC → `ctf_fvg_alignment` + `ctf_ob_alignment`; microstructure (OFI/CVD) → `ctf_score` as gate
- [ ] 45-01-PLAN.md — exhaustion_utils wiring applicability map + guard/boost wiring for trend/momentum/breakout families (CONF-01)
- [ ] 45-02-PLAN.md — ctf_* wiring for trend/mean-reversion plugin families + exhaustion for reversal/sweep families (CONF-02)
- [ ] 45-03-PLAN.md — ctf_* + exhaustion wiring for SMC + microstructure families + unified shadow logging (CONF-03)

### Phase 41: Intelligence Gap Fill
**Goal**: Intelligence fields that were stubs are now populated with real computed values — FVG and OB cross-TF alignment drive I6 scores, Volume Profile levels anchor T1/T2 targets, roll premium/discount is stored per bar, higher-TF S/R context reaches I7 plugins, VWAP/session guards prevent intraday-only plugins firing on wrong TFs.
**Depends on**: Phase 45 (confluence wiring complete; I6 data quality now matters for I7 confidence)
**Requirements**: INTEL-01, INTEL-02, INTEL-03, INTEL-04, INTEL-05
**Success Criteria** (what must be TRUE):
  1. `i6_fvg_tf_alignment` is non-zero in live `intelligence_features` rows for symbols where FVGs exist on multiple timeframes — the hardcoded `0.0` stub is absent from `cross_timeframe.py`.
  2. `i6_ob_tf_alignment` is non-zero in live `intelligence_features` rows for symbols where Order Blocks align across TFs — the hardcoded `0.0` stub is absent.
  3. When price is near a value area boundary, `trade_framer.py` sets `target_1` to POC and `target_2` to VAH or VAL — verifiable in `signal_ledger` rows where `distance_to_vah_atr < 0.5` or `distance_to_val_atr < 0.5`.
  4. For futures symbols within 5 days of roll, `intelligence_features` rows contain a non-NULL `roll_premium_pct` field equal to `(front_price - back_price) / back_price` — verifiable by querying near a known roll date.
  5. I7 plugins receive 1h POC/VAH/VAL and I6 CTF data via `trade_framer` context — stop and target fields in `signal_ledger` reflect higher-TF levels when they are closer than the bar-level levels.
**Plans**: 3 plans

Plans:
- [ ] 41-01-PLAN.md — FVG + OB cross-TF alignment scoring in cross_timeframe.py (INTEL-01, INTEL-02)
- [ ] 41-02-PLAN.md — Volume Profile POC/VAH/VAL as T1/T2 targets in trade_framer.py (INTEL-03)
- [ ] 41-03-PLAN.md — HTF context injection + VWAP/session TF guards + aggregator/write-back comments (INTEL-05)

### Phase 42: Candlestick Pattern Expansion
**Goal**: The I5 candlestick pattern library grows from 19 to 29 patterns, and CandlestickPatternSetup applies database-driven confidence weights that self-calibrate from live outcomes.
**Depends on**: Phase 41 (trade_framer context stable before adding new signal sources)
**Requirements**: CANDLE-01, CANDLE-02
**Success Criteria** (what must be TRUE):
  1. `I5Patterns` schema contains 10 new candlestick pattern fields — `grep -E "harami_bull|abandoned_baby|tweezer_top|belt_hold|kicker" src/intelligence/schemas.py` shows all 10 patterns declared; `extra=forbid` validation passes.
  2. Each of the 10 new patterns fires at least once in a one-week historical replay on ES 1m — verifiable via `SELECT SPLIT_PART(signal_type, '_', 2) AS pattern_name, COUNT(*) FROM signal_ledger WHERE setup_plugin = 'trad_CandlestickPatternSetup' AND computed_at > NOW() - INTERVAL '7 days' GROUP BY pattern_name` showing new pattern labels.
  3. `pattern_reliability` table exists with PRIMARY KEY (pattern_name, timeframe) and 10 bootstrap priors seeded (Tier 1: 0.70 for abandoned_baby/kicker; Tier 2: 0.55-0.60 for harami/tweezer/belt_hold).
  4. All new patterns have unit tests — `.venv/bin/pytest tests/unit/test_candlestick_patterns.py -xvs` passes with valid pattern detection and malformed fixture rejection.
  5. `weight_updater.py` extends to calibrate pattern_reliability from signal_ledger outcomes — patterns with sample_size >= 30 and p < 0.05 promoted to data-driven weights (is_bootstrap=false).
**Plans**: 4 plans

Plans:
- [x] 42-01-PLAN.md — 10 new I5 candlestick patterns + schema extension + unit tests (CANDLE-01) [wave 1]
- [x] 42-02-PLAN.md — pattern_reliability table + bootstrap priors migration (CANDLE-02) [wave 1]
- [x] 42-03-PLAN.md — CandlestickPatternSetup I7 extended with DB-driven weights (CANDLE-02) [wave 2]
- [x] 42-04-PLAN.md — weight_updater pattern calibration + 7-day backtest validation (CANDLE-01, CANDLE-02) [wave 2]

### Phase 46: I6 Confluence Expansion
**Goal**: The I6 confluence score reflects cross-asset dynamics and VIX regime — market_analysis_service injects cross-asset features into frames before I6 execution, and CrossTimeframeConfluencePlugin scores VIX suppression and equity sector rotation alongside existing TF alignment.
**Depends on**: Phase 41 (i6_fvg_tf_alignment and i6_ob_tf_alignment live), Phase 42 (candlestick patterns stable)
**Requirements**: CONF-01, CONF-02, CONF-03, CONF-04
**Success Criteria** (what must be TRUE):
  1. `market_analysis_service` consumes from `development.cross_asset` topic and injects cross-asset features into the frame dict before I6 plugin execution — verifiable by confirming `frames.get('cross_asset')` is non-None in a live `CrossTimeframeConfluencePlugin.compute()` call log.
  2. When VIX spread z-score is high (simulated injection), mean-reversion setups show reduced `ctf_score` and volatility/breakout setups show increased `ctf_score` — the VIX suppression multiplier is logged per bar.
  3. When ES/NQ/RTY/YM spread z-scores are all aligned (same direction), `ctf_score` gets a sector rotation boost — the contributing fields are logged in `intelligence_features.i6` JSONB.
  4. `i6_fvg_tf_alignment` and `i6_ob_tf_alignment` have non-zero weights in the `CrossTimeframeConfluencePlugin` scoring formula — querying `intelligence_features.i6` for ES 1m bars shows non-zero `ctf_score` contributions from these fields.
**Plans**: 4 plans

Plans:
- [ ] 039-01-PLAN.md — SignalStatus enum replacing raw string literals (DATA-06)
- [ ] 039-02-PLAN.md — CIS null repair exit-1 gate + alpha validation re-run (DATA-01, DATA-02)
- [ ] 039-03-PLAN.md — OHLCV rebuild script + signal_ledger composite index (DATA-03, DATA-04)
- [ ] 039-04-PLAN.md — Gap-fill service with RTH detection + systemd timer (DATA-05)

### Phase 47: Shadow Mode Graduation
**Goal**: Shadow-mode features graduate to live after empirical validation — hmm_regime thresholds adjusted if data supports it, cross-asset and roll monitor enabled, trad_DualDivergence promoted once it passes the statistical gate.
**Depends on**: Phase 46 (I6 expansion complete; all shadow features accumulating data throughout v2.0 phases)
**Requirements**: SHADOW-01, SHADOW-02, SHADOW-03, SHADOW-04
**Success Criteria** (what must be TRUE):
  1. A query of `signal_ledger WHERE is_shadow = TRUE` for regime_suppressed signals produces enough rows (N >= 200) to compute empirical win rates by threshold bucket — the analysis result (confirm or adjust thresholds) is documented in a decision log entry.
  2. `CROSS_ASSET_ENABLED=true` is set in the production environment; `indicagent-cross-asset` publishes live data and `signal_generator_service` injects cross-asset frames for EQ_INDEX symbols — verifiable by querying `signal_ledger` for `trad_CrossAssetDivergence` signals after enablement.
  3. `ROLL_MONITOR_ENABLED=true` is set; with a real or simulated roll event, `contract_metadata.is_front_month` toggles and pipeline services receive the roll event without restarting — verifiable in `system_events` table.
  4. `trad_DualDivergence` `IS_SHADOW` flag is removed; the plugin fires live signals that appear in `signal_ledger` with `is_shadow = FALSE` — N >= 50 resolved signals with win rate > 50% is confirmed before flag removal.
**Plans**: 4 plans

Plans:
- [ ] 039-01-PLAN.md — SignalStatus enum replacing raw string literals (DATA-06)
- [ ] 039-02-PLAN.md — CIS null repair exit-1 gate + alpha validation re-run (DATA-01, DATA-02)
- [ ] 039-03-PLAN.md — OHLCV rebuild script + signal_ledger composite index (DATA-03, DATA-04)
- [ ] 039-04-PLAN.md — Gap-fill service with RTH detection + systemd timer (DATA-05)

### Phase 48: Auth + External Access
**Goal**: The API is protected by JWT authentication, the dashboard runs as a production build served over Cloudflare Tunnel, SSE works correctly through the auth layer, and keyset pagination enables efficient large features export.
**Depends on**: Phase 47 (pipeline stable and shadow modes resolved before exposing external access)
**Requirements**: AUTH-01, AUTH-02, AUTH-03, AUTH-04, AUTH-05, AUTH-06
**Success Criteria** (what must be TRUE):
  1. Every API endpoint (including SSE) returns HTTP 401 when called without a valid JWT cookie — `curl https://api.indicagent.com/api/signals/recent` without credentials returns `{"detail": "Not authenticated"}`.
  2. The dashboard SSE connection works at `dash.indicagent.com` with `EventSource` using `withCredentials: true` — live signal updates appear in the browser with no auth errors in the console.
  3. CORS configuration explicitly lists `dash.indicagent.com` and `192.168.1.158` as allowed origins — `OPTIONS /api/signals/recent` with `Origin: https://dash.indicagent.com` returns `Access-Control-Allow-Credentials: true`.
  4. Login, logout, token refresh, and authentication failure events are logged as structured records — `grep "auth_event" logs/api.log` shows timestamped entries for each event type.
  5. The Next.js dashboard runs as a standalone production build managed by a systemd unit — `systemctl status indicagent-dashboard` shows `active (running)` and the build serves from the compiled output directory.
  6. Auth endpoints (login, refresh) enforce rate limiting — more than 10 failed login attempts within 60 seconds returns HTTP 429 for subsequent attempts.
**Plans**: 4 plans

Plans:
- [ ] 039-01-PLAN.md — SignalStatus enum replacing raw string literals (DATA-06)
- [ ] 039-02-PLAN.md — CIS null repair exit-1 gate + alpha validation re-run (DATA-01, DATA-02)
- [ ] 039-03-PLAN.md — OHLCV rebuild script + signal_ledger composite index (DATA-03, DATA-04)
- [ ] 039-04-PLAN.md — Gap-fill service with RTH detection + systemd timer (DATA-05)

### Phase 49: ML Scoring Model
**Goal**: A LightGBM model scores every new signal in shadow mode, trained on signal_features with stationarity gates and regime segmentation, with walk-forward retraining and SHAP attribution. LLM call audit trail completes the training data feed (token counts, retry chain, outcome back-fill).
**Depends on**: Phase 48 (auth + external access in place before exposing ML endpoints)
**Requirements**: ML-01, ML-02, ML-03, ML-04, ML-05, ML-06, ML-07
**Success Criteria** (what must be TRUE):
  1. `feature_builder.py` produces a feature matrix using only columns from `signal_features` that existed at signal fire time — no `signal_ledger` outcome columns (outcome, pnl_r, mae, mfe) appear in the training feature set.
  2. Non-stationary features (ATR, price levels) are differenced before training — ADF test on the differenced series returns p < 0.05; bounded oscillators (RSI, CIS score) are used as-is with a logged justification.
  3. `ml_score` field is populated in `signal_ledger` for every new signal in shadow mode — `SELECT COUNT(*) FROM signal_ledger WHERE ml_score IS NULL AND computed_at > now() - interval '1 hour'` returns 0.
  4. SHAP attribution values are stored per signal in `signal_features` — querying `signal_features WHERE feature_name LIKE 'shap_%'` returns rows for every signal that has an `ml_score`.
  5. Walk-forward retraining runs on schedule (every 7 days via systemd timer) with 60-day expanding window and 14-day hold-out — the timer completion and AUC/Brier metrics are logged to `logs/ml_trainer.log`.
  6. After 8-week shadow gate passes (AUC >= 0.56, Brier < 0.25, Pearson r > 0.20 p < 0.05, win rate lift > +3% at ml_score > 0.6), ML blend is enabled in the aggregator with α=0.20 — `_build_all_ranked()` uses `calibrated_confidence * (1 - α) + ml_score * α` as the sort key.
  7. Global LightGBM model and 3 regime-specific models (ranging/trending/volatile) are trained independently — the regime-specific model is used when `N >= 500` for that regime; otherwise falls back to global model with a logged reason.
**Plans**: 4 plans

Plans:
- [ ] 039-01-PLAN.md — SignalStatus enum replacing raw string literals (DATA-06)
- [ ] 039-02-PLAN.md — CIS null repair exit-1 gate + alpha validation re-run (DATA-01, DATA-02)
- [ ] 039-03-PLAN.md — OHLCV rebuild script + signal_ledger composite index (DATA-03, DATA-04)
- [ ] 039-04-PLAN.md — Gap-fill service with RTH detection + systemd timer (DATA-05)

### Phase 50: Renaissance Observability (Attribution, A/B Testing, Causal Inference)
**Goal**: The DAG pipeline has Renaissance-grade observability — performance attribution tracks value added by each stage, live A/B experimentation tests configuration changes, causal inference proves improvements are not just correlation, counterfactual analysis quantifies missed opportunities, LLM analyzes attribution to recommend optimizations. Intelligence tier audit surface makes every feature vector inspectable (I3/I4/I5/I6 fields visible in dashboard). Staleness is a first-class quality signal: stale intelligence reduces confidence in signal_ledger so ML training can exclude unreliable rows; dashboard badge is a side effect of the data-quality fix, not the primary deliverable.
**Depends on**: Phase 40 (DAG foundation with basic attribution in place), Phase 49 (ML model provides additional signal features for causal analysis)
**Requirements**: None (observability infrastructure)
**Success Criteria** (what must be TRUE):
  1. Every signal has full attribution chain in `performance_attribution` table — can query value added by each stage
  2. Can answer: "Which stages add most value?" — aggregation query returns ranked stages by avg_value_added
  3. Can answer: "Which stages suppress winners?" — counterfactual analysis quantifies opportunity cost
  4. A/B tests run automatically — minimum 1000 samples or 14 days, statistical significance (p < 0.05)
  5. Every stage change proven causal — randomized trials with control/treatment branches
  6. LLM generates nightly recommendations — analyzes attribution + counterfactuals, creates experiments
  7. Full DAG observability in dashboard — real-time latency, error rates, attribution metrics, circuit breaker status
  8. Every intelligence tier field (I3/I4/I5/I6) is inspectable in the drill panel — when a signal fires, the contributing feature values from all tiers are visible and auditable.
  9. `signal_ledger.data_age_ms` is populated at signal fire time; signals with `data_age_ms > 900000` (15 min) are flagged in dashboard with a staleness badge and excluded from ML training sets by default.
**Plans**: TBD (6-7 plans)

Plans:
- [ ] 47-01-PLAN.md — Performance Attribution Service: subscribe to attribution stream, aggregate, write to DB (Phase 1)
- [ ] 47-02-PLAN.md — Counterfactual Analysis: track suppressed signals, simulate outcomes, quantify opportunity cost (Phase 2)
- [ ] 47-03-PLAN.md — A/B Test Framework: deploy multiple variants, statistical winner selection (Phase 3)
- [ ] 47-04-PLAN.md — Causal Inference Engine: randomized trials, causal effect estimation (Phase 4)
- [ ] 47-05-PLAN.md — LLM Gate Optimizer: analyze attribution + counterfactuals, recommend changes (Phase 3)
- [ ] 47-06-PLAN.md — Dashboard & Monitoring: DAG visualization, stage health metrics, attribution reports (Phase 5)

**Out of scope (future phases):**
- Stage splitting (if attribution shows stages do too much)
- Full trade simulation for counterfactuals (currently MFE/MAE only)
- ML-based stage optimization (use ML to predict optimal configs)
- Cross-asset DAG extension (Phase 46 addresses cross-asset features)

## Backlog

Items decided but not yet scheduled. Pull into a milestone when ready.
Re-prioritized 2026-03-19 after v2.0 roadmap defined.

### Tier 1 — v2.1 candidates

| Item | Notes | Analysis |
|------|-------|---------|
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
Phases execute in numeric order. v1.0–v1.9 complete (Phases 0-38 shipped). v2.0 in progress (Phases 39-46).

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
| 44. I7 DAG Refactor | v2.0 | 5/5 | Complete    | 2026-03-21 |
| 45. I6 → I7 Confluence Wiring | v2.0 | 0/2 | Not started | — |
| 46. I6 Confluence Expansion | v2.0 | 0/TBD | Not started | — |
| 47. Shadow Mode Graduation | v2.0 | 0/TBD | Not started | — |
| 48. Auth + External Access | v2.0 | 0/TBD | Not started | — |
| 49. ML Scoring Model | v2.0 | 0/TBD | Not started | — |
| 50. Renaissance Observability | v2.0 | 0/TBD | Not started | — |
