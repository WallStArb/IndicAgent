# Milestones

## v3.1 AlphaEngine Validation + Alpha Scoring (Shipped: 2026-09-02)

**Phases:** 24 complete (140.5, 141, 141.1, 142A, 142B, 142B.1, 142.5, 143, 143.1, 144, 146, 148, 160, 161, 162, 163, 164, 165, 166, 167, 170, 171, 172, 173); 145/168/169 planned but never executed (blocked/superseded at close); 151 Waves 6-7 paused. Timeline: 2026-06-26 → 2026-08-26.
**Verdict the milestone exists to deliver:** no construction earned promotion to live capital — Phase 148 Gate 1 PASS / Gate 2 FAIL; Phase 167's original PASS retracted after the CTF-leak correction; 5/5 discovery-track candidates DEAD. The corpus, measurement discipline, and governance systems it built are the asset.

**Key accomplishments:**

1. **Measurement integrity foundation** (141.1, 143.1, 162) — OOS holdout enforcement with gate-look audit trail, Fisher-z/bootstrap CIs, whole-cell fingerprint incremental recompute (equivalence-proven)
2. **Ensemble + frame simulation** (142A, 142B, 142B.1) — `alpha_ensemble_ic`, `alpha_frames` + `CounterfactualTracker`, E1 shrunk-IC weighting champion over mean-variance
3. **Feature Factory expansion** (142.5, 151, 163-165) — 89 Renaissance primitives, VP/SR structural, SMC footprint, swing/fib/trend/session; `FeatureVector` 249→292 fields
4. **Governance registries** (160, 161, 170) — `concept_registry` (sole feature-lifecycle system after Phase 170 retired `feature_registry`), CVR + drift auditor, `TagCalibrator`
5. **Regime system corrected** (144, 171, 172) — cross-sectional `regime_group` model; production HMM trend labels proven a volatility partition mislabeled; `regime_volatility` (K=3, walk-forward) replacement
6. **Proof gates run honestly** (148, 166, 167, 173) — per-symbol OOS proof gates, frame recalibration, cross-sectional construction (retracted on re-verification), broadcast significance correction + full 8-step corpus recompute

**Post-milestone state:** research continues under the pre-registered personal-scale edge determination program (`docs/plans/2026-09-02-personal-scale-edge-determination-plan.md`) on the research track, outside the phase system; its decision gate's winning branch earns the next phase.

**Archive:** `.planning/milestones/v3.1-phases/` (all 26 phase directories)

---

## v3.0 Intelligence Vectors — AlphaEngine (Shipped: 2026-06-24)

**Phases completed:** 4 phases (137, 138, 139, 140); Phase 140 correctness follow-on completed 2026-06-25
**Plans completed:** 23 plans (7 + 9 + 3 + 4)
**Timeline:** 2026-06-20 → 2026-06-24 (4 days); Phase 140 one day later

**Key accomplishments:**

1. **Feature Factory** (Phase 137) — 54-feature typed `feature_vectors` hypertable replaces `intelligence_features` as the v3.0 training corpus; I5/I6/I7 archived intact; backfill oneshot with checkpoint/resume; `BaseBatch` Ring 0 base class
2. **IC Engine + forward returns** (Phase 138) — vectorized Spearman IC per (feature, symbol, tf, regime, lookahead) with circular-block-bootstrap 95% CI, BH-FDR correction, 20K independent-observation gate, 3-fold walk-forward validation (60-bar embargo); causal HMM regime labeling via forward-filter alpha-pass; forward returns via `LEAD()` with `TRAINING_WINDOW_END` OOS holdout gate; full 58-symbol corpus run executed 2026-06-24
3. **Ensemble + alpha emission** (Phase 139) — Ledoit-Wolf covariance shrinkage with cluster deflation, per-feature 20% weight cap, `effective_N` diversification metric; `AlphaEmitter` shadow-mode Kafka emission to `alpha_events`; direction-aware CI gate
4. **Correctness follow-on** (Phase 140) — stride-per-scale bug fix, migration 171, feature collinearity clustering, BH-FDR meta-level gate in ensemble trainer

**Key decisions (load-bearing):** `HMM_RANDOM_STATE=42` (changing it invalidates all `feature_ic_scores`); pooled IC (`is_pooled=true`) is diagnostic-only; IC Sharpe gate is `n_raw_bars >= 20,000`; gradient column naming (`return_fast/mid/slow/extended`) tunable via APR not migration.

**Archive:** `.planning/milestones/v3.0-ROADMAP.md`

---

## v2.10 Data Architecture Evolution (Shipped: 2026-06-20)

**Phases completed:** 12 phases (123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 134, 136); Phase 133 CANCELLED
**Plans completed:** ~58 plans
**Timeline:** 2026-06-14 → 2026-06-20 (7 days)

**Key accomplishments:**

1. **ECL boundary restored** (Phase 123) — All 37 I7 plugins emit on intrinsic criteria only; CTF score, zone friction, exhaustion state demoted to annotations; `context_features` + `factor_scores` promoted to first-class persisted signal fields; `_nullable_float()` pattern preserves None vs 0.0 ML semantics; SIGNAL_SCHEMA_VERSION bumped to v3
2. **Signal universe integrity + APR** (Phases 124-126) — 5 over-firing plugins (15-30%/bar) corrected to event-onset detection (<3%/bar); 51 constants externalized across all 3 APR tiers; weight sum invariant enforced in all Tier B plugins; universal zone width gate in `frame_trade()` eliminates sub-ATR phantom stops; `_I7_I6_EXEMPT` frozenset deleted; all 8 formerly-exempt plugins wired with I6 confluence via pipeline layer
3. **3-table signal architecture** (Phases 128-130) — `signal_events` / `trade_frames` / `trade_executions` deployed; `counterfactual_pnl_r` as first-class ML training target on `trade_frames`; 1,443,231 rows migrated from `signal_ledger`; all writers/trackers/APIs/backfill scripts migrated; `signal_ledger` dropped (migration 143); `signal_ledger` JOIN view retained for backward compat
4. **Clean replay + validation** (Phase 127) — Full historical replay on corrected pipeline with `--warmup`; 3-table validation report (no Welch's t-test; null distribution + bootstrap CI); calibration curves retrained; RCA Part VI updated
5. **Signal generation integrity** (Phase 131) — I6 CTF zero bug fixed; asset_class injection corrected for rolled contracts; BOCPD look-ahead bias removed; 16 I7 plugins had HMM regime gates removed; 6 additional stability bugs patched
6. **Stop geometry + type safety** (Phases 132, 134) — Stops measured from actual entry price; 35 trade_framer constants in APR; stopped_at_entry rate below 5%; PG ENUM types on all classification columns (exit_reason, outcome, entry_type, status); EntryType Python enum replaces 15+ string literals; SignalOutcome persisted to trade_executions
7. **Post-reboot repair** (Phase 136) — 1,343 orphaned intelligence_features rows recovered via replay; feature_writer pre-flight schema check; intelligence_pipeline graceful SIGTERM; FVGFill disabled; ValidationResult NamedTuple for signal rejection reasons

**Archive:** `.planning/milestones/v2.10-ROADMAP.md`, `.planning/milestones/v2.10-REQUIREMENTS.md`

---

## v2.7 Mathematical Correctness, Storage & Hardening (Shipped: 2026-05-29)

**Phases completed:** 9 phases (093, 100, 100.5, 104, 105, 106, 107, 108, 109), 43 plans
**Timeline:** 2026-05-20 → 2026-05-29 (10 days)

**Key accomplishments:**

1. **Mathematical correctness audit** — ATR Wilder bug fixed; all 28 I1 indicators validated against pandas-ta reference; Kalman/GARCH stateful invariant tests; edge case coverage; CI gate prevents merges with failing correctness tests (Phase 093)
2. **Plugin shared infrastructure** — IncrementalMixin for 31 genuine incremental plugins; shared utilities (atr_utils, state_utils, confidence_utils, plugin_utils); PluginObserver + emit_signal() contract; 24 plugins migrated; CI hard-block on non-compliance (Phases 100, 100.5)
3. **Storage architecture redesigned** — 9 hypertable retention policies, 6 Kafka byte caps; 13 GB freed (feature_snapshots_shadow dropped); intelligence_features columns renamed (i1–i8 → concept names); signal_ledger slimmed from 97 to ~38 columns; ml_signal_training hypertable (Phases 104, 105)
4. **Foundation + hygiene (Renaissance)** — Dead code deleted (ShadowRecorder, GuardrailsValidator); DAG correctness (31→42+ services); 9/9 HYGIENE criteria verified; PluginCircuitBreaker wired; O(1) PluginStateManager; enqueue_blocking backpressure (Phases 106, 107)
5. **Self-healing hardening** — WatchdogSec=60 on 39 daemons; DLQ quarantine (.dead-final); consumer stall detection; api_health gauge; oneshot job_completed_total counters; CLAUDE.md OTel SOP (Phase 108)
6. **Config foundation + self-healing engine** — DB-backed OPS config (4 tables), ConfigService HTTP API (port 9001), Kafka transactional outbox, BaseAgent hot-reload, SelfHealingAgent (port 9002) with Alertmanager integration and remediation ledger (Phase 109)

**Archive:** `.planning/milestones/v2.7-ROADMAP.md`, `.planning/milestones/v2.7-REQUIREMENTS.md`

---

## v2.6 Foundation Hardening & Signal Transform (Shipped: 2026-05-20)

**Phases completed:** 9 phases (084–092), ~35 plans
**Timeline:** 2026-05-16 → 2026-05-20 (4 days)

**Key accomplishments:**

1. **Base agent hardening** — Pydantic contracts on BaseWriterAgent, _setup_with_retry, OTel on BaseAIAgent._on_error, circuit breaker opt-in, dead-code cleanup (Phase 084)
2. **Persistence writer migration** — All 6 writers adopt 084 contracts; lineage_writer silent data loss fixed; named params fleet migration (Phase 085)
3. **Pipeline hardening** — PluginCircuitBreaker per-plugin; validate_signal() at I7 boundary; checkpoint fail-fast; output queue block/retry; /api/health/system Prometheus aggregation (Phase 086)
4. **God class decomposition** — IntelligencePipelineComputeAgent 1928→763 lines via PluginExecutor, PluginStateManager, SignalProcessor, CacheManager, OutputQueue extraction (Phase 088)
5. **Compute performance** — Per-bar allocation waste eliminated; plugin state race fixed; per-key concurrency via PerKeyWorkerManager (Phase 089)
6. **Signal quality + registry** — Signal ledger thread safety (RLock); FX PK collision fix; pg_notify trigger; asyncpg LISTEN; soft-delete route; BarAuditorAgent gap-fill hardening (Phases 090, 091, 091.1, 092)

---

## v2.5 Data Quality & Intelligence Completion (Shipped: 2026-05-16)

**Phases completed:** 15 phases (69–83), ~61 plans
**Timeline:** 2026-04-23 → 2026-05-16 (23 days)
**LOC:** ~133,625 Python · ~12,419 TypeScript

**Key accomplishments:**

1. **AI/LLM architecture hardening** — `src/core/ai/` infrastructure (BaseAIAgent, BaseGroupService, AIContext, LLMProviderChain); mandate-based agent groups; 6 LLM chain fixes; `signal_lineage` hypertable; `prompt_version` A/B tracking auto-injected (Phase 73)
2. **Swarm intelligence layer** — Full swarm agent stack (Skeptic, Correlation, RegimeCoherence, Counterfactual) via BaseMultiplierAgent; shadow_only=True by default; per-TF Spearman-learned weights; `adjusted_confidence` in signal_ledger (Phase 80)
3. **Signal lifecycle hardening** — `SignalReplayAuditorAgent` (L9, 5-min) + `BarReplayProviderAgent` (L1, one-shot); zero DB write paths in `SignalTrackerComputeAgent`; `signal_replay_unresolved_gauge=0` permanent health invariant; 16+4 tests covering all 8 outcome types (Phase 81)
4. **Signal quality foundation** — Zero-width signal zones eliminated via mandatory `make_signal_from_frame()`; `signal_schema_version` column + ML training filter; `entry_type` + co-fire tracking; all 36 I7 plugins migrated (Phase 79)
5. **ML scoring + AI decoupling** — LightGBM scoring layer (shadow_only); `signal_ai_enrichment` + `intelligence_ai_enrichment` tables isolate AI from quant pipeline (AI-SEP-01); walk-forward CV; SHAP via MLflow (Phase 70)
6. **OTel observability unification + hardening** — Single OTel SDK meter replaces 24 per-process servers; `observed_span()` with auto ERROR recording; `DLQDrainAgent` + `dlq_events` hypertable; 5 Alertmanager rules; 6 orphaned topics deleted; prometheus_client fully removed (Phases 77, 83)
7. **Shadow governance** — `shadow_registry` DB table; `ShadowAuditorAgent` auto-enrollment/promotion/demotion; promotion gate n>=100 + bootstrap_ci_lower>0; demotion gate EV[R]<-0.05 × 3 cycles (Phase 75/77)

**Known deferred items at close:** 7 backlog todos (AUTH-01 to AUTH-06, ML-06 shadow gate, transform graduation Phase 2-4, PERF-07, DATA-02)

**Archive:** `.planning/milestones/v2.5-ROADMAP.md` · `.planning/milestones/v2.5-REQUIREMENTS.md`

---

## v2.1 Data Foundation & Signal Confidence (Shipped: 2026-03-28)

**Phases completed:** 13 phases (48, 49, 49.1, 49.2, 51, 52.1–52.8)

**Key accomplishments:**

1. **Live tick aggregation + I7 reuse** — 5s RTBs → canonical 1m bars via IBKR push; 3 shared I7 utilities (microstructure, state, volume_profile) removing 550+ lines duplication; 40–60% per-bar latency reduction
2. **Signal ledger completeness** — ALL I7 signals written unconditionally; regime_type_at_fire + hmm_regime_at_fire populated; composite lifecycle index drops UPDATE latency 34ms → <5ms
3. **BaseAgent DAG standard** — Lifecycle contract (setup/teardown, metrics_port, tracer, topic manifest) on all 4 pipeline agents; ProcessManifest replaces singleton AgentRegistry; uniform SIGTERM drain
4. **Autonomous shadow parity** — FeatureSnapshotWriterAgent dual-writes via independent consumer group; ParityAuditorAgent validates 60 consecutive clean cycles before publishing `SHADOW_PARITY_CERTIFIED`
5. **End-to-end distributed tracing** — Grafana Tempo as 6th Docker service; W3C `traceparent` in Kafka transport; bar-to-signal waterfall trace visible across all agents in Grafana Tempo
6. **Per-layer automated validation** — I1→I7 sanity checks run on each deploy; signal outcome completeness audited; setup_performance gate verified

---

## v2.0 Signal Integrity & ML Foundation (Shipped: 2026-03-22)

**Phases completed:** 14 phases, 60 plans, 111 tasks

**Key accomplishments:**

- signal_ledger enriched with effective_ts trigger column, pipeline_lag_ms latency instrumentation, two CHECK constraints, and signal_stats_daily materialized view (33,859 rows) for fast IC computation
- Exit-1 completeness gate added to repair_cis_nulls.py; DATA-02 deferred — 0 resolved outcomes for DerivOsc and AC Osc (N < 30 gate)
- OHLCV hypertable rebuild script with chunk-count/latency verification gate and signal_ledger composite index migration for lifecycle UPDATE performance
- Self-healing gap-fill service detecting missing 1m RTH bars via asyncpg set-diff, fetching from IBKR, inserting with ON CONFLICT DO NOTHING; scheduled daily at 09:20 ET via systemd timer
- signal_performance_segmented table with Pearson IC scores per plugin-regime slice; 3,227 rows written; trad_MeanReversion leads at IC=0.81 (15m); 512/3,227 slices statistically significant
- 1. [Rule 1 - Bug] Fixed no-label Gauge .labels() call
- PatternPlugin Protocol extended with mandatory regime_type field and validate_tier() now hard-crashes service startup if any I7 plugin is missing or has an invalid regime_type value
- One-liner:
- One-liner:
- Before:
- 1. SignalOutcome Enum (`src/intelligence/trading/signal_outcome.py`)
- Hardcoded string scan results:
- CircuitBreaker, DataQualityMonitor, and Stage base class for 6-stage signal pipeline DAG with fault tolerance, schema validation, and attribution emission
- 6 DAG pipeline stage services (QualityGate → RegimeGate → TODAdjuster → Calibrator → Ranker → WinnerSelector) implementing the typed, attributed signal processing chain with circuit breaker protection
- 8 Redpanda pipeline topics and 6 systemd microservices deployed — full DAG stage infrastructure running on :9119–:9124
- Removed:
- Replaced hardcoded 0.0 stubs in CrossTimeframeConfluencePlugin with direction-weighted FVG and Order Block proximity scores across higher timeframes, including per-TF contribution decomposition for full auditability.
- 1. [Rule 1 - Bug] Fixed test scenario with logically inconsistent entry vs POC for near-boundary long test
- 1. [Rule 1 - Bug] TF guard broke all existing tests that don't set frames["timeframe"]
- 1. [Rule 1 - Bug] Fixed incorrect test fixtures from plan spec
- CandlestickPatternSetup I7 plugin extended to read DB-driven pattern weights from frames injection with fallback priors, and 10 new Phase 42 patterns integrated via scalable pattern_flags loop
- Pattern reliability calibration function added to weight_updater.py closing the Renaissance feedback loop, with 7-day ES 1m backtest confirming 4/5 pattern groups (97 tweezer + 85 belt_hold + 17 kicker + 1 harami fires)
- 4 new Python modules establishing shared I7 utility foundation: plugin_utils (no_signal/extract_ohlcv/signal_type helpers), atr_utils (ATR null-guard), confidence_utils ([0.10,0.95] system clamp), utils/common.py (tier-agnostic composites); 58 tests all green
- 1. [Rule 1 - Bug] Test assertions assumed `{}` for insufficient-data paths
- cross_timeframe.py decomposed from 464-line monolith into 3 focused modules (confluence_weights, confluence_alignment, confluence_smc) + 133-line thin orchestrator, with CrossTimeframeConfluencePlugin interface unchanged
- Task 1 — Fix type contracts in all 8 microstructure plugins:
- Task 1 — Plugin wiring (5 transformations):
- 1. [Rule 2 - Missing] Tick buffer from indicator_service
- 1. [Rule 3 - Blocking] Port conflict on metrics endpoint
- Three legacy systemd units deleted, development.indicators Redpanda topic retired, and full 2743-test suite confirmed green — Feature Pipeline Renaissance topology fully clean.
- One-liner:
- One-liner:
- Deleted 6 stage microservice files, stages/ directory, and old stage tests; retired 6 systemd units; SignalGeneratorService running with in-process pipeline confirmed via Prometheus metrics
- 9 pytest-asyncio tests validate the full bar → BarIntelligenceRecord pipeline with mocked I/O — no live infra required
- DB migration adding 11 columns to intelligence_features + FeatureWriterService simplified to single atomic INSERT per bar from BarIntelligenceRecord, eliminating i7/i8 two-phase partial-row writes
- One-liner:
- FeaturePipelineService writes live 1m bars to market_data_ohlcv via async batch (buffer 50, flush 5s, ON CONFLICT DO NOTHING) — market_data_ohlcv is now single OHLCV ground truth
- 1. [Rule 1 - Bug] Fixed broken RankedSignal field names in signal-scorecard.tsx
- One-liner:
- 1. [Rule 1 - Bug] mean_reversion.py already wired
- 15 I7 plugins (SMC family + microstructure family) wired with capture_confluence_features shadow capture and per-plugin exhaustion handling; all emit signal["_shadow"] for Phase 49 ML training
- 10 regression tests verify PERF-04: O(1) active signal index dict lookup and 0.01% chandelier write guard in signal_lifecycle_service
- One-liner:
- `capture_confluence_features()` shadow dict extended to 15 keys with VIX regime and EQ_INDEX sector rotation fields, using None-default semantics per D-06 to distinguish absent data from zero z-scores.
- Two new I4 macro context plugins (VIXRegimePlugin, CrossAssetContextPlugin) registered in TIER_I4; I4Context extended to 97 fields; I6Confluence pass-through removed; CROSS_ASSET_VALID_TFS centralized
- VIX frame injection fixed to VIX_REGIME_TF='1h'; I6 outputs locked by test; capture_signal_features renamed across all 36 I7 plugins with I4 key names
- Query result:
- One-liner:
- Roll monitor graduation checkpoint reached — D-21 validation skipped (market_data_5m empty), ROLL_MONITOR_ENABLED kept false, scaffolding removal deferred to todo 023
- CROSS_ASSET_ENABLED feature flag fully removed from 4 services and Settings — cross-asset intelligence unconditionally active in DAG (SHADOW-02 graduated)
- D-21 validation gate

---

## v1.9 I7 Alpha Engine (Shipped: 2026-03-18)

**Phases completed:** 8 phases (31-38), 23 plans
**Timeline:** 2026-03-16 → 2026-03-18 (2 days)
**Plugins:** 121 + 2 aggregation (was 103) · **Requirements:** 47/47 ✓
**Files changed:** 104 · **LOC delta:** +15,446 / -1,934

**Key accomplishments:**

- CIS self-improving learning loop: binary win/loss labels, asset-cluster logistic regression (5 clusters), `signal_features` hypertable for mid-bar ML snapshots; `is_shadow` column + A/B promotion gate (Phase 31)
- Structure-first stop architecture centralized in `trade_framer.py`: FVG-priority stop, GARCH-adaptive ATR (0.8×/1.0×/1.35×), `stop_basis` logging; Chandelier trailing stop + staleness decay + shadow tracking (Phase 32)
- 5 new I7 setups (FailedBreakout, ORB15, ORB30, PrevDayLevelTest, SecondLegContinuation, VCP) + 5-input divergence stack (RSI 0.30/MACD 0.25/vol 0.20/OBV 0.15/CMF 0.10) (Phase 32-33)
- I4 AnchoredVWAP + VolumeProfile infrastructure: 93-field I4Context; 5 new I7 VWAP/VP plugins (Phase 34)
- Full confidence pipeline: isotonic regression calibration + TOD Bayesian multiplier (120 cells) + CIS Kalman filter (per (symbol, tf), dual fire gate); dashboard shows raw/filtered/calibrated trio (Phase 35)
- OFI + CVD I1 indicators with tick/proxy dual-path; 7 I7 microstructure plugins; IS_SHADOW plugin flag pattern established (Phase 36)
- `cross_asset_service` microservice: ES/NQ/RTY/YM spread z-scores + correlation break; CrossAssetDivergencePlugin I7; shadow mode default (Phase 37)
- Automated futures roll detection: volume z-score + 3-bar confirmation + TOD adjustment; full pipeline propagation; `seed_roll_chain` backfill script (Phase 38)

---

## v1.8 Signal Intelligence (Shipped: 2026-03-13)

**Phases completed:** 2 phases (28-29), 15 plans
**Timeline:** 2026-03-12 → 2026-03-13 (2 days)
**Tests:** 1,659 passing · **Ruff:** 167 errors (E501 line-too-long, non-blocking) · **Plugins:** 103 (101 + 2 agg)
**LOC:** ~69,326 Python · ~8,654 TypeScript · **Files changed:** 147

**Key accomplishments:**

- Signal Scorecard panel: full I7 signal competition in dashboard — all ranked signals with confidence, direction, composite rank, suppression labels, and regime eligibility via SSE `signal_scorecard` event (Phase 28)
- DB signal history in drill panel: `signal_ledger` history loaded on mount, merged with live SSE, deduplicated by `signal_id`; `GET /api/signals/recent` endpoint (Phase 28)
- GARCH/Kalman I4 fields + SMC detail surfaced: volatility regime context + BSL/SSL dist_atr/touches/significance + premium/discount in drill panel (Phase 28)
- Tier tooltips: I1–I8 tier labels show hover explanations for each intelligence tier (Phase 28)
- CIS constituent contributions: per-setup feature score breakdown on every CIS computation — enables future attribution analysis without recomputation (Phase 29)
- Alpha decay + freshness decay: repeated same-setup signals down-weighted; active signal confidence decays as `exp(-λ × bars_since_fire)` — in-memory, ML ground truth preserved (Phase 29)
- HurstExponentPlugin + ShannonEntropyPlugin (I4): Hurst suppresses setups in wrong regime (H>0.65 mean-reversion, H<0.45 trend); Shannon entropy reduces confidence 30–50% during noisy market periods (Phase 29)
- KS + CUSUM drift detection: `drift_monitor_service` background job monitors feature distribution drift (p<0.05) and per-setup win rate degradation; `/api/drift` endpoint exposed; `drift_monitor` TimescaleDB hypertable (Phase 29)

---

## v1.5 Production Hardening (Shipped: 2026-03-10)

**Phases completed:** 5 phases (18-22), 25 plans
**Timeline:** 2026-03-07 → 2026-03-09 (2 days)
**Tests:** 1,318 passing · **Ruff:** 74 errors (E501 line-too-long, non-blocking)
**Plugins:** 91 + 2 aggregation · **LOC:** ~62,600 Python · **Files changed:** 134

**Key accomplishments:**

- Epsilon tolerance (1e-9) for all floating-point comparisons in trade_framer + CIS scorer; all ATR multipliers, regime thresholds, and magic numbers documented as named constants (Phase 18)
- Configurable IBKR/LLM timeouts in Settings; per-key asyncio.Lock() concurrency protection across market_analysis_service, indicator_service, and ai_narrative_service (Phase 18)
- Characterization tests pinning RSI zero-loss behavior (100.0), zero-ATR emergency fallback, and concurrent lock isolation (Phase 19)
- retry_utils.py with exponential backoff + jitter; PluginCircuitBreaker wired to all 4 LLM providers and IBKR provider; circuit breaker Prometheus metrics on all state transitions (Phase 20)
- DataFrame cache invalidated only on buffer capacity exceeded (indicator + market_analysis); CIS scorer numpy/BLAS vectorization; plugin call metrics modulo sampling (PLUGIN_METRICS_SAMPLE_RATE=10) (Phase 21)
- Three-tier I8 narrative redesign: action_tag (deterministic, instant), narrative_short (~500ms), narrative_deep (~5-8s) — concurrent asyncio tasks, independent SSE routing, dashboard progressive disclosure; old single-call path retired (Phase 22)

---

## v1.4 Quant Foundation (Shipped: 2026-03-07)

**Phases completed:** 6 phases (12-17), 29 plans
**Timeline:** 2026-03-04 → 2026-03-07 (4 days)
**Tests:** 1,286 passing · **Ruff:** 34 errors (E501 line-too-long, non-blocking)
**Plugins:** 91 + 2 aggregation · **LOC:** ~59,000 Python

**Key accomplishments:**

- Regime-aware gating on all 17 I7 plugins (hmm_regime + prob≥0.60 + duration≥5 gates); shadow signals track counterfactual MAE/MFE/outcome for empirical gate tuning
- `intelligence_features` enriched with `i7 JSONB` (all_ranked signals per bar), `i8 JSONB` (narrative metadata), `days_to_expiry` — complete, permanent ML training dataset with no missing samples
- `setup_performance` table + daily weight-update job + adaptive aggregator `perf_multiplier` — outperforming setups rank higher automatically; Renaissance promotion gate (n≥30) prevents overfitting
- `validate_alpha.py` statistical promotion gate (Pearson r>0, p<0.05, N≥30 + ADF stationarity) + 4 new live alpha sources: DerivativeOscillator (I2), 10 Candlestick Tier 1 patterns (I5/I7), MACD histogram acceleration (I2), AC Oscillator (I1)
- Full LLM audit log (`llm_calls` TimescaleDB hypertable, every call captured), outcome back-fill from signal lifecycle exits, 15-min `llm_model_scores` recompute, adaptive model routing per regime (Phase 16)
- E2E Flows 3+4 restored by Phase 17: `signal_id` UUID threaded through `signals:aggregated` stream into `llm_calls`, regime vocabulary standardized for score routing

---

## v1.0 MVP (Shipped: 2026-02-28)

**Phases completed:** 9 phases, 29 plans, 4 tasks

**Key accomplishments:**

- 62 plugins + 4 aggregation components + feature store + typed intelligence bus
- 796 tests passing
- 22 contracts active across equity index, energy, metals, rates, volatility, agriculture, FX, crypto
- 8 systemd services + weight-updater timer running in production
- 413K signals + 482K feature rows in TimescaleDB

---

## v1.1 Code Quality Sprint (Shipped: 2026-03-01)

**Phases completed:** 1 phase, 1 plan

**Key accomplishments:**

- Ruff errors: 206 → 0 (entire codebase)
- Tests: 787 → 803 passing
- Service startup: 9.2s → 1-2s (parallel warmup reads)
- 3 pattern files O(N²) → O(N)
- All 6 services use `ensure_consumer_group_with_reset`
- VX contract rolled to VXM6

---

## v1.2 Intelligence Palette Expansion (Shipped: 2026-03-02)

**Phases completed:** 4 phases, 8 tasks

**Key accomplishments:**

- 84 plugins + 2 aggregation components total (I2, I5, I6 expanded within this milestone)
- Tests: 803 → 965 passing (+162 tests)
- I2 composite events: 5 plugins running on I1 features
- I5 patterns: +7 new pattern plugins (CupHandle, FlagPennant, TriangleWedge, HeadShoulders, DoubleTopBottom, Candlestick, MeasuredMove)
- I6 SMC: +5 new SMC plugins (ICTKillzones, AMDCycle, BreakerBlocks, MitigationBlocks, PremiumDiscount)
- I6 confluence: recency weighting + I2 event scoring (CrossTimeframeConfluence expanded to 10 output fields)
- I1-I6 correctness audit: 35 tests verifying mathematical correctness across tiers
- Code simplification: 5 SMC plugins + refactor review findings addressed
- Documentation: CLAUDE.md updated to v5.10.0, plugin counts aligned

---

## v1.3 Signal Intelligence Expansion (Shipped: 2026-03-04)

**Phases completed:** 4 phases + Signal Lifecycle redesign

**Key accomplishments:**

- 88 plugins + 2 aggregation components (I2: +1 MomentumAcceleration; I7: +3 new setups)
- Tests: 965 → 1083 passing (+118 tests)
- Phase 08: MomentumAcceleration (I2) — RSI/MACD/ROC 2nd-derivative + inflection detection
- Phase 09: GapAnalysisSetup (I7) — opening gap fade/continuation for ES/NQ (3 sub-setups)
- Phase 10: CandlestickPatternSetup (I7) — confluence-gated candlestick setups consuming I5 output
- Phase 11: SessionExtremesSetup (I7) — Asian session H/L fade during London/NY sessions
- Signal Lifecycle redesign: zone-aware activation, MAE/MFE tracking, 8-class outcome classification
- New `signal_lifecycle_service` (replaces `signal_tracker_service`), migration 015

---
