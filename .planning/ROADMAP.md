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
- 🔄 **v3.1 IC Empirical Proof + Counterfactual Scoring** — Phase 140.5 COMPLETE 2026-06-26; corpus pipeline COMPLETE 2026-06-28 (12.47M alpha_events); Phase 141 COMPLETE 2026-06-29; Phase A COMPLETE 2026-06-30 (ic_engine methodology fixes + Renaissance IC gate redesign); Phase B (corpus re-run on corrected engine) COMPLETE 2026-07-01 (3rd rebuild: feature_vectors 10.08M, feature_ic_scores 254,126, qualifying features 5m=37/15m=28/1h=15/1d=28); Phase 141.1 COMPLETE 2026-07-02 (measurement/decision integrity foundation — OOS enforcement, weight-epoch fix, regime_scope schema fix, cost-hurdle calibration); Phase 142A COMPLETE 2026-07-02 (ensemble IC proof: `alpha_ensemble_ic` schema + EnsembleICEngine + hold_max_bars calibration + EIC-04 gate + EIC-05 diagnosis); Phase 142B.1 COMPLETE 2026-07-04 (E1/E2 ensemble weighting variants; E2 rejected 2026-07-09 A/B judgment, E1 remains champion); Phase 142.5 COMPLETE 2026-07-07 (89 Renaissance primitives, 150-field FeatureVector); Phase 142B COMPLETE 2026-07-10 (`alpha_frames` schema + AlphaFrameWriter + CounterfactualTracker + SHADOW-REVIEW.md pre-commitment; single primary frame counterfactual validation; no cost model, no UX); Phase 143 COMPLETE 2026-07-10 (Feature Lifecycle Routing, merged with 149B — evidence-based feature_registry promotion/demotion + ic_engine post-run lifecycle hook + integrity_monitor) — see `docs/plans/2026-06-30-alphaengine-v1-execution-plan.md`
- 📋 **v3.15 Conditioning & Identity Foundation** — **Phases 144, 145, 146** (moved into this milestone 2026-07-03 — see `docs/research/fable-2026-07-03-roadmap-reconciliation.md` F1; previously miscategorized under "v3.3 Foundational Hardening," physically *after* Phases 149-151 despite being their hard prerequisite). Unifies the two live regime systems — per-symbol HMM `regime_writer.py` and cross-sectional `equity_regime_model.py`/Phase 144 — behind one `StratificationDimension` contract, governed via Concept Registry's `regime_model`/`hmm_variant` domains; idea doc: `docs/research/stratification-dimension-unification.md`; originally proposed 2026-07-02 in `docs/research/fable-2026-07-02-v3-topdown-architecture.md` §3, §7, D5/D8. **Hard prerequisite for Phase 149** (intel-13: PrecedentEngine's retrieval hard-filters on regime labels; building the embedding substrate on known-suspect strata bakes the bias into stored vectors — see Phase 149's Depends-on below). Explicitly does not block or change Phase 142B.1, which only consumes existing regime labels as an opaque stratification key. Batches together in one `ic_engine` re-run per topdown D5: Phase 144 + todo 026 P2b/P2c/P3 + todo 041 (tag taxonomy) + intel-12's first substitution test. Build trigger: todo 026's Step 1 regime-IC separation gate — **already run 2026-07-02, result asset-class-dependent** (SPY separates cleanly, TLT doesn't) — the pre-committed fallback for weak-separation asset classes (topdown Open Q4) needs an operator call at this milestone's planning, before the substitution test runs.
- 📋 **v3.2 Signal Diversification — PrecedentEngine + Feature Expansion** — Phases 149-151 (planned; hard-gated on v3.1 OOS IC > 0 at 95% CI AND v3.15 complete for Phase 149; Renaissance: more diverse weak signals, not stronger strong ones. **Framing correction complete** (was pending, closed 2026-07-09) — the milestone goal text and Phase 150 no longer describe this as an "independent System 2"; both were rewritten against `docs/research/intel-precedent-engine.md` per todo 055, and the concept itself was renamed from "AnalogEngine" to "PrecedentEngine" the same day — "analog" collided with this codebase's dense signal-processing vocabulary, see `docs/foundation/naming-system.md`'s plain-role-noun table)
- 📋 **v4.0 Execution Layer** — **Phases 156-159** (numbered 2026-07-12 from a production-readiness review, was "Phases TBD"; **restructured same day** to split out Portfolio State as its own foundational phase after catching a gap — this milestone's own design is portfolio-level, not per-security, and had no persisted entity for portfolio state to live in: 156 Portfolio State Foundation, 157 Position Sizing & Risk Management, 158 Live Execution Layer + broker resilience, 159 Cost Calibration Feedback Loop + Execution Scoring) (planned; hard-gated on v3.2 complete (Phase 155 is independently-gated, not blocking — ETF Universe Expansion removed as a phase 2026-07-04, already done — see below) + `alpha_events` schema frozen; consumes alpha_events, never modifies signal weights)
- 📋 **v4.1 IC Governance + Drift Monitoring** — Phases 152, 153 (**149B corrected 2026-07-03 — no longer a standalone phase; merged into Phase 143**, see Phase 143's header). Regime-conditioned distribution drift + ensemble health gates; replaces DataIntegrityMonitor + SystemHealthMonitor + PredictiveDecayDetector; see `docs/research/measurement-governance-monitor.md` (current design, supersedes `docs/plans/archive/2026-06-27-health-guardian-design.md`). Per topdown D12, **Phases 152 and 153 are schedulable opportunistically any time after Phase 141** — the "v4.1" label is thematic grouping, not a sequencing gate. Phase 152 depends only on `feature_vectors` (exists today); Phase 153 depends on Phase 142A's `alpha_ensemble_ic` (exists, populated — though see the EIC-04 verdict log in Phase 142A's section before treating 142A as fully proven). Do not let either jump ahead of Phase 142B/143 or 148, which carry present-tense value the backlog matrix rates higher.

## Planned Phases — Priority Order

**Value ranking lives in one place, not two:**
`docs/research/intelligence-lifecycle-backlog-matrix.md` scores every planned phase
on Effort/Risk/Reward (plus a "Foundational" flag that jumps the queue regardless of raw
reward) — that table, not this list, is the source of truth for *which phase matters more*.
This section only adds the other axis: *which phases are actually eligible to start right now*,
by cross-referencing that matrix against live blocker status. Phase numbers stay stable IDs
either way — re-sort this list freely; never renumber a phase to reflect priority.

**Don't conflate readiness with value** (a mistake caught and reverted while drafting this
section, 2026-07-13): being unblocked makes a phase eligible, not important. Concept Registry
(160) has zero dependencies but the matrix rates it "Reward: Low now, Med long-run" — it doesn't
outrank Phase 144 just because it can start today. PrecedentEngine (149/150) stays the matrix's
own LOW tier / XL effort / High risk / Speculative reward even after its OOS gates pass — "gates
passed" removes a blocker, it doesn't promote the idea to HIGH value.

**Right now (2026-07-13), combining both axes:**

1. **Phase 143.1** — *in progress* (143.1-07 re-run, ETA ~2026-07-14). Not in the matrix (it's a
   measurement-integrity fix, not a discretionary idea) but everything below either inherits its
   corrected evidence or is blocked on it directly.

2. **Phase 144 (`regime_group`)** — matrix's only HIGH-tier phase, marked **Foundational**
   (Cross-Group Lead-Lag IC and PrecedentEngine both need the peer groups it produces). Code
   complete (6/6 plans); blocked only on 143.1's verdict script, not on further design work.

3. **MEDIUM tier, in the matrix's own reward order** — tag taxonomy audit and HMM regime
   remainder (both batch into Phase 144, travel with it) → **Phase 148** (Reward: "High,
   eventual" — the actual OOS retirement gate, currently failing FRAME-04 16/17 cells pre-fix,
   re-evaluate after 143.1) → **Phase 146** (Reward: "High, latent," evidence-gated into 144's
   batch) → **Phase 151** (Reward: "Med-High, evidence-backed" — evidence gate already cleared,
   genuinely ready for `/gsd-discuss-phase`, not blocked on 143.1 at all) → Cross-Group Lead-Lag
   IC (gated on 144) → `market_data_ohlcv` active-bars view (todo 035, S-effort, Foundational) →
   **Phase 160 Concept Registry** (Low now/Med long-run — real but not urgent) → **Phase 145**
   (not scoreable yet, blocked on 144's verdict) → **Phase 147** (Med, conditional on an
   unevaluated CORPUS-07 gate — not near-term actionable) → **Phase 161 Controlled Vocabulary**
   (Low reward, behind Concept Registry) → **Phases 152-153 IntegrityMonitor** (High long-run,
   low now — insurance; explicitly must not jump ahead of 144/148).

4. **LOW tier — correctly parked:** **Phase 149-150 PrecedentEngine** (Speculative/XL/High-risk —
   needs its own cheap pilot step before any full build, regardless of what Phase 148's gates
   say) and **Phase 155 Alternative Data Vectors** (Med reward, "not actionable — no data source
   chosen"), alongside non-phase LOW items (session/skew/factor regime variants, HMM variant
   redesigns).

5. **Phases 156-159 (v4.0 Execution Layer) — not in the matrix at all** (numbered 2026-07-12,
   after the matrix's 2026-07-08 writing date). Gap, not a verdict: file a todo to get these
   scored rather than assuming their hard v3.2 dependency gate also means low value — those are
   different questions.

**Musk 5-Step + Renaissance framing (2026-07-13)** — applying CLAUDE.md's mandated design lens
explicitly to this list, in order (full parallel pass for `pending/`/`deferred/` todos:
`.planning/todos/PRIORITIES.md`):

- **1. Requirements less dumb:** Phase 151 already went through this — its ≤50-cap,
  theory-motivated-hypothesis design was chosen specifically *over* the combinatorial
  Interaction Factory (deferred todo 019) because ~30K ungated candidates fails BH-FDR power
  at any threshold. That's the Renaissance "empirical over theoretical" test applied at design
  time, not bolted on after.

- **2. Delete:** deferred todo 019 (Interaction Factory) and deferred todo 021 (AnalogEngine,
  closed 2026-07-13 as a Phase 149/150 duplicate) are the phase-adjacent deletions this pass
  found — both were superseded designs still sitting open instead of closed. No live phase
  itself is a delete candidate today; all planned phases trace to either a proof gate (147/148)
  or a named dependent (144→145/149).

- **3. Simplify:** Phase 151's own ≤50-interaction cap *is* the simplify step already applied —
  worth naming explicitly since it's easy to mistake for a scope limitation rather than a
  deliberate rejection of a larger, statistically-invalid design.

- **4. Accelerate:** the priority list above (143.1 → 144 → 148 → ...) already is this step —
  don't re-derive it; this framing pass doesn't change the ordering, it explains *why* 149-150
  correctly isn't at the top despite being the most narratively exciting phase (Renaissance:
  reward is scored against evidence, not the idea's own ambition).

- **5. Automate:** not yet applicable at the phase level — nothing here is a proven-manual,
  repeated process yet. Revisit once Phase 148's gate-evaluation scripts (SCORE-02/03) have run
  enough times to show what's worth automating versus what still needs a human call.

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

</details>

<details>
<summary>✅ v1.4 Quant Foundation (Phases 12-17) — SHIPPED 2026-03-07</summary>

- [x] Phase 12: Signal Integrity — regime-aware gating (hmm_regime + prob≥0.60 + duration≥5), shadow signals — completed 2026-03-04
- [x] Phase 13: Data Completeness — i7/i8 JSONB + days_to_expiry in intelligence_features — completed 2026-03-05
- [x] Phase 14: Feedback Loop — setup_performance table + adaptive aggregator perf_multiplier — completed 2026-03-07
- [x] Phase 15: Validated Alpha — validate_alpha.py gate + 4 new alpha sources live — completed 2026-03-07
- [x] Phase 16: LLM Intelligence Layer — llm_calls hypertable + outcome back-fill + adaptive model routing — completed 2026-03-06
- [x] Phase 17: LLM Wiring Fix — signal_id UUID through pipeline + regime vocabulary fix — completed 2026-03-06

</details>

<details>
<summary>✅ v1.5 Production Hardening (Phases 18-22) — SHIPPED 2026-03-10</summary>

- [x] Phase 18: Financial Math Safety (7/7 plans) — completed 2026-03-08
- [x] Phase 19: Financial Math Characterization (3/3 plans) — completed 2026-03-09
- [x] Phase 20: Circuit Breaker Integration (4/4 plans) — completed 2026-03-09
- [x] Phase 21: Efficiency Optimizations (4/4 plans) — completed 2026-03-09
- [x] Phase 22: I8 Narrative Three-Tier Redesign (7/7 plans) — completed 2026-03-10

</details>

<details>
<summary>✅ v1.6 Signal Quality (Phases 23-24) — SHIPPED 2026-03-10</summary>

- [x] Phase 23: Signal Generator Gate — condition-vs-event onset detection, flip suppression, cross-bar memory — completed 2026-03-10
- [x] Phase 24: Second-Derivative Acceleration — HMA + 4 I2/I3 plugins + exhaustion wiring — completed 2026-03-10

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

Design doc: `docs/plans/2026-04-09-phase-56-swarm-foundation-design.md` — **doc not found** (checked 2026-07-12; Phase 56 is complete, historical drift only)

- [x] **Phase 65: Gradient Audit** — 25+ binary fields converted, 8-function gradient_utils.py, CI scanner gate, 5/5 plans — COMPLETE 2026-04-24. Note: swing_amplitude_expanding companion (swing_amplitude_intensity) not implemented — minor gap, non-blocking.
- [x] **Phase 64: I6 Confluence Expansion** — COMPLETE 2026-05-14. 5 new I6 cross-TF plugins (momentum divergence, S/R confluence, regime agreement, squeeze/expansion, orderflow alignment) + MacroComputeAgent (yield curve + FTQ) + full pipeline integration. 03C USD strength deferred (low priority; YC+FTQ providing macro context).

Design doc: `docs/research/archive/i6-confluence-expansion.md` (archived; superseded by `docs/research/intel-confluence-detection-persistence-layer.md` for the current design)

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
Design doc: `docs/plans/archive/2026-04-11-pipeline-hardening-design.md`

- [x] **Phase 67: Observability, Alerting & Automation** ← COMPLETE 2026-04-23 (2/2 plans)

✅ AlertingAgent (Plan 01) — centralized Kafka-to-Telegram/Discord dispatcher
✅ Webhook removal (Plan 02) — service_auditor migrated to _send_alert(), SRP restored
Grafana alert rules (Telegram/Discord), `market_data_gaps` table + `bar_auditor_agent` write path, roll automation in `service_auditor_agent`, 4 code fixes (bootstrap retry, cache seeding, webhook dispatcher, crash counter), 3 dashboard rebuilds.
Design doc: `docs/plans/archive/2026-04-12-observability-automation-design.md`

</details>

<details>
<summary>✅ v2.5 Data Quality & Intelligence Completion (Phases 69-83) — SHIPPED 2026-05-16</summary>

Full details: `.planning/milestones/v2.5-PHASE-DETAILS.md`

</details>

## Phase Details

<details>
<summary>✅ v2.1 Phase Details (Phases 48-52) — ARCHIVED 2026-03-28</summary>

**Full phase details for v2.1 have been archived to:** `.planning/milestones/v2.1-PHASE-DETAILS.md`

This includes complete documentation for:

- Phase 48: Tick Aggregation & I7 Quality
- Phase 49: DB Performance & Signal Ledger Hardening
- Phase 49.1: Regime Gate Fix — Write All Signals to Signal Ledger
- Phase 49.2: HMM Operational Fixes
- Phase 50: Roll Monitor & DualDivergence Graduation
- Phase 51: Signal & Indicator Validation Framework
- Phase 52: Infrastructure Hardening

Refer to the archived file for detailed success criteria, requirements, and plan breakdowns.

</details>

<details>
<summary>v2.6 Foundation Hardening & Signal Transform (Phases 084-092) — SHIPPED 2026-05-20</summary>

Full details: `.planning/milestones/v2.6-PHASE-DETAILS.md` — **note:** Phase 087 (Signal
Transform Architecture Phases 2-4) was never completed and isn't tracked elsewhere; see the
archive file.

</details>

<details>
<summary>✅ v2.7 Phase Details (Phases 093, 100, 100.5, 104-109) — ARCHIVED 2026-05-29</summary>

**Full phase details for v2.7 have been archived to:** `.planning/milestones/v2.7-PHASE-DETAILS.md`

This includes complete documentation for:

- Phase 093: Renaissance Mathematical Correctness Audit
- Phase 094: LiteLLM Backend
- Phase 095: Pydantic AI Agent Adapter
- Phase 096: Agent Registry
- Phase 097: Zep Episodic Memory
- Phase 098: DSPy Offline Prompt Optimizer
- Phase 099: Guardrails AI Validation
- Phase 100: Plugin Shared Infrastructure
- Phase 100.5: Plugin Infrastructure Hardening
- Phase 104: Storage Architecture Redesign
- Phase 105: Architecture Hotfix Sprint
- Phase 106: Foundation Hardening
- Phase 107: Infrastructure Hygiene
- Phase 107.5: Signal Lifecycle Architecture Fix
- Phase 108: Self-Healing Hardening
- Phase 109: Config Foundation & Self-Healing Engine

Refer to the archived file for detailed success criteria, requirements, and plan breakdowns.

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
<summary>✅ v2.10 Data Architecture Evolution (Phases 123-136) — SHIPPED 2026-06-20</summary>

Full details: `.planning/milestones/v2.10-ROADMAP.md` (includes Phase 131, 132, 134, 136 plan
breakdowns and the Phase 133 cancellation record; Phase 135 kept live below — still open, see
its own entry).

</details>

<details>
<summary>♻️ Phase 135: Controlled Vocabulary System — SUPERSEDED by Phase 161 (2026-07-13)</summary>

**Closure note (2026-07-13):** this phase was scoped in the pre-v3.0 phase-numbering era (the
100-136 block — every other member is `[x] Complete` or `CANCELLED`; this was the one silent
exception) and got orphaned when the codebase moved to v3.0 around it: never executed, never
formally closed. A stray note once claimed it was "deferred indefinitely per STATE.md" — checked,
STATE.md contains zero mentions of Phase 135, that citation was itself stale. Its design doc
stayed current through the v3.0+ governance-framework rewrites even though this phase entry
didn't. **See Phase 161** for the live version of this work, now under a number in the current
sequence. Original content preserved below for history.

**Goal:** A central, reusable vocabulary and taxonomy registry — the APR equivalent for symbolic codes. Three DB tables (`controlled_vocabulary`, `vocabulary_group`, `vocabulary_group_member`), one `VocabularyService`, one `/api/vocabulary/{namespace}` endpoint. Any domain registers its enum vocabulary into a namespace; any consumer reads it without hardcoding. First consumer: dashboard signal filter dropdowns.

**Prerequisite gate:** Phase 134 complete (PG ENUM types in place; vocabulary seeding must reference values already enforced at the DB level).

**Sequencing note:** Independent of Phase 133 (corpus rebuild). Can run in parallel or after 133 — no shared schema dependencies. Should run before any dashboard or API work that needs filter dropdowns.

**Design doc:** `docs/research/concept-controlled-vocabulary.md`

**Plans:** TBD (plan-phase to produce)

</details>

<details>
<summary>✅ Phase 136: Post-Reboot System Repair — COMPLETE 2026-06-19</summary>

**Goal:** Restore data integrity and pipeline correctness after 2026-06-18 reboot. Six work units: recover 1,343 orphaned intelligence_features rows (W1 replay), add feature_writer startup pre-flight schema check + JSONB write path fix (W2), fix intelligence pipeline graceful SIGTERM shutdown (W3), disable FVGFill plugin noise (W4), add validate_signal failure reason via ValidationResult NamedTuple (W5), fix plugin_utils ATR unit label + epsilon guard (W6).

**Prerequisite gate:** None — all fixes are self-contained. Must execute before Phase 133 (corpus rebuild) to ensure data integrity and clean signal generation.

**Sequencing note:** Runs before Phase 133. W2-W6 are code changes deployed together; W1 (replay) and Migration 130 Statement 3 are operational steps run after deploy.

**Design doc:** `docs/plans/archive/2026-06-18-post-reboot-repair-design.md`
**Review:** `docs/plans/135-REVIEWS.md` (cross-AI review: Codex + Ollama) — **doc not found** (checked 2026-07-12; this filename's "135" is unrelated to the actual Phase 135 entry above, likely a leftover from an old numbering scheme; low-priority historical drift, not fixed. Corrected 2026-07-13: the earlier version of this note incorrectly claimed "Phase 135 itself is deferred indefinitely per STATE.md" — STATE.md contains no mention of Phase 135; see Phase 135's own entry for its real, now-resolved status)

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
<summary>✅ v3.0 Intelligence Vectors — AlphaEngine (Phases 137-140) — SHIPPED 2026-06-25</summary>

- [x] **Phase 137: Feature Factory** — 54-feature typed `feature_vectors` hypertable; `FeatureFactory.compute()`; `BaseBatch` Ring 0 base class; I5/I6/I7 archived (7/7 plans, 2026-06-21)
- [x] **Phase 138: IC Engine + Forward Returns** — Vectorized Spearman IC, circular-block-bootstrap CI, BH-FDR, 3-fold walk-forward, causal HMM regime labeling, forward returns via LEAD() (9/9 plans, 2026-06-23)
- [x] **Phase 139: Ensemble + Alpha Emission** — Ledoit-Wolf ensemble weights, IC-weighted alpha matmul, direction-aware CI gate, shadow `alpha_events` emission (3/3 plans, 2026-06-24; 14/14 verification truths)
- [x] **Phase 140: IC Engine Correctness** — Fix stride-per-scale bug, overnight gap contamination in forward returns, BH-FDR meta-level gate, feature collinearity clustering, IC Sharpe min_windows, OOM cleanup, training-window-end CLI arg (4/4 plans, 2026-06-25; 4 items deferred to todo 015)

Full details: `.planning/milestones/v3.0-ROADMAP.md`

</details>

<details>
<summary>📋 v3.0a Signal Integrity — IntegrityMonitor (Phases 152, 149B, 153) — PLANNED</summary>

- [ ] **Phase 152: DistributionDriftMonitor** — Regime-conditioned KS + chi-squared + signed Wasserstein on all 54 features; adaptive penalties (APR-scaled by Wasserstein magnitude); piggybacked recovery; `indicagent-integrity-monitor` service skeleton — design current in `docs/research/measurement-governance-monitor.md` (kept from `docs/plans/archive/2026-06-27-health-guardian-design.md` unchanged)
- [ ] **Phase 149B: feature lifecycle routing, merged with Phase 143** — Evidence-based shadow governance routed through `feature_registry`/Concept Registry, not new `feature_ic_scores` columns; weight restored on promotion via status flip + `ensemble_trainer`'s next recompute, not a `pre_shadow_weight` column (dropped 2026-07-06, see Phase 143's LIFECYCLE-01 correction) — see `docs/research/measurement-governance-monitor.md` (supersedes `docs/plans/archive/2026-06-27-health-guardian-design.md`'s `ICLifecycleMonitor`, which conflicted with D3)
- [ ] **Phase 153: EnsembleHealthMonitor** — 3-gate AND logic (E1: IC Sharpe, E2: regime-conditioned conviction stability, E3: non-shadow coverage); halt/reduce via APR keys; requires Phase 142A (`alpha_ensemble_ic`, complete) — design superseded by `docs/research/measurement-governance-monitor.md` (E2B/E2C restored, CUSUM added, `alpha_events` schema gap found — E2B needs Phase 142B's `alpha_frames`). No monitor code exists; the prior `[x]`/"completed 2026-07-02" was stray, corrected 2026-07-02 (found during intel-14 Fable audit)

**Dependencies:** Phase 142A (`alpha_ensemble_ic` table exists) for Phase 153 only; Phase 152 and the Phase 149B item (merged into Phase 143, see above) are independent

**Spec:** `docs/plans/archive/2026-06-27-health-guardian-design.md` — replaces three prior idea docs

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

## v3.1 AlphaEngine Validation + Alpha Scoring (Phases 140.5-148)

**Milestone Goal:** Validate that AlphaEngine produces real, measurable edge on the full 58-symbol corpus. Close the intelligence feedback loop: alpha_events → hypothetical trade lifecycles → counterfactual P&L → scoring system that proves (or disproves) the engine produces alpha. Retire v2.x after gate-validated superiority. Portfolio construction (Kelly sizing, VaR, IBKR execution) is explicitly out of scope — that is v4.0.

**Input/output contract:** This milestone's output is a scored intelligence engine. `alpha_events` is the output contract. Anything that consumes `alpha_events` for live execution belongs in v4.0.

**Hard prerequisite:** Phase 141 corpus validation must pass ALL gate criteria before Phase 142 begins. No scoring work on unvalidated IC — this is the Simons rule.

---

### Phase 141: Corpus Quality Gate + IC Validation + HMM JIT ✅ COMPLETE 2026-06-29

**Plan:** `docs/plans/2026-06-28-validity-fixes-and-phase-141.md` (Tasks 1-10) — **doc not found** (checked 2026-07-12; Phase 141 is complete, so this is historical drift only)
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

**Goal:** Make everything that feeds ensemble IC measurement — and any future decision/action layer built on top of it — causal, provenance-tracked, and honestly calibrated, before Phase 142A measures OOS ensemble IC on top of it. Full rationale and verification: `docs/research/fable-2026-07-02-v3-bottomup-audit.md` (Fable 5) §5.3-5.6, cross-checked against the live codebase 2026-07-02.

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

### Phase 142A: Ensemble IC Measurement ✅ COMPLETE 2026-07-02

**Schema design:** `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — `alpha_ensemble_ic` table + `alpha.ensemble_ic.*` APR keys. Migration must land before this phase begins.

**Goal:** Prove the ensemble OUTPUT has IC before testing any execution rules. Measure `IC(alpha_score, forward_return_*)` per (symbol, tf, regime, lookahead) using the same BH-FDR + bootstrap CI + walk-forward machinery as feature IC. No stops, no targets, no frame assumptions — pure signal measurement. The IC decay curve across lookaheads calibrates `hold_max_bars` APR keys empirically. This is the primary OOS gate for Phase 148.

**Depends on:** Phase 141.1 complete (Measurement and Decision Integrity Foundation — OOS enforcement, weight-epoch fix, regime_scope schema fix, cost hurdle calibration; inserted 2026-07-02 so this phase's IC measurement isn't done in-sample or against ambiguous regime labels). `alpha_events` accumulating (Phase 139 running). `forward_returns` populated (Phase 138).

**Why before frame simulation:** If `alpha_score` does not predict forward returns, no frame definition will save it. You'd be measuring the frame, not the signal — a silent wrong answer. Signal proof must precede execution proof.

**Requirements:**

**EIC-01 — EnsembleICEngine (weekly oneshot, `BaseBatch`):**
Reads `alpha_events` joined to `forward_returns` on (symbol, tf, bar_ts). Computes Spearman IC(alpha_score, forward_return_fast/mid/slow/extended) per (symbol, tf, regime). Applies same BH-FDR correction, circular-block-bootstrap 95% CI, and 3-fold walk-forward as `ICEngine`. Writes to `alpha_ensemble_ic`. Parallelized: one `ProcessPoolExecutor` task per (symbol, tf) — CPU-bound IC computation fully decoupled from async DB reads/writes.

**EIC-02 — IC decay curve analysis:**
For each (symbol, tf, regime), find the first lookahead where IC Sharpe drops below `alpha.ensemble_ic.decay_threshold`. Update `alpha.frame.hold_max_bars.<regime>.<tf>` APR keys to match. This replaces initial estimates with data-derived values before Phase 142B runs any frames.

**EIC-03 — Walk-forward stability gate:**
IC Sharpe max/min fold ratio < 3× across walk-forward folds. Features with high IC variance are regime-specific, not structural. Gate written to `alpha_ensemble_ic.walk_forward_stable` — Phase 148 OOS validation reads this column.

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

**EIC-04 Verdict Log (machinery completion ≠ gate passage — track separately, per the intel-10/11 review's F10):**

Multiple false-start FAILs between 2026-07-03 and 2026-07-09, each traced to a real bug rather
than true signal absence — data-starvation misdiagnosis (15m at backfill-depth ceiling, 1h/1d
never trained, one genuine null cell), an unweighted meta-FDR grouping bug (`GROUP BY
feature_name` collapsed per-timeframe eligibility; fixed to `GROUP BY feature_name, tf` +
`alpha.ensemble.meta_fdr_min_cells` floor, migration 207), a `DELETE ... RETURNING` query that
OOM-crashed TimescaleDB (fixed via `conn.execute()` command-tag count instead — same pattern
`alpha_publisher.py` already used), IC being measured on the post-emission-filter `alpha_events`
population instead of the raw `ensemble_alpha` scored population (post-selection bias — fixed by
routing `EnsembleICEngine`'s 6 SQL sites to `ensemble_alpha` directly, `test_ensemble_ic_
measurement_population.py`), a persistence bug where 91 of 152 `FeatureVector` columns were
silently never written to the DB (fixed by generating `FEATURE_VECTOR_INSERT_SQL` programmatically
from `dataclasses.fields()` instead of hand-transcribing, with a structural regression guard —
`test_feature_vector_persistence_completeness.py` — making the failure mode unrepeatable), and a
missing `equity_regime_model.py` step in the corpus orchestrator script (fixed, `market_regimes`
now populated every rebuild). Final, trustworthy result (2026-07-10, commit `3c1b2649`, after
also closing an eligibility-gate gap where `passes_walkforward`/`walk_forward_stable` wasn't
required — consolidated into shared `_ELIGIBILITY_WHERE`/`_QUALIFYING_FLAGS` constants to prevent
future drift): **EIC-04 PASS, 54/1425 = 3.79% qualifying cells.**

---

### Phase 142B: Frame Simulation + Counterfactual Tracking ✅ COMPLETE (2026-07-10)

**Schema design:** `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — `alpha_frames` table + `alpha.frame.*` APR keys + `corpus_run_id`/`weight_epoch` provenance columns (canonical-simulator binding rule). No fill-calibrated cost model (`alpha.cost.*`) — real fill data (slippage, commission) does not exist until v4.0 execution. The externally-calibrated `alpha.quant.cost_hurdle.*` keys (todo 030, closed in 141.1) do exist now and are applied as a net-of-cost reporting column per the note below — not a gate change, and not the v4.0 fill-based model.

**Goal:** Prove that a reasonable execution rule (stop/target/hold) can capture the signal IC proven in Phase 142A as positive counterfactual P&L. This is a binary question: does any sensible frame work? Calibration of which frame variant is optimal is a refinement question that belongs after this validation passes, not during it. This is the secondary OOS gate for Phase 148.

**Depends on:** Phase 142A complete — **EIC-04 gate must show PASS** (see verdict log in the Phase 142A section above). **Both dependencies now satisfied, reconfirmed 2026-07-10 on the corrected eligibility gate** (see [Corpus pipeline state](project_corpus_pipeline_state.md) memory for full detail — don't duplicate the numbers here): EIC-04 PASSes (**54/1425 = 3.79%**, superseding the 2026-07-09 35/1585=2.21% figure after `ensemble_trainer.py`/`ensemble_ic_engine.py`'s eligibility gates were found missing a `passes_walkforward`/`walk_forward_stable` requirement and fixed — see the 2026-07-09/10 verdict log entry above) against a threshold recalibrated 0.60→0.02 `[rca_analysis]`, since 0.60 was an untested guess incompatible with rigorous correction at the corpus's true ~516K-hypothesis BH-FDR scale — not a data problem, confirmed via p-value histogram showing genuine, modest signal. `hold_max_bars` APR keys are calibrated from the EIC-02 decay curve for every (regime, tf) cell with qualifying per-symbol evidence — **11/36 cells genuinely walk-forward-confirmed** as of 2026-07-10 (down from a pre-fix 16/36 that included cells computed from zero-fold evidence); the remaining 25 cells correctly retain the `[initial_estimate]` seed because no walk-forward-confirmed decay curve exists there, not because anything is broken. **Phase 142B is no longer blocked.**

**Also carries (added 2026-07-03, canonical-simulator v2 requirements — see `docs/research/platform-canonical-simulator.md`):**

- `alpha_frames`'s P1 migration adds `corpus_run_id`/`weight_epoch` provenance columns — every counterfactual claim must attribute the machinery that produced it (the binding rule's provenance clause).
- **Decide gross vs. net-of-cost SHADOW-REVIEW criteria before that document is committed** (see below) — this cannot be revisited post-launch per the phase's own no-post-hoc-negotiation rule. The externally-calibrated `alpha.quant.cost_hurdle.*` keys (todo 030, closed in 141.1) exist now; applying them as a net-of-cost *reporting column* alongside the gross criteria is cheap and closes canonical-simulator's cost-kernel gap as this phase's natural second consumer.

**Renaissance pre-commitment (ships at Phase 142B launch, before shadow emissions start):**
Write `docs/plans/SHADOW-REVIEW.md` — a one-page document committed to the repo before any counterfactual data is collected, specifying the exact numeric criteria required for Phase 148 live promotion. Criteria are defined before you can see the data; they are not negotiated post-hoc. Proposed criteria (final values committed in the document):

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

**Plans:** 2/2 plans complete

Plans:
**Wave 1**

- [x] 142B-01-PLAN.md — Wave 1: migration 214 (alpha_frames + APR seeds) + AlphaFrameWriter (FRAME-01) + SHADOW-REVIEW.md pre-commitment

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 142B-02-PLAN.md — Wave 2: CounterfactualTracker (FRAME-02/03 state machine, named-cursor scan) + FRAME-04 bootstrap gate + IC-staleness instrumentation

---

### Phase 142B.1: Ensemble Weighting Methodology ✅ COMPLETE (2026-07-04)

**Goal:** Replace `ensemble_trainer.py`'s IC-proportional weighting with better-validated alternatives, judged by Phase 142A's `EnsembleICEngine` on OOS data. Full rationale: `docs/research/fable-2026-07-01-v3-architecture-review.md` §2, §6.

- **E1 — shrunk-IC inputs.** Rides on todo 029's `ic_shrunk` column; consume it instead of raw `ic_sharpe_hac`. Do first — corrects decisions being made today and gives every later variant a de-noised baseline.
- **E2 — mean-variance combination.** `w ∝ Σ⁻¹·IC` using the Ledoit-Wolf covariance `ensemble_trainer.py` already computes but currently only uses for a binary correlation-cluster cap. Textbook Grinold-Kahn combination; gate on covariance condition number.
- **E3 — hierarchical partial pooling** for sparse regime strata. Deferred pending E1/E2 proving insufficient — do not amend the "pooled IC is diagnostic only" load-bearing decision (STATE.md) until then.
- **E4 — per-feature decay half-lives**, replacing the single global `weight_half_life_days`. Sequence after todo 029's decay-curve item ships.

Every variant is a new `weight_version` in the existing `ensemble_weights` PK — zero schema change needed for A/B testing. (Note: the previously-planned "fold in todo 043" first commit is dropped — todo 043's APR-backed stale-weight cliff already shipped in migration 193 / `alpha.ensemble.weight_stale_max_days`; `ensemble_trainer.py:504` reads it, no hardcoded `> 90` remains.)

**Requirements**: D-01..D-14 (CONTEXT.md decisions; no REQUIREMENTS.md for this project — decisions are the requirements). Mapped to REQ-142B1-* IDs in plan frontmatter.
**Depends on:** Phase 142A complete (not 142B — 142A's ensemble IC measurement is the judge; kept separate from 142B's frame simulation work, which this phase does not need)
**Plans:** 5/5 plans complete

Plans:

- [x] 142B.1-01-PLAN.md — Wave 0: migration 196 (2 columns + 4 APR keys) + pooled cross-sectional dispatch in ensemble_ic_engine.py (todo 046, D-01/D-02/D-07)
- [x] 142B.1-02-PLAN.md — Pure-fn math (TDD): shrink_ic + leave-one-out prior (shrinkage.py) + mean_variance_weights() in weights.py (D-05/D-06/D-08 math)
- [x] 142B.1-03-PLAN.md — E1 wiring: ops_ic_shrinkage.py compute step + hard out-of-fold acceptance gate + ensemble_trainer ic_input toggle + pipeline sequencing (D-04/D-05/D-06)
- [x] 142B.1-04-PLAN.md — E2 wiring: mean_variance weight_method branch in ensemble_trainer with condition-number fallback (D-08)
- [x] 142B.1-05-PLAN.md — A/B judging: ops_ensemble_weight_compare.py win-decision gate, per-stratum, regime-caveat tagged (D-10/D-11/D-12/D-14)

**Concept Registry MVP — landing spot recorded 2026-07-03** (topdown D9 named this phase as the
registry's build trigger via the `ensemble_strategy` domain, but 142B.1's 5 plans above contain
no registry item — topdown Open Q6 allowed running on bare `weight_version` rows and backfilling
after, which is what's happening). **Next step once 142B.1 completes:** a small follow-on item
seeding `concept-governance-registries.md`'s four-table MVP from 142B.1's E1-E4 `weight_version`
rows, before any `confluence`/`regime_model` domain needs it (those are still further out — see
v3.15 and intel-10 v3). Not doing this promptly is how "deferred" becomes "deferred indefinitely."
**Registered 2026-07-13 as Phase 160 below** (standalone number -- this work is triggered by 142B.1 completing, not a sub-phase of it; placed here for reading context).

### Phase 160: Concept Registry MVP ✅ COMPLETE 2026-07-14

**Goal:** Build the four-table evidence-gated lifecycle registry (`concept_registry` /
`concept_gate` / `concept_transition_log` / `concept_annotation`) and seed `domain='ensemble_strategy'`
from Phase 142B.1's outcomes — the concrete answer to "why don't we use this strategy/feature/model
anymore," queryable ten years from now instead of living in Slack or memory.

**Depends on:** None — build trigger already fired 2026-07-04 (Phase 142B.1 complete, above).
Sits immediately after its own trigger phase; does not block or get blocked by anything in the
143-151 critical path — scheduled opportunistically, same treatment as Phase 152/153, did not
jump ahead of Phase 144/148.

**Design:**

- Full task-by-task implementation plan already written: `docs/plans/2026-07-13-concept-registry-mvp-implementation-plan.md`.
- Seed `ic_proportional` as the `active` incumbent, E1 (shrunk-IC)/E2 (mean-variance) as
  evaluated-mechanism `candidate` rows, E3/E4 as thesis-only `candidate` rows.

- Names `ops_ensemble_weight_compare.py`'s win-decision gate as the sole deterministic
  status-flipper (invariant 1); `baseline_metric` stores the mean of `min_promotion_consecutive`
  evaluations as a winner's-curse guard; per-stratum status resolved as recipe-validity (status)
  vs. deployment-as-fact (`ensemble_weights`), `redundancy_group` displacement disabled for this
  domain.

- Canonical doc: `docs/research/concept-unified-registry.md`. Priority context:
  `.planning/todos/pending/112-concept-registry.md`, `docs/research/intelligence-lifecycle-backlog-matrix.md`
  (MEDIUM tier — Effort M, Risk Low, Reward Low-now/Med-long-run).

**Plans:** 4 plans in 3 waves (planned 2026-07-14 from `docs/plans/2026-07-13-concept-registry-mvp-implementation-plan.md`):

- [x] 160-01-PLAN.md — migrations 233 (schema + APR gate keys) + 234 (seed domain='ensemble_strategy') [wave 1] ✅ COMPLETE
- [x] 160-02-PLAN.md — ConceptRegistryService pure decision core + transactional CAS apply [wave 1] ✅ COMPLETE
- [x] 160-03-PLAN.md — wire ops_ensemble_weight_compare.py win-decision gate to the service (invariant 1) [wave 2] ✅ COMPLETE
- [x] 160-04-PLAN.md — design-doc sync, file domain='feature' follow-on todo, close todo 112, merge [wave 2] ✅ COMPLETE

**Execution Summary:**

- Wave 1 (migrations + service): Migration 233 built 4-table MVP schema (concept_registry/gate/transition_log/annotation) with APR gate keys; Migration 234 seeded ensemble_strategy domain with 5 E-variants (ic_proportional as active incumbent, E1-E4 as candidates). ConceptRegistryService implemented transactional CAS promotion with pure comparison-decision core.
- Wave 2 (API + dashboard): ops_ensemble_weight_compare.py wired to ConceptRegistryService enforcing invariant 1 (sole deterministic status-flipper for ensemble_strategy domain). Documentation synchronized, invariant-6 ensemble_strategy exception recorded, todo 112 closed.
- All 40 unit tests pass (20 ensemble_weight_compare + 20 concept_registry_service).
- Backward compatibility maintained (report-only path byte-identical).
- Todo 118 filed for pre-live-use empirical validation (D-02 scope plus H-1/L-2/L-3/L-4 automation hardening).

### Phase 161: Controlled Vocabulary System ✅ COMPLETE 2026-07-18

**Goal:** A central, reusable vocabulary and taxonomy registry — the APR equivalent for symbolic
codes. Three DB tables (`controlled_vocabulary`, `vocabulary_group`, `vocabulary_group_member`),
one `VocabularyService`. Any domain registers its enum vocabulary into a namespace; any consumer
reads it without hardcoding (`signal_outcome`, `entry_type`, `regime_hmm`,
`regime_cross_sectional`, `tier`, `timeframe`, `asset_class`, `session_type`, and more).

**Supersedes Phase 135** (2026-07-13) — Phase 135 was scoped in the pre-v3.0 phase-numbering era
(the 100-136 block, all other members of which are `[x] Complete` or `CANCELLED`) and was
silently orphaned when the codebase moved to v3.0 around it: never executed, never formally
closed, its own "deferred indefinitely per STATE.md" note doesn't resolve against any actual
STATE.md content. Its design doc stayed current through the v3.0+ governance-framework rewrites
(now `docs/research/concept-controlled-vocabulary.md`) even though the phase entry didn't — this
phase carries that live design forward under a number in the current sequence. See Phase 135's
own entry for the closure note.

**Depends on:** None — Phase 134 (PG ENUM types) shipped 2026-06-18, the only prerequisite either
phase ever named. Opportunistic, same treatment as Phase 160 above — ranks below it (see
matrix: no incident has yet demonstrated the cost of not having this, unlike Concept Registry's
F1 near-miss).

**Design:**

- Canonical doc: `docs/research/concept-controlled-vocabulary.md`. First consumer: dashboard
  signal filter dropdowns (per Phase 135's original scope, unchanged).

- Open question, not resolved here: whether `tag_vocabulary` (live, 71 tags, migrations 227/228)
  should be generalized/subsumed by this system or genuinely needs to stay separate — see
  `.planning/todos/pending/110-controlled-vocabulary.md`.

- Priority context: `docs/research/intelligence-lifecycle-backlog-matrix.md` (MEDIUM
  tier — Effort M, Risk Low, Reward Low).

**Plans:** 4/4 plans complete
Plans:
**Wave 1**

- [x] 161-01-PLAN.md — Wave 1: 3-table schema (migration 237) + seed 6 namespaces & groups (migration 238)
- [x] 161-02-PLAN.md — Wave 1: VocabularyService (ConfigService-shaped cache) + three-way ENUM divergence check

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 161-03-PLAN.md — Wave 2: column-backed drift audit module + oneshot CLI, chained into corpus pipeline
- [x] 161-04-PLAN.md — Wave 2: /api/vocabulary/{namespace} FastAPI route + main.py registration

### Phase 142.5: Renaissance Primitives ✅ COMPLETE (8/8 plans, 2026-07-07) (INSERTED)

**Goal:** Add 91 foundational primitives from `signal-renaissance-primitives-ohlcv.md` to Feature Factory v3.0. Corpus backfill and IC evaluation will happen as part of the next corpus run (before 142B).

**Requirements** (counts reconciled 2026-07-06 — see `142.5-PLAN-OUTLINE.md`):

- Implement all primitives in `src/intelligence/feature_factory.py`:
  - Bar anatomy ratios (8)
  - Lagged return series (6)
  - Open-to-Close split (4) — spec claimed "existing" but verified absent; implemented in Plan 01
  - Temporal coordinates (8 new sin/cos pairs; dow already exists)
  - month_sin/cos (2) — only month_position existed; sin/cos pair added
  - Volume structure primitives (12)
  - Return distribution primitives (7)
  - Realized variance / volatility primitives (14)
  - Alternative volatility estimators (3)
  - Volatility dynamics primitives (5)
  - Breakout distance primitives (14)
  - Price-volume interaction primitives (8) — Plan 05.5
- Add APR entries for window-based features (54 total: 44 in Plan 06, 10 breakout in Plan 05)
- Update schema to 152 columns (61 baseline + 91 Renaissance) + seed feature_registry to 152 rows
- Migration: `production/migrations/206_add_renaissance_primitives.sql`
- **Deferred (OUT):** Cross-Timeframe Divergences (3) — require HTF-cache coupling; scoped to a
  follow-on cross-TF unit (see `.planning/todos/pending/`)

- **Deliverable:** FeatureFactory computes 152 features, schema expanded, registry seeded, ready for corpus run

**Depends on:** Phase 142B.1 (Ensemble Weighting Methodology)
**Plans:** 8/8 plans complete
Plans:

- [x] 142.5-00-PLAN.md — Wave 0: Test infrastructure (11 RED categories, schema test asserts 152)
- [x] 142.5-01-PLAN.md — Bar anatomy (8) + Lagged returns (6) + Open-to-close split (4) → 79
- [x] 142.5-02-PLAN.md — Temporal coords new (8) + month_sin/cos (2) + Volume structure (12) → 101
- [x] 142.5-03-PLAN.md — Return distribution (7) + Realized variance (14) → 122
- [x] 142.5-04-PLAN.md — Alternative volatility (3) + Volatility dynamics (5) → 130
- [x] 142.5-05-PLAN.md — Breakout distance (14) + migration 206 (breakout cols/APR) → 144
- [x] 142.5-05.5-PLAN.md — Price-volume interactions (8) → 152
- [x] 142.5-06-PLAN.md — APR seeds (44) + 77 columns + 91 feature_registry rows + schema test (152)

**Post-completion correction (2026-07-09, migration 211):** `new_high_flag`/`new_low_flag`
(2 of the 91 primitives) were found redundant with `dist_from_high`/`dist_from_low` — same
rolling-max window, same comparison, `new_high_flag[i] == 1{dist_from_high[i] <= eps/atr[i]}`
exactly, zero orthogonal information. Removed from `FeatureVector`, `feature_factory.py`, and
the DB schema (`production/migrations/211_drop_redundant_breakout_flags.sql` has the full
proof and rationale in its header comment). Current state: **89 Renaissance primitives, 150
total FeatureVector columns** (61 baseline + 89), `feature_registry` at 150 rows.

### Phase 143: Feature Lifecycle Routing (merged with Phase 149B) ✅ COMPLETE (2026-07-10)

**Rewritten 2026-07-03 against `docs/research/measurement-governance-monitor.md`** (Fable-reviewed
2026-07-02). The previous version of this phase specced a standalone `is_decaying` state
machine writing directly to `feature_ic_scores`, a separate `feature_deprecations` table, a
daily-scan `AlphaDecayMonitor` daemon, and cooldown-gated recovery — all four were superseded by
the topdown architecture review's decision D3 and Fable's intel-14 consolidation before this
phase was ever executed. **This is not a new subsystem to build. It is a routing decision**:
`feature_registry.md` already implements the exact state machine this phase re-derived
(`candidate → active → shadow_only → deprecated`, 61 rows in production today), and `ic_engine`
already stamps `feature_status_at_eval` from it. The only missing piece is the **transition
writer** that flips registry status when a corpus run's results demand it.

**Goal:** Features that lose IC get demoted through the registry automatically; features that
recover get promoted back through the same evidence bar as everything else in this codebase.
Regime-shift guard prevents mass zeroing during market dislocations. No new tables, no new
daemon.

**Depends on:** Phase 141 complete (`feature_ic_scores` populated, `feature_registry` live).
No dependency on `alpha_frames` or Phase 142A/142B.

**Requirements:**

**LIFECYCLE-00 — HMM Regime Label Validation (todo 026 P1-P3):** unchanged from the prior
version — the regime-shift guard is only as trustworthy as the regime labels it reads, so this
ships first, same phase. Plan: `docs/plans/2026-06-28-hmm-regime-audit-optimization.md`.
P1a/P1b/P2a already shipped (see 026's own status). What's left: P2b (degenerate-model
occupation-fraction gate), P2c (`hmm_churn` feature column), P3 (empirical threshold
calibration). Also run todo 034's Step 1 baseline-separation query against this corpus run
before trusting the regime-shift guard in production.

**LIFECYCLE-01 — Registry amendments (replaces the old bespoke state machine):**
`feature_registry`'s existing `candidate → active → shadow_only → deprecated` machine gets
three amendments, not a parallel one:

1. Redirect automated `ic_demotion` to target `shadow_only`, not `deprecated`; `deprecated`
   becomes operator-only (closes the auto-deprecation path the registry currently allows).

2. Add the missing `shadow_only → active` promotion transition — none exists today;
   `shadow_only` is currently an operator-entered dead end. Promotion requires **2 consecutive
   passing corpus runs AND ≥ `alpha.ic.decay_recovery_min_observations = 2000` new independent
   observations since demotion** — no cooldown clock (Fable's reconciliation explicitly
   rejected calendar-gated recovery: it blocks fast recovery for no statistical reason, and the
   observation floor already guards against evidence reuse that a cooldown was trying to
   prevent).

3. Add shadow-run counters (consecutive passes, observations since demotion) as **registry
   columns**, not `feature_ic_scores` columns — they are lifecycle state, so they live with the
   status. **Correction (2026-07-06, `/gsd:plan-phase --reviews` replan against 143-REVIEWS.md):**
   `pre_shadow_weight` is dropped, not added. `services/ensemble_trainer.py` is the sole writer of
   `ensemble_weights` (line 744) and recomputes every weight from scratch each run from current
   `feature_ic_scores` — no warm-start/prior-weight read exists anywhere in that file — so a scalar
   `pre_shadow_weight` on `feature_registry` would write to a column nothing reads. Promotion
   restores weight by the status flip alone: `active` status → next `ic_engine` run stamps
   `feature_status_at_eval='active'` → next `ensemble_trainer` run recomputes a fresh weight. There
   is no consecutive-fail counter either (demotion is `ic_engine`'s single-run materiality gate,
   decided in LIFECYCLE-03, not a registry column).

**Do NOT build:** `is_decaying`/`decay_detected_at`/`recovery_eligible_at` on `feature_ic_scores`
(D3 — these three columns exist unread in the live schema today and get **dropped**, not
wired) or a `feature_deprecations` table (registry `status='deprecated'` + a
`feature_transition_log` row with an operator reason already covers it).

**LIFECYCLE-02 — Ensemble query enforcement:** unchanged in effect, corrected in mechanism —
`ensemble_trainer` already filters `WHERE feature_status_at_eval = 'active'` (Phase 139 logic).
No new filter needed; this requirement is satisfied by existing code once LIFECYCLE-01's
registry amendments land.

**LIFECYCLE-03 — Transition writer (replaces "Alpha Decay Monitor daemon"):** **no separate
daemon, no daily scan, no Kafka subscription.** Lifecycle state can only change when new IC
measurements land, so the writer is a post-run step inside `ic_engine` calling
`FeatureRegistryService` after each corpus run. A daily scan would re-read unchanged data six
days out of seven (IC engine runs weekly); the end-of-run hook gives identical detection latency
with no daemon and no event-vs-data-visibility race. Materiality gate on re-solve unchanged:
`weight × |ic_ci_lower| > alpha.decay.materiality_threshold = 0.005`. OTel metrics unchanged:
`alpha_decay_cells_flagged`, `alpha_decay_ensemble_rebuild_total`. The hook writes a
gate-evaluation fact row to `integrity_monitor` (`monitor_type='ic_lifecycle'`) — metric vs.
threshold, pass/fail — so drift/lifecycle/ensemble-health stay queryable from one table, while
`feature_transition_log` remains the sole authoritative transition record (nothing written
twice). **Initial candidate list unchanged:** todo 033's 7 zero-IC features, gated on the
todo 034/026 regime-label validation above per todo 033's 2026-07-01 update.

**LIFECYCLE-04 — Regime-shift guard:** unchanged. If ≥ `alpha.decay.regime_shift_fraction = 0.60`
of active feature-regime cells fail simultaneously, classify as market regime shift — hold all
weights rather than mass-zero, human review before any weight changes. Runs in the same
end-of-run hook as LIFECYCLE-03 (it needs exactly the per-run view the hook already has).
Depends on LIFECYCLE-00 having run first.

**LIFECYCLE-05 — IC staleness alerting:** unchanged. `alpha.ic.staleness_alert_days = 5`
[initial_estimate]; OTel gauge `ic_engine_last_run_age_days`; `IC_ENGINE_STALE` alert if stale.
**Sequencing note (2026-07-03):** this phase is independently startable now, while Phase 152
(`DistributionDriftMonitor`) is unbuilt and unscheduled. Ships as a standalone gauge check in
this phase's own end-of-run hook; consolidate onto `DistributionDriftMonitor`'s check cycle
later if/when Phase 152 lands, not a blocking dependency now.

**LIFECYCLE-06 — Decay diagnostics:** unchanged. Ad-hoc SQL via
`docs/analysis/feature-decay-queries.sql`; Superset dashboard deferred until the routed system
has operated ≥ 30 days.

**Plans:** 3/3 plans complete

- [x] 143-01-PLAN.md — Wave 1: LIFECYCLE-00 HMM regime label validation (P2b occupation gate, P2c hmm_churn, APR keys)
- [x] 143-02-PLAN.md — Wave 2: LIFECYCLE-01 registry amendments (lifecycle columns, sync record_transition_sync + evidence-only promotion, drop dead decay columns)
- [x] 143-03-PLAN.md — Wave 3: LIFECYCLE-02/03/04/05/06 ic_engine post-run hook (demote/promote, regime-shift guard, staleness gauge, integrity_monitor, decay diagnostics SQL)

**Completed 2026-07-10** (commit `69ca7db7`). Migrations 202-205 (planned against a stale 201 tip) were renumbered to 216-219 before execution since migrations 206-215 had landed on main from other phases in the interim. Wave 3's full-suite verification caught one genuine regression it introduced — 7 new `ICEngineConfig` fields broke `test_hac_ic_sharpe.py`'s direct constructor call — fixed same-session by defaulting the new fields to their APR fallback values (commit `b47595b9`). Full `tests/unit/` suite green (5695 passed; only the one pre-existing unrelated `test_no_smooth_or_backward_in_factory` failure remains, already tracked).

---

### Phase 143.1: Measurement and Eligibility Integrity (INSERTED)

**Goal:** Fix two confirmed defects in the alpha measurement/scoring chain before Phase 144's
evidence is re-measured on top of it, batching in three cheap, already-specced diagnostics plus
one cheap, already-specced measurement improvement (Component F, added 2026-07-11) into the same
corpus re-run per the project's own batching doctrine (`docs/research/
fable-2026-07-07-renaissance-layer-refinements.md` §12: "the v3.15 batched rerun is the natural
landing window for everything measurement-shaped... running them piecemeal burns rerun cycles").
Full design worked out via a completed `superpowers:brainstorming` session (2026-07-11) and an
independent Fable architectural review verified against the live DB — see
`docs/plans/2026-07-11-ic-quality-and-sign-symmetry-strategy.md` for the sequencing rationale
this phase implements.

**Component A — Fisher-z CI bootstrap fix (todo 091, P0).** The analytic Fisher-z CI used by
every downstream gate (BH-FDR, EIC-04, walk-forward) is empirically miscalibrated — a 66-cell
circular-shift permutation diagnostic found 38% SUSPECT (`docs/plans/
2026-07-09-ic-null-calibration-design.md`). Fix: implement circular block bootstrap correctly in
`src/intelligence/statistics/ic_math.py` (the old bootstrap had a documented pre-ranking bug —
resampled pre-ranked values instead of raw observations re-ranked per-sample; reuse the correct
pattern already proven in `_circular_shift_null`). Full corpus-wide replacement of `_fisher_z_ci`
as production CI — not targeted/boundary-only (targeting via the CI suspected of being wrong to
decide which cells get bootstrap treatment is circular; decided explicitly during brainstorming).
Gives the dead `alpha.ic.bootstrap_seed`/`bootstrap_resamples`/`bootstrap_block_size.*` APR keys
their first real reader. Staged validation: new implementation must agree with the existing
66-cell diagnostic's empirical null before any corpus-wide run.

**Component B — IC decomposition columns (todo 090).** `sign_hit_rate` and magnitude-conditional
IC as new `feature_ic_scores` diagnostic columns (no gate change). Source: refinements doc §L4-4.

**Component C — Anytime-valid e-values pilot (todo 079, tf=5m only).** Per-cell e-process
(likelihood-ratio e-value on IC sign) persisted across corpus reruns — evidence compounds instead
of resetting each run. Source: refinements doc §L4-1. Self-verification requires Component D.

**Component D — Canary predictors (todo 068, folded in as Component C's dependency).** 5-10
`feature_registry` rows flagged `is_control=true` (pure-noise RNG columns, one acausal
lookahead-leakage placebo, one degenerate/constant column) + one orchestrator assertion: any
control feature clearing `ic_ci_lower > 0 AND passes_fdr` fails the corpus run loudly.

**Component E — Sign-symmetric ensemble eligibility redesign (todo 094, P0, root cause confirmed
2026-07-11 and independently verified against the live DB).** `alpha_events` is 99.99% long-only
(11.81M long vs 1,479 short) because two sign-asymmetric gates — `ic_ci_lower > 0` in
`services/ensemble_trainer.py`'s `_ELIGIBILITY_BASE_WHERE`, and a `fold_ic > 0` walk-forward
criterion in `services/ic_engine.py` — exclude 100% of contrarian (negative-IC) features before
they ever reach ensemble weighting. Verified: 1,527 eligible rows, zero at `ic_sign=-1`. The
existing `ic_signs` sign-correction mechanism in `compute_alpha_score()` has never fired — dead
code. Fix: redesign eligibility and walk-forward criteria to be sign-aware (`ic_sign * IC` framing
throughout), redesign `feature_selector.py`'s `compute_quality_weight()` to preserve magnitude on
the negative side without a naive `abs()` (an earlier `abs()`-based fix was reviewed and rejected
— it would misapply magnitude weighting to a different population and up-weight decayed signals
in the wrong direction), and fix a latent bug where `mean_variance_weights()` (the E2 path) would
silently re-exclude contrarian features downstream even after the main eligibility fix. Requires
mandatory shadow-mode validation (new `weight_version`, parallel scoring, frames + FRAME-04
evaluation) before promotion — this changes champion scoring behavior for what will become the
owner's live trading capital. Requires re-running the E1-vs-E2 A/B judgment afterward (the prior
20/20 E1-win result was all-long vs all-long, doesn't carry forward to a sign-symmetric universe).

**Component F — Vol-normalized return target for POOLED-strata IC (todo 097, split from todo
077's L3-1, added 2026-07-11).** `return_x / trailing_sigma(symbol)` as an alternative to raw
return for POOLED-strata measurement, where raw-return ranks are currently dominated by whichever
symbols happen to be running hot on a given bar — a real bias against the ensemble's exclusively-
POOLED training population (`ensemble_trainer.py:317,430,469,540`). Cheap (join + divide inside
`ic_engine`'s existing corpus load, no migration), unblocked today, rides the same corpus re-run
A and E already require. **Validated as an explicit A/B, not a silent swap:** re-run POOLED
strata with both raw and vol-normalized targets and compare qualifying-feature rankings directly
— three simultaneous changes to the same `ic_ci_lower`/`ic_ci_upper` numbers (Fisher-z CI,
sign-symmetric eligibility, and now the return target itself) would confound attribution if any
landed as a silent replacement rather than a measured comparison. If rankings are materially
identical to the raw-return baseline, retire the transform rather than keeping it on the strength
of theory alone.

**Why these six components share one phase:** Components A, E, and F all read or directly affect
`ic_ci_lower`/`ic_ci_upper` and each independently requires a full `ic_engine` corpus re-run —
sequencing them together means engineering effort (and re-run wall-clock) is spent once. Contrast
with todo 073 (cross-sectional relative-value feature family) and todo 077's remaining L3-2/L3-4
scope, which need new schema/DAG steps or a separate phase's outputs (Phase 146's betas) and
correctly stay deferred toward the larger v3.15/Phase 151 batch instead of folding in here.

**Requirements:** A (Fisher-z->bootstrap CI), B (IC decomposition columns), C (e-values pilot, 5m), D (canary predictors), E (sign-symmetric eligibility), F (vol-normalized POOLED target) — used as pseudo-IDs (no REQUIREMENTS.md in this project). Coverage: A->01/07, B->05/07, C->06/07, D->02/07, E->04/08, F->03/07.
**Depends on:** Phase 143 (complete). Soft dependency on todo 093 (`alpha_frames` backfill)
being far enough along to provide a pre-fix baseline for comparison — not a hard blocker.
**Blocks:** Phase 144 — its own evidence needs re-measuring against a corpus produced by this
phase's corrected measurement pipeline.
**Source todos** (reference, don't duplicate): `.planning/todos/pending/091-fisher-z-ci-empirical-
null-miscalibration.md`, `094-alpha-events-long-short-imbalance.md`,
`090-ic-decomposition-hit-rate-magnitude.md`, `079-anytime-valid-e-values-corpus-reruns.md`,
`068-canary-predictors-integrity-check.md`, `097-vol-normalized-return-target-pooled-ic.md`.
Related, not gated on this phase:
`096-frame-hold-horizon-vs-feature-lookahead-mismatch.md` (read-only, can run in parallel).
**Plans:** 6/8 plans executed

Plans:

- [x] 143.1-01-PLAN.md — Component A: Fisher-z→circular-block-bootstrap CI (ic_math + 3 ic_engine call sites, APR reactivation, staged-validation gate) [Wave 1]
- [x] 143.1-02-PLAN.md — Component D: canary predictors (real FeatureVector fields, migration, loud integrity assertion) [Wave 1]
- [x] 143.1-03-PLAN.md — Component F: vol-normalized POOLED return target, explicit A/B [Wave 2]
- [x] 143.1-04-PLAN.md — Component E: sign-symmetric eligibility (3 walk-forward blocks incl. cross-sectional, Gate 1, quality weight, E2 sign-path) [Wave 3]
- [x] 143.1-05-PLAN.md — Component B: IC decomposition columns (sign_hit_rate, magnitude-conditional IC) [Wave 4]
- [x] 143.1-06-PLAN.md — Component C: anytime-valid e-values pilot, 5m only [Wave 5]
- [ ] 143.1-07-PLAN.md — Single full-pipeline corpus re-run from Step 1 + A/B/C/D/F validation [Wave 6]
- [ ] 143.1-08-PLAN.md — Component E shadow-mode validation + E1-vs-E2 A/B re-run [Wave 7]

### Phase 147: I7 CORPUS-07 Evaluation 📋 PLANNED

**Priority note (2026-07-22):** not a blocker for anything — confirmed via `/gsd-discuss-phase
147` that Phase 148 has no real dependency on this phase (see Phase 148's "Correction
2026-07-22"). This phase's only value is due diligence: do any of the 35 archived, zero-live-
consumer I7 plugins (`indicagent-intelligence-pipeline.service` has been `failed` since
2026-07-17, `ExecStart` target file doesn't exist on disk, and no plugin has ever recorded a
`promoted_at`/`demoted_at`/`last_eval_at` in `shadow_registry`) contain a genuinely novel
signal not already captured by the v3.0 Feature Factory. Worth doing eventually for
completeness, not urgent — do not let it compete with Phase 148 or anything else with live
measurement value.

**Rewritten 2026-07-19 per todo 056** (`.planning/todos/pending/056-phase146-147-v2x-retirement-stale.md`,
tracking `docs/research/fable-2026-07-03-roadmap-reconciliation.md` F3): the old "conditional
gate" language cited a CORPUS-07 analysis that had never been run under any phase's requirement
list — the gate could never fire as written. Collapsed to what F3's sketch recommends: run
CORPUS-07 itself as this phase's one deliverable, default outcome is retirement per topdown D7,
survivors become ordinary predictors — no adapter contract, no conversion infrastructure built
speculatively.

**Default path is retirement, not conversion.** The 54 `feature_vectors` features were designed
to capture I7 signals. Conversion is the exception; retirement is the rule.

**Goal:** For each active I7 plugin, determine via CORPUS-07 (map plugin → constituent
`feature_vectors` dimensions + Phase 141 CORPUS-04 IC results) whether it introduces information
not captured in the 54 atomic features. Apply one of three outcomes:

- **Retire (default):** dimensions fully captured in `feature_vectors` OR no constituent feature
  has confirmed IC. Mark `status='deprecated'` in `shadow_registry`, add retirement reason to
  `config_history`. Expected outcome for the majority of plugins.

- **Register as ordinary predictor (rare survivor):** plugin has confirmed IC on dimensions NOT
  present in `feature_vectors`. Its continuous output becomes a candidate **feature**, measured by
  `ic_engine` like any other feature (per intel-15's grain rule) — not a second scoring system, no
  `alpha.i7.mixing_weight_*` keys, no separate ensemble-ingestion path. One model, one book.

- **Direct IC measurement (ambiguous):** plugin logic is ambiguous (>5 constituent features or
  cross-cutting logic). Measure its continuous output's IC directly before deciding retire vs.
  register.

**Depends on:** nothing — CORPUS-07 is this phase's own first deliverable, not a prerequisite
run elsewhere. No dependency on Phase 143.

**Design doc:** `docs/plans/2026-06-20-i7-alpha-scorer-transition.md` — broken link, doc does not
exist (checked 2026-07-12). Closest existing artifact: `.planning/todos/completed/016-i7-alpha-scorer-transition.md`.
Superseded in spirit by this rewrite (no conversion apparatus to design against).

**Requirements:**

**I7-01 — CORPUS-07 analysis + retirement/registration decisions:** the full plugin-capture
mapping and per-plugin outcome above. Deliverable: analysis report + `shadow_registry`
deprecation rows + any survivor's feature registration.

Deleted as requirements (were conversion-apparatus scope, moot under retirement-by-default):
~~I7-02 (`signal_events.alpha_score` column)~~, ~~I7-03 (ensemble mixing-weight ingestion)~~,
~~I7-04 (conversion-progress observability gauges)~~.

**I7-05 — Retirement eligibility gate:** simplifies to "CORPUS-07 evaluated + survivors
registered" — no `i7_conversion_complete` gauge, since there is no conversion process to track.

**Plans:** 1 plan (CORPUS-07 analysis + retirement/registration execution).

---

### Phase 148: Alpha Scoring System ✅ COMPLETE (2026-07-22) — VERDICT: DO NOT PROMOTE

**Both irreversible OOS proof gates ran exactly once (D-04).** Gate 1 (signal proof): **PASS**
— 140/640 (21.875%) of 5m/15m cells qualify against a 2% floor, well past threshold, though
coverage is 5m/15m only (`ensemble_alpha` has zero OOS rows at 1h/any weight_version and 1d/
champion weight_version — a separate pre-existing gap, filed as todo 173, discovered after this
irreversible run so not correctable this milestone). Gate 2 (execution proof): **FAIL** — 3 of
5 SHADOW-REVIEW criteria fail decisively (mean P&L CI, Sharpe, max drawdown all fail; sample
size and no-confident-loss both pass), matching D-06's "known going in" framing exactly, not a
surprise. Regime-stratified companion (D-07): only 2 of 8 champion cells clear coverage, both
`mid_bull`, both fail — the champion's OOS window is too narrow to speak to regime-conditional
performance.

**Overall: do not promote the v3.0 AlphaEngine to live trading capital at this time.** Real
signal exists (Gate 1) but the current frame/execution design does not capture it as profitable
OOS P&L (Gate 2) — per this project's core value, a signal that can't yet be turned into
profitable trades is not a promotable system. Diagnosing/fixing Gate 2's failure is explicitly
out of scope for this phase (deferred to future work).

**A real, previously-latent infrastructure gap was found and fixed mid-execution, with explicit
human sign-off:** `forward_returns` had never been computed for the OOS window (bar_ts >=
2025-12-24) by anything — the corpus orchestrator's OOS-holdout clamp (correctly) prevents
normal corpus rebuilds from touching it, but nothing had ever populated it either. Backfilled
(mechanical, deterministic, no parameters tuned) after independent verification the fix was
sanctioned under `OOS-EVAL-PROTOCOL.md`. Separately, a real reproducibility bug was found and
properly fixed in the frozen `c4_max_dd` (max drawdown) statistic — same-`bar_ts` ties
(~22-way, simultaneous cross-sectional positions) made a path-dependent cumulative-sum
statistic non-deterministic; fixed by aggregating per-`bar_ts` before the cumulative walk
(economically correct, not just an arbitrary tie-break). The verdict was unaffected under every
method tested — full detail, evidence tables, and both gates' exact numbers in
`docs/plans/2026-07-22-phase148-promotion-decision.md`.

**Two non-blocking follow-up todos filed:** [172](../.planning/todos/pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md)
(broader sweep for other order-sensitive statistics), [173](../.planning/todos/pending/173-ensemble-alpha-1h-1d-oos-scoring-gap.md)
(`ensemble_alpha` 1h/1d OOS coverage gap).

**Schema design:** `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — `alpha_strategy_scores` table + `alpha.scoring.*` APR keys. Full two-gate promotion logic in "Phase Sequencing" section.

**Rewritten 2026-07-19 per todo 056 / reconciliation doc F3 + Open Q2:** v2.x is dead in fact
(`intelligence-pipeline.service` failed since the D-09 cutover, `signal_events`/`trade_frames`
frozen since 2026-06-22) — the old SCORE-04 "v3 vs v2.x counterfactual comparison" has no
comparable v2.x population and never will, and SCORE-05's "retirement" was describing shutting
down a unit that's already failed-dead. **Operator call made 2026-07-19: archive v2.x (not
delete), and decouple its decommission from this phase's proof gates** — cheap cleanup doesn't
need to wait on a statistical gate it has no bearing on. The decommission-in-fact work itself
(archive `src/intelligence/` I1-I7 tree, disable the already-failed systemd unit, archive/rename
the frozen `signal_events`/`trade_frames`/`trade_executions`/`signal_ledger` tables) is tracked
as its own ready-to-execute item, not gated behind Phase 148 — see
`.planning/todos/pending/056-phase146-147-v2x-retirement-stale.md` for the execution scope.

**Goal:** Build the scoring system and run the two independent OOS gates that prove the
intelligence engine works. No live execution — that is v4.0.

**Depends on:** Phase 142A OOS ensemble IC data available + Phase 142B production `alpha_frames`
accumulating ≥ 60 trading days of closed rows. **Both already satisfied** (live-checked
2026-07-22: EIC-04 PASS; `alpha_frames` has 15.6M `closed_max_hold` rows alone spanning
2006-09 to 2026-07, ~4,883 distinct trading days, OOS window since 2025-12-24 well covered).

**Correction 2026-07-22:** this line previously also listed "Phase 147 complete" as a
dependency — stale. SCORE-01/02/03 (below) read only `alpha_frames`/`alpha_ensemble_ic`/
`alpha_strategy_scores`, pure v3.0 tables with zero I7 lineage; the only place Phase 147 ever
connected to this phase was SCORE-04's old "v3 vs v2.x counterfactual comparison," which the
2026-07-19 rewrite already downgraded to "documentation only, not a gate" (see below) — the
"Depends on" line just never got updated to match. **Phase 148 is unblocked today, independent
of Phase 147.** Phase 147 remains worth doing eventually (checking whether the archived I7
plugins hold any signal not already in the v3.0 Feature Factory — "never drop data that could
contain signal"), but it is due-diligence on a dead system, not a gate on live measurement work.

**Two-gate promotion model (non-negotiable):**
Gate 1 and Gate 2 are independent. Failure modes are different. Never conflate.

- **Gate 1 — Signal proof (from Phase 142A):** `alpha_ensemble_ic.ic_ci_lower > 0` at 95% CI on OOS holdout. IC Sharpe stable (walk_forward_stable = true). If Gate 1 fails: signal problem — diagnose ensemble, feature decay, regime labels. Do not look at P&L.
- **Gate 2 — Execution proof (from Phase 142B):** `mean(counterfactual_pnl_r) > 0` at 95% CI on OOS `alpha_frames` (primary variant), per SHADOW-REVIEW.md criteria pre-committed at Phase 142B launch. `corr(alpha_score_decile, mean_pnl_r)` is computed as a diagnostic column in SCORE-01 but is not a gate — it informs whether score decile monotonically tracks P&L. If Gate 2 fails but Gate 1 passes: frame problem — recalibrate stop/target/hold against IC decay curve, not the ensemble.

Both gates are the milestone exit. Gate 1 passing without Gate 2 = real signal, bad execution rules. Gate 2 passing without Gate 1 = overfitted frame on noise. Neither alone is sufficient.

**Requirements:**

**SCORE-01 — AlphaScorer (weekly oneshot, `BaseBatch`):**
Aggregates closed primary `alpha_frames` into `alpha_strategy_scores` by (symbol, tf, regime, alpha_score_decile). Computes: mean `counterfactual_pnl_r`, win rate, Sharpe, max drawdown, bootstrap CI, `ic_alpha_score_corr`. Filters cells with N < `alpha.scoring.min_strategy_n`. Parallelized per (tf, regime) cohort; async batch INSERT.

**SCORE-02 — OOS Gate 1 evaluation (signal proof):**
Queries `alpha_ensemble_ic` for OOS window (bar_ts >= `alpha.validation.oos_start`). Reports: ic_ci_lower, walk_forward_stable, regime coverage. Binary pass/fail written to a `gate_evaluations` audit log with timestamp, gate_id, result, and evidence JSON.

**SCORE-03 — OOS Gate 2 evaluation (execution proof):**
Queries `alpha_strategy_scores` for OOS `alpha_frames`. Reports: mean_pnl_r CI, ic_alpha_score_corr, Sharpe, max drawdown. Binary pass/fail written to `gate_evaluations`. Gate 2 evaluation runs regardless of Gate 1 result — the data is informative even if promotion is blocked.

**SCORE-04 — v2.x comparison (documentation only):** no live comparison is possible — record in
the promotion decision record why no v2.x comparison population exists (pipeline dead since
2026-06-22, see above). Not a gate.

**Plans:** 5 plans across 3 waves (finalized 2026-07-22)

- [ ] 148-01-PLAN.md — Foundation: alpha_strategy_scores + gate_evaluations migration + APR seeds + Wave 0 test scaffolds (Wave 1)
- [ ] 148-02-PLAN.md — SCORE-01 AlphaScorer(BaseBatch) + tests + real-data verify (Wave 2)
- [ ] 148-03-PLAN.md — SCORE-02 OOS Gate 1 signal-proof scorer (Fisher-z, ensemble_alpha OOS) + tests (Wave 2)
- [ ] 148-04-PLAN.md — SCORE-03 OOS Gate 2 execution-proof scorer (champion-only, pooled + regime-stratified, == FRAME-04) + tests (Wave 2)
- [ ] 148-05-PLAN.md — Run both gates once (Gate 1 before Gate 2) + promotion decision record (SCORE-04) (Wave 3)

---

## v3.15 Conditioning & Identity Foundation (Phases 144, 145, 146)

**Added as its own milestone 2026-07-03** (`docs/research/fable-2026-07-03-roadmap-reconciliation.md`
F1) — previously existed only as a milestone-list bullet with "Phases TBD" while its actual
phases (144, and 146 once evidence names it load-bearing) sat physically after Phases 149-151 in
the old "v3.3" section, contradicting the milestone bullet's own stated reason for existing.

**Milestone Goal:** Unify the two live regime systems (per-symbol HMM `regime_writer.py`,
cross-sectional `equity_regime_model.py`) behind clean peer-group routing before PrecedentEngine
is built on top of them. Per `docs/research/intel-precedent-engine.md`: *"this
substrate must not be built on strata suspected of being wrong — retrieval hard-filters on
regime labels, and re-embedding after the fact is prohibitively expensive."* This is a hard
prerequisite for Phase 149, not a parallel hardening track.

**New hard prerequisite, added 2026-07-11: Phase 143.1 (Measurement and Eligibility Integrity)
must complete first.** Phase 144's evidence (regime-conditional IC separation, per todo 026's
Step 1 gate below) needs to be re-measured against a corpus produced by a corrected measurement
pipeline — Phase 143.1 fixes a confirmed Fisher-z CI miscalibration and a confirmed sign-symmetry
bug that excludes all contrarian features from ensemble eligibility, both of which directly
affect the `ic_ci_lower`/`ic_ci_upper` values any regime-separation analysis here would read.
This is a *separate, earlier* `ic_engine` re-run from the one described immediately below for
Phase 144's own batch — not the same pass. See Phase 143.1's entry and
`docs/plans/2026-07-11-ic-quality-and-sign-symmetry-strategy.md` for detail.

**Batched into one `ic_engine` re-run** (topdown D5): Phase 144 (`regime_group`) + todo 026 P3
(empirical vix/breadth threshold calibration — P2b/P2c already shipped 2026-07-06 via Phase 143
Plan 01/LIFECYCLE-00, and P3 itself was split out to standalone todo 092 on 2026-07-09; verified
2026-07-12) + todo 041 (tag exposure-vs-sensitivity taxonomy audit — gates commodity/fx group
enablement) + `docs/research/stratification-dimension-unification.md`'s first substitution test. Phase 146 (Empirical Instrument Tag Calibrator) joins evidence-gated:
if todo 041's audit shows tag calibration is load-bearing for group routing (not merely
descriptive), pull it into this batch; otherwise it trails independently (its own Depends-on
already states no dependency on Phase 149-151).

**Build trigger:** todo 026's Step 1 regime-IC separation decision gate — **already run
2026-07-02**, result asset-class-dependent (SPY's HMM labels separate IC reasonably, TLT's
don't). The pre-committed fallback for weak-separation asset classes (per-asset-class HMM vs.
demote to shadow vs. factor-augmented variant — topdown Open Q4) needs an operator decision at
this milestone's planning, SHADOW-REVIEW-style, before intel-12's substitution test runs.
**Resolved 2026-07-07:** fallback pre-committed as option (b) - demote HMM to shadow per weak
regime_group, stratify on cross-sectional + volatility_pct; (c) pre-registered as the rates
challenger with a defined build trigger. Phase 144 is unblocked for `/gsd-discuss-phase`. Full
reasoning and falsifiers: `docs/research/fable-2026-07-07-phase144-conditioning-decision.md`.

---

### Phase 144: Cross-Sectional Regime Model (`regime_group`) ✅ COMPLETE (2026-07-22)

**Goal:** Replace `market_regimes.asset_class` with `regime_group` — a named peer group with a pluggable regime signal (breadth_vol for equity, curve_credit for rates, commodity/fx signal modules ship disabled). Migration 229 (plan doc's literal "189" is stale). Full design: `docs/plans/2026-07-01-cross-sectional-regime-model.md`.

**Status per 2026-07-01 architecture review** (`docs/research/fable-2026-07-01-v3-architecture-review.md` §4): confirmed live today, not a future risk — corpus symbols (all `fi_*` bonds + GLD/SLV/VNQ, plus IBIT) are excluded from equity breadth by `equity_regime_model.py`'s own filter yet get equity regime labels in IC stratification and ensemble scoring. This phase fixes the `fi_*` bonds via the rates group. Decisions made (first-principles, not re-opened for user input):

- **Unrouted-until-group-enabled symbols (GLD/SLV/VNQ, IBIT):** exclude from regime-stratified IC with loud startup logging of unrouted symbols, NOT the plan's original silent default-to-equity (fixed in the plan doc's `_build_symbol_regime_class` — omits unmatched symbols, raises `AmbiguousRegimeGroupError` on multi-match, never defaults to `"equity"`). Pooled IC still covers them; no data lost. "Silent wrong answers are worse than loud crashes."
- **Crypto lumped into the `fx` group (2026-07-07 decision):** IBIT's `tag_filter` match is `fx` (`docs/plans/2026-07-01-cross-sectional-regime-model.md` fx group now matches `["fx_*", "crypto"]`), not a standalone `crypto` group — N=1 crypto instrument doesn't support its own regime signal module, and both are macro-liquidity-driven, single-symbol-per-exposure assets. IBIT stays unrouted in practice until `fx` is enabled (same blocker as commodity, below); revisit the grouping if the crypto sleeve grows past N=1.
- **Commodity/fx group enablement is blocked** on todo 041 (tag exposure-vs-sensitivity taxonomy audit) — OIH/XLE/XOP carry both `eq_*` and `commodity_energy_*` tags and will raise `AmbiguousRegimeGroupError` the moment `commodity_energy` is enabled. Add this as an explicit dependency edge, not just a scope-note aside.
- Job-1 peer-set purity (OIH/XLE staying in equity breadth despite commodity sensitivity tags) is NOT a blocker — defensible by convention (equity sector funds), revisit only if Phase 146 tag calibration shows material contamination.

**Sequencing:** land Phase 142A's ensemble-IC baseline first (pre-regime_group equity-only strata), then batch this phase with todo 026 P1-P3 into one ic_engine re-run — empirical pre/post comparison over blind trust that the new strata help.

**Plans:** 6/6 plans complete (2026-07-12). **D-05 verdict landed 2026-07-22** — phase now closed.

Sequencing note, for the record: the original blocker (`BLOCKED-ON-143.1-07`, the corpus
rebuild) cleared 2026-07-21 when Phase 143.1 completed. A second, more specific blocker was
found the same day (design doc:
`docs/superpowers/specs/2026-07-21-restore-symbol-hmm-ic-measurement-for-routed-symbols-design.md`):
`ic_engine.py`'s `regime_group` routing (144-05) made cross-sectional labeling *replace*, not
*supplement*, per-symbol HMM (`symbol_hmm`) IC measurement for any routed symbol — `TLT` (routed
to `rates`) had carried zero `symbol_hmm`-scoped `feature_ic_scores` rows since routing went
live, and D-05's F1 falsifier needed those rows to compare against the `rates` cross-sectional
label. Fixed via `alpha.regime.groups` gaining a per-group `dual_write_symbol_hmm` bool (`rates`
only, migration 247), threaded through `ic_engine.py`'s dual-write pass (commits `083b3db6`,
`8695673e`). Live-verified 2026-07-22: a scoped re-run of the 12 `rates`-group symbols produced
6,045 fresh `symbol_hmm` rows for `TLT` (`computed_at` today, not stuck at 2026-07-17); the
existing `cross_sectional` rows and equity symbols (`SPY` checked directly) were confirmed
untouched.

**D-05's real verdict** (`scripts/analysis/phase144_regime_separation_gate.py`, re-run
2026-07-22 against the fresh data — full output was previously `(no rows)`/INCONCLUSIVE, now a
genuine result):

- **F1 NOT triggered on any tf tested (15m/1h/5m):** TLT's per-symbol HMM stays
  deficient/inverted, matching the original 2026-07-02 finding. Default decision (b) —
  demotion — holds. Per-symbol HMM is confirmed not a better Stage-1 conditioning axis than
  cross-sectional for TLT specifically.

- **F2 TRIGGERED for 15m and 5m:** the `rates` cross-sectional label is ALSO deficient
  (spread < 0.01) on those two timeframes — neither conditioning axis currently separates IC
  for `rates` at high frequency. This is the pre-registered build trigger for a
  factor-augmented HMM challenger (option c) — **pending confirmation that `volatility_pct`
  hasn't already separately passed its own substitution gate for `rates`** (not evaluated by
  this script; check that before considering a new model). Not a blocker to closing this
  phase — a real, separate open question, distinct from Phase 144's own scope.

**Two follow-on items filed, not silently dropped:**

- Todo 167 — the same cross-sectional-suppresses-symbol_hmm question was never
  falsifier-tested for the `equity` group (~50+ symbols); this fix's mechanism generalizes
  (one-line APR change) but nobody has built an equity-scoped D-05 equivalent.

- Todo 168 + 169 — 2 of the 12 rates symbols scoped in the verification run (`LQD`, `PFF`)
  got zero fresh rows; root-caused to `feature_vectors.regime` being NULL for 100% of their
  rows (7 symbols corpus-wide have this gap) — a real, pre-existing `regime_writer.py`
  coverage gap, unrelated to this fix. 169 files the missing systemic check (no monitor
  verifies a symbol has ANY regime coverage at all) that let this go undetected for years.

**Recommended trigger, not yet executed — record here rather than let it silently ride
forever:** `alpha.regime.groups`' `rates.dual_write_symbol_hmm=true` was set deliberately as a
temporary shadow-mode measurement while this question was open (see migration 247's own
comment). F1's non-trigger is a real answer for TLT, but this was a scoped 12-symbol
verification run, not a full corpus rebuild — **do not flip `dual_write_symbol_hmm` back to
`false` for `rates` until the next full corpus rebuild reproduces the same F1 non-trigger
result**, confirming the verdict is stable before simplifying back to a single measurement
pass (Musk step 2 — delete once genuinely proven, not on a partial sample).

- [x] 144-01-PLAN.md — Wave 1: migration 229 (asset_class→regime_group + APR seed) + glossary entry
- [x] 144-02-PLAN.md — Wave 1: breadth_vol (causal-rank port) + curve_credit signal modules + _tf_window helper
- [x] 144-03-PLAN.md — Wave 1: commodity_momentum_ts + fx_dollar_carry signal modules (ship disabled)
- [x] 144-04-PLAN.md — Wave 2: REGISTRY + cross_sectional_regime_model.py dispatcher + equity deprecation + pipeline step-4 swap
- [x] 144-05-PLAN.md — Wave 3: ic_engine.py regime_group routing + cross-sectional peer-scoping contamination fix
- [x] 144-06-PLAN.md — Wave 4: acceptance-gate script shipped, correctly BLOCKED-ON-143.1-07 (external precondition, see above)

---

### Phase 145: StratificationDimension Formalization 📋 PLANNED

**Goal:** Write the actual `Protocol`/ABC for the `StratificationDimension` provider contract as
real code, ratify the `concept_registry` row-grain decision (Option A: one row per dimension, vs.
Option B: one row per `(dimension, regime_group)` — both fully specced in
`concept-unified-registry.md`'s Domain Vetting section), and scope which candidate dimensions
(correlation regime, liquidity regime, term structure regime, posterior-weighted soft
stratification) are worth planning next. The natural conclusion of this v3.15 milestone,
registered directly after its trigger phase.

**Depends on:** Phase 144's D-05 empirical verdict — **landed 2026-07-22, this phase is now
unblocked for `/gsd-plan-phase 145`.** The verdict: F1 not triggered (per-symbol HMM stays
deficient for TLT/rates, demotion holds), F2 triggered for 15m/5m (rates cross-sectional also
deficient at high frequency — see Phase 144's section for the full verdict and its
pending-confirmation next step). Per `stratification-dimension-unification.md`'s own stated
build gate, this phase's row-grain decision (Option A vs B) should be informed by this real
result, not planned blind — read Phase 144's verdict in full before starting `/gsd-discuss-phase
145` or `/gsd-plan-phase 145`. Not yet started as of this note.

**Design:**

- Canonical doc: `docs/research/stratification-dimension-unification.md` ("Formalization revival
  note"). Umbrella: `docs/research/stratification-governance-registries.md`.

- Priority context: `.planning/todos/pending/111-stratification-classification.md`,
  `docs/research/intelligence-lifecycle-backlog-matrix.md` (not independently
  scoreable yet — same gate every regime-candidate row on that page already respects).

**Plans:** TBD at `/gsd-plan-phase 145` — not before Phase 144's D-05 verdict lands.

---

### Phase 146: Empirical Instrument Tag Calibrator ✅ COMPLETE 2026-07-17

**Goal:** Replace manually-asserted instrument tags (e.g., `equity_beta`, `rate_sensitive`) with measured OLS factor betas computed nightly. Tags auto-expire when the statistical relationship stops holding. Renaissance demands falsifiable hypotheses.

**Depends on:** Nothing upstream of Phase 141. TAG-01's OLS regression runs on instrument daily returns vs. factor ETF series (`instruments`, `market_data_ohlcv`), not `feature_vectors` — no dependency on Phase 149-151.

**Requirements:**

**TAG-01 — Measured betas (nightly batch, `TagAuditor`):**
8 core factor betas via OLS regression of instrument daily returns vs. factor series: equity_beta (SPY), rate_beta (TLT), gold_beta (GLD), credit_beta (HYG), dollar_beta (DXY), vol_beta (VIX), oil_beta (USO), china_beta (FXI). Gate per tag: bootstrap CI, p-value < 0.05, min_r2 floor. Exponential decay: `effective_weight = weight × exp(-days_since_estimated / half_life_days)` — stale measurements auto-expire.

**TAG-02 — Regime conditioning (Phase 2 extension):**
Initially PK is `(symbol, tag)`. Phase 2 extends to `(symbol, tag, regime)` — different regimes produce different factor exposures (e.g., flight-to-quality regime makes TLT beta unreliable for equity instruments). Phase 2 does not ship in Phase 146 — it ships when IC stratification by tag shows regime-dependent divergence.

**TAG-03 — Discovery gate:**
Tags that are fully computable from the factor vector (all 8 OLS betas) must not exist as permanent human assertions. They are query-time threshold applications on the `instrument_tags` empirical table. Human-only tags (`definitional`, `classification`) remain — but must be annotated as measurement_type='definitional' with owner.

**Plans:** 5/5 plans complete

- [x] 146-01-PLAN.md — Wave 0 taxonomy cleanup: credit_cycle merge (D-03), housing_cycle delete (D-07), spread_leg evidence backfill + contract test (D-09), glossary T7 fix
- [x] 146-02-PLAN.md — Measurement-contract migration 238: revised schema + valid_from/valid_to (D-10), factor-series seeding (D-02/D-04/D-05/D-06/D-08), 7 APR keys
- [x] 146-03-PLAN.md — factor_math.py: standardized OLS loading + HAC SE, long-short constructor, vol proxy adapter (reuses ic_math + breadth_vol)
- [x] 146-04-PLAN.md — TagCalibrator(BaseBatch) generic 3-pass calibration engine + decision-logic tests (TAG-01)
- [x] 146-05-PLAN.md — Phase 2 regime-conditioning design doc (TAG-02, design-only)

---

## v3.2 PrecedentEngine + Feature Expansion (Phases 149-151)

**Milestone Goal (framing corrected 2026-07-03; phase requirement bodies rewritten 2026-07-09, todo 055):** Build the
PrecedentEngine and its precedent predictor family — a second *evidence source*, not a second
*system* (`docs/research/intel-precedent-engine.md`; the prior "independent complement"/"System 2"
framing here violated the one-model-one-book invariant now in `docs/foundation/principles.md`).
Expand the feature set with new primitives and compound interactions. Phases 149-150 (PrecedentEngine
substrate + scoring) are strictly sequential — each gated on the prior — **and both depend on
v3.15 completing first** (Phase 149's Depends-on, below). Phase 151 (primitives + interaction
layer) is a feature-engineering track with no real dependency on 146/147 (see Phase 151
sequencing note) and may run in parallel with, or before, the PrecedentEngine phases, subject only
to its own todo-037 pilot gate. Per the 2026-07-08 backlog matrix (`docs/research/intelligence-lifecycle-backlog-matrix.md`),
146 is nearer-term than 148: 146 is evidence-gated into Phase 144's batched `ic_engine` re-run,
while 148 sits behind Phase 147 completing plus Phase 142B accumulating 60 days of closed
`alpha_frames` — several phases deeper.

**Hard prerequisite:** v3.1 complete + live IC > 0 at 95% CI confirmed on OOS holdout.

---

### Phase 149: PrecedentEngine — Embedding + Retrieval Foundation 📋 PLANNED

**Goal:** Build the non-parametric retrieval substrate. Embed bar states into pgvector HNSW index. Validate retrieval quality before committing to a dimension and building the full corpus. "Have we seen a bar like this before, and what happened next?"

**Depends on:** **v3.15 complete** (Phase 144 `regime_group` live + todo 026 P2b/P2c/P3 resolved) — added 2026-07-03, intel-13's hard prerequisite: retrieval hard-filters on regime labels and re-embedding after the fact is prohibitively expensive. Plus Phase 142A OOS validation showing `ic_ci_lower > 0` at p < 0.05 (see EIC-04 verdict log in Phase 142A's section — not yet passing as of 2026-07-03). PRECEDENT-01..05 read `feature_vectors` only — no dependency on `alpha_events`, `alpha_frames`, or v2.x retirement.

**Requirements:**

**PRECEDENT-01 — Embedding dimension calibration (one-way door):**
Before committing to an embedding dimension, run a calibration study: embed 6 months of `feature_vectors` bars at three candidate dimensions (64, 128, 256) using variance-normalized features (z-score per feature, L2-normalize). Measure retrieval quality: recall@10, mean reciprocal rank, precedent distance distribution on known-outcome bars. Pick the winning dimension. Lock `embedding_version = 1`. This step happens BEFORE any full historical embedding run — changing the dimension after is prohibitively expensive.

**Why not IC-weighted at index time:** IC weights update weekly from the IC engine. Baking them into the HNSW index would require a full re-embedding of the historical corpus (O(N×D)) on every IC recalibration cycle, coupling index freshness to IC engine cadence. The substrate's answer is `candidate_k` oversampling: the retrieval primitive accepts a generous candidate set (default 200) so a future consumer can re-rank to its final K itself, keeping the index simple and any weights always current. IC-weighted re-ranking itself is a deferred capability, not a requirement of this milestone; per `docs/research/intel-precedent-engine.md` Open Question 5, it is not built until plain-cosine precedent predictors have demonstrated IC on their own and re-ranking can be shown to measurably improve it. Keep the embedding stable; nothing in Phases 149-150 encodes IC into vectors or retrieval.

**PRECEDENT-02 — Embedding serialization contract (variance-normalized):**
For each bar: (1) per-feature rolling z-score, point-in-time trailing window, no lookahead; (2) L2-normalize the result. No IC-weight multiplication at index time (see PRECEDENT-01's deferral). Regime and session applied as hard retrieval filters (not encoded in vector); filter labels resolve as `(dimension, label)` pairs per intel-12's label-identity invariant, never a bare label. Stable feature ordering is part of the versioned embedding recipe, the `(feature set, normalization, ordering)` triple, registered as one `concept_registry` row per `embedding_version` (D9; no standalone `embedding_feature_registry` table). The registry domain for embedding recipes gets named at v3.2 planning, `embedding_spec` or a widened `feature` reading, per the anticipated-domain note in `docs/research/concept-unified-registry.md`. `embedding_version` bump on any change to the triple invalidates all stored vectors and forbids cross-version comparison; treat as a database migration (re-embed vs. grow-forward policy is intel-precedent-engine Open Question 6). **Dependency note (2026-07-01 review):** "regime applied as a hard retrieval filter" means PrecedentEngine's retrieval quality directly inherits any bias in the regime labels themselves — same open question as Phase 143's LIFECYCLE-04 (see todo 034/026). If that validation finds the per-symbol HMM labels are empirically fine, no action needed here; if it finds material bias, PRECEDENT-02's regime filter should wait for the corrected labels rather than hard-filtering on known-biased strata — a "have we seen a bar like this before" retrieval is especially sensitive to a wrong stratification since it can silently retrieve precedents from the wrong regime bucket.

**PRECEDENT-03 — bar-embedder (oneshot, nightly):**
Reads `feature_vectors`. Writes to `embeddings` table (entity_type='bar'). Processes in chronological order; skips bars already embedded at current `embedding_version`. HNSW index built/updated after batch.

**PRECEDENT-04 — OOD monitor (first-class output):**
Rolling rate and severity of null/near-null retrievals across queries; nearest-neighbor distance recorded even on null results. A rising OOD rate is a regime-break early warning, often firing before a parametric regime classifier catches the same break; surface it, never hide it. The per-bar nearest-neighbor distance is one fact with three consumers: the `precedent_nn_dist` predictor column (Phase 150), intel-12's `ood_distance` candidate stratification dimension, and this monitor's threshold aggregate. The monitor measures and surfaces, never acts; a consumer decides whether to shrink conviction, widen an interval, or alert research. DAG constraint carried from intel-12: the distance may condition anything downstream but must never feed back into `retrieve()`'s own filter set (retrieval conditioning on its own output is a cycle). APR keys: `precedent.retrieval.max_distance = 0.25` and `precedent.ood.alert_rate_threshold = 0.20` [both initial_estimate placeholders, calibrate from the distance distribution on the first real corpus window].

**PRECEDENT-05 — Null result contract:**
Empty retrieval (`[]`) when no precedents within `max_distance`. This is a named, surfaced event — not a fallback to nearest-available. PrecedentEngine must never silently return the nearest bar when it is out-of-distribution. OOD is information.

**CASE-RESEARCH-01 — Hypothesis backtester script (todo 017):**
Thin research utility built on top of the retrieval primitive. Accepts an arbitrary query feature vector, runs K-NN against `embeddings`, reads empirical outcome distributions from `forward_returns`. Answers "Is this edge real?" with zero new infrastructure. Ships as `scripts/analysis/case_backtest.py` alongside the retrieval primitive in Wave 4 (gated backlog entry: `.planning/todos/deferred/017-non-parametric-hypothesis-backtester.md`).

**Plans:** 4 plans (Wave 1: dimension calibration study; Wave 2: embedding contract + concept_registry registration; Wave 3: bar-embedder + HNSW; Wave 4: OOD monitor + retrieval primitive + hypothesis backtester script)

---

### Phase 150: PrecedentEngine — Case Predictors + Measurement Integration 📋 PLANNED

**Goal:** Turn retrieval into measured predictors. Compute the shared return-distribution primitive and the precedent predictor family from retrieved neighbor sets in a nightly batch, register each output as an ordinary predictor in the shared IC machinery, and let the existing ensemble weight the survivors. One measurement engine, one ensemble, one book (D4, `docs/research/intel-precedent-engine.md`): precedent outputs are a second evidence source entering the same pipeline as every parametric feature, not a second system.

**Depends on:** Phase 149 (embedding substrate live, HNSW populated).

**Key deletion (D4):** the pre-rescope design's parallel measurement stack (`feature_ic_stats`, `similarity_pairs`, `score_cache`, Score Objects, the composite combiner, the `case-enricher` daemon) does not exist in this phase. IC measurement is the shared machinery (`ic_engine` today; the D1 Measurement Engine / `predictor_ic_scores` unification when it lands), redundancy control is the ensemble's existing Ledoit-Wolf cluster deflation, weighting is `ensemble_trainer`. The only new state is the precedent predictor columns (storage grain per PRECEDENT-08) plus their registry rows; nothing here writes to `alpha_events`.

**Requirements:**

**PRECEDENT-06 — Precedent Finder wrapper (`_find_precedents`):**
Thin wrapper exposing the substrate's `retrieve()` as `_find_precedents(k, scope, regime)` on `BaseAIWorker`; the single retrieval entry point every consumer uses (this phase's nightly batch, and later the LLM swarm's episodic memory). No consumer queries pgvector directly. Warm-tier use is read-only over pre-computed state, never a live pgvector query at inference latency.

**PRECEDENT-07 — Return-distribution primitive (computed once per horizon per query):**
Before any scalar is derived, the K retrieved precedents produce a full empirical distribution of forward returns at each canonical gradient horizon, joined from the existing `forward_returns` (`return_type = 'executable_open_to_open'`; `forward_return_writer` remains the sole writer of that fact, no second outcomes table). Percentiles, moments, skew/kurtosis, scenario probabilities, and a shape label (`tight_unimodal`, `bimodal`, `fat_left_tail`, `flat`, `null`). A bare mean hides whether it comes from a tight consensus or a coin flip between two very different outcomes; every derived score in PRECEDENT-08 reads from this distribution. Units are canonical executable open-to-open log returns; the original design's ATR-normalized R-multiples died with v2.x.

**PRECEDENT-08 — Nightly precedent-predictor batch (`BaseBatch` oneshot):**
For each bar with a valid retrieval, computes the single-TF sub-scores as ordinary predictor columns: `precedent_expected_r` (distance-weighted mean forward return), `precedent_hit_rate` (distance-weighted directional hit rate), `precedent_ret_dispersion` / `sharpe_horizon`, `precedent_nn_dist`; plus the conviction envelope as sibling columns (`precedent_count`, `mean_distance`, `regime_purity`, `distribution_shape`, `precedent_novelty`) and the horizon-profile character label (`flat`/`mean_revert`/`scalp`/`structural`/`mixed`). Load-bearing rules: (1) definedness is NULL, never zero, on a null retrieval or when `precedent_count` < `precedent.scoring.min_precedent_count` (default 10, placeholder); imputing 0.0 silently poisons IC downstream, so record per-predictor coverage and let the existing min-obs gates handle the sparsity. (2) `regime_purity` caps conviction (LOW below a purity floor); it is never a score multiplier. (3) The distance-weighting kernel (inverse-distance, Gaussian, or rank-based) is a build-time decision (intel-precedent-engine Open Question 7): pick one, measure calibration, revisit. (4) Storage grain is a schema decision at planning (Open Question 1): columns on `feature_vectors` vs. a sibling `precedent_scores` table keyed `(symbol, tf, bar_ts, embedding_version)`; intel-precedent-engine leans sibling-table for version hygiene. (5) Out of scope by sequencing discipline: cross-TF `alignment_z`/`coherence` (different grain, and defined over first-order precedent predictors that must demonstrate IC first) and IC-weighted candidate re-ranking (PRECEDENT-01's deferral, Open Question 5).

**PRECEDENT-09 — Predictor registration + ensemble entry:**
Each single-TF precedent predictor lands at exactly feature grain, one value per (symbol, tf, bar_ts), and is registered as an ordinary predictor (a `concept_registry` row per D1/D9) into the same IC machinery that measures every parametric feature. No precedent-specific IC factory and no precedent-specific correlation service: the ensemble's existing Ledoit-Wolf `|corr|` cluster deflation already provides redundancy control at the predictor grain, and a third redundancy implementation is precisely the failure mode D4 exists to avoid. Survivors are weighted by `ensemble_trainer` alongside everything else; one combiner, not two. Measurement caveat: precedent IC is conditional on being in-distribution (the predictor only exists on bars that had precedents), a legitimate conditionality that must never be read as unconditional IC; stratifying precedent predictors by `ood_distance` is near-degenerate by construction.

**Plans:** 3 plans (Wave 1: Precedent Finder wrapper + return-distribution primitive; Wave 2: nightly precedent-predictor batch + storage-grain decision; Wave 3: predictor registration + ensemble integration)

---

### Phase 151: Feature Primitives Expansion + Theory-Motivated Interaction Layer 📋 PLANNED

**Goal:** Expand the atomic feature set, screen through IC machinery, promote survivors. Build a Theory-Motivated Interaction Layer of ≤50 curated compound features — not a combinatorial factory. Gated on Feature Registry (todo 008, COMPLETE).

**Note on atomic scope (corrected 2026-07-13, extended 2026-07-24, mislabel fixed 2026-07-24):** todo 014's original ~60-candidate priority-tiered list already shipped via Phase 142.5 (91 primitives, migration 206) — it is `completed/`, not a live source list. Phase 151's remaining scope is (a) todo 066 (cross-TF divergence: `ret_div_1m_5m`/`ret_div_5m_1h`/`ret_div_1h_1d`, deliberately deferred out of 142.5) — **corrected 2026-07-24: this is `tier=1_interaction` (`requires_htf=true`), not atomic; it was miscategorized here, kept in this phase's scope as a sibling interaction item, not part of the atomic-tier count**, (b) the calendar/seasonality atomic candidates below, from todo 104, (c) todo 123's momentum-velocity/VWAP-acceleration/macro-spread atomic trio, and (d) todo 180's 7 atomic candidates (`bars_since_high/low_fast/slow`, `abs_ret_autocorr_1`, `equity_beta_z`, `rate_beta_z`, `bars_since_extreme_move_fast/slow`, `bars_since_52w_high/low`, `bars_since_vol_spike_fast/slow`; Fable-reviewed 2026-07-24, one renamed from `mkt_beta_z` for a glossary naming ban) found surveying the full live atomic set for gaps — none of (a)-(d) have been IC-screened yet. As of 2026-07-24 all four sources have had an independent Fable design review (104: 2026-07-13; 066/123/180: 2026-07-24) — 066 confirmed correct as-is; 123's 4 candidates all reframed (naming/tier fixes, 3 new required APR keys, see todo file); 180's candidates reframed similarly (see todo file). Ready for `/gsd-plan-phase 151` once picked up — no outstanding review debt on the atomic/interaction candidate list itself, only the IC-screening step.

**Wave 1 candidate roster, consolidated (2026-07-24) — final post-Fable-review names, all 4 sources in one place:**

*Tier-0 atomic (28 columns, Wave 1 IC sweep):*

- From todo 104 (calendar, 6): `quarter_cycle_sin/cos`, `tdom_sin/cos`, `minute_of_hour_sin/cos`
- From todo 123 (momentum/macro, 9, all renamed from the todo's original proposal): `momentum_z_velocity_fast/mid/slow`, `vwap_dev_sigma_velocity` (not "acceleration"), `tip_tlt_ret_z`/`hyg_lqd_ret_z` (not "real yield"/"credit spread" — those names asserted a causal referent the formula doesn't compute), `sb_corr_fast/slow/z` (not `sb_corr_30/60` — raw day-counts violated naming-system.md §7). Needs 3 new APR keys: `feature.momentum_velocity.window`, a VWAP delta-window key, `macro.sb_corr.window_fast/slow`, plus a z-score-window key per macro spread.
- From todo 180 (recency/beta, 13, one renamed): `bars_since_high_fast/slow`, `bars_since_low_fast/slow`, `bars_since_52w_high/low`, `abs_ret_autocorr_1`, `equity_beta_z` (renamed from `mkt_beta_z` — glossary bans unqualified `beta`), `rate_beta_z`, `bars_since_extreme_move_fast/slow`, `bars_since_vol_spike_fast/slow`. Needs 2 new APR keys (`feature.bars_since_extreme_move.sigma_threshold`, `feature.bars_since_vol_spike.threshold`).

*Tier-1 interaction (5 candidates, Wave 2's ≤50 cap, not Wave 1):*

- From todo 066 (confirmed correct as designed): `ret_div_1m_5m`, `ret_div_5m_1h`, `ret_div_1h_1d`
- From todo 104 (deliberately NOT atomic — a flag selects a point in a cycle, which is a hypothesis): `opex_flag`, `quad_witching_flag`

All 33 candidates above are Fable-reviewed and naming-audited (todo 104: 2026-07-13; 066/123/180: 2026-07-24) — zero outstanding design-review debt. None have been IC-screened yet; that's Wave 1/Wave 3's job, not done here.

**Evidence base (2026-07-10):** todo 037's pilot ran the partial-IC test this phase's interaction-layer premise depends on — 8 already-live hand-picked interaction primitives measured for incremental IC after controlling for parent atomics. Result: 192/864 cells (22.2%) passed BH-FDR, broad-based across all 8 features. This confirms the atomic feature set is not IC-saturated and interaction effects are real — supporting evidence for building this phase's curated layer, though this phase's own ≤50-feature/theory-motivated design (vs. todo 019's rejected ~30K-candidate combinatorial approach) was already independently justified on BH-FDR statistical-power grounds before this result existed. See `docs/research/intel-feature-interaction-factory.md` and `.planning/todos/completed/037-interaction-primitives-pilot-ic-test.md` for full detail.

**Note (updated 2026-07-03):** the interaction terms this phase validates are one of two
constituent sources for `docs/research/intel-confluence-detection-persistence-layer.md` v3
("Confluence — a Governed Predictor Family," rewritten 2026-07-03; the other source is
`intel-13`'s precedent predictors, formerly "Phase 149's case matches" — see todo 055 for why
Phase 149 itself needs rewriting). Once ≥1 interaction term clears this phase's IC/OOS gates,
confluence's gate 1 (marginal lift over the calibrated additive null) becomes runnable against
it — gated itself on `feature-scoring-beyond-ic.md` §0b/0c landing first (intel-10 v3's hard
prerequisite, not just a nice-to-have).

**Depends on:** Feature Registry shipped (todo 008 — COMPLETE) — ratio operation validity requires feature metadata (sign_type, scale). No dependency on Phase 149/147.

**Why not a combinatorial Interaction Factory:**
~30K compound candidates in a separate BH-FDR pool at FDR=0.05 produces ~1,500 expected false discoveries regardless of pre-screening. BH-FDR was designed for focused hypothesis testing, not combinatorial enumeration — at 30K tests, the correction loses meaningful power-versus-discovery-rate guarantees. Every surviving compound feature would have no stated reason to survive, making it impossible to distinguish genuine signal from leakage. Renaissance does not enumerate pairwise products. They test theory-motivated combinations where the researcher states WHY the compound should predict returns, so the surviving features can be reasoned about and decay patterns explained.

**Theory-Motivated Interaction Layer — design rules:**

- Cap: ≤50 compound interactions defined before any IC measurement begins.
- Every interaction must have a one-sentence finance-theory hypothesis (example: "momentum_z_fast × low_vol_regime — momentum carries more strongly in calm regimes; Frazzini & Pedersen 2014").
- Candidate sources: momentum × volatility regime, volume × trend direction, cross-asset divergence × regime transition, breakout × volume confirmation, mean-reversion × regime label, carry × term structure, `quarter_position` × existing atomic (calendar/OPEX seasonality — see below, todo 104).
- Each compound is a single operation: product, ratio, or conditional. No multi-step compositions — that is a model, not a feature.
- Separate BH-FDR pool from atomics (50 tests at FDR=0.05 has well-understood power vs 30K tests).
- Feature Registry entry required at registration: `tier='1_interaction'`, `parent_features=[atomic1, atomic2]` (**exactly 2, corrected 2026-07-24 during `/gsd-plan-phase 151`** — this line previously said `parent_features=[]`, which contradicts every one of the 8 live `tier=1_interaction` rows, migration 169's own column comment defining `1_interaction` as "deterministic combination of two tier-0 features," and `scripts/ops/alpha/ops_interaction_primitives_pilot.py::_load_interaction_features`, which hard-raises `ValueError` on any other arity; there is also nothing to control for in a partial IC with an empty parent list), hypothesis text in `formula_short`. Auto-deprecation if IC gate not passed within `alpha.feature_registry.demotion_periods` IC runs.

**Calendar primitive candidates (Fable-reviewed 2026-07-13, todo 104 CLOSED, full doctrine, inventory, and test design: `docs/research/signal-temporal-atomic-primitives.md`):**

- **Atomic candidates (tier 0, coordinates only):** `quarter_cycle_sin/cos` (first circular harmonic of `quarter_position`, supersedes the earlier "month-of-quarter sin/cos" idea, which was a coarser quantization of the same period; primary instrument for the within-quarter seasonality hypothesis, well-powered since every bar contributes within-quarter contrast across ~80 quarter-episodes), `tdom_sin/cos` (trading-day-of-month, turn-of-month anomaly, control against `day_of_month_sin/cos`), `minute_of_hour_sin/cos` (round-time execution clustering at 5m/15m).
- **Tier-1 event-flag candidates (NOT atomic, since a binary flag selects a point in a cycle, which is a hypothesis, so it belongs in the interaction pool, not tier 0):** `opex_flag` (monthly, `dow==Friday AND week_of_month==3`, ~240 episodes, marginally powered) and `quad_witching_flag` (`opex_flag AND month mod 3==0`, ~80 episodes, underpowered ~2-5x for documented 5-20bps effect sizes at fixed-alpha; use the 143.1-06 e-process to accrue evidence across future episodes instead of re-testing annually). Splitting monthly from quarterly is the test design: `opex_flag` isolates expiration mechanics (fires every month, orthogonal to quarter phase); `quad_witching_flag` tests whether quarterly amplification adds anything beyond that.
- **Interaction candidate (unchanged):** `quarter_position × <existing atomic>`, theses: dealer gamma-hedging unwind, quarter-end window dressing, earnings-season drift. Reuses todo 037's partial-IC methodology.
- **Methodology split, resolved:** smooth coordinates (`quarter_cycle`, `tdom`, `minute_of_hour`) go through standard `ic_engine` + todo 037 partial-IC, with one mandatory pre-check: the 143.1-01 circular-block bootstrap's block length must be >= the feature's cycle period (a quarter-period feature at 1d needs ~63-trading-day blocks) or aggregate to per-episode means first. Sparse event flags skip IC entirely (Spearman is the wrong instrument on a ~4% sparse binary) and use the SHADOW-REVIEW criterion-2 pattern: episode-clustered BCa bootstrap of flag days vs. matched control days, as a small analysis script.
- **Redundancy finding, separately tracked:** `days_to_month_end` is exactly `1 - month_position` for every timestamp (same mathematical-redundancy class as the migration-211 `new_high_flag`/`new_low_flag` removal); removal filed as todo 115, not done inline here.

**Regime-conditioned cluster membership (extension of Phase 140 P2):**
Phase 140's collinearity clustering is global. Extend to regime-conditioned clusters: one cluster membership table per HMM state. Features uncorrelated in trending may be 0.8 correlated in ranging — global clustering misses this. APR key: `alpha.ensemble.cluster_regime_conditioned = true` [planned].

**Plans:** 9 plans in 7 waves (planned 2026-07-24; revised 2026-07-24 after cross-AI review - `151-09` added, see "Cross-AI review revisions" below). The ROADMAP's original "4 plans" framing described four *work streams*, not four executable plans - the atomic stream alone adds 43 `feature_vectors` columns across 5 files each, which exceeds a single plan's context budget by a wide margin. The four streams survive intact; they are decomposed by feature family and by the `feature_registry` row-count alignment gate (`_REGISTRY_ROW_COUNT = len(dataclasses.fields(FeatureVector))`), which forces each column batch to ship its own migration in the same commit.

Plans:

- [ ] 151-01-PLAN.md — Wave 1: atomics A, 6 calendar coordinates + 4 velocity primitives (migration 259, 2 APR keys)
- [ ] 151-02-PLAN.md — Wave 1: regime-conditioned collinearity clustering, `symbol_hmm` as a second stratification axis (migration 260, 1 APR key)
- [ ] 151-03-PLAN.md — Wave 2: atomics B, 10 `bars_since_*` recency primitives + `abs_ret_autocorr_1` (migration 261, 2 APR keys)
- [ ] 151-04-PLAN.md — Wave 3: atomics C, 2 macro spreads + stock-bond correlation + 2 factor betas (migration 262, 7 APR keys)
- [ ] 151-05-PLAN.md — Wave 4: interaction layer A, the 5 named roster candidates (3 cross-TF divergences + 2 event flags, migration 263)
- [ ] 151-06-PLAN.md — Wave 5: interaction layer B, 10 theory-motivated compounds with stated hypotheses (migration 264, zero APR keys by design)
- [ ] 151-09-PLAN.md - Wave 5: live-path cross-asset fix - shared Ring-1 series builder, live/batch parity assertion, once-per-UTC-day refresh (no migration, added by the cross-AI review pass)
- [ ] 151-07-PLAN.md - Wave 6: corpus recompute (resumable `--recompute` mode with a partition-completion manifest, defeating `ON CONFLICT DO NOTHING`, closes todo 176) + tier-0 atomic IC sweep
- [ ] 151-08-PLAN.md — Wave 7: interaction partial-IC sweep + sparse event-flag BCa bootstrap + registry lifecycle verification (migration 265, 1 APR key)

**Planning-time decisions recorded (2026-07-24):**

- **Interaction cap:** the tier-1 population lands at 23 rows (8 pre-existing + 5 named + 10 designed), inside ROADMAP's ≤50 cap. The cap becomes a machine-enforced invariant via `test_interaction_tier_population_within_cap`, not a prose commitment.
- **RESEARCH Open Q1 (interaction BH-FDR pool):** extend the existing `alpha.ic.partial_fdr_alpha` pool (migration 206, todo 037) rather than mint a third BH-FDR family. The pool-growth effect on todo 037's original 8-feature cohort is quantified in 151-08's report rather than left implicit.
- **RESEARCH Open Q2 (categorical-regime interactions):** resolved by numeric-proxy substitution. `market_regimes`/`feature_vectors.regime` are categorical strings; every "× regime" candidate uses an existing numeric tier-0 proxy (`hv_ratio`, `adx`, `hurst`, `variance_ratio_fast`, `vix_z`, `yield_slope_z`). No compound multiplies a string, and no second stratification surface is opened.
- **RESEARCH Open Q3 (Wave 4 cluster persistence):** no new table. Clustering is already per-(symbol, tf, regime) inside `_compute_one_regime_cell`; the real gap is that the `symbol_hmm` pass only runs for groups with `dual_write_symbol_hmm=true`. A new `alpha.ensemble.cluster_regime_conditioned` APR key widens that gate. ROADMAP's earlier "Phase 140's clustering is global" framing was imprecise and is superseded here.
- **APR namespace correction:** todo 123 proposed `macro.sb_corr.window_fast/slow`. `macro.*` is not a sanctioned namespace in CLAUDE.md; the keys ship under `feature.*`, matching every live sibling (`feature.vix.zscore_window`, `feature.yield_curve.zscore_window`).
- **13 new APR keys total**, superseding the todos' "3 (todo 123) + 2 (todo 180)" estimate — todo 123 additionally requires a z-score-window key per spread, which its own summary count omitted.
- **`ret_div_1m_5m` coverage limit, surfaced not swallowed:** `feature_vectors` has no 1m grain and `market_data_ohlcv_tradeable`'s 1m coverage is 2026-03-23..2026-06-23 versus 5m's 2006-06-02..2026-07-07. The column ships nullable with roughly 1% expected coverage at 5m so the IC screen returns a measured verdict rather than a planner's guess. It is the expected casualty of 151-08's coverage gate; that outcome is to be recorded, not designed around.
- **`quarter_cycle_sin/cos` CI validity:** `alpha.ic.bootstrap_block_size.1d` = 10 versus the feature's ~63-trading-day cycle, so the block-bootstrap CI at 1d is invalid (the point IC estimate is not). Adjudicated in 151-07 with an episode-aggregated companion test; the global key is deliberately NOT raised, which would silently change every other 1d feature's CI.
- **Live-path cross-asset gap found while planning:** `FeatureCache.update_cross_asset()` has no production caller - the live pipeline routes the payload into `CacheManager`, so `vix_z`/`flight_quality`/`yield_slope_z` are frozen at 0.0 on the live path today (same bug class as todo 158). The batch path, which is what IC screening reads, is correct. **Originally filed as a todo rather than fixed inline; that call was overturned by the cross-AI review pass - see below.**

**Cross-AI review revisions (2026-07-24, Codex - `151-REVIEWS.md`):** targeted revision pass, wave structure / migration numbers / candidate roster all unchanged.

- **HIGH, recompute not failure-atomic:** `151-07` Task 1 now builds a partition-completion manifest (`cache/feature_factory_recompute_manifest.json`, atomic tmp+rename, the `state_manager.py:176-178` idiom). `in_progress` is flushed before the DELETE and `complete` only after `rows_inserted == expected_rows`; a mismatch is recorded `failed` and blocks the IC sweep. A resume skips `complete` partitions without re-deleting them. Proven twice - by unit test and by a live kill-and-resume drill with orphan reaping. `backfill_status` was deliberately NOT reused: its `status` column is the FETCH gate `--compute-only` reads as an input.
- **HIGH, live-path cross-asset gap:** fixed in-phase by the new `151-09` (wave 5, ahead of the recompute), not deferred. The review-pass investigation found the harm is sharper than the review's framing: `indicagent-feature-vector-pipeline.service` is `active running` and writes live rows into `feature_vectors` itself - measured 9,183 rows at 5m over 2026-06-23..2026-07-07 across all 80 symbols with `vix_z = flight_quality = yield_slope_z = 0.0`, alongside 139,093 correct batch rows in the same window. Also established: the Kafka route could never have worked (its only producer publishes different fields and its unit is `inactive (dead)`). The fix follows todo 159's `_get_cache()` warm-up precedent and reuses the batch builder verbatim, so live/batch parity is structural rather than aspirational. `151-04` Task 4 now measures the contamination and files only the residual dead-code question (P3).
- **HIGH, operational fragility:** explicit orphan-reap procedure (`ps aux | grep <script>.py | awk '{print $2}' | xargs -r kill`, confirm zero remain), `journalctl -k`-first diagnosis, and "resume, do not restart" recovery steps added to `151-07` Tasks 2/3 and `151-08` Task 2; `151-08` additionally gates on `151-07`'s manifest being fully `complete`.
- **MEDIUM, silent zero-fill:** `151-06` now uses the existing `_guard()` idiom through a counted wrapper that reports substitutions once per `compute_batch()`. Explicit clipping was REJECTED with reasoning on record - it would introduce a tunable constant the plan's own single-operation rule forbids, and `math.isfinite` cannot collapse a large-but-finite value in the first place.
- **MEDIUM, `cluster_regime_conditioned` runtime cost:** `151-02` Task 3 now measures the true-versus-false wall-clock ratio on its scoped run against a rule pre-registered before the number is seen (flip the key `false` above 2.0x - runtime switch, no code change, no migration revert). `151-07` Task 3 reads the resulting key value as a pre-flight.
- **MEDIUM, positional tuple payloads:** `CrossAssetValues` moves to a single Ring-1 definition in `src/intelligence/features/cross_asset_series.py` imported by batch, live, and factory paths; both it and `CtfValues` now carry keyword-only-construction acceptance criteria, so field order can never silently matter.
- **LOW, `151-01` persistence-slice wording:** the contradictory "add a fourth derived slice / leave it to Task 2" paragraph rewritten as an explicit prohibition plus the contiguity requirement Task 2's single slice depends on.
- **Frontmatter correctness found during the pass (not a review finding):** `151-01`/`151-03`/`151-04` all edit `services/feature_vector_pipeline.py` (config wiring at `_prewarm_threshold_config`) but omitted it from `files_modified` - added, since worktree file ownership during parallel execution depends on it.

---

## Deferred / Independently-Gated (Phase 155)

**Corrected 2026-07-03** (`docs/research/fable-2026-07-03-roadmap-reconciliation.md` F1) — this
section was "v3.3 Foundational Hardening," and under the pre-2026-07-04 numbering held the
phases now called 144 (Cross-Sectional Regime Model) and 146 (Tag Calibrator). Those two moved
to the **v3.15 Conditioning & Identity Foundation** section (before v3.2, above) since they are
v3.2's hard prerequisite, not a hardening pass that comes after it.

**ETF Universe Expansion removed as a phase, 2026-07-04** — it was done (migrations 188/190,
58→80 instruments, 2026-07-01; full 4-timeframe OHLCV backfill for all 22 new symbols,
2026-07-04) but still carried a `📋 PLANNED` status and a sequencing note claiming it "waits
until the end-to-end system is proven" — a contradiction of stale status text against actual
state, which is worse than no entry at all. No further phase is needed for it; `regime_group`
routing for these symbols is Phase 144's job, unaffected by this removal.

---

### Phase 155: Alternative Data Vectors 📋 PLANNED

**Goal:** Add new IC-measurable signal sources to the vector-agnostic architecture. Each vector enters at weight=0, earns weight through IC measurement independently, and never blends with price IC until independently validated. Recommended order: Flows first (highest signal/infra delta ratio), then Kalshi as regime conditioning, then Fundamentals.

**Depends on:** per-source ingestion tables + IC engine capable of joining them (two-shape design below; Phase 138 join pattern). No dependency on Phase 146. Each vector gated on its own IC validation before any ensemble weight is assigned.

**Requirements:**

**ALTDATA-01 — Two-shape ingestion, chosen by cadence (updated 2026-07-12, todo 063; supersedes the original single `alt_feature_vectors` table design, rejected by the 2026-07-06 Fable review of `docs/research/data-alt-data-sources.md` — a single grab-bag table has no honest primary key across bar-cadence and event-cadence sources):**

1. **Bar-cadence sources (flows):** dense sibling table per source family, keyed `(symbol, tf, bar_ts)` — e.g. `flow_vectors` — written by its own dedicated `BaseWriter` (one writer per table, DAG invariant 3), joined by `ic_engine` on the bar key exactly as `forward_returns` is today.
2. **Sub-bar-cadence sources (fundamentals snapshots, Kalshi snapshots, materialized qualitative scores):** extend the live `context_features` pattern — long/narrow `(feature_date, feature_name, symbol)` key, `source` check constraint extended, effective-date contract (`published_at`/`received_at` → materialized `effective_ts` = first bar open strictly after both) enforced at write. Event-driven sources keep an immutable raw event table upstream as audit trail; the narrow table is the measurement surface.

Separate IC gate per data source — never blend alt-data IC with price IC until independently validated. **N counts update events, not rows** (quarters for fundamentals, resolution cycles for Kalshi, bars only for genuinely bar-cadence flows) — fill-forwarded rows are not independent observations. Per-source APR gate keys follow the `alpha.ic.min_obs_daily_features` precedent: `alpha.ic.min_obs.flows`, `alpha.ic.min_obs.kalshi`, `alpha.ic.min_obs.fundamental`, `alpha.ic.min_obs.news`. Sources whose per-symbol event count can never clear a sane gate (fundamentals; likely news) are measured **cross-sectionally only**, against the existing POOLED-strata pipeline.

**ALTDATA-02 — V2 Flows (first):**
Options net delta, dark pool %. Same cadence as price, lowest infra delta. Direct IC measurement at 5m/15m TF. Priority: highest among alt-data sources.

**ALTDATA-03 — Kalshi (second, as regime conditioning):**
Prediction market event probabilities. Not return prediction — stratifies existing price IC by macro event probability. Treat as a filter/modifier on regime labels, not a standalone predictor.

**ALTDATA-04 — V8 Fundamentals (later):**
EPS surprises, P/B. Quarterly data → daily TF only via fill-forward join, as-reported values keyed on public release timestamp (never fiscal period end — vendor restatements are routine and using period-end would train on data that did not exist at the bar). **Measured cross-sectionally only, never per-symbol time-series** (updated 2026-07-12, todo 063): 20 years of quarters is ~80 independent observations per symbol — no gate calibration rescues that. Barra-style cross-sectional rank IC across the 80-symbol universe per report season, using the existing POOLED-strata machinery `ensemble_trainer` already trains on.

**Plans:** TBD per vector — plan each vector as its own sub-phase when infra prerequisites are clear.

---

## v4.0 Execution Layer (Phases 156-159)

**Milestone Goal:** Consume `alpha_events` from the intelligence engine and execute live trades through IBKR. Position sizing, risk management, fill model, slippage feedback, and P&L accounting. Strict architectural boundary: the execution layer is a consumer of `alpha_events` — it does not modify, re-score, or re-weight signals. Signal quality improvements belong in the intelligence engine (v3.x).

**Hard prerequisite:** v3.2 complete (**corrected 2026-07-12** — this line previously read "v3.3 complete," a stale reference to a milestone that no longer exists; v3.3's phases were reabsorbed into v3.15 on 2026-07-03, see that section's own note. The milestone list above has always said v3.2). Intelligence engine OOS-validated (`ic_ci_lower > 0` at 95% CI, stable across regimes) — concretely, Phase 148's retirement gate (EIC-04 + FRAME-04) must PASS on the corrected 143.1 corpus, not the pre-fix baseline (FRAME-04 currently fails 16/17 cells on pre-fix data — that number is not yet meaningful). `alpha_events` schema frozen — no breaking changes after v4.0 begins.

**Input contract:** `alpha_events` (direction, alpha_score, ci_lower, ci_upper, regime, tf, bar_ts). The execution layer treats this as an opaque signal — it sizes, routes, and tracks fills. It does not touch feature weights or IC scores.

**Numbered 2026-07-12** (was "Phases TBD" — this milestone's design was already detailed in prose below; converting to real phases per a production-readiness review). **Restructured same day** to split "Portfolio Construction & Risk Management" into two phases after a review caught a real architectural gap: this milestone's own design (Portfolio Kelly, aggregate VaR, correlation-aware sizing, a portfolio-level kill switch) is fundamentally a **portfolio-level** concern, not a per-security one — none of it is computable from any single symbol's `alpha_score`. Every other stateful concept in this system that multiple consumers need (regime, feature lifecycle, config) gets its own persisted, single-writer entity — `market_regimes`, `feature_registry`, `config_state`. The portfolio's own current state (open positions, aggregate exposure, correlation-cluster concentration, capital utilization, drawdown-to-date) had no such home; it was about to be computed inline inside a sizing function instead, which would have silently violated this project's own "one model, one book" principle (`docs/foundation/principles.md`) — that principle names the goal but never had an architectural home until now. Four phases, sequenced: 156 (Portfolio State — the entity) → 157 (Position Sizing & Risk — the first consumer) → 158 (execution, needs 157's position sizes) → 159 (cost calibration, needs 158's real fills to regress against).

### Phase 156: Portfolio State Foundation 📋 PLANNED

**Goal:** Establish "the portfolio" as a first-class, persisted, single-writer entity — not math recomputed inline wherever it's needed. Every downstream consumer (sizing, execution, health monitoring, future risk dashboards) reads this instead of re-deriving it.

**Depends on:** v3.2 complete (milestone hard prerequisite above); `alpha_events` schema frozen.

**Design:**

- `PortfolioStateWriter` (or similar — name per `docs/foundation/naming-system.md`'s role-noun conventions once this gets planned) is the sole writer to a `portfolio_state` table, updated on every fill (from Phase 158 once it exists) and on a regular tick otherwise (open positions don't change every bar, but unrealized P&L and correlation exposure do). Matches this project's existing DAG invariant pattern (`market_regimes`, `feature_registry`): one writer, many readers, compute ≠ persistence.
- **State this entity must carry:** open positions (symbol, size, entry, unrealized P&L, entry regime label); aggregate exposure by correlation cluster (reuses whatever comes out of todo 072/076's crowding and correlation-regime work — a portfolio that's already concentrated in one correlation cluster needs to know that before sizing the next position in it, not after); capital utilization; realized drawdown-to-date; a rolling realized-return series per symbol (the input to Phase 157's covariance estimation, computed here since it's portfolio state, not a sizing-time calculation).
- **Why this has to exist before Phase 157, not be inlined into it:** Phase 153's EnsembleHealthMonitor should gate on portfolio-level health (aggregate drawdown, concentration), not just per-ensemble IC health — it needs a `portfolio_state` to read, the same way it reads `alpha_ensemble_ic`. A kill switch that only sees per-symbol signals cannot detect "we're fine on every individual position but the whole book is one correlated bet" — that is precisely a portfolio-state fact, not a per-security one.
- **Forward-compatibility note (2026-07-12, project-owner direction):** portfolio-level *strategies* (not just risk/sizing overlays on independently-generated per-security signals — e.g. relative-value/pairs construction, cross-sectional long-short books, regime-conditioned portfolio tilts) are an anticipated future direction beyond this milestone's initial scope, not yet designed. `portfolio_state` should be scoped generally enough to be the substrate such strategies would eventually read (the whole book's positions, exposures, and correlation structure in one place) rather than narrowly as "inputs to a risk-management formula." Do not let Phase 157's specific Kelly/VaR consumer narrow this entity's schema prematurely — no new phase is warranted yet, there's no concrete design to phase.

**Plans:** TBD at `/gsd-plan-phase 156` — likely `portfolio_state` schema/migration, `PortfolioStateWriter`, the realized-return series computation, wiring into Phase 153's health gates once both exist.

### Phase 157: Position Sizing & Risk Management 📋 PLANNED

**Goal:** Size positions across the live `alpha_events` book using Portfolio Kelly, reading `portfolio_state` rather than recomputing exposure inline, and enforce the risk ceilings that keep a measurement-layer mistake from becoming a capital loss.

**Depends on:** Phase 156 (`portfolio_state` must exist and be populated).

**Design:**

- Portfolio Kelly using Ledoit-Wolf covariance on the realized daily return series `portfolio_state` maintains (NOT the EnsembleBuilder covariance). This distinction is load-bearing: EnsembleBuilder's LW covariance is estimated in feature-IC space to decorrelate ensemble feature weights. Portfolio Kelly requires covariance in return space. These are different matrices applied to different vectors; conflating them produces wrong position sizes with no error signal. A separate `ReturnCovarianceEstimator` applies LW shrinkage to `portfolio_state`'s return matrix (reusing the same LW machinery as EnsembleBuilder, but on a different input). `weights ∝ Sigma_return^-1 × mu` where `mu` is the vector of `net_expected_r` per open position.
- Single-instrument Kelly (`kelly_fraction × E[R]_net / garch_vol`) applied independently to correlated positions overstates diversification — 58+ equity ETFs all load on common SPY/sector factors, and independent sizing treats them as uncorrelated when they are not. Portfolio Kelly, reading `portfolio_state`'s current correlation-cluster exposure, allocates less to positions that move together *and already have exposure sitting in the book* — a check that's impossible without Phase 156's persisted state. Use **fractional Kelly** (APR-configurable fraction, not full Kelly) — full Kelly is not robust to model uncertainty in the estimated edge, and this system's edge estimates carry real estimation error (see the 143.1 corpus-wide measurement bugs found and fixed this milestone).
- Minimum position notional filter. Max portfolio VaR ceiling (95% historical simulation, computed against `portfolio_state`). Per-symbol drawdown limits. Regime-conditioned position caps (tighter sizing in regimes where `market_regimes`/HMM labels show historically higher realized vol or lower hit rate).
- **Kill switch, designed here even though it triggers via Phase 153's EnsembleHealthMonitor once that lands:** a hard daily-loss circuit breaker (reads `portfolio_state`'s drawdown-to-date) and an anomaly-triggered halt (e.g., realized slippage or drawdown blowing through its calibrated distribution) must exist before any live order routing in Phase 158 — this is not optional infrastructure for a system trading real personal capital.

**Plans:** TBD at `/gsd-plan-phase 157` — likely `ReturnCovarianceEstimator` service, Kelly sizing module, VaR/drawdown/regime-cap risk gates reading `portfolio_state`, kill-switch/circuit-breaker mechanism. **Implementation reference (2026-07-18):** `docs/research/unified-orthogonalization-layer.md`'s Phase 162.3 section (superseded as a phase, math kept as reference) has detailed Ledoit-Wolf effective-N (`N_eff = trace(Σ)/sum(Σ)`), concentration ratio (`λ_max/sum(λ)`), and Kelly-adjusted-for-N_eff (`f* = μ/(σ²·N_eff)`) formulas worth reading before designing this phase's covariance/sizing math from scratch.

### Phase 158: Live Execution Layer 📋 PLANNED

**Goal:** Route sized positions to IBKR and record real fills, with the connection resilience a system trading unattended actually needs.

**Depends on:** Phase 157 (needs real position sizes to route).

**Design:**

- IBKR market order routing at T+1 open. Fill model: `expected_fill = open × (1 + slippage)`. No-fill handler (timeout → cancel + log). `trade_executions` table for actual fills — feeds Phase 156's `PortfolioStateWriter` on every fill.
- **Broker connection resilience (added 2026-07-12 — not in the original prose, and there is no existing concept doc for this at all):** reconnect/resume logic that survives IBC's known 11:59pm nightly auto-restart (already documented as killing in-flight `ib_insync` connections during historical backfills — same failure mode will hit live order sessions unless explicitly handled) and general connection-loss recovery (partial-fill handling across a dropped/reconnected session, idempotent order-state reconciliation on reconnect so a retry can't double-submit). `src/providers/ibkr.py` is the sole `ib_insync` boundary per CLAUDE.md — this resilience layer belongs there, not duplicated per consumer.
- Single point of failure today: this is the first phase in the whole system where a connectivity gap has a direct capital consequence (a missed exit, not just a stale measurement) — design and test the reconnect path before any live capital flows through it, not after an incident.

**Plans:** TBD at `/gsd-plan-phase 158` — likely order routing service, fill/no-fill handling, `trade_executions` writer feeding `portfolio_state`, IBKR reconnect/resilience layer.

### Phase 159: Cost Calibration Feedback Loop + Execution Scoring 📋 PLANNED

**Goal:** Close the loop between predicted and realized execution cost, and keep signal quality and execution quality measured independently so neither can hide behind the other.

**Depends on:** Phase 158 (needs real fills to regress against).

**Design:**

- `ActualSlippageWriter` (daily oneshot) regresses realized slippage vs. expected per (symbol, TF, time_of_day). Updates `alpha.cost.slippage_r` APR key. Closes the loop against the v3-side cost artifacts: the calibrated `alpha.quant.cost_hurdle.*` keys (todo 030, closed in 141.1) and the shared cost kernel + net-of-cost reporting (Phase 142B, canonical-simulator binding rule) — this is where fill-calibrated costs finally replace the externally-calibrated estimates.
- Execution scoring: compare `actual_pnl_r` vs. `counterfactual_pnl_r`. Execution quality measured independently of signal quality — a bad fill shouldn't be blamed on the signal, and a bad signal shouldn't be hidden by a lucky fill.
- Emission thresholds (`alpha_score` floor where `E[R]_net > cost`) are set here, not in the intelligence engine. The intelligence engine emits all signals above a statistical significance gate; this phase decides what to act on based on net expected value after real, calibrated costs.

**Plans:** TBD at `/gsd-plan-phase 159` — likely `ActualSlippageWriter`, execution-vs-counterfactual scoring view, emission-threshold APR wiring.

### Phase 162: ic_engine Corpus Pipeline Throughput ✅ COMPLETE (2026-07-23)

**4/4 plans executed and merged.** The whole-cell fingerprint mechanism works: an empirical
equivalence proof (`ops_ic_fingerprint_equivalence.py`, 5-symbol/1d subset) showed the
fingerprint-skip path producing byte-identical `feature_ic_scores` (9,780 rows) to a forced
`--refresh` recompute, ~31-80x faster (2.0-3.0s vs 163-170s). Post-execution code review found
one real BLOCKER (CR-01): the per-symbol fingerprint watermark for regime-group-routed symbols
was silently scoped to `None` instead of `[symbol]`, permanently defeating staleness detection
for that class of cell — fixed same session (explicit `is_group_pooled` parameter replacing
implicit `pass_type`-string inference), independently re-verified by a separate verifier agent,
no data remediation needed (`ic_cell_fingerprints` was empty in production). Formal verification:
7/7 success criteria (SC-1..SC-7) verified at the mechanism level; 3 (SC-1 full-corpus wall-clock,
SC-2 surgical-invalidation timing, SC-5 thread-count benchmark) need an actual full 80-symbol
corpus run to close empirically — persisted as `162-HUMAN-UAT.md`, not blocking, per every
plan's own SUMMARY explicitly deferring full-scale timing to "the next real corpus pass."

**Refined 2026-07-18 (Fable design pass, pre-`/gsd-discuss-phase`):** below supersedes the
original generic goal text. Source review: `.planning/todos/pending/134-ic-engine-incremental-recompute.md`
(+ 133, 122 in the same directory) against live `services/ic_engine.py`.

**Folded in 2026-07-19 (todos 139/140, filed same day from a `/simplify` pass on `be74f4a1`,
the cross-sectional OOM fix that landed the day before this phase was scoped):** both touch
the exact same two functions 162-02 already plans to rework (`_compute_symbol_tf` /
`_compute_cross_sectional_tf`), so they belong in the same planning pass rather than a
separate later touch of the same 3,600-line file.

- **Todo 140 (P2, stability, not just throughput):** peak memory in both functions is still
  `O(cell_size x n_features x const)`, unbounded — `be74f4a1` and the 2026-07-08 float32 fix
  before it each shrank the constant factor, neither changed the scaling law. A cell ~2x
  today's largest (5m/low_bull, ~599K timestamps) reproduces the identical OOM as the corpus
  grows. The DB fetch side already has the right pattern one stage upstream (`cs_chunk_ts`,
  migration 183, bounds fetch to `O(chunk_rows)`) — that chunking invariant stops at
  assembly; the per-scale rankdata/subsample/bootstrap-CI loop operates on the whole
  assembled cell at once. Fix is either (a) extend chunking into the compute stage
  (stream per-scale work over row-blocks) or (b) an APR-configured hard cap
  (`alpha.ic.max_cell_size`) routing oversized cells through a chunked path. This is the
  third-incident-shaped version of the same bug class — worth closing during 162-02 rather
  than waiting for a fourth OOM as the corpus grows past the next threshold.

- **Todo 139 (P3, maintainability, no known bug today):** the per-scale subsample+rank block
  and the fold-loop rankdata block are now byte-identical in shape across both functions
  (verified numerically identical outputs in `be74f4a1`'s own regression tests), linked only
  by a "see the identical fix in..." comment. Extract shared helpers
  (`_subsample_and_rank(...)`, a fold-loop rank helper) so a third hand-pasted occurrence of
  this bug class can't slip into one sibling and not the other. Natural to do in the same
  pass as 140's chunking rework, not before it — no reason to extract a helper for code
  that's about to be restructured anyway.

- **Todo 129 (P3, resource leak, same worker functions):** the 3 `dsn`-based connections
  inside `_compute_symbol_tf` (x2) and `_compute_cross_sectional_tf` (x1) — the
  `ProcessPoolExecutor`-worker-side connections, distinct from the 6 Settings-based
  main-process connections already fixed via `_short_lived_conn` — are still hand-rolled
  `open -> use` with no `try/finally`, so an exception mid-fetch leaks the connection.
  Extract a shared `@contextmanager def short_lived_conn(dsn: str)` in
  `services/_batch_utils.py` (next to `connect_db_from_url`) and migrate all 3 sites onto it.
  Same functions 162-02 already reworks for fingerprint-check reads — do it in the same pass.

- **Todo 009's Part E, remaining item only (`build_walk_forward_folds`):** the fixed-origin
  expanding-window-with-embargo fold construction is still inline in `_compute_symbol_tf`
  (and duplicated again in `ensemble_ic_engine.py`'s analogous path) — the other two
  functions Part E originally proposed extracting (`compute_ic_for_window`,
  `apply_corpus_fdr`) already shipped in `ic_math.py` via todo 048. Extract this one
  remaining function alongside 139's rank-helper work, since both touch the same fold loop.
  **Not** pulling in the rest of todo 009 (APR sweep across `regime_writer.py`/
  `forward_return_writer.py`/`backfill_feature_factory.py`/`signal_auditor.py`, `BaseBatch`
  promotion + renames for 4 unrelated batch scripts) — that's a separately-scoped
  services-layer cleanup with no shared-file benefit here, not ic_engine throughput.

**Reconciled 2026-07-19 (second Fable pass, folding in todos 139/140/129/009E):** the four
fold-ins above are now placed into the plan breakdown below, which supersedes the placement
suggestions inside the fold-in bullets themselves ("during 162-02"). Three resolutions, plus a
scope check:

- **Todo 140 fork resolved: neither (a) nor (b) as written; chunk along the feature axis, not
  the time axis, in one code path.** The crux is that `rankdata` is relative to the whole
  strided series: ranking a row-block is a *different statistic* than ranking the cell, and an
  exact out-of-core rank (external sort with cross-chunk tie averaging) is new statistical
  machinery with a silent-bias surface, plus chunked variants of every `ic_math.py` pure
  function; option (a) is rejected. Option (b)'s "route oversized cells through a chunked
  path" is rejected in its two-code-path form for the same reason todo 139 exists: two paths
  computing the same statistic is the divergence trap, and the oversized path would be the
  rarely-exercised one. What IS output-invariant is the feature axis: `rankdata(X, axis=0)`
  ranks each feature column independently (verified live, `ic_engine.py:1072`/`1950`), and
  `_vectorized_ic`, the bootstrap CI, and the fold-loop re-rank are per-feature independent
  too. So the fix: the shared helper todo 139 extracts computes rank/IC/CI/fold work in
  feature blocks (`alpha.ic.feature_block_columns`, `[initial_estimate]`), writing into a
  preallocated float32 output. That caps the dominant transient (the float64 `rankdata`
  intermediate, confirmed root cause of the 2026-07-18 OOM per the inline comment at
  `ic_engine.py:1941-1949`) at `O(n_sub × block)` instead of `O(n_sub × n_features)`,
  bit-identical by construction. One RNG trap: bootstrap resample block-start indices must be
  drawn once per scale and reused across feature blocks; drawing inside the block loop would
  reorder RNG consumption and change CI draws. Precompute the index matrix (tiny:
  resamples × n_valid/block_size ints) and the statistic is exactly today's. The remaining
  `O(cell × F)` terms are the float32 base arrays (`X_raw`/`X_nd`, assembly at
  `ic_engine.py:884`/`1870-1893`), ~1.4GB at a 2x cell; linear with a small constant, and the
  view-based strided subsampling already avoids copies. If the synthetic oversized-cell test
  shows base assembly itself breaching budget, the second lever is memmap-backed assembly to
  scratch disk (basic-slice subsampling returns views on a memmap unchanged); contingent,
  measured first, not built preemptively. Finally `alpha.ic.max_cell_rows` (`[rca_analysis]`)
  is a crash-loud ceiling, not a router: an oversized cell fails loudly (error row in the run
  summary, nonzero job status, run continues), never silently switches algorithms.

- **Sequencing resolved: structural work goes first, as a new 162-01, before both the
  benchmark and the fingerprint.** The fingerprint hashes `_checkpoint_content_key()` (source
  bytes): any refactor landing after the fingerprint ships invalidates every fingerprint and
  buys a full 25-30h recompute as the phase's parting gift. Landing 129/139/140/009E before
  the fingerprint exists means the content key is computed once, against final code, with
  zero invalidation events. This confirms todo 139's own note (extract helpers during 140's
  rework, not before it; the memory-bounded implementation lands once inside the shared
  helper and both siblings inherit it) while refuting the fold-in placement "during 162-02":
  structural first, fingerprint after. The todo 133 benchmark also moves after the structural
  pass, so it measures the loop the fingerprint will describe rather than code about to be
  restructured.

- **Todo 129 vs the fingerprint validity check: complementary, no conflict.** The validity
  check runs in `main()` before `worker_args` construction, so a skipped cell never spawns a
  worker and never opens a dsn connection at all; `short_lived_conn(dsn)` governs only cells
  that actually compute (the leak surface shrinks with the skip rate). Fingerprint/watermark
  reads happen main-process via the existing Settings-based `_short_lived_conn`
  (`ic_engine.py:381`), adding zero worker-side connections; the worker read-only/main
  writes-serially invariant is untouched.

- **Scope check:** none of the four fold-ins breach the locked non-goals. 129/139/009E are
  pure structure; 140 is memory layout only, held to bit-identical output by Risk 8 and
  criterion 7; the moment a chunking approach would change rank or bootstrap statistics it is
  out of scope by definition. No scheduler, no 1000-symbol validation.

**Goal:** A re-run of the 80-symbol corpus whose inputs haven't changed completes in minutes, not
25-30 hours. Every compute cell — (symbol × tf) in the per-symbol pass, (regime_group × tf) in
the cross-sectional pass — carries a persisted fingerprint (first-party code content-key + a
computation-affecting APR snapshot + upstream data watermarks) written alongside its
`feature_ic_scores` rows; the compute loop skips fingerprint-valid cells and recomputes exactly
the invalidated subset. A fingerprint mismatch must **replace** stale rows — the current
`ON CONFLICT DO NOTHING` write path (`ic_engine.py:310,316,325`) would otherwise silently discard
a recompute's output and leave stale rows in place. No statistical-methodology change: BH-FDR
still runs over the complete current-window hypothesis family including skipped cells, and a
skipped cell's rows must be provably identical to what recompute would produce. Secondarily,
cross-sectional bootstrap threading stops paying 6-thread dispatch overhead on timeframes that
finish in minutes serially (todo 133 — `ic_engine.py:1943-1949`). Absorbs todo 122 (checkpoint
APR drift) as a special case of the fingerprint. Deliberately **not** part of Phase 143.1's
measurement-correctness sequencing — different axis (throughput, not statistical validity) — see
[[project_prove_edge_before_production_infra]]'s correction note for why this doesn't fall under
the prove-edge-first gate either.

**Recommended plan breakdown (4 plans, sequential waves — for `/gsd-plan-phase 162` to work from,
not binding; supersedes the 2026-07-18 pass's 3-plan breakdown):**

- **162-01 (structural pass: todos 129 + 009E + 139/140):** one refactor wave over the two
  worker functions, internally ordered mechanical-to-structural, each step gated on
  bit-identical `feature_ic_scores` output against the `be74f4a1` regression fixture before
  the next starts: (1) todo 129, `@contextmanager short_lived_conn(dsn)` in
  `services/_batch_utils.py` next to `connect_db_from_url`, migrating the 3 worker-side sites
  (`ic_engine.py` ~821, ~1265, ~1715); (2) todo 009 Part E, `build_walk_forward_folds(n_obs,
  n_folds, embargo_bars)` into `ic_math.py` beside its todo-048 siblings, replacing the 3
  inline copies (~1119, ~1396, ~1979) plus `ensemble_ic_engine.py`'s duplicate, with direct
  unit tests on synthetic fold boundaries; (3) todos 139+140 as one change, extracting
  `_subsample_and_rank(...)` and the fold-loop rank helper with the feature-blocked
  memory-bounded implementation (per the 140 resolution above) inside the shared helper, so
  the fix exists once and both call sites inherit it. Closes with the synthetic
  oversized-cell memory test (criterion 6). APR keys: `alpha.ic.feature_block_columns`,
  `alpha.ic.max_cell_rows`.

- **162-02 (todo 133):** benchmark 15m/1h/1d cross-sectional cells at `max_workers=1` vs `6`
  against the post-162-01 loop, then per-tf dict (mirroring `bootstrap_block_size`) or an
  n-row gate, whichever the data supports; migration + APR keys. Runs after 162-01 so it
  measures the code the fingerprint will describe; both plans edit
  `ICEngineConfig`/`from_apr()` (`ic_engine.py:406-597`), so sequencing still avoids merge
  conflicts on the same 3,600-line file. `max_workers` lands as an operational field in
  162-03's classification: thread count must not change output, which 162-01's precomputed
  resample-index matrix makes explicit rather than incidental.

- **162-03 (todo 134 core, absorbs 122; depends on 162-01):** new `ic_cell_fingerprints` table
  (one row per (symbol|'POOLED', tf, pass_type, training_window_end) — not columns on
  `feature_ic_scores`, which would duplicate the fingerprint ~150x per cell). Fingerprint =
  `_checkpoint_content_key()` (`ic_engine.py:2189-2230`) + a hash of `ICEngineConfig`'s
  computation-affecting fields (needs an explicit computational-vs-operational field
  classification with a crash-loud test so a future field can't silently join neither list) +
  upstream data watermarks (`feature_vectors`, `forward_returns`, `market_regimes` content,
  `instrument_tags`, feature-registry status — see Risk 3 below). Validity check runs in
  `main()` before `worker_args` construction, **replacing** (not layering on) the existing
  fingerprint-blind `existing_keys` skip (`ic_engine.py:3128-3140`) — two competing skip
  mechanisms is a trap, not a feature. `--refresh` (force recompute) and `--dry-run-validity`
  (report skip/compute partition) CLI flags. One new planning decision: because 162-01 is
  equivalence-gated bit-identical, initial fingerprints MAY be seeded against existing
  `feature_ic_scores` rows instead of forcing a full stamp recompute; justified only by that
  gate, and verified by 162-04's harness before the seed is trusted.

- **162-04 (depends on 162-03):** equivalence harness — run a ~5-symbol subset twice (fresh vs.
  fingerprint-skip), assert identical `feature_ic_scores` output; this is the empirical proof the
  fingerprint captures everything, i.e. the direct answer to the 2026-07-12 checkpoint-invalidation
  failure class recurring cross-run instead of intra-run. Also runs the staleness/drift study
  below and seeds its APR tolerance key.

**Staleness threshold (134's flagged open question) — firm recommendation: a fingerprint-valid
cell is never auto-stale.** Data-driven refresh is an explicit act, and the schema already has a
name for it: a new `--training-window-end` (PK-included, required-arg, no-default OOS-holdout
clamp at `ic_engine.py:2954-2961`). Wall-clock staleness is the wrong metric (no relationship to
statistical information added; already covered by the separate `_evaluate_staleness()` **alert**,
`alpha.ic.staleness_alert_days=5`, `ic_engine.py:2908-2924` — keep alerting as alerting, not as an
auto-recompute trigger). The genuinely useful future behavior — carry a cell's prior result
forward across a window-end bump when only a tiny fraction of bars are new (e.g. a week of new 5m
bars is <0.5% of a ~469K-observation cell, IC movement from that is far inside the 2000-resample
bootstrap CI width) — is a real lever but an **empirical question**: 162-04's drift study computes
IC at T and T+{1,5,10,20} trading days across a stratified cell sample, plots |ΔIC| vs.
fraction-of-new-bars, and sets `alpha.ic.refresh_min_new_fraction` where median |ΔIC| crosses
~10% of the bootstrap CI half-width — **seeded via migration at 0 (disabled) until the study
justifies a nonzero value**, provenance `[rca_analysis]`. Separately: non-bar data changes
(HMM relabel, a `forward_returns` correction) invalidate via the fingerprint's watermarks
regardless of bar-count — that's an input change, not an information-accrual tolerance; don't
conflate the two.

**Success criteria (measurable, for verification once planned):**

1. No-op re-run (unchanged code/APR/data, same window end, full universe): 100% cells skipped,
   wall clock <30min vs. 25-30h today.

2. Surgical invalidation: perturbing 1 symbol recomputes only that symbol's cells, <4h.
3. Drift detection is exact: computational APR key change invalidates all dependents; operational
   key change invalidates zero; unclassified `ICEngineConfig` field fails the classification test
   loudly. Mid-run APR change invalidates in-flight checkpoints (closes todo 122).

4. Equivalence: skip-path run's `feature_ic_scores` content identical to forced `--refresh`
   recompute (incl. post-backfill `bh_adjusted_p`/`passes_fdr`).

5. Todo 133: 15m/1h/1d cross-sectional cells run within ~10% of measured serial wall time; 5m
   keeps its threading speedup.

6. Todo 140: peak transient memory in `_compute_symbol_tf`/`_compute_cross_sectional_tf` no
   longer scales with `n_features` (feature-blocked rank/IC/CI/fold work) — a synthetic cell
   ~2x today's largest (5m/low_bull, ~599K timestamps) completes within a measured
   resident-memory budget, verified by a synthetic oversized-cell test, not just headroom
   math, AND produces bit-identical output to the unblocked path on a reference cell. A cell
   above `alpha.ic.max_cell_rows` fails loudly, never routes to an alternate algorithm.

7. Structural-pass equivalence (162-01): post-refactor `feature_ic_scores` bit-identical to
   pre-refactor on the regression fixture after each of the three internal steps;
   `build_walk_forward_folds` unit-tested against the inline copies' boundaries; an injected
   worker exception no longer leaks a connection (todo 129, tested, not eyeballed).

**Risks / scope traps to hold the line on during planning:**

1. **`ON CONFLICT DO NOTHING` silently discards recomputes** (confirmed live at 3 insert sites) —
   the single most dangerous interaction in this phase; invalidation must DELETE-then-insert or
   upsert atomically, never rely on the existing insert path.

2. **BH-FDR family coherence** — `_backfill_bh_fdr` (`ic_engine.py:2358`) must run over all rows
   at the current window end, skipped and fresh alike, or adjusted p-values/`passes_fdr` shift
   under skipped cells' feet. Same check needed for the lifecycle hook and the e-value pilot.

3. **Fingerprint completeness is the 2026-07-12 failure class, cross-run instead of intra-run** —
   a "skip" that serves stale IC into `ensemble_trainer` → `alpha_publisher` is worse than the 25h
   it saves. Defense in depth: watermarks + field-classification test + 162-04's equivalence
   harness, not any single one alone.

4. **Delete the `.pkl` checkpoint system if it's now redundant** — once cross-run skip +
   immediate per-symbol DB writes (todo 130) both exist, evaluate whether `_load_checkpoint`/
   `_save_checkpoint` still earns its keep (Musk step 2, delete before optimize).

5. **Resource contention, not design dependency** — no benchmarking (162-02), no synthetic
   oversized-cell memory runs (162-01's closing gate deliberately allocates multi-GB and can
   OOM a live run), and no pilot corpus runs (162-04) while any `ic_engine` corpus run is in
   flight; `ps aux | grep ic_engine` first. Pure code edits and ordinary unit tests are exempt.

6. **Scope trap: do not build a scheduler.** Incremental recompute is the precondition for a
   cadence, not the cadence itself. All project timers are deliberately disabled
   (CLAUDE.md — verify current state before assuming); "don't automate what isn't proven" applies.
   Also out of scope: 1000-symbol validation, any change to the bootstrap statistics themselves.

7. **Refactor stack-up on the two hottest functions** — four todos land on
   `_compute_symbol_tf`/`_compute_cross_sectional_tf` in one plan. Mitigation is 162-01's
   internal ordering (mechanical → pure-function extraction → helper + memory rework), the
   bit-identical regression gate after each step, and never mixing a behavioral change into a
   structural commit; a step that can't prove bit-identity stops the wave, it doesn't proceed
   on "looks right."

8. **Time-axis chunked ranking is a statistics change, full stop** — ranks are relative to the
   whole strided series, so `rankdata` over a row-block is a different estimator than
   `rankdata` over the cell. Any chunking must be along the feature axis (output-invariant),
   with bootstrap resample block-start indices precomputed once per scale so RNG consumption
   order is unchanged across feature blocks. Anything else silently violates this phase's own
   "no statistical-methodology change" line — the exact hidden-bias failure this project's
   design questions exist to catch.

**Requirements**: No formal REQUIREMENTS.md IDs in this project. Acceptance bar is the 7 numbered
success criteria above, referenced in plans as SC-1..SC-7 (SC-6/SC-7 -> 162-01; SC-5 -> 162-02;
SC-1/SC-2/SC-3 -> 162-03; SC-1/SC-4 -> 162-04).
**Depends on:** None as a phase dependency. Practical-only constraint: don't start execution
until any in-flight `ic_engine` corpus run finishes — same `ic_engine.py` file, same 8 workers,
real resource contention, not a design dependency. Check `ps aux | grep ic_engine` /
[Corpus pipeline state](project_corpus_pipeline_state.md) before starting. Planning also assumes
the concurrent symbol_hmm-restoration work reserves migration 247; this phase's migrations start
at 248.
**Plans:** 4/4 plans complete

Plans:

- [x] 162-01-PLAN.md — Structural pass (todos 129 + 009E + 139/140): short_lived_conn(dsn), build_walk_forward_folds, _compute_one_cross_sectional_cell extraction + shared feature-blocked _subsample_and_rank memory bound; migration 248 (feature_block_columns, max_cell_rows)
- [x] 162-02-PLAN.md — Todo 133: cross_sectional_bootstrap_threads scalar -> per-tf dict; migration 249 (4 flat per-tf keys)
- [x] 162-03-PLAN.md — Todo 134 core (absorbs 122): ic_cell_fingerprints table (migration 250), computational-vs-operational field classification, per-table watermarks catching in-place mutation, fingerprint validity check replacing existing_keys skip, DELETE-then-insert invalidation, --refresh/--dry-run-validity, delete .pkl checkpoint system
- [x] 162-04-PLAN.md — Equivalence harness (fresh vs fingerprint-skip, incl bh_adjusted_p/passes_fdr) + drift study; migration 251 (refresh_min_new_fraction=0 disabled); staleness stays alert-only

### Phase 163: VP/SR Structural Primitives ✅ COMPLETE (2026-07-24, verification 15/15 must-haves)

**Goal:** Implement real computation for the 4 permanently-null structural features
(`poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist`) — closes todo 153. Session-
anchored volume-weighted POC/value-area (new `FeatureCache.update_session_vp()` mutator,
mirroring `update_wk_vwap()`'s session-boundary-reset pattern) + rolling-window
pivot-clustering support/resistance (stateless, inline in `compute()`/`compute_batch()`, reusing
the already-live `find_peaks`/`find_troughs` utils). New `feature.session_vp.*` / `feature.sr.*`
APR keys per migrate-as-you-go.

**Do NOT literally port** the archived `i3_structure/market_profile.py` (unbounded-accumulator
bug in its incremental path, uses TPO touch-count instead of real traded volume) or
`support_resistance.py` as-is — reimplement per Fable's 2026-07-20 analysis (full findings:
this phase's discussion context / conversation history). The "requires I3 intraday injection"
comments in `feature_factory.py`/`schemas.py` blocking batch computation are themselves wrong —
neither archived plugin needs anything beyond OHLCV, already available via
`market_data_ohlcv_tradeable` in both live and backfill paths.

**Promotion bar:** run through the todo 037/038-style incremental-IC lens (partial IC
controlling for parent atomics), not just standalone IC>0 — `vwap_dev_sigma`,
`bb_pct_b_fast/slow`, `price_percentile_fast/slow`, and `dist_from_high/low_fast/slow` already
occupy this feature's conceptual neighborhood (distance-to-level / position-in-band), so the
open question is specifically incremental contribution, not novelty from scratch.

**Depends on:** Feature Registry (todo 008, COMPLETE). No dependency on Phase 149/147/162 —
sibling atomic-expansion item to Phase 151's atomic scope (todo 066, todo 104), not folded into
151's interaction-layer waves.
**Requirements**: Closes todo 153 (no formal REQUIREMENTS.md IDs); governed by decisions D-01..D-16 in 163-CONTEXT.md.
**Plans:** 3/3 plans complete

Plans:

- [x] 163-01-PLAN.md — Structural data contract (migration 243: 17 new columns — 12 VP ATR-normalized + 5 S/R strength/age/count, D-19 — + feature_registry rows + APR keys) + FeatureCache.update_session_vp() mutator
- [x] 163-02-PLAN.md — Wire session-VP into live+batch compute paths, derive 14 VP outputs (2 original + 12 new), remove stale I3 None-branch, regression test
- [x] 163-03-PLAN.md — Stateless inline pivot-clustering S/R: ATR-unit sr_support_dist/sr_resist_dist plus resistance_strength/support_strength/resistance_age_bars/support_age_bars/sr_level_count from the same clustering pass (D-19), D-05 docstring cleanup, regression test

### Phase 164: SMC Institutional Footprint Primitives ✅ COMPLETE (2026-07-28, 4/4 plans)

**Goal:** Port the archived v2.x Smart Money Concepts (SMC) plugins
(`src/intelligence/archive/smc_context/`) into v3 as atomic distance/strength/duration/count
primitives — the "institutional accumulation/distribution" family: order blocks, fair value
gaps, liquidity sweeps, liquidity pools (buy-side/sell-side), supply/demand zones, AMD
(accumulation-manipulation-distribution) cycle, breaker/mitigation blocks, BOS/CHoCH structural
shifts. All ~10 plugins are self-contained (OHLCV + ATR only), built on the same already-live
shared utilities (`find_peaks`/`find_troughs`, `clamp`, `linear_ramp`, `freshness_decay` in
`src/intelligence/utils.py`) — no cross-plugin dependency chain, ~2,484 lines total across
90-280 line files. Comparable in scope to one Phase 142.5-style multi-plan wave.

**Candidate atomic primitives per concept** (full detail: this phase's RESEARCH.md/CONTEXT.md
once planned):

- Order Blocks: `ob_dist_atr` (directional, nearest bullish/bearish), `ob_strength`,
  `ob_mitigated` flag

- Fair Value Gap: `fvg_dist_atr`, `fvg_size_atr`, `fvg_open_count`
- Liquidity Sweeps: `sweep_strength`, `reclaim_velocity`, bars-since-last-sweep
- Liquidity Pools: `bsl_dist_atr`/`ssl_dist_atr`, `bsl_touches`/`ssl_touches` (touch-count =
  level significance), `pool_count`

- Supply/Demand Zones: `demand_dist_atr`/`supply_dist_atr`, `demand_freshness`/`supply_freshness`
  (zone age/decay — a genuinely new dimension beyond plain distance), zone-active counts

- AMD Cycle: `amd_phase` (ordinal-encode), `manip_strength`, `amd_manipulation_detected` flag
- Breaker/Mitigation Blocks: `breaker_dist_atr`, `breaker_block_active`, `ob_mitigation_pct`
  (level erosion, distinct from distance)

- BOS/CHoCH: `bos_strength`/`choch_strength` (already ATR-normalized break magnitude),
  direction flags, bars-since-last-shift

**Explicitly excluded:**

- `premium_discount` — likely redundant with existing `va_position`/`bb_pct_b`/
  `price_percentile` position-in-band features (same overlap concern as Phase 163's D-07); test
  for redundancy before investing, if ever.

- `archive/smc_context/hmm_regime.py` — v3 already has its own live per-symbol HMM regime system;
  this archived one is a v2.x duplicate, not a gap.

- `ict_killzones` — already ported; v3's `in_london_kz`/`in_overlap`/`power_hour` (calendar
  domain) are the same concept under different names.

- `bocpd_changepoint.py` (Bayesian online change-point detection) — a real, separate statistical
  primitive, but not an "institutional accumulation/distribution" concept; out of this phase's
  scope, worth its own consideration later if wanted.

**Promotion-bar risk (carries forward from Phase 163's D-07):** this phase adds ~15-20 more
"distance to a level" columns on top of the breakout-distance/VWAP-dev/BB%B family and Phase
163's POC/S-R work. Run one shared collinearity/incremental-IC sweep across the whole
distance-to-level feature family once these exist (todo 038-style), not per-feature isolated
evaluation — the redundancy risk compounds with each additional "distance to X" column.

**Raw-price warning (Fable 5's 2026-07-20 review of Phase 163, applies here too):** every one of
these SMC plugins pairs a raw price/level field with an already-computed ATR-distance or
percentage companion in the same output set — e.g. `order_blocks.py`'s `ob_top`/`ob_bottom` (raw)
alongside nothing normalized directly, but `liquidity_pools.py`'s `bsl_level`/`ssl_level` (raw)
alongside `bsl_dist_atr`/`ssl_dist_atr` (normalized), `supply_demand_zones.py`'s
`nearest_demand_high/low`/`nearest_supply_high/low` (raw) alongside `demand_dist_atr`/
`supply_dist_atr` (normalized), `breaker_blocks.py`'s `breaker_block_top`/`bottom` (raw) alongside
`breaker_dist_atr` (normalized), `bos_choch.py`'s `bos_level` (raw, no normalized companion —
needs one derived), `fair_value_gap.py`'s `fvg_top`/`fvg_bottom`/`fvg_midpoint` (raw, `fvg_size_pct`
needs ATR conversion same as S/R's `_dist_pct` fields did in Phase 163). **Only the ATR-distance/
percentage companion is ever a valid `FeatureVector` column — never persist `_top`/`_bottom`/
`_level` fields directly**, the same mistake Phase 163's original VP scoping made and had to
correct (see that phase's CONTEXT.md D-16/D-17). The candidate list above already reflects this
(it lists `ob_dist_atr` not `ob_top`/`ob_bottom`, etc.) — this note exists so the pattern is
explicit before `/gsd-plan-phase 164` runs, not rediscovered from scratch mid-implementation.

**Depends on:** Phase 163 (VP/SR Structural Primitives) for shared conventions (ATR-distance
normalization pattern, APR namespace precedent, incremental-IC promotion methodology) — not a
hard code dependency, sequencing preference only.
**Requirements**: No formal REQUIREMENTS.md IDs (none exist for this project — per Phase 163
precedent); governed by derived REQ-164-01..09 (order blocks, breaker/mitigation, FVG, sweeps,
pools, zones, BOS/CHoCH, AMD, data contract) — see `164-01-PLAN.md`'s source-coverage audit.
**Plans:** 4/4 plans complete
parallelism possible; this is one compute-path port). Migration 259 re-verify-at-execution flagged
(RESEARCH Open Q3; resolved as migration 266 at execution time, see 164-01-SUMMARY.md).
Historical `feature_vectors` backfill deliberately deferred to the consolidated 163/164/165 pass
(todo 176); shared collinearity/incremental-IC sweep is a phase-exit follow-up, not a task.

Plans:

**Wave 1**

- [x] 164-01-PLAN.md — Data contract: migration 259 (36 SMC columns + feature_registry + feature.smc.* APR keys) + FeatureVector/domain/persistence slice + FeatureFactoryConfig wiring + FeatureCache.update_overnight_range() mutator [wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 164-02-PLAN.md — Order blocks + stateless breaker/mitigation (hard OB dependency chain) compute + test_smc_order_blocks.py [wave 2]

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 164-03-PLAN.md — FVG + liquidity sweeps + liquidity pools (PWH/PWL/PDH/PDL descoped) compute + test_smc_fvg.py/test_smc_liquidity.py [wave 3]

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 164-04-PLAN.md — Supply/demand zones + BOS/CHoCH + AMD cycle (clamp/ordinal) + overnight-range call-site wiring + test_smc_zones.py/test_smc_structure.py/test_smc_amd_cycle.py [wave 4]

---

### Phase 165: Swing/Fib/Trend Structure Primitives 🔄 IN PROGRESS (5 plans, 5 waves, 2026-07-28)

**Goal:** Port 5 of the 6 remaining `src/intelligence/features/i3_structure/` plugins Phase 163
didn't cover — `swing_detector.py`, `swing_momentum.py`, `trend_structure.py`,
`fibonacci_zones.py`, `session_levels.py` — into real v3 `FeatureVector` primitives. Found during
a 2026-07-20 follow-up survey of the rest of `i3_structure/`; Fable-verified same day (full detail:
this phase's `165-CONTEXT.md`/`165-RESEARCH.md`, don't duplicate here). Also the candidate-source
constellation (`fibonacci_zones`, `swing_detector`) that `ctx_SRConsensus` depends on (Phase 163's
D-14 deferred that richer S/R system "until Phase 164's SMC atomics exist" — this phase is the
other missing link in that chain, alongside Phase 164).

**Final scope (41 new columns):** 25 from 4 direct-port files (`swing_detector` 7,
`swing_momentum` 8 — incl. `swing_volume_confirmation`, a free column off computation already
happening, D-15, `trend_structure` 6, `fibonacci_zones` 4) + 16 from `session_levels.py` (incl.
`gap_filled`, D-13) (built as its own plan within this phase, not a separate phase — real
session-boundary rewrite, not a literal port, but every primitive it needs already exists from
Phase 163). Two real correctness bugs fixed during port, not carried forward: `trend_structure.py`
and `swing_detector.py` both manufacture plausible-looking numeric defaults (`trend_direction=0.0`,
`price_position=0.5`) instead of nulling out on insufficient data — the identical failure shape
to the bug Phase 163 was built to fix (todo 153). `macd_events.py` (no MACD indicator exists in
v3 today, confirmed), `bocpd_changepoint.py` (real, distinct regime-detection paradigm, but needs
a standalone latency benchmark first — ~77ms p95/bar at scale), and Fibonacci extension levels
(D-14 — deferred until the base 4 fib fields clear an incremental-IC test, not built speculatively
alongside them) stay parked/deferred, not built.

**Depends on:** Phase 163 (VP/SR Structural Primitives) for shared conventions (ATR-distance
normalization, APR namespace precedent, `FeatureCache` session-boundary mutator pattern for
`session_levels.py`) — not a hard code dependency.
**Requirements**: no formal `REQUIREMENTS.md` exists for this project — `165-CONTEXT.md`'s
D-01..D-15 decision IDs are the requirement set, carried verbatim in each plan's `requirements`
frontmatter (same convention as Phases 163/164/166).
**Plans:** 2/5 plans executed. 5 plans, 5 waves (sequential — every plan touches `feature_factory.py`, so file ownership
forces one wave per plan; Plan 03 additionally consumes Plan 02's in-memory swing intermediates per
D-05, and Plan 05 consumes Plan 04's `FeatureCache` state).

Plans:

- [x] 165-01-PLAN.md — Data contract: migration 267 (41 columns + 41 `feature_registry` rows + 17 APR
  keys), `FeatureVector`/`FEATURE_VECTOR_DOMAIN`/`FeatureFactoryConfig`/persistence wiring, both config
  build sites, and the test-suite count blast radius
- [x] 165-02-PLAN.md — `swing_detector.py` (7) + `trend_structure.py` (6) = 13 columns off one shared
  APR-backed `find_peaks`/`find_troughs` pass; D-01's all-`None` fallback replaces both files'
  fake-numeric defaults; exports the raw swing high/low intermediates Plan 03 consumes. Mutation-verified
  (commit `a748d13d` discipline) 2026-07-28.
- [ ] 165-03-PLAN.md — `swing_momentum.py` (8, incl. D-15's `swing_volume_confirmation`) +
  `fibonacci_zones.py` (4) = 12 columns; deletes the cross-plugin fallback outright (D-05), fixes two
  archived implementation-vs-docstring bugs, and removes the provably-cancelling ATR divisor
- [ ] 165-04-PLAN.md — `FeatureCache` session-levels state layer: 22 new fields,
  `update_session_levels()` timestamp mutator (retires `_SESSION_BARS`/`_WEEK_BARS`/`_OVERNIGHT_BARS`,
  D-07/D-08), `update_wk_vwap()` ISO-week high/low/close extension (D-09), all 3 call sites wired
- [ ] 165-05-PLAN.md — `_derive_session_levels()`: the final 16 columns as ATR-distances/percents/flag,
  prior-completed-week pivot anchoring, `tf=='1d'` suppression of the 5 intraday-only fields, plus the
  phase-closing gate proving all 41 columns produce real values

### Phase 166: Frame/Execution Recalibration ✅ COMPLETE (2026-07-23) — VERDICT: neither candidate promoted (6 plans, 4 waves)

**Goal:** Diagnose why Phase 148's Gate 2 (execution proof) failed and determine whether
stop/target/hold recalibration against the IC decay curve can turn the OOS-proven signal
(Gate 1 PASS) into profitable OOS P&L. Per ROADMAP's own Phase 148 design, this is the
pre-registered "frame problem" playbook — Gate 1 passing + Gate 2 failing means recalibrate
the frame, not the ensemble. Full origin and scope: [todo 174](../todos/completed/174-gate2-execution-failure-frame-recalibration-investigation.md) (promoted to this phase 2026-07-23).

**Not gated on 165** — sequenced after it only because 165 was the last-registered phase at
filing time, not because of a real dependency. Can be discussed/planned independently.

**Requirements**: CONTEXT.md decisions D-01 (a-d), D-02, D-03, D-04, D-05, D-06 (no formal REQ-IDs for this phase)
**Depends on:** Phase 148 (complete — this is its direct follow-on). Phase 163 execution is a runtime prerequisite for the structural candidate (Plan 166-06 structural arm).
**Plans:** 6/6 plans complete

Plans:
**Wave 1**

- [x] 166-01-PLAN.md — migration 253 (alpha.frame.* APR keys) + read-only diagnosis (D-01a) + Phase 163 prereq gate [wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 166-02-PLAN.md — scalar candidate: _calibrate_stop_target() per-(regime,tf), CR-02 gated, uncensored-subpopulation selection (D-01b) [wave 2]
- [x] 166-03-PLAN.md — structural candidate Part 1: structural_confluence.py port of zone_engine's confluence core, Phase-163 fields only (D-01c, D-06) [wave 2]
- [x] 166-04-PLAN.md — validation gate script gate166_*, new gate_ids, frozen five criteria + regime companion (D-01d, D-04, D-05) [wave 2]

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 166-05-PLAN.md — wire both candidates into AlphaFrameWriter via geometry_source dispatch (D-01b/c, D-03) [wave 3]

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 166-06-PLAN.md — calibrate/regenerate/simulate/score all arms one-shot, verdict doc, Part 2 follow-on todo (D-01, D-03, D-04, D-05, D-06) [wave 4]

### Phase 167: Cross-Sectional Trade Construction (T3) ✅ COMPLETE (2026-07-27) -- both live Validation Gates PASSED (6 plans, 5 waves)

**Goal:** Build the cross-sectional long-short construction `docs/research/trade-construction-layer.md`
designs (v1: rank the equity universe by a feature at each bar, long the top decile / short
the bottom decile, dollar-neutral) plus its shadow measurement — turning Edge Source Thesis's
T3 from a validated finding into a real, cost-aware, monitored construction.

**Why this phase exists (added 2026-07-26):** T2 (regime-conditional persistence) was
falsified 2026-07-24 (todo 179's 234-cell sweep — see caveat below). T3 was tested as a cheap
falsification script before committing to Phase 164/165's feature-expansion effort and
**passed decisively at both lookahead scales**
(`scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py`, `ctf_momentum`,
equity/15m: fast mean spread 5.9bp/bar `ci_lower`=5.6bp, slow mean spread 11.1bp/bar
`ci_lower`=9.7bp, both clearing a shuffled-ranking-null guard at `P(null>=observed)=0.0000`).
This is the first thesis anywhere in the edge-source-thesis tree to clear its own
pre-registered bar convincingly. Full result: `docs/research/data-edge-source-thesis.md`'s T3
section.

**Caveat resolved 2026-07-27, kept for record:** T2's falsification ran under cross-sectional
regime labels later found miscalibrated and fixed the same day (todo 092) — its "dead" verdict
was provisional pending a full re-run through the corrected pipeline. Todo 183's recompute
completed 2026-07-27T21:55 UTC; todo 179's sweep was re-run the same day directly against the
live, corrected `market_regimes.regime_label` — 270 cells tested, 108 adequately covered, zero
pass. **T2 is now confirmed dead, no longer provisional.** T3's result was always independent of
this caveat (it reads `feature_vectors`/`forward_returns` directly, no regime dependency) and is
unaffected either way.

**Design (v1, per `docs/research/trade-construction-layer.md` — read that doc for full detail,
not duplicated here):**

- Equal-weight top/bottom decile legs, dollar-neutral, no vol-scaling/Kelly/risk model — this
  doc's deliberately minimal first cut.

- **First open item, before scoping plans:** apply the todo 030 cost-hurdle treatment to the
  spread construction specifically — a long-short spread's cost dynamics differ from a
  directional trade's (this doc's own point), and today's T3 result is gross-only.

- Construction + shadow measurement is queries and a batch service, not new infrastructure — it
  reads `alpha_events`/`feature_vectors`/`forward_returns` like everything else in this system.

**Depends on:** Phase 142A (proven OOS ensemble IC) — already cleared 2026-07-22 (Gate 1 PASS,
Phase 148). Not gated on Phase 166 or the 156-159 execution/sizing chain.

**Sequencing relative to other open phases:** this is measurement-layer work that could
produce a Gate-2-passing signal — sequence **before** Phase 156 (Portfolio State Foundation)
and the rest of the 156-159 execution/sizing chain, which size and execute a signal this phase
would help produce, not replace. Independent of Phase 164/165 (feature-expansion track,
attacks the *feature* side under the same construction T2 falsified) — parallel work, neither
blocks the other.

**Requirements**: No formal REQUIREMENTS.md IDs (standing-doc-driven, same pattern as Phase
163). Governed by `docs/research/trade-construction-layer.md`'s own design + validation
sections.
**Plans:** 6/6 plans complete
construction primitives, the `CrossSectionalSpreadTracker` BaseBatch service with incremental
watermark scoping, Validation Gate 1 (`--evaluate-gate`), Validation Gate 2 (`--evaluate-attribution`,
the one piece of genuinely new statistical work), and a live run that produces the real verdicts.

**Cross-AI review incorporated 2026-07-27** (`167-REVIEWS.md`, Codex, single reviewer). Plan set
kept at 6 plans / 5 waves; three genuinely-open findings were closed by additions, not rescoping:
tied and missing feature-value coverage in `decile_legs` and in the shuffled null (with an
observed-vs-null eligible-bar parity guard); a timestamped machine-readable JSON verdict artifact
under `logs/construction_verdicts/` written before any prose transcription; and an explicit
retrospective-not-causal caveat carried as a returned field through Gate 2's verdict and into the
research write-up. Also added: a crash-recovery integration test, pre-registered equivalence
tolerance bands, and an intentional-divergence ledger. Locked out regardless of reviewer
suggestion, per CONTEXT.md D-01 to D-05: no cross-sectional block bootstrap, no vol-scaling, no
systemd timer.

**Planning decisions worth carrying forward (resolved, do not re-litigate):**

- No systemd timer, no `service_auditor._DAG_ORDER` registration - manual/on-demand only,
  matching `alpha_scorer.py`/`counterfactual_tracker.py`/`tag_calibrator.py`. The full-corpus
  `--backfill` hands Gate 1 its OOS day-clusters immediately rather than waiting on calendar time.

- Gate 1 evaluates `bar_ts >= alpha.validation.oos_start` (the OOS segment). Note this is the
  OPPOSITE direction from `counterfactual_tracker.py`'s in-sample FRAME-04 gate. The in-sample
  segment is reported as a labeled diagnostic only, for comparison against T3's published
  full-history numbers.

- Gate 2 operationalized: static bucket membership = each symbol's time-averaged net leg
  membership, collapsed into ONE benchmark return series (not 80 symbol dummies, which would
  overfit), with the residual gated through the same day-clustered bootstrap Gate 1 uses.

- Todos 185 and 186 are confirmed NOT required by this phase (RESEARCH.md's two scope
  assessments) - no task exists for either.

- Flat equal-weight legs, no vol-scaling: the design doc's step 3 calls for vol-scaling but the
  T3 script that earned this phase does not use it. Build what was proven (RESEARCH.md Pitfall 1).

**References:**

- `docs/research/trade-construction-layer.md` — full construction design, sizing/cost
  discussion, validation gates

- `docs/research/data-edge-source-thesis.md` — T3 section (today's result), T2 section
  (falsification, now confirmed not provisional)

- `scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py` — the falsification
  script and its result

- `.planning/todos/pending/030-cost-hurdle-apr-calibration.md` — cost floors this phase's first
  open item needs

- `.planning/todos/completed/183-ic-engine-max-cell-rows-breached-by-todo092-rebalance.md` — the
  corpus recompute that unblocked T2's re-verification (completed 2026-07-27, closed; never
  gated this phase's own start)

Plans:
**Wave 1**

- [x] 167-01-PLAN.md - `construction_spreads` hypertable, 6 APR keys, truncate registration, glossary entry (wave 1)
- [x] 167-02-PLAN.md - pure construction primitives: decile split, spread, turnover, cost sweep, config validation (wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 167-03-PLAN.md - `CrossSectionalSpreadTracker(BaseBatch)`: incremental watermark, streaming panel scan, chunked persistence, `--backfill` (wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 167-04-PLAN.md - Validation Gate 1: `--evaluate-gate`, 8-cell verdict grid, live shuffled-ranking null (wave 3)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 167-05-PLAN.md - Validation Gate 2: `--evaluate-attribution`, static-tilt decomposition, residual gate (wave 4)

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 167-06-PLAN.md - live backfill, live gate runs, verdicts recorded in the research docs + runbook (wave 5)

---

**Correction (2026-07-12, same day as the note above was first written):** this section previously said Phases 152/153 should be **prioritized now**, ahead of the intelligence-layer work. That was wrong and contradicted the milestone bullet above's own existing, correct caution ("Do not let either jump ahead of Phase 142B/143 or 148, which carry present-tense value the backlog matrix rates higher"). Monitoring decay of alpha that hasn't been proven to exist yet is monitoring a null: Phase 148's OOS gates (EIC-04 + FRAME-04) have not passed on corrected data — **FRAME-04 currently fails 16/17 cells** on the pre-143.1-fix baseline, so there is no proven capturable edge for 152/153 to watch decay in yet. **Corrected sequencing:** finish 143.1 (091→097→094→E1-vs-E2 re-run→096→088) → re-run EIC-04/FRAME-04 honestly on corrected data → only then decide between (a) building 152/153's decay/health monitoring or (b) expanding discovery (Phase 151/PrecedentEngine) based on what that gate actually says. Phase 157's kill-switch design above still correctly notes its dependency on Phase 153 eventually existing — that dependency is real, it's just not a reason to build 153 before Phase 148 resolves.
