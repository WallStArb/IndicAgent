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
- 🔄 **v1.9 I7 Alpha Engine** — Phases 31-38 (in progress)

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

- [x] **Phase 28: Dashboard Completion** — Signal Scorecard panel, drill panel history from DB, GARCH/Kalman I4 fields, SMC detail fields, tier tooltips (7/7 plans) — completed 2026-03-12
- [x] **Phase 29: Renaissance Signal Quality** — constituent_contributions, alpha decay, signal freshness decay, volume/killzone CIS gates, Hurst/entropy I4 plugins, KS + CUSUM drift detection (8/8 plans) — completed 2026-03-13

Full details: `.planning/milestones/v1.8-ROADMAP.md`

</details>

<details>
<summary>✅ Phase 30: Redpanda Migration — SHIPPED 2026-03-14</summary>

- [x] **Phase 30: Redpanda Migration** — Replace DragonflyDB with Redpanda across all 8 services; pure transport-layer migration (5/5 plans) — completed 2026-03-14

</details>

---

### v1.9 I7 Alpha Engine — In Progress

- [x] **Phase 31: CIS Learning Loop + Signal Feature Snapshots** - Self-improving CIS with DB weight loading, binary win labels, asset-cluster segmentation, and mid-bar feature snapshots for ML training (completed 2026-03-17)
- [x] **Phase 32: Stop Architecture + Extended Divergence Stack** - Structure-first stop placement centralized in trade_framer.py (all 17 plugins inherit), Chandelier trailing stop, staleness score, and 5-input divergence convergence scoring (completed 2026-03-17)
- [x] **Phase 33: Five New I7 Signal Plugins** - FailedBreakout, ORB, PrevDayLevel, SecondLeg, VCP — covering reversal, session, level-test, and contraction setups (completed 2026-03-17)
- [x] **Phase 34: I4 Infrastructure — Anchored VWAP + Volume Profile** - Two new I4 computation plugins plus two I7 setups consuming them (completed 2026-03-17)
- [x] **Phase 35: Calibration + TOD Multiplier + CIS Kalman Filter** - Isotonic regression confidence calibration, time-of-day win rate multiplier, and Kalman-smoothed CIS score (completed 2026-03-18)
- [ ] **Phase 36: Microstructure Plugins** - OFI and CVD as I1 features plus two new I7 plugins consuming order-flow signals
- [ ] **Phase 37: Cross-Asset Intelligence Service** - New cross_asset_service microservice, equity spread features, and CrossAssetDivergence I7 plugin
- [x] **Phase 38: Automated Futures Roll Detection** - Volume-based roll detection in TWS daemon, DB-backed active contracts, plugin state migration, roll boundary markers (completed 2026-03-18)

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
**Plans**: 1 plan

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
- [ ] 031-01-PLAN.md — Migration 034 + CISScorer.update_weights() + 30-min refresh loop
- [ ] 031-02-PLAN.md — Binary win labels + asset-cluster segmented training
- [ ] 031-03-PLAN.md — signal_features atomic write + is_shadow LedgerEntry + CLI promotion gate

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
- [ ] 33-01-PLAN.md — FailedBreakout + ORB15 + ORB30 plugins with TDD tests
- [ ] 33-02-PLAN.md — PrevDayLevelTest + SecondLegContinuation + VCP plugins with TDD tests
- [ ] 33-03-PLAN.md — Register all 6 plugins in TIER_I7 + TREND_SETUPS wiring

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
- [ ] 34-01-PLAN.md — Migrate AnchoredVWAP to I4/context/ with std bands, sigma, velocity (VWAP-01)
- [ ] 34-02-PLAN.md — Migrate VolumeProfile to I4/context/ with session-reset + rolling dual-track POC/VAH/VAL (VOL-01)
- [ ] 34-03-PLAN.md — Five I7 plugins (VWAPReversion, VWAPReclaim, POCRejection, HVNRejection, LVNBreakout) + registration (VWAP-02, VOL-02)

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
- [ ] 35-01-PLAN.md — DB migration 038 + LedgerEntry extension + confidence_calibrator module
- [ ] 35-02-PLAN.md — TOD multiplier (pre-CIS Bayesian-smoothed) + calibrated_confidence sort key in aggregator
- [ ] 35-03-PLAN.md — CIS Kalman filter + shadow fire condition + dashboard confidence fields

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
- [ ] 036-01-PLAN.md — I1 OFI + CVD plugins, tick buffer wiring in indicator_service
- [ ] 036-02-PLAN.md — 7 I7 microstructure trading plugins + TIER_I7 registration

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
- [ ] 037-01-PLAN.md — Core service + spread feature computation + stream key + Settings + systemd unit
- [ ] 037-02-PLAN.md — CrossAssetDivergence I7 plugin (stateless, regime-biased direction)
- [ ] 037-03-PLAN.md — Pipeline wiring: TIER_I7 registration + signal_generator frame injection + feature_writer persistence

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
- [ ] 38-01-PLAN.md — DB foundation: migration 037, roll chain utility, DB-backed get_active_contracts(), stream key (ROLL-01, ROLL-02, ROLL-03)
- [ ] 38-02-PLAN.md — Roll detection engine: tws_daemon volume tracking, z-score detection, confirmation window, cooldown, roll event publishing (ROLL-04)
- [ ] 38-03-PLAN.md — Pipeline integration: downstream service consumption, plugin state migration, roll boundary markers, backfill seeding (ROLL-05, ROLL-06)

## Backlog

Items decided but not yet scheduled. Pull into a milestone when ready.
Re-prioritized 2026-03-15 after v1.8 shipped.

### Tier 1 — Ready now / v1.9 candidates (data exists, no blockers)

| Item | Notes | Analysis |
|------|-------|---------|
| Expand I5 candlestick + I7 setup | 18 patterns spec'd (Tier 1: Harami, Dark Cloud, Three Soldiers/Crows, Morning/Evening Star). Research doc complete. | `docs/ideas/candlestick-pattern-expansion-research.md` |
| VWAP/Session plugin TF guards | Research: VWAP and session plugins may fire on TFs where they're not meaningful (e.g. 1d). Add guards. | `.planning/todos/pending/2026-03-10-research-vwap-and-session-plugin-timeframe-guards.md` |
| LLM Call Tracking | Real token counts (Ollama eval counts), error details, cis_score/zone fields, retry chain visibility. | `.planning/todos/pending/2026-03-07-improve-llm-call-tracking.md` |
| CIS Null Repair Execution | Phase 25 repair script complete + tested (11 tests). Blocked by PostgreSQL shared memory error on 1.8M row JOIN. Investigate Docker cgroup limits, batch by symbol/TF, then run repair. Code: `production/scripts/repair_cis_nulls.py`. | memory: `Phase 25 Complete` |
| validate_alpha.py re-runs | Re-run `validate_alpha.py --promote` for bootstrap-promoted plugins (DerivOsc, AC Osc) once 30+ bars accumulate. | — |
| Auth and External Access | JWT + API key via single Depends(verify_auth); Cloudflare Tunnel; authenticated SSE. SSE fan-out: one Redpanda consumer → broadcast to N clients (not N independent pollers). `next build` + nginx for prod dashboard. | — |

### Tier 2 — v1.9+ (moderate dependencies)

| Item | Notes | Analysis |
|------|-------|---------|
| I6 Confluence Expansion | Cross-TF + cross-asset confluence (ES/NQ/RTY alignment, VIX regime, sector rotation). Design complete. Needs new IBKR subs. | `docs/ideas/i6-confluence-expansion.md` |
| Intelligence Stack Latency | Parallel plugin workers within tiers (2-7× speedup potential). Thread-safety audit required. | `docs/ideas/intelligence-stack-latency-reduction.md` |
| ML Scoring Model | XGBoost/LightGBM on intelligence_features + signal_ledger outcomes. Needs ~90 days signal history — not yet accumulated. | — |
| Gap-fill service | Detect + backfill gaps in market_data_ohlcv from TWS downtime. Query gaps in 1m series, fetch only missing windows from IBKR, replay. | `.planning/todos/pending/2026-03-04-add-gap-fill-service.md` |
| Roll premium/discount feature | Front/back month spread at roll = contango/backwardation signal. Needs back-month IBKR fetch. | `.planning/todos/pending/2026-03-04-add-roll-premium-discount-feature.md` |
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

## Progress

**Execution Order:**
Phases execute in numeric order. v1.0–v1.8 complete (Phases 0-29 shipped). Phase 30 (Redpanda Migration): complete 2026-03-14. v1.9 (Phases 31-38): in progress.

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
| 34. I4 Infrastructure — Anchored VWAP + Volume Profile | 3/3 | Complete    | 2026-03-17 | - |
| 35. Calibration + TOD Multiplier + CIS Kalman Filter | 3/3 | Complete    | 2026-03-18 | - |
| 36. Microstructure Plugins | v1.9 | 0/2 | Not started | - |
| 37. Cross-Asset Intelligence Service | v1.9 | 0/3 | Not started | - |
| 38. Automated Futures Roll Detection | v1.9 | 0/3 | Not started | - |
